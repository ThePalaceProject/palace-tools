from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Self

import httpx
import typer
from ddsketch import LogCollapsingLowestDenseDDSketch
from httpx import Limits, Response, Timeout
from rich.console import Console
from rich.progress import (
    Progress,
    ProgressColumn,
    SpinnerColumn,
    Task,
    TimeElapsedColumn,
)
from rich.text import Text

console = Console()

from palace_tools.utils.typer import run_typer_app_as_main


class RequestsPerSecondColumn(ProgressColumn):
    """A custom column that displays requests per second."""

    def render(self, task: Task) -> Text:
        if speed := task.speed:
            return Text(f"{speed:.1f} req/s", style="cyan")
        return Text("0.0 req/s", style="cyan")


class FailedCountColumn(ProgressColumn):
    """A custom column that displays the failed count in red."""

    def __init__(self, stats: StressTestStats) -> None:
        super().__init__()
        self.stats = stats

    def render(self, task: Task) -> Text:
        failed_requests = self.stats.failed_requests()
        if failed_requests > 0:
            return Text(f"{failed_requests} failed", style="red bold")
        return Text("0 failed", style="dim")


class CompletedHarvestColumn(ProgressColumn):
    """A custom column that displays the number of completed harvests."""

    def __init__(self, stats: StressTestStats) -> None:
        super().__init__()
        self.stats = stats

    def render(self, task: Task) -> Text:
        return Text(f"{self.stats.full_harvests} harvests", style="dim green")


class CompletedRequestsColumn(ProgressColumn):
    """A custom column that displays the number of completed requests."""

    def render(self, task: Task) -> Text:
        return Text(f"{task.completed} requests", style="green")


app = typer.Typer()


@dataclass(frozen=True)
class RequestResult:
    url: str
    status_code: int
    response_time: float
    success: bool
    response_headers: dict[str, str] | None = None
    response_body: str | None = None

    MAX_BODY_LENGTH = 500

    @classmethod
    def from_response(cls, response: Response) -> Self:
        """Create a RequestResult from a httpx Response.

        Only stores headers and body for failed requests to save memory.
        Body is truncated to MAX_BODY_LENGTH characters.
        """
        success = response.status_code == 200
        if success:
            body = None
        else:
            body = response.text
            if len(body) > cls.MAX_BODY_LENGTH:
                body = body[: cls.MAX_BODY_LENGTH] + "... [truncated]"
        return cls(
            url=str(response.url),
            status_code=response.status_code,
            response_time=response.elapsed.total_seconds(),
            success=success,
            response_headers=None if success else dict(response.headers),
            response_body=body,
        )


class ResponseTimeStats:
    """Response time statistics using DDSketch for approximate percentiles.

    Uses LogCollapsingLowestDenseDDSketch which provides bounded memory usage
    with relative error guarantees (default 1%) for quantile queries.
    Min and max are tracked exactly since DDSketch only provides approximate values.
    """

    def __init__(self, relative_accuracy: float = 0.01, bin_limit: int = 2048) -> None:
        self._sketch = LogCollapsingLowestDenseDDSketch(
            relative_accuracy=relative_accuracy, bin_limit=bin_limit
        )
        self._min: float = float("inf")
        self._max: float = float("-inf")

    def add(self, value: float) -> None:
        self._sketch.add(value)
        self._min = min(self._min, value)
        self._max = max(self._max, value)

    @property
    def count(self) -> int:
        return int(self._sketch.count)

    @property
    def avg(self) -> float:
        return self._sketch.avg if self.count > 0 else 0.0

    @property
    def min_val(self) -> float:
        return self._min

    @property
    def max_val(self) -> float:
        return self._max

    def percentile(self, q: float) -> float | None:
        """Return the q-th percentile (0-100 scale) or None if no data."""
        if self.count == 0:
            return None
        return self._sketch.get_quantile_value(q / 100.0)

    def histogram(self, num_buckets: int = 10) -> list[tuple[float, float, int]]:
        """Generate histogram with fixed-width time buckets.

        Returns a list of (bucket_start, bucket_end, count) tuples.
        Buckets are evenly spaced between min and max values.
        Counts are approximate, derived from percentile queries.
        """
        if self.count == 0:
            return []

        min_val = self._min
        max_val = self._max

        # Avoid division by zero if all values are the same
        if min_val == max_val:
            return [(min_val, max_val, self.count)]

        bucket_width = (max_val - min_val) / num_buckets
        buckets: list[tuple[float, float, int]] = []
        total_count = self.count

        for i in range(num_buckets):
            bucket_start = min_val + (i * bucket_width)
            bucket_end = min_val + ((i + 1) * bucket_width)

            # Find what percentile range this bucket covers
            # by querying where bucket boundaries fall in the distribution
            start_pct = self._find_percentile_for_value(bucket_start)
            end_pct = self._find_percentile_for_value(bucket_end)

            # Estimate count from percentile difference
            bucket_count = int((end_pct - start_pct) / 100.0 * total_count)
            buckets.append((bucket_start, bucket_end, bucket_count))

        return buckets

    def _find_percentile_for_value(self, value: float) -> float:
        """Binary search to find approximately what percentile a value represents."""
        if self.count == 0:
            return 0.0

        # Handle edge cases
        if value <= self._min:
            return 0.0
        if value >= self._max:
            return 100.0

        # Binary search for the percentile
        low, high = 0.0, 100.0
        for _ in range(20):  # ~6 decimal places of precision
            mid = (low + high) / 2
            mid_val = self.percentile(mid)
            if mid_val is None:
                break
            if mid_val < value:
                low = mid
            else:
                high = mid

        return (low + high) / 2

    def merge(self, other: ResponseTimeStats) -> None:
        """Merge another ResponseTimeStats into this one (mutates self)."""
        self._sketch.merge(other._sketch)
        self._min = min(self._min, other._min)
        self._max = max(self._max, other._max)


