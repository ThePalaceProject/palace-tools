"""Shared HTTP retry policy for feed downloads.

Used by the OPDS, OPDS+ODL, and Overdrive feed clients. Retries on transient
failures (network errors, non-200 responses, malformed JSON bodies) up to
``MAX_ATTEMPTS`` total attempts (the initial request counts as attempt 1).
On terminal failure the process exits with code ``-1``.
"""

from __future__ import annotations

import sys
from json import JSONDecodeError
from typing import Any, NoReturn

import httpx

MAX_ATTEMPTS = 4


def _log_attempt(url: str, attempt: int, detail: str) -> None:
    print(f"Request error ({attempt}/{MAX_ATTEMPTS}): {detail} [{url}]")


def _exit_after_retries(url: str, last_error: str) -> NoReturn:
    print(f"Giving up after {MAX_ATTEMPTS} attempts.")
    print(f"URL: {url}")
    print(last_error)
    sys.exit(-1)


def request_with_retry_sync(client: httpx.Client, url: str) -> dict[str, Any]:
    last_error = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.get(url)
        except httpx.RequestError as e:
            last_error = f"Request error: {e}"
            _log_attempt(url, attempt, str(e))
            continue

        if response.status_code != 200:
            last_error = f"Status code: {response.status_code}\nBody: {response.text}"
            _log_attempt(url, attempt, f"HTTP {response.status_code}")
            continue

        try:
            return response.json()  # type: ignore[no-any-return]
        except JSONDecodeError as e:
            last_error = f"JSON decode error: {e}\nBody: {response.text}"
            _log_attempt(url, attempt, f"JSON decode error: {e}")
            continue

    _exit_after_retries(url, last_error)


async def request_with_retry_async(
    client: httpx.AsyncClient, url: str
) -> dict[str, Any]:
    last_error = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = await client.get(url)
        except httpx.RequestError as e:
            last_error = f"Request error: {e}"
            _log_attempt(url, attempt, str(e))
            continue

        if response.status_code != 200:
            last_error = f"Status code: {response.status_code}\nBody: {response.text}"
            _log_attempt(url, attempt, f"HTTP {response.status_code}")
            continue

        try:
            return response.json()  # type: ignore[no-any-return]
        except JSONDecodeError as e:
            last_error = f"JSON decode error: {e}\nBody: {response.text}"
            _log_attempt(url, attempt, f"JSON decode error: {e}")
            continue

    _exit_after_retries(url, last_error)
