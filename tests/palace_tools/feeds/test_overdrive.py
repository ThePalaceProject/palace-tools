"""Tests for the Overdrive feed client, focused on access token refresh.

Overdrive access tokens live for about an hour, which is much shorter than a
full feed harvest takes, so the client has to notice an expiring or rejected
token and get a new one without losing any requests.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import respx

from palace.tools.feeds import overdrive
from palace.tools.feeds.retry import MAX_ATTEMPTS

API_HOST = "api.overdrive.com"
API_URL = f"https://{API_HOST}/v1/anything"
COLLECTION_TOKEN = "COL123"


class FakeClock:
    """Stands in for the ``time`` module so token expiry can be controlled."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeOverdrive:
    """An Overdrive API that issues, validates and revokes bearer tokens."""

    def __init__(self, expires_in: int | None = 3600) -> None:
        self.expires_in = expires_in
        self.token_requests = 0
        self.unauthorized = 0
        # The bearer token presented on each API request, in order.
        self.presented: list[str] = []
        self._valid: set[str] = set()
        self._issued = 0

    @property
    def current_token(self) -> str:
        return f"token-{self._issued}"

    def revoke_all(self) -> None:
        """Invalidate every outstanding token, without warning."""
        self._valid.clear()

    def issue_token(self, request: httpx.Request) -> httpx.Response:
        self.token_requests += 1
        self._issued += 1
        token = self.current_token
        self._valid.add(token)
        body: dict[str, Any] = {"access_token": token, "token_type": "bearer"}
        if self.expires_in is not None:
            body["expires_in"] = self.expires_in
        return httpx.Response(200, json=body)

    def check_auth(self, request: httpx.Request) -> httpx.Response | None:
        """Record the token presented, returning a 401 if it isn't valid."""
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        self.presented.append(token)
        if token not in self._valid:
            self.unauthorized += 1
            return httpx.Response(401, json={"errorCode": "AccessDenied"})
        return None

    def respond(self, request: httpx.Request) -> httpx.Response:
        return self.check_auth(request) or httpx.Response(200, json={"ok": True})


class FakeFeed(FakeOverdrive):
    """The slice of the Overdrive feed API that ``fetch`` walks.

    ``revoke_after`` invalidates every token once that many requests have been
    served, standing in for a token expiring partway through a harvest.
    """

    def __init__(
        self,
        item_count: int,
        page_size: int,
        revoke_after: int | None = None,
    ) -> None:
        super().__init__()
        self.item_count = item_count
        self.page_size = page_size
        self._revoke_after = revoke_after
        self._served = 0

    def respond(self, request: httpx.Request) -> httpx.Response:
        rejected = self.check_auth(request)
        if rejected is not None:
            return rejected

        self._served += 1
        if self._revoke_after is not None and self._served == self._revoke_after:
            self.revoke_all()

        path = request.url.path
        if path.startswith("/v1/libraries/"):
            return httpx.Response(200, json={"collectionToken": COLLECTION_TOKEN})
        if path == f"/v1/collections/{COLLECTION_TOKEN}/products":
            return self._products_page(request)
        if path.endswith("/metadata"):
            product_id = path.split("/")[-2]
            return httpx.Response(
                200, json={"id": product_id, "title": f"Title {product_id}"}
            )
        return httpx.Response(404, json={"error": "not found"})

    def _products_page(self, request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params.get("offset", 0))
        limit = int(request.url.params.get("limit", self.page_size))
        products = [
            self._product(index)
            for index in range(offset, min(offset + limit, self.item_count))
        ]
        return httpx.Response(
            200,
            json={
                "totalItems": self.item_count,
                "limit": self.page_size,
                "products": products,
            },
        )

    def _product(self, index: int) -> dict[str, Any]:
        product_id = f"PID{index:04d}"
        base = f"https://{API_HOST}/v1/collections/{COLLECTION_TOKEN}/products/{product_id}"
        v2 = f"https://{API_HOST}/v2/collections/{COLLECTION_TOKEN}/products/{product_id}"
        return {
            "id": product_id,
            "links": {
                "metadata": {"href": f"{base}/metadata"},
                "availability": {"href": f"{base}/availability"},
                "availabilityV2": {"href": f"{v2}/availability"},
            },
        }


@contextlib.asynccontextmanager
async def overdrive_api(
    fake: FakeOverdrive,
) -> AsyncIterator[respx.MockRouter]:
    """Route the token endpoint and the whole API host at ``fake``."""
    async with respx.mock(assert_all_called=False) as router:
        router.post(overdrive.TOKEN_ENDPOINT).mock(side_effect=fake.issue_token)
        router.get(host=API_HOST).mock(side_effect=fake.respond)
        yield router


@contextlib.asynccontextmanager
async def auth_client(fake: FakeOverdrive) -> AsyncIterator[httpx.AsyncClient]:
    async with overdrive_api(fake):
        async with httpx.AsyncClient(
            auth=overdrive.OverdriveAuth("key", "secret")
        ) as client:
            yield client


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Token request retries shouldn't make the suite sleep."""
    monkeypatch.setattr(overdrive, "TOKEN_RETRY_DELAY", 0.0)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake_clock = FakeClock()
    monkeypatch.setattr(overdrive, "time", fake_clock)
    return fake_clock