@dataclass
class StressTestStats:
    # Keep only a limited number of recent failures for debugging
    max_recent_failures: int = 50

    # Running statistics instead of storing all results
    _success_times: ResponseTimeStats = field(default_factory=ResponseTimeStats)
    _error_times: ResponseTimeStats = field(default_factory=ResponseTimeStats)
    _failures_by_status: defaultdict[int, int] = field(
        default_factory=lambda: defaultdict(int)
    )
    _recent_failures: deque[RequestResult] = field(init=False)

    start_time: float = 0.0
    end_time: float = 0.0
    full_harvests: int = 0

    def __post_init__(self) -> None:
        self._recent_failures = deque(maxlen=self.max_recent_failures)

    def add_result(self, result: RequestResult) -> None:
        if result.success:
            self._success_times.add(result.response_time)
        else:
            self._error_times.add(result.response_time)
            self._failures_by_status[result.status_code] += 1
            # deque with maxlen automatically evicts oldest entries
            self._recent_failures.append(result)

    def total_requests(self) -> int:
        return self._success_times.count + self._error_times.count

    def successful_requests(self) -> int:
        return self._success_times.count

    def failed_requests(self) -> int:
        return self._error_times.count

    def success_response_times(self) -> ResponseTimeStats:
        return self._success_times

    def error_response_times(self) -> ResponseTimeStats:
        return self._error_times

    def all_response_times(self) -> ResponseTimeStats:
        """Return combined stats for all requests (success + error)."""
        combined = ResponseTimeStats()
        combined.merge(self._success_times)
        combined.merge(self._error_times)
        return combined

    def failed_results(self) -> Sequence[RequestResult]:
        return self._recent_failures

    def failures_by_status(self) -> dict[int, int]:
        return dict(self._failures_by_status)

    def total_duration(self) -> float:
        return self.end_time - self.start_time

    @staticmethod
    def _format_timing_stats(times: ResponseTimeStats, label: str, style: str) -> None:
        if times.count == 0:
            return

        console.print(f"  [bold]{label}:[/bold]")
        console.print(
            f"    [dim]Avg:[/dim]    [{style}]{times.avg * 1000:.0f}ms[/{style}]"
        )
        if (median := times.percentile(50)) is not None:
            console.print(
                f"    [dim]Median:[/dim] [{style}]{median * 1000:.0f}ms[/{style}]"
            )
        if (p90 := times.percentile(90)) is not None:
            console.print(
                f"    [dim]P90:[/dim]    [{style}]{p90 * 1000:.0f}ms[/{style}]"
            )
        if (p99 := times.percentile(99)) is not None:
            console.print(
                f"    [dim]P99:[/dim]    [{style}]{p99 * 1000:.0f}ms[/{style}]"
            )
        console.print(
            f"    [dim]Min:[/dim]    [{style}]{times.min_val * 1000:.0f}ms[/{style}]"
        )
        console.print(
            f"    [dim]Max:[/dim]    [{style}]{times.max_val * 1000:.0f}ms[/{style}]"
        )

    @staticmethod
    def _format_histogram(times: ResponseTimeStats, label: str) -> None:
        """Print an ASCII histogram of response time distribution."""
        if times.count == 0:
            return

        histogram = times.histogram(num_buckets=10)
        if not histogram:
            return

        console.print(f"\n  [bold]{label} Distribution:[/bold]")
        max_count = max(count for _, _, count in histogram)
        bar_width = 30

        for lower, upper, count in histogram:
            # Scale bar to max width
            bar_len = int((count / max_count) * bar_width) if max_count > 0 else 0
            bar = "[cyan]" + "█" * bar_len + "[/cyan]"
            empty = " " * (bar_width - bar_len)
            # Format time range
            lower_ms = lower * 1000
            upper_ms = upper * 1000
            console.print(
                f"    [dim]{lower_ms:6.0f}-{upper_ms:6.0f}ms[/dim] │{bar}{empty}│ [green]{count}[/green]"
            )

    def display(self, concurrency: int) -> None:
        duration = self.total_duration()
        total = self.total_requests()
        successful = self.successful_requests()
        failed = self.failed_requests()
        all_times = self.all_response_times()
        success_times = self.success_response_times()
        error_times = self.error_response_times()
        failed_results = self.failed_results()

        # Print error details first if there are any
        if failed_results:
            console.print("\n[bold red]Error Details[/bold red]")
            console.print("[red]=============[/red]")
            for i, result in enumerate(failed_results, 1):
                console.print(f"\n[bold red]\\[Error {i}][/bold red]")
                console.print(f"  [dim]URL:[/dim] {result.url}")
                console.print(f"  [dim]Status:[/dim] [red]{result.status_code}[/red]")
                console.print(
                    f"  [dim]Response time:[/dim] {result.response_time * 1000:.0f}ms"
                )
                if result.response_headers:
                    console.print("  [dim]Headers:[/dim]")
                    for key, value in result.response_headers.items():
                        console.print(f"    [dim]{key}:[/dim] {value}")
                if result.response_body:
                    console.print(f"  [dim]Body:[/dim] {result.response_body}")

        console.print("\n[bold cyan]Stress Test Results[/bold cyan]")
        console.print("[cyan]===================[/cyan]")
        console.print(f"[dim]Concurrency:[/dim] [cyan]{concurrency}[/cyan]")
        console.print(f"[dim]Full harvests:[/dim] [green]{self.full_harvests}[/green]")

        console.print("\n[bold]Timing:[/bold]")
        console.print(
            "  [dim]Total duration:[/dim] ", Text(f"{duration:.2f}s", style="cyan")
        )
        if duration > 0:
            console.print(
                "  [dim]Requests/second:[/dim] ",
                Text(f"{total / duration:.1f}", style="cyan"),
            )

        # Show timing stats for all requests
        self._format_timing_stats(all_times, "All requests", "cyan")
        self._format_histogram(all_times, "All requests")

        # Show timing stats for successful requests if there are also failures
        if success_times.count > 0 and error_times.count > 0:
            self._format_timing_stats(success_times, "Successful requests", "green")

        # Show timing stats for errors if there are any
        if error_times.count > 0:
            self._format_timing_stats(error_times, "Failed requests", "red")

        console.print("\n[bold]Results:[/bold]")
        console.print(f"  [dim]Total requests:[/dim] {total}")
        if total > 0:
            success_pct = (successful / total) * 100
            fail_pct = (failed / total) * 100
            console.print(
                f"  [dim]Successful:[/dim] [green]{successful}[/green] ({success_pct:.1f}%)"
            )
            if failed > 0:
                console.print(
                    f"  [dim]Failed:[/dim] [red]{failed}[/red] ({fail_pct:.1f}%)"
                )
                failures_by_status = self.failures_by_status()
                for status, count in sorted(failures_by_status.items()):
                    console.print(f"    [dim]-[/dim] [red]{status}[/red]: {count}")
            else:
                console.print(f"  [dim]Failed:[/dim] {failed} ({fail_pct:.1f}%)")


