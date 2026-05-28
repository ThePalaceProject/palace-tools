"""Tests for the streaming download helpers."""

from __future__ import annotations

import asyncio
from io import BytesIO

import httpx

from palace.tools.utils.http.streaming import streaming_fetch


def test_streaming_fetch_follows_redirects_using_existing_client() -> None:
    """A passed-in client is reused and redirects are followed by default.

    The download endpoint commonly returns a 302 to a (signed) storage URL, so
    ``streaming_fetch`` must follow it. Using a ``MockTransport`` also proves the
    supplied ``http_client`` is reused: if a fresh client were created instead,
    our handler would never run.
    """
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        if request.url.path == "/download":
            return httpx.Response(
                302, headers={"Location": "https://storage.example.com/object"}
            )
        return httpx.Response(200, content=b"audiobook-bytes")

    async def run() -> tuple[httpx.Response, bytes]:
        buffer = BytesIO()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            response = await streaming_fetch(
                "https://app.example.com/download",
                into_files=buffer,
                http_client=client,
            )
        return response, buffer.getvalue()

    response, body = asyncio.run(run())

    assert seen_paths == ["/download", "/object"]
    assert body == b"audiobook-bytes"
    assert str(response.url) == "https://storage.example.com/object"


def test_streaming_fetch_auth_none_suppresses_client_credentials() -> None:
    """``auth=None`` drops the client's auth, e.g. for a public storage redirect.

    A publication download often redirects to a public object-storage URL that
    rejects an unexpected ``Authorization`` header, so callers must be able to
    suppress the credentials configured on the shared client.
    """

    def record_auth_header(seen: list[str | None]) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.headers.get("Authorization"))
            return httpx.Response(200, content=b"bytes")

        return httpx.MockTransport(handler)

    async def default_auth() -> str | None:
        seen: list[str | None] = []
        async with httpx.AsyncClient(
            transport=record_auth_header(seen), auth=httpx.BasicAuth("user", "pass")
        ) as client:
            await streaming_fetch(
                "https://app.example.com/download",
                into_files=BytesIO(),
                http_client=client,
            )
        return seen[0]

    async def no_auth() -> str | None:
        seen: list[str | None] = []
        async with httpx.AsyncClient(
            transport=record_auth_header(seen), auth=httpx.BasicAuth("user", "pass")
        ) as client:
            await streaming_fetch(
                "https://app.example.com/download",
                into_files=BytesIO(),
                http_client=client,
                auth=None,
            )
        return seen[0]

    # By default the client's BasicAuth is applied; auth=None suppresses it.
    assert asyncio.run(default_auth()) is not None
    assert asyncio.run(no_auth()) is None


def test_streaming_fetch_can_opt_out_of_redirects() -> None:
    """Callers can disable redirect following with ``follow_redirects=False``."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302, headers={"Location": "https://storage.example.com/object"}
        )

    async def run() -> httpx.Response:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await streaming_fetch(
                "https://app.example.com/download",
                into_files=BytesIO(),
                http_client=client,
                follow_redirects=False,
            )

    response = asyncio.run(run())

    assert response.status_code == 302
