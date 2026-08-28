"""Tests for the shared async HTTP client.

Every request Palace makes should identify itself, so the User-Agent is a
client default rather than something each call site remembers to pass.
"""

from __future__ import annotations

import httpx
import pytest

from palace.tools.constants import DEFAULT_USER_AGENT
from palace.tools.utils.http.async_client import HTTPXAsyncClient


def echo_transport(seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    return httpx.MockTransport(handler)


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE", "PATCH"])
async def test_user_agent_is_set_on_every_method(method: str) -> None:
    seen: list[httpx.Request] = []
    async with HTTPXAsyncClient(transport=echo_transport(seen)) as client:
        await client.request(method, "https://example.com/thing")

    assert seen[0].headers["User-Agent"] == DEFAULT_USER_AGENT


async def test_user_agent_is_set_on_streamed_requests() -> None:
    """stream() doesn't go through request(), so it needs a client default."""
    seen: list[httpx.Request] = []
    async with HTTPXAsyncClient(transport=echo_transport(seen)) as client:
        async with client.stream("GET", "https://example.com/download") as response:
            await response.aread()

    assert seen[0].headers["User-Agent"] == DEFAULT_USER_AGENT


async def test_user_agent_is_set_on_sent_requests() -> None:
    """send() bypasses request() as well."""
    seen: list[httpx.Request] = []
    async with HTTPXAsyncClient(transport=echo_transport(seen)) as client:
        await client.send(client.build_request("GET", "https://example.com/thing"))

    assert seen[0].headers["User-Agent"] == DEFAULT_USER_AGENT


async def test_user_agent_can_be_overridden_for_the_client() -> None:
    seen: list[httpx.Request] = []
    async with HTTPXAsyncClient(
        "Palace/test", transport=echo_transport(seen)
    ) as client:
        await client.get("https://example.com/thing")

    assert seen[0].headers["User-Agent"] == "Palace/test"


async def test_user_agent_can_be_overridden_per_request() -> None:
    seen: list[httpx.Request] = []
    async with HTTPXAsyncClient(transport=echo_transport(seen)) as client:
        await client.get(
            "https://example.com/thing", headers={"User-Agent": "Something/else"}
        )

    assert seen[0].headers["User-Agent"] == "Something/else"


async def test_other_client_headers_are_kept() -> None:
    seen: list[httpx.Request] = []
    async with HTTPXAsyncClient(
        headers={"Accept": "application/opds+json"},
        transport=echo_transport(seen),
    ) as client:
        await client.get("https://example.com/thing")

    assert seen[0].headers["User-Agent"] == DEFAULT_USER_AGENT
    assert seen[0].headers["Accept"] == "application/opds+json"


async def test_client_headers_can_supply_the_user_agent() -> None:
    seen: list[httpx.Request] = []
    async with HTTPXAsyncClient(
        headers={"User-Agent": "Palace/from-headers"},
        transport=echo_transport(seen),
    ) as client:
        await client.get("https://example.com/thing")

    assert seen[0].headers["User-Agent"] == "Palace/from-headers"