def get_next_url(response_data: dict[str, Any]) -> str | None:
    """Extract the next page URL from an OPDS2 response."""
    links = response_data.get("links", [])
    for link in links:
        rel = link.get("rel")
        if rel == "next" or (isinstance(rel, list) and "next" in rel):
            href = link.get("href")
            if isinstance(href, str):
                return href
    return None


async def run_stress_test(
    url: str,
    concurrency: int,
    max_retries: int,
    username: str | None,
    password: str | None,
    stats: StressTestStats,
) -> None:
    stats.start_time = time.time()

    # Configure authentication
    if username and password:
        auth = httpx.BasicAuth(username, password)
    else:
        auth = None

    async with httpx.AsyncClient(
        auth=auth,
        timeout=Timeout(60.0, pool=None),
        limits=Limits(
            max_connections=concurrency * 2,
        ),
        headers={
            "User-Agent": "Palace",
            "Accept": "application/opds+json, application/json;q=0.9, */*;q=0.1",
        },
    ) as client:
        # Track streams and pending requests
        pending_requests: set[asyncio.Task[Response]] = set()
        retries: dict[str, int] = defaultdict(int)

        with Progress(
            SpinnerColumn(),
            TimeElapsedColumn(),
            CompletedRequestsColumn(),
            CompletedHarvestColumn(stats),
            RequestsPerSecondColumn(),
            FailedCountColumn(stats),
        ) as progress:
            requests_task = progress.add_task("Requests", total=None)

            def update_progress() -> None:
                """Update all progress indicators."""
                progress.update(requests_task, completed=stats.total_requests())

            try:
                while True:
                    if len(pending_requests) < concurrency:
                        # Add new streams up to concurrency limit
                        for _ in range(concurrency - len(pending_requests)):
                            req_task = asyncio.create_task(client.get(url))
                            pending_requests.add(req_task)

                    done_requests, pending_requests = await asyncio.wait(
                        pending_requests, return_when=asyncio.FIRST_COMPLETED
                    )

                    for completed_task in done_requests:
                        response = await completed_task
                        result = RequestResult.from_response(response)
                        stats.add_result(result)
                        update_progress()

                        # Handle response
                        response_url = str(response.url)
                        if result.success:
                            # Clear failure count on success
                            retries.pop(response_url, None)

                            # Success - parse for next URL
                            data = response.json()
                            next_url = get_next_url(data)
                            if not next_url:
                                stats.full_harvests += 1
                        else:
                            # Failure - Retry the same URL
                            next_url = response_url
                            retries[response_url] += 1
                            if retries[response_url] > max_retries:
                                # Exceeded max retries, test is over, report an error and exit
                                console.print(
                                    f"[bold red]Max retries exceeded for {response_url}. Exiting stress test.[/bold red]"
                                )
                                return

                        if next_url:
                            pending_requests.add(
                                asyncio.create_task(client.get(next_url))
                            )
            except asyncio.CancelledError:
                # Cancel pending requests on interruption
                for task in pending_requests:
                    task.cancel()
            finally:
                stats.end_time = time.time()


