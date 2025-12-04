from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from functools import cached_property
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
    response_headers: dict[str, str] | None = None
    response_body: str | None = None

    @cached_property
    def success(self) -> bool:
        return self.status_code == 200

    @classmethod
    def from_response(cls, response: Response) -> Self:
        return cls(
            url=str(response.url),
            status_code=response.status_code,
            response_time=response.elapsed.total_seconds(),
            response_headers=dict(response.headers),
            response_body=response.text,
        )


@dataclass
class StressTestStats:
    results: list[RequestResult] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0
    full_harvests: int = 0

    def add_result(self, result: RequestResult) -> None:
        self.results.append(result)

    def total_requests(self) -> int:
        return len(self.results)

    def successful_requests(self) -> int:
        return sum(1 for r in self.results if r.success)

    def failed_requests(self) -> int:
        return sum(1 for r in self.results if not r.success)

    def success_response_times(self) -> list[float]:
        return [r.response_time for r in self.results if r.success]

    def error_response_times(self) -> list[float]:
        return [r.response_time for r in self.results if not r.success]

    def failed_results(self) -> list[RequestResult]:
        return [r for r in self.results if not r.success]

    def failures_by_status(self) -> dict[int, int]:
        failures: defaultdict[int, int] = defaultdict(int)
        for r in self.results:
            if not r.success:
                failures[r.status_code] += 1
        return failures

    def total_duration(self) -> float:
        return self.end_time - self.start_time

    @staticmethod
    def _format_timing_stats(times: list[float], label: str) -> None:
        if times:
            avg_time = sum(times) / len(times)
            min_time = min(times)
            max_time = max(times)
            print(f"  {label}:")
            print(f"    Avg: {avg_time * 1000:.0f}ms")
            print(f"    Min: {min_time * 1000:.0f}ms")
            print(f"    Max: {max_time * 1000:.0f}ms")

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
                    # Truncate body if too long
                    body = result.response_body
                    if len(body) > 500:
                        body = body[:500] + "... [truncated]"
                    print(f"  Body: {body}")

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
        if error_times:
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
    username: str
    | None = typer.Option(
        None,
        "--username",
        "-u",
        help="Username for authentication",
    ),
    password: str
    | None = typer.Option(
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
) -> None:
    """Stress test an OPDS2 feed by fetching it multiple times in parallel."""
    # Create stats outside async so it survives interruption
    stats = StressTestStats()
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