class TestOverdriveAuth:
    async def test_fetches_and_sends_a_bearer_token(self) -> None:
        fake = FakeOverdrive()
        async with auth_client(fake) as client:
            response = await client.get(API_URL)

        assert response.status_code == 200
        assert fake.token_requests == 1
        assert fake.presented == ["token-1"]

    async def test_reuses_a_valid_token(self) -> None:
        fake = FakeOverdrive()
        async with auth_client(fake) as client:
            for _ in range(5):
                assert (await client.get(API_URL)).status_code == 200

        assert fake.token_requests == 1
        assert fake.presented == ["token-1"] * 5
        assert fake.unauthorized == 0

    async def test_refreshes_before_the_token_expires(self, clock: FakeClock) -> None:
        fake = FakeOverdrive(expires_in=3600)
        async with auth_client(fake) as client:
            await client.get(API_URL)

            # Still inside the expiry margin, so the token is left alone.
            clock.advance(3600 - overdrive.TOKEN_EXPIRY_MARGIN - 1)
            await client.get(API_URL)
            assert fake.token_requests == 1

            # Now within the margin of expiring: replace it before use.
            clock.advance(2)
            await client.get(API_URL)

        assert fake.token_requests == 2
        assert fake.presented == ["token-1", "token-1", "token-2"]
        # The API never saw an expired token, so it never had to reject one.
        assert fake.unauthorized == 0

    async def test_assumes_a_default_lifetime_when_expires_in_is_missing(
        self, clock: FakeClock
    ) -> None:
        fake = FakeOverdrive(expires_in=None)
        async with auth_client(fake) as client:
            await client.get(API_URL)

            clock.advance(
                overdrive.DEFAULT_TOKEN_LIFETIME - overdrive.TOKEN_EXPIRY_MARGIN - 1
            )
            await client.get(API_URL)
            assert fake.token_requests == 1

            clock.advance(2)
            await client.get(API_URL)

        assert fake.token_requests == 2

    async def test_short_lived_token_keeps_half_its_lifetime(
        self, clock: FakeClock
    ) -> None:
        # A lifetime shorter than the expiry margin would otherwise be treated
        # as expired on arrival, and we'd fetch a token for every request.
        fake = FakeOverdrive(expires_in=100)
        assert 100 < overdrive.TOKEN_EXPIRY_MARGIN

        async with auth_client(fake) as client:
            await client.get(API_URL)

            clock.advance(49)
            await client.get(API_URL)
            assert fake.token_requests == 1

            clock.advance(2)
            await client.get(API_URL)

        assert fake.token_requests == 2

    async def test_refreshes_and_retries_when_the_token_is_rejected(self) -> None:
        fake = FakeOverdrive()
        async with auth_client(fake) as client:
            assert (await client.get(API_URL)).status_code == 200

            # The API drops the token early, without the client knowing.
            fake.revoke_all()
            response = await client.get(API_URL)

        # The caller sees a success: the 401 was absorbed and retried.
        assert response.status_code == 200
        assert fake.unauthorized == 1
        assert fake.token_requests == 2
        assert fake.presented == ["token-1", "token-1", "token-2"]

    async def test_gives_up_after_one_retry(self) -> None:
        """A token that is rejected even after refreshing returns the 401."""
        fake = FakeOverdrive()
        fake.revoke_all()

        async with overdrive_api(fake) as router:
            router.get(host=API_HOST).mock(
                return_value=httpx.Response(401, json={"errorCode": "AccessDenied"})
            )
            async with httpx.AsyncClient(
                auth=overdrive.OverdriveAuth("key", "secret")
            ) as client:
                response = await client.get(API_URL)

        assert response.status_code == 401
        # One initial fetch plus one refresh, rather than an endless loop.
        assert fake.token_requests == 2

    async def test_concurrent_requests_share_one_token_fetch(self) -> None:
        """Requests that start together shouldn't each fetch their own token."""
        fake = FakeOverdrive()
        release = asyncio.Event()

        async def slow_issue_token(request: httpx.Request) -> httpx.Response:
            await release.wait()
            return fake.issue_token(request)

        async with respx.mock(assert_all_called=False) as router:
            router.post(overdrive.TOKEN_ENDPOINT).mock(side_effect=slow_issue_token)
            router.get(host=API_HOST).mock(side_effect=fake.respond)

            async with httpx.AsyncClient(
                auth=overdrive.OverdriveAuth("key", "secret")
            ) as client:
                tasks = [asyncio.create_task(client.get(API_URL)) for _ in range(10)]
                # Let every request reach the token fetch before releasing it.
                await asyncio.sleep(0)
                release.set()
                responses = await asyncio.gather(*tasks)

        assert [r.status_code for r in responses] == [200] * 10
        assert fake.token_requests == 1
        assert fake.presented == ["token-1"] * 10

    async def test_concurrent_401s_trigger_a_single_refresh(self) -> None:
        """A wave of 401s from one expired token means one refresh, not many."""
        requests = 10
        fake = FakeOverdrive()
        # Hold every rejected request until they have all been rejected, so
        # they are all refreshing from the same token.
        barrier = asyncio.Barrier(requests)

        async def respond(request: httpx.Request) -> httpx.Response:
            response = fake.respond(request)
            if response.status_code == 401:
                await barrier.wait()
            return response

        async with respx.mock(assert_all_called=False) as router:
            router.post(overdrive.TOKEN_ENDPOINT).mock(side_effect=fake.issue_token)
            router.get(host=API_HOST).mock(side_effect=respond)

            async with httpx.AsyncClient(
                auth=overdrive.OverdriveAuth("key", "secret")
            ) as client:
                # Prime the token, then pull it out from under the requests.
                await client.get(API_URL)
                fake.revoke_all()

                responses = await asyncio.gather(
                    *(client.get(API_URL) for _ in range(requests))
                )

        assert [r.status_code for r in responses] == [200] * requests
        assert fake.unauthorized == requests
        # The initial fetch, plus exactly one refresh for the whole wave.
        assert fake.token_requests == 2