@app.command()
def stress_test(
    url: str = typer.Argument(..., help="The OPDS2 feed URL to stress test"),
    concurrency: int = typer.Option(
        10,
        "--concurrency",
        "-c",
        help="Number of concurrent streams",
    ),
    username: str | None = typer.Option(
        None,
        "--username",
        "-u",
        help="Username for authentication",
    ),
    password: str | None = typer.Option(
        None,
        "--password",
        "-p",
        help="Password for authentication",
    ),
    max_retries: int = typer.Option(
        3,
        "--max-retries",
        "-r",
        help="Maximum number of retries for failed requests",
    ),
    max_failures: int = typer.Option(
        50,
        "--max-failures",
        "-f",
        help="Maximum number of recent failed requests to save for display",
    ),
) -> None:
    """Stress test an OPDS2 feed by fetching it multiple times in parallel."""
    # Create stats outside async so it survives interruption
    stats = StressTestStats(max_recent_failures=max_failures)
    try:
        asyncio.run(
            run_stress_test(
                url=url,
                concurrency=concurrency,
                max_retries=max_retries,
                username=username,
                password=password,
                stats=stats,
            )
        )
    except KeyboardInterrupt:
        pass
    stats.display(concurrency)


def main() -> None:
    run_typer_app_as_main(app, prog_name="stress-test-opds2")


if __name__ == "__main__":
    main()
