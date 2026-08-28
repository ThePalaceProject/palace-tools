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

from palace.tools.constants import DEFAULT_USER_AGENT
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
        # The User-Agent seen on each kind of request. The token endpoint is
        # reached with a client of its own, so it's tracked separately.
        self.token_user_agents: set[str] = set()
        self.api_user_agents: set[str] = set()
        self._valid: set[str] = set()
        self._issued = 0

    @property
    def current_token(self) -> str:
        return f"token-{self._issued}"

    def revoke_all(self) -> None:
        """Invalidate every outstanding token, without warning."""
        self._valid.clear()

    def issue_token(self, request: httpx.Request) -> httpx.Response:
        self.token_user_agents.add(request.headers.get("User-Agent", ""))
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
        self.api_user_agents.add(request.headers.get("User-Agent", ""))
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
        if path.endswith("/availability"):
            product_id = path.split("/")[-2]
            # The two availability endpoints name the product differently.
            key = "reserveId" if path.startswith("/v2/") else "id"
            return httpx.Response(200, json={key: product_id, "copiesOwned": 1})
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
def held_at_once(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Samples how many products a harvest is holding, every time it takes one."""
    samples: list[int] = []

    class Sampling(overdrive.PendingProducts):
        def add(self, product: dict[str, Any]) -> bool:
            added = super().add(product)
            samples.append(len(self._products))
            return added

    monkeypatch.setattr(overdrive, "PendingProducts", Sampling)
    return samples


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

    async def test_token_request_identifies_itself(self) -> None:
        """The token endpoint is reached with a client of its own, which used
        to go out with httpx's default User-Agent instead of ours."""
        fake = FakeOverdrive()
        async with auth_client(fake) as client:
            await client.get(API_URL)

        assert fake.token_requests == 1
        assert fake.token_user_agents == {DEFAULT_USER_AGENT}

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
                with pytest.raises(overdrive.OverdriveError) as exc_info:
                    await client.get(API_URL)

        assert f"Giving up after {MAX_ATTEMPTS} attempts." in str(exc_info.value)
        assert token_route.call_count == MAX_ATTEMPTS

    async def test_bad_credentials_are_not_retried(self) -> None:
        async with respx.mock(assert_all_called=False) as router:
            token_route = router.post(overdrive.TOKEN_ENDPOINT).mock(
                return_value=httpx.Response(401, json={"error": "invalid_client"})
            )
            async with httpx.AsyncClient(
                auth=overdrive.OverdriveAuth("key", "secret")
            ) as client:
                with pytest.raises(overdrive.OverdriveError) as exc_info:
                    await client.get(API_URL)

        assert "invalid_client" in str(exc_info.value)
        assert token_route.call_count == 1

    def test_cannot_be_used_with_a_sync_client(self) -> None:
        auth = overdrive.OverdriveAuth("key", "secret")
        with httpx.Client(auth=auth) as client:
            with pytest.raises(RuntimeError, match="AsyncClient"):
                client.get(API_URL)


async def fetch_feed(
    collected: list[dict[str, Any]] | None = None,
    **overrides: Any,
) -> list[dict[str, Any]]:
    """Harvest whatever the router currently in force is serving.

    ``fetch`` yields products as it completes them, so a harvest that aborts
    has already handed some over. Pass ``collected`` to keep hold of those.
    """
    products = [] if collected is None else collected
    kwargs: dict[str, Any] = {
        "library_id": "1234",
        "parent_library_id": None,
        "fetch_metadata": True,
        "fetch_availability": False,
        "connections": 4,
        "skip_not_found": False,
        **overrides,
    }
    async for product in overdrive.fetch(
        f"https://{API_HOST}", "key", "secret", **kwargs
    ):
        products.append(product)
    return products


async def harvest(fake: FakeFeed, **overrides: Any) -> list[dict[str, Any]]:
    async with overdrive_api(fake):
        return await fetch_feed(**overrides)


class TestFetch:
    """The full harvest loop, which is where an expiring token first bit us."""

    async def test_harvests_every_product(self) -> None:
        fake = FakeFeed(item_count=10, page_size=5)

        products = await harvest(fake)

        assert len(products) == 10
        assert all("metadata" in product for product in products)
        assert fake.token_requests == 1
        assert fake.unauthorized == 0
        # Every request a harvest makes identifies itself, feed and token alike.
        assert fake.api_user_agents == {DEFAULT_USER_AGENT}
        assert fake.token_user_agents == {DEFAULT_USER_AGENT}

    async def test_harvest_survives_a_token_expiring_partway_through(self) -> None:
        # Before token refresh, the harvest died here: every request from the
        # revocation onwards failed with a 401 until the retry budget ran out.
        fake = FakeFeed(item_count=10, page_size=5, revoke_after=4)

        products = await harvest(fake)

        assert len(products) == 10
        assert all("metadata" in product for product in products)
        # The token really was rejected, and replaced exactly once.
        assert fake.unauthorized > 0
        assert fake.token_requests == 2


class BrokenMetadataFeed(FakeFeed):
    """A feed with one product whose metadata request never succeeds."""

    def __init__(
        self,
        item_count: int,
        page_size: int,
        broken_product: str,
        status: int = 500,
    ) -> None:
        super().__init__(item_count, page_size)
        self.broken_product = broken_product
        self.status = status

    def respond(self, request: httpx.Request) -> httpx.Response:
        if self._is_broken(request):
            return httpx.Response(self.status, json={"error": "no"})
        return super().respond(request)

    def _is_broken(self, request: httpx.Request) -> bool:
        path = request.url.path
        return path.endswith("/metadata") and path.split("/")[-2] == self.broken_product


class RepeatingFeed(FakeFeed):
    """A feed that lists one of its products on every page.

    Paging a collection that is being edited underneath the harvest can do
    this, and it used to be hidden by collecting the feed into one dict.
    """

    def __init__(self, item_count: int, page_size: int, repeated: str) -> None:
        super().__init__(item_count, page_size)
        self.repeated = repeated

    def _products_page(self, request: httpx.Request) -> httpx.Response:
        response = super()._products_page(request)
        page = response.json()
        listed = {product["id"] for product in page["products"]}
        if page["products"] and self.repeated not in listed:
            index = int(self.repeated.removeprefix("PID"))
            page["products"].append(self._product(index))
        return httpx.Response(200, json=page)


class NoMetadataFeed(FakeFeed):
    """A feed that has no metadata for any of its products."""

    def respond(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/metadata"):
            return httpx.Response(404, json={"error": "not found"})
        return super().respond(request)


class ConfusedFeed(FakeFeed):
    """A feed that answers a metadata request with a product it never listed.

    Stands in for the unforeseen: a response the harvest has no idea what to do
    with, which blows up somewhere other than the paths that expect to fail.
    """

    def respond(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/metadata"):
            return httpx.Response(200, json={"id": "PID9999", "title": "Who?"})
        return super().respond(request)


class TestPartialHarvest:
    """A harvest that ends early keeps what it downloaded.

    A harvest runs for hours, so whatever it collected before it died is worth
    keeping, even though the feed is incomplete. Products it finished have
    already been handed over by then; ``HarvestAborted`` carries the ones that
    were still waiting on a request.
    """

    async def _abort(
        self, fake: FakeFeed
    ) -> tuple[list[dict[str, Any]], overdrive.HarvestAborted]:
        """Harvest until it fails, returning what was yielded and what wasn't."""
        yielded: list[dict[str, Any]] = []
        async with overdrive_api(fake):
            with pytest.raises(overdrive.HarvestAborted) as exc_info:
                await fetch_feed(yielded)
        return yielded, exc_info.value

    async def test_a_request_that_never_succeeds_keeps_the_rest(self) -> None:
        fake = BrokenMetadataFeed(item_count=10, page_size=5, broken_product="PID0003")

        yielded, aborted = await self._abort(fake)

        assert f"Giving up after {MAX_ATTEMPTS} attempts." in str(aborted)
        # Every product the feed listed is accounted for, with the metadata of
        # all but the one whose request kept failing.
        harvested = yielded + aborted.products
        assert sorted(product["id"] for product in harvested) == [
            f"PID{index:04d}" for index in range(10)
        ]
        assert sorted(product["id"] for product in yielded) == [
            f"PID{index:04d}" for index in range(10) if index != 3
        ]
        # The one still waiting on its metadata is the one that never arrived.
        assert [product["id"] for product in aborted.products] == ["PID0003"]

    async def test_a_token_that_cannot_be_refreshed_keeps_the_rest(self) -> None:
        """The failure this is really for: a token expires hours into a
        harvest, and the token endpoint is down when we go to replace it."""
        fake = FakeFeed(item_count=10, page_size=5, revoke_after=5)
        issued = 0

        def issue_one_token(request: httpx.Request) -> httpx.Response:
            nonlocal issued
            issued += 1
            if issued > 1:
                return httpx.Response(503)
            return fake.issue_token(request)

        yielded: list[dict[str, Any]] = []
        async with respx.mock(assert_all_called=False) as router:
            router.post(overdrive.TOKEN_ENDPOINT).mock(side_effect=issue_one_token)
            router.get(host=API_HOST).mock(side_effect=fake.respond)

            with pytest.raises(overdrive.HarvestAborted) as exc_info:
                await fetch_feed(yielded)

        aborted = exc_info.value
        assert f"Giving up after {MAX_ATTEMPTS} attempts." in str(aborted)
        # The token really was rejected, and really couldn't be replaced.
        assert fake.unauthorized > 0
        assert issued > 1
        # The products listed by the pages fetched before the token expired.
        assert len(yielded) + len(aborted.products) == 10

    async def test_an_unforeseen_error_keeps_the_rest(self) -> None:
        fake = ConfusedFeed(item_count=10, page_size=5)

        yielded, aborted = await self._abort(fake)

        assert "KeyError" in str(aborted)
        assert len(yielded) + len(aborted.products) == 10

    async def test_an_interrupted_harvest_keeps_what_it_had(self) -> None:
        """Ctrl-C hours into a harvest shouldn't throw the hours away.

        ``asyncio.run`` turns a Ctrl-C into a cancellation of the coroutine it
        is running, which is what this does to it by hand.
        """
        fake = FakeFeed(item_count=10, page_size=5)
        metadata_served = asyncio.Event()

        def note_metadata(request: httpx.Request) -> httpx.Response:
            response = fake.respond(request)
            if request.url.path.endswith("/metadata"):
                metadata_served.set()
            return response

        yielded: list[dict[str, Any]] = []
        async with respx.mock(assert_all_called=False) as router:
            router.post(overdrive.TOKEN_ENDPOINT).mock(side_effect=fake.issue_token)
            router.get(host=API_HOST).mock(side_effect=note_metadata)

            harvesting = asyncio.create_task(fetch_feed(yielded))
            # Interrupt once the pages are in and metadata is being fetched.
            await metadata_served.wait()
            harvesting.cancel()

            with pytest.raises(overdrive.HarvestAborted) as exc_info:
                await harvesting

        aborted = exc_info.value
        assert str(aborted) == "Harvest interrupted."
        # Every product the pages listed, most still waiting on metadata.
        assert len(yielded) + len(aborted.products) == 10
        assert aborted.products

    async def test_a_harvest_that_finishes_does_not_raise(self) -> None:
        """The abort handling shouldn't fire on the way out of a good harvest."""
        products = await harvest(FakeFeed(item_count=10, page_size=5))

        assert len(products) == 10


class TestStreaming:
    """Products are handed over as they complete, not accumulated.

    A large collection's feed is far too big to hold in memory, so the harvest
    keeps only the products with a request still in flight.
    """

    async def test_holds_on_to_no_more_than_the_requests_in_flight(
        self, held_at_once: list[int]
    ) -> None:
        """The point of the whole thing: memory tracks concurrency, not size.

        Doubling the size of the collection must not change how much of it is
        held in memory at once.
        """
        small = await harvest(FakeFeed(item_count=100, page_size=10), connections=2)
        small_peak = max(held_at_once)
        held_at_once.clear()

        large = await harvest(FakeFeed(item_count=400, page_size=10), connections=2)
        large_peak = max(held_at_once)

        assert len(small) == 100
        assert len(large) == 400
        assert large_peak == small_peak
        # Bounded by the pages in flight, not by the 400 products harvested.
        assert large_peak < 100

    async def test_a_product_is_yielded_only_once_it_is_complete(self) -> None:
        fake = FakeFeed(item_count=10, page_size=5)

        products = await harvest(fake, fetch_availability=True)

        assert len(products) == 10
        for product in products:
            assert "metadata" in product
            assert "availability" in product
            assert "availabilityV2" in product

    async def test_a_product_with_nothing_to_fetch_is_yielded_straight_away(
        self,
    ) -> None:
        fake = FakeFeed(item_count=10, page_size=5)

        products = await harvest(fake, fetch_metadata=False)

        assert len(products) == 10
        assert not any("metadata" in product for product in products)

    async def test_a_title_on_two_pages_is_harvested_once(self) -> None:
        """Paging a collection that is being edited can list a title twice.

        Collecting the feed into one dict keyed by id used to hide that.
        """
        fake = RepeatingFeed(item_count=10, page_size=5, repeated="PID0000")

        products = await harvest(fake)

        assert sorted(product["id"] for product in products) == [
            f"PID{index:04d}" for index in range(10)
        ]

    async def test_a_skipped_request_does_not_strand_its_product(self) -> None:
        fake = BrokenMetadataFeed(
            item_count=10, page_size=5, broken_product="PID0003", status=404
        )

        products = await harvest(fake, skip_not_found=True)

        assert sorted(product["id"] for product in products) == [
            f"PID{index:04d}" for index in range(10)
        ]
        assert [product["id"] for product in products if "metadata" not in product] == [
            "PID0003"
        ]

    async def test_skipped_products_are_released_as_they_are_skipped(
        self, held_at_once: list[int]
    ) -> None:
        """A product whose only request 404s is never getting it, so it has to
        be let go of there and then rather than held to the end of the run."""
        fake = NoMetadataFeed(item_count=100, page_size=10)

        products = await harvest(fake, connections=2, skip_not_found=True)

        assert len(products) == 100
        assert not any("metadata" in product for product in products)
        # Held at once stays near the pages in flight, nowhere near all 100.
        assert max(held_at_once) < 50


class TestPendingProducts:
    def test_releases_a_product_once_its_last_request_lands(self) -> None:
        pending = overdrive.PendingProducts(2)
        assert pending.add({"id": "PID0000"}) is True

        pending.attach("pid0000", "availability", {"copies": 1})
        assert pending.take_finished() == []

        pending.attach("pid0000", "availabilityV2", {"copies": 2})
        assert pending.take_finished() == [
            {
                "id": "PID0000",
                "availability": {"copies": 1},
                "availabilityV2": {"copies": 2},
            }
        ]
        # Released means released: it isn't still being held.
        assert pending.take_remaining() == []

    def test_releases_a_product_with_nothing_to_wait_for(self) -> None:
        pending = overdrive.PendingProducts(0)

        assert pending.add({"id": "PID0000"}) is True

        assert pending.take_finished() == [{"id": "PID0000"}]

    def test_refuses_a_product_it_has_already_seen(self) -> None:
        pending = overdrive.PendingProducts(1)
        pending.add({"id": "PID0000"})
        pending.attach("pid0000", "metadata", {})
        pending.take_finished()

        # Already harvested and let go of, so it isn't taken up again.
        assert pending.add({"id": "PID0000"}) is False
        assert pending.take_finished() == []

    def test_giving_up_releases_a_product_that_is_only_waiting_on_that(self) -> None:
        pending = overdrive.PendingProducts(1)
        pending.add({"id": "PID0000"})

        pending.give_up_on("pid0000")

        assert pending.take_finished() == [{"id": "PID0000"}]

    def test_giving_up_on_a_product_it_does_not_hold_is_harmless(self) -> None:
        pending = overdrive.PendingProducts(1)

        pending.give_up_on("pid9999")

        assert pending.take_finished() == []

    def test_take_remaining_includes_products_not_yet_taken(self) -> None:
        pending = overdrive.PendingProducts(1)
        pending.add({"id": "PID0000"})
        pending.attach("pid0000", "metadata", {})
        pending.add({"id": "PID0001"})

        # The finished product and the one still waiting, both handed back.
        assert sorted(product["id"] for product in pending.take_remaining()) == [
            "PID0000",
            "PID0001",
        ]
        assert pending.take_remaining() == []


class TestAttachedProductId:
    @pytest.mark.parametrize(
        "url, expected",
        [
            (
                f"https://{API_HOST}/v1/collections/C/products/PID0001/metadata",
                "pid0001",
            ),
            (
                f"https://{API_HOST}/v1/collections/C/products/PID0001/availability",
                "pid0001",
            ),
            (
                f"https://{API_HOST}/v2/collections/C/products/PID0001/availability",
                "pid0001",
            ),
            # A page of the feed belongs to no single product.
            (f"https://{API_HOST}/v1/collections/C/products?offset=200", None),
            (f"https://{API_HOST}/v1/libraries/1234", None),
        ],
    )
    def test_reads_the_product_out_of_a_url(
        self, url: str, expected: str | None
    ) -> None:
        assert overdrive.attached_product_id(url) == expected
