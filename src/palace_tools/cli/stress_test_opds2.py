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

from palace_tools.utils.typer import run_typer_app_as_main

console = Console()


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
        failed_requests = self.stats.failed_requests
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
    """

    def __init__(self) -> None:
        self._sketch = LogCollapsingLowestDenseDDSketch()

    def add(self, value: float) -> None:
        self._sketch.add(value)

    @property
    def count(self) -> int:
        return int(self._sketch.count)

    @property
    def avg(self) -> float:
        return self._sketch.avg if self.count > 0 else 0.0

    @property
    def min_val(self) -> float:
        # XXX: We access protected member _min here because DDSketch does not provide
        #   a public method to get the minimum value. This is covered by the TestStressTestStats
        #   unit tests, so if the DDSketch API changes, the tests will catch it.
        #   We could use get_quantile_value(0.0), but that returns the calculated value
        #   which is within 1% relative error, whereas _min is the exact minimum.
        return self._sketch._min if self.count > 0 else 0.0

    @property
    def max_val(self) -> float:
        # XXX: We access protected member _max here because DDSketch does not provide
        #   a public method to get the maximum value. Similar to min_val, this is covered
        #   by unit tests.
        return self._sketch._max if self.count > 0 else 0.0

    def percentile(self, percent: float) -> float | None:
        """Return the value at the given percentile or None if no data.

        :param percent: The percentile to retrieve, on a 0-100 scale.
            For example, 50 for median, 99 for 99th percentile.
        :returns: The approximate value at that percentile, or None if no data.
        """
        if self.count == 0:
            return None
        return self._sketch.get_quantile_value(percent / 100.0)

    def merge(self, other: ResponseTimeStats) -> None:
        """Merge another ResponseTimeStats into this one (mutates self)."""
        self._sketch.merge(other._sketch)

    def __add__(self, other: Any) -> ResponseTimeStats:
        if not isinstance(other, ResponseTimeStats):
            return NotImplemented

        combined = ResponseTimeStats()
        combined.merge(self)
        combined.merge(other)
        return combined


@dataclass
class StressTestStats:
    # Keep only a limited number of recent failures for debugging
    max_recent_failures: int = 50

    # Running statistics
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
            self._recent_failures.append(result)

    @property
    def total_requests(self) -> int:
        return self.successful_requests + self.failed_requests

    @property
    def successful_requests(self) -> int:
        return self.success_response_times.count

    @property
    def failed_requests(self) -> int:
        return self.error_response_times.count

    @property
    def success_response_times(self) -> ResponseTimeStats:
        return self._success_times

    @property
    def error_response_times(self) -> ResponseTimeStats:
        return self._error_times

    @property
    def all_response_times(self) -> ResponseTimeStats:
        """Return combined stats for all requests (success + error)."""
        return self.success_response_times + self.error_response_times

    @property
    def failed_results(self) -> Sequence[RequestResult]:
        return self._recent_failures

    @property
    def failures_by_status(self) -> dict[int, int]:
        return dict(self._failures_by_status)

    @property
    def total_duration(self) -> float:
        return self.end_time - self.start_time

    @staticmethod
    def _format_timing_stats(times: ResponseTimeStats, label: str, style: str) -> None:
        if times.count == 0:
            return

        console.print(Text(f"  {label}:", style="bold"))
        console.print(
            Text("    Avg: ", style="dim"),
            Text(f"{times.avg * 1000:.0f}ms", style=style),
        )

        # Build percentile ladder
        percentiles = [
            ("Min", times.min_val),
            ("P50", times.percentile(50)),
            ("P75", times.percentile(75)),
            ("P90", times.percentile(90)),
            ("P95", times.percentile(95)),
            ("P99", times.percentile(99)),
            ("Max", times.max_val),
        ]

        # Filter out None values and convert to ms
        valid_percentiles = [
            (name, val * 1000) for name, val in percentiles if val is not None
        ]

        if not valid_percentiles:
            return

        # Find max value for scaling bars
        max_val = max(val for _, val in valid_percentiles)
        bar_width = 40

        console.print(Text("    Percentiles:", style="dim"))
        for name, val in valid_percentiles:
            # Scale bar length relative to max
            bar_len = int((val / max_val) * bar_width) if max_val > 0 else 0
            bar_len = max(1, bar_len)  # At least 1 char for visibility
            bar = "█" * bar_len

            console.print(
                Text(f"      {name:>3}: ", style="dim"),
                Text(f"{val:>6.0f}ms ", style=style),
                Text(bar, style=style),
            )

    def display(self, concurrency: int) -> None:
        """Display the stress test results to the console.

        Outputs a formatted summary including:

        - Error details for any failed requests (up to max_recent_failures)
        - Overall timing statistics with percentile ladder visualization
        - Request counts and success/failure rates
        - Breakdown of failures by HTTP status code

        :param concurrency: The concurrency level used during the test,
            displayed in the output for reference.
        """
        duration = self.total_duration
        total = self.total_requests
        successful = self.successful_requests
        failed = self.failed_requests
        all_times = self.all_response_times
        success_times = self.success_response_times
        error_times = self.error_response_times
        failed_results = self.failed_results

        # Print error details first if there are any
        if failed_results:
            console.print(Text("\nError Details", style="bold red"))
            console.print(Text("=============", style="red"))
            for i, result in enumerate(failed_results, 1):
                console.print(Text(f"\n[Error {i}]", style="bold red"))
                console.print(Text("  URL: ", style="dim"), Text(result.url))
                console.print(
                    Text("  Status: ", style="dim"),
                    Text(str(result.status_code), style="red"),
                )
                console.print(
                    Text("  Response time: ", style="dim"),
                    Text(f"{result.response_time * 1000:.0f}ms"),
                )
                if result.response_headers:
                    console.print(Text("  Headers:", style="dim"))
                    for key, value in result.response_headers.items():
                        console.print(Text(f"    {key}: ", style="dim"), Text(value))
                if result.response_body:
                    console.print(
                        Text("  Body: ", style="dim"), Text(result.response_body)
                    )

        console.print(Text("\nStress Test Results", style="bold cyan"))
        console.print(Text("===================", style="cyan"))
        console.print(
            Text("Concurrency: ", style="dim"), Text(str(concurrency), style="cyan")
        )
        console.print(
            Text("Full harvests: ", style="dim"),
            Text(str(self.full_harvests), style="green"),
        )

        console.print(Text("\nTiming:", style="bold"))
        console.print(
            Text("  Total duration: ", style="dim"),
            Text(f"{duration:.2f}s", style="cyan"),
        )
        if duration > 0:
            console.print(
                Text("  Requests/second: ", style="dim"),
                Text(f"{total / duration:.1f}", style="cyan"),
            )

        # Show timing stats for all requests
        self._format_timing_stats(all_times, "All requests", "cyan")

        # Show timing stats for successful requests if there are also failures
        if success_times.count > 0 and error_times.count > 0:
            self._format_timing_stats(success_times, "Successful requests", "green")

        # Show timing stats for errors if there are any
        if error_times.count > 0:
            self._format_timing_stats(error_times, "Failed requests", "red")

        console.print(Text("\nResults:", style="bold"))
        console.print(Text("  Total requests: ", style="dim"), Text(str(total)))
        if total > 0:
            success_pct = (successful / total) * 100
            fail_pct = (failed / total) * 100
            console.print(
                Text("  Successful: ", style="dim"),
                Text(f"{successful}", style="green"),
                Text(f" ({success_pct:.1f}%)"),
            )
            if failed > 0:
                console.print(
                    Text("  Failed: ", style="dim"),
                    Text(f"{failed}", style="red"),
                    Text(f" ({fail_pct:.1f}%)"),
                )
                failures_by_status = self.failures_by_status
                for status, count in sorted(failures_by_status.items()):
                    console.print(
                        Text("    - ", style="dim"),
                        Text(str(status), style="red"),
                        Text(f": {count}"),
                    )
            else:
                console.print(
                    Text("  Failed: ", style="dim"), Text(f"{failed} ({fail_pct:.1f}%)")
                )


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
                progress.update(requests_task, completed=stats.total_requests)

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
