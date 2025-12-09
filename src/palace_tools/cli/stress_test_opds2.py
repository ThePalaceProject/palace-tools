from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Self

import httpx
import typer
from httpx import Limits, Response, Timeout
from rich.progress import (
    Progress,
    ProgressColumn,
    SpinnerColumn,
    Task,
    TimeElapsedColumn,
)
from rich.text import Text

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


@dataclass
class RunningStats:
    """Running statistics that can be updated incrementally without storing all values."""

    count: int = 0
    total: float = 0.0
    min_val: float = float("inf")
    max_val: float = float("-inf")

    def add(self, value: float) -> None:
        self.count += 1
        self.total += value
        self.min_val = min(self.min_val, value)
        self.max_val = max(self.max_val, value)

    @property
    def avg(self) -> float:
        return self.total / self.count if self.count > 0 else 0.0


@dataclass
class StressTestStats:
    # Keep only a limited number of recent failures for debugging
    max_recent_failures: int = 50

    # Running statistics instead of storing all results
    _success_times: RunningStats = field(default_factory=RunningStats)
    _error_times: RunningStats = field(default_factory=RunningStats)
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

    def success_response_times(self) -> RunningStats:
        return self._success_times

    def error_response_times(self) -> RunningStats:
        return self._error_times

    def failed_results(self) -> Sequence[RequestResult]:
        return self._recent_failures

    def failures_by_status(self) -> dict[int, int]:
        return dict(self._failures_by_status)

    def total_duration(self) -> float:
        return self.end_time - self.start_time

    @staticmethod
    def _format_timing_stats(times: RunningStats, label: str) -> None:
        if times.count > 0:
            print(f"  {label}:")
            print(f"    Avg: {times.avg * 1000:.0f}ms")
            print(f"    Min: {times.min_val * 1000:.0f}ms")
            print(f"    Max: {times.max_val * 1000:.0f}ms")

    def display(self, concurrency: int) -> None:
        duration = self.total_duration()
        total = self.total_requests()
        successful = self.successful_requests()
        failed = self.failed_requests()
        success_times = self.success_response_times()
        error_times = self.error_response_times()
        failed_results = self.failed_results()

        # Print error details first if there are any
        if failed_results:
            print("\nError Details")
            print("=============")
            for i, result in enumerate(failed_results, 1):
                print(f"\n[Error {i}]")
                print(f"  URL: {result.url}")
                print(f"  Status: {result.status_code}")
                print(f"  Response time: {result.response_time * 1000:.0f}ms")
                if result.response_headers:
                    print("  Headers:")
                    for key, value in result.response_headers.items():
                        print(f"    {key}: {value}")
                if result.response_body:
                    print(f"  Body: {result.response_body}")

        print("\nStress Test Results")
        print("===================")
        print(f"Concurrency: {concurrency}")
        print(f"Full harvests: {self.full_harvests}")

        print("\nTiming:")
        print(f"  Total duration: {duration:.2f}s")
        if duration > 0:
            print(f"  Requests/second: {total / duration:.1f}")

        # Show timing stats for successful requests
        self._format_timing_stats(success_times, "Successful requests")

        # Show timing stats for errors if there are any
        if error_times.count > 0:
            self._format_timing_stats(error_times, "Failed requests")

        print("\nResults:")
        print(f"  Total requests: {total}")
        if total > 0:
            success_pct = (successful / total) * 100
            fail_pct = (failed / total) * 100
            print(f"  Successful: {successful} ({success_pct:.1f}%)")
            print(f"  Failed: {failed} ({fail_pct:.1f}%)")

            failures_by_status = self.failures_by_status()
            for status, count in sorted(failures_by_status.items()):
                print(f"    - {status}: {count}")


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
                                print(
                                    f"Max retries exceeded for {response_url}. Exiting stress test."
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