class TestTokenRequestFailures:
    async def test_retries_a_server_error(self) -> None:
        fake = FakeOverdrive()
        async with respx.mock(assert_all_called=False) as router:
            router.post(overdrive.TOKEN_ENDPOINT).mock(
                side_effect=[
                    httpx.Response(503),
                    httpx.Response(500),
                    fake.issue_token(httpx.Request("POST", overdrive.TOKEN_ENDPOINT)),
                ]
            )
            router.get(host=API_HOST).mock(side_effect=fake.respond)

            async with httpx.AsyncClient(
                auth=overdrive.OverdriveAuth("key", "secret")
            ) as client:
                response = await client.get(API_URL)

        assert response.status_code == 200

    async def test_retries_a_network_error(self) -> None:
        fake = FakeOverdrive()
        async with respx.mock(assert_all_called=False) as router:
            router.post(overdrive.TOKEN_ENDPOINT).mock(
                side_effect=[
                    httpx.ConnectError("connection refused"),
                    fake.issue_token(httpx.Request("POST", overdrive.TOKEN_ENDPOINT)),
                ]
            )
            router.get(host=API_HOST).mock(side_effect=fake.respond)

            async with httpx.AsyncClient(
                auth=overdrive.OverdriveAuth("key", "secret")
            ) as client:
                response = await client.get(API_URL)

        assert response.status_code == 200

    async def test_gives_up_after_max_attempts(self) -> None:
        async with respx.mock(assert_all_called=False) as router:
            token_route = router.post(overdrive.TOKEN_ENDPOINT).mock(
                return_value=httpx.Response(503)
            )
            async with httpx.AsyncClient(
                auth=overdrive.OverdriveAuth("key", "secret")
            ) as client:
                with pytest.raises(SystemExit) as exc_info:
                    await client.get(API_URL)

        assert exc_info.value.code == -1
        assert token_route.call_count == MAX_ATTEMPTS

    async def test_bad_credentials_are_not_retried(self) -> None:
        async with respx.mock(assert_all_called=False) as router:
            token_route = router.post(overdrive.TOKEN_ENDPOINT).mock(
                return_value=httpx.Response(401, json={"error": "invalid_client"})
            )
            async with httpx.AsyncClient(
                auth=overdrive.OverdriveAuth("key", "secret")
            ) as client:
                with pytest.raises(SystemExit) as exc_info:
                    await client.get(API_URL)

        assert exc_info.value.code == -1
        assert token_route.call_count == 1

    def test_cannot_be_used_with_a_sync_client(self) -> None:
        auth = overdrive.OverdriveAuth("key", "secret")
        with httpx.Client(auth=auth) as client:
            with pytest.raises(RuntimeError, match="AsyncClient"):
                client.get(API_URL)


class TestFetch:
    """The full harvest loop, which is where an expiring token first bit us."""

    async def _harvest(self, fake: FakeFeed) -> list[dict[str, Any]]:
        async with overdrive_api(fake):
            return await overdrive.fetch(
                f"https://{API_HOST}",
                "key",
                "secret",
                library_id="1234",
                parent_library_id=None,
                fetch_metadata=True,
                fetch_availability=False,
                connections=4,
                skip_not_found=False,
            )

    async def test_harvests_every_product(self) -> None:
        fake = FakeFeed(item_count=10, page_size=5)

        products = await self._harvest(fake)

        assert len(products) == 10
        assert all("metadata" in product for product in products)
        assert fake.token_requests == 1
        assert fake.unauthorized == 0

    async def test_harvest_survives_a_token_expiring_partway_through(self) -> None:
        # Before token refresh, the harvest died here: every request from the
        # revocation onwards failed with a 401 until the retry budget ran out.
        fake = FakeFeed(item_count=10, page_size=5, revoke_after=4)

        products = await self._harvest(fake)

        assert len(products) == 10
        assert all("metadata" in product for product in products)
        # The token really was rejected, and replaced exactly once.
        assert fake.unauthorized > 0
        assert fake.token_requests == 2
