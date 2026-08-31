from __future__ import annotations

import asyncio
import json
import math
import time
from collections import defaultdict, deque
from collections.abc import AsyncGenerator, AsyncIterator
from json import JSONDecodeError
from typing import Any

import httpx
from httpx import URL, HTTPStatusError, Limits, RequestError, Response, Timeout
from rich.progress import MofNCompleteColumn, Progress, SpinnerColumn

from palace.tools.feeds.retry import MAX_ATTEMPTS
from palace.tools.utils.http.async_client import HTTPXAsyncClient

QA_BASE_URL = "https://integration.api.overdrive.com"
PROD_BASE_URL = "https://api.overdrive.com"

TOKEN_ENDPOINT = "https://oauth.overdrive.com/token"
EVENTS_ENDPOINT = "/v1/collections/%(collection_token)s/products"
LIBRARY_ENDPOINT = "/v1/libraries/%(library_id)s"
ADVANTAGE_LIBRARY_ENDPOINT = (
    "/v1/libraries/%(parent_library_id)s/advantageAccounts/%(library_id)s"
)
ADVANTAGE_ACCOUNTS_ENDPOINT = "/v1/libraries/%(parent_library_id)s/advantageAccounts"

# Assumed token lifetime, in seconds, if the token response omits "expires_in".
DEFAULT_TOKEN_LIFETIME = 3600.0
# How long before a token actually expires we consider it expired, so that
# in-flight requests aren't sent with a token that expires mid-flight.
TOKEN_EXPIRY_MARGIN = 120.0
# Base delay, in seconds, between retries of a failed token request.
TOKEN_RETRY_DELAY = 1.0


class OverdriveError(Exception):
    """A response we can't use, or a request we've given up on."""


class HarvestAborted(OverdriveError):
    """A harvest that failed part way through, carrying what it still held.

    A full harvest runs for hours, so the products it was still waiting on
    when something went wrong are worth handing back even though the feed is
    incomplete -- everything already finished has been yielded by then. This
    is for failures only; a Ctrl-C is an ordinary cancellation and propagates.
    """

    def __init__(self, products: list[dict[str, Any]], cause: Exception) -> None:
        super().__init__(_abort_reason(cause))
        self.products = products


def _abort_reason(cause: Exception) -> str:
    # The errors we raise ourselves explain themselves; anything else may not
    # carry a message at all, so fall back to its repr.
    detail = str(cause) if isinstance(cause, OverdriveError) else repr(cause)
    return f"Harvest aborted: {detail}"


def raise_for_error(resp: Response) -> None:
    if resp.status_code == 200:
        return
    raise OverdriveError(
        "\n".join(
            [
                f"URL: {resp.url}",
                f"Error: {resp.status_code}",
                f"Headers: {json.dumps(dict(resp.headers), indent=4)}",
                resp.text,
            ]
        )
    )


class OverdriveAuth(httpx.Auth):
    """Bearer token authentication that transparently refreshes the token.

    Overdrive access tokens are short lived (an hour, typically), which is much
    shorter than a full feed harvest takes. Without refreshing, every request
    made after the token expires fails with a 401.

    The token is refreshed proactively once it is close to expiring, and
    reactively if the API rejects it with a 401 anyway. Refreshes are
    serialized, so a wave of concurrent 401s only triggers a single token
    request; requests that were using the token that has already been replaced
    just pick up the new one.
    """

    def __init__(
        self,
        client_key: str,
        client_secret: str,
        expiry_margin: float = TOKEN_EXPIRY_MARGIN,
    ) -> None:
        self._client_key = client_key
        self._client_secret = client_secret
        self._expiry_margin = expiry_margin
        self._token: str | None = None
        self._expires_at = 0.0
        # Incremented on every successful token fetch. Requests record the
        # generation of the token they used, so that when they get a 401 we can
        # tell whether the token has already been refreshed by someone else.
        self._generation = 0
        self._lock = asyncio.Lock()

    def sync_auth_flow(
        self, request: httpx.Request
    ) -> Any:  # pragma: no cover - async only
        raise RuntimeError("OverdriveAuth can only be used with an AsyncClient.")

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, Response]:
        token, generation = await self._current_token()
        request.headers["Authorization"] = f"Bearer {token}"
        response = yield request

        if response.status_code != 401:
            return

        # The token was rejected, most likely because it expired. Refresh it
        # and give the request one more try with the new token.
        token, _ = await self._refresh_token(generation)
        request.headers["Authorization"] = f"Bearer {token}"
        yield request

    async def _current_token(self) -> tuple[str, int]:
        # These reads happen without awaiting, so they see a consistent token,
        # expiry and generation.
        token = self._token
        generation = self._generation
        if token is not None and time.monotonic() < self._expires_at:
            return token, generation
        return await self._refresh_token(generation)

    async def _refresh_token(self, seen_generation: int) -> tuple[str, int]:
        async with self._lock:
            if self._token is not None and self._generation != seen_generation:
                # Someone else already replaced the token we were using.
                return self._token, self._generation
            return await self._fetch_token()

    async def _fetch_token(self) -> tuple[str, int]:
        """Request a new access token. Called with ``self._lock`` held."""
        async with HTTPXAsyncClient(timeout=Timeout(20.0)) as token_client:
            for attempt in range(1, MAX_ATTEMPTS + 1):
                detail: str
                try:
                    response = await token_client.post(
                        TOKEN_ENDPOINT,
                        auth=(self._client_key, self._client_secret),
                        data=dict(grant_type="client_credentials"),
                    )
                except RequestError as e:
                    detail = str(e)
                else:
                    if response.status_code < 500:
                        # A 200 gives us a token, anything else in this range
                        # (bad credentials, for example) won't be fixed by
                        # retrying, so let raise_for_error report it.
                        raise_for_error(response)
                        return self._store_token(response.json())
                    detail = f"HTTP {response.status_code}"

                print(
                    f"Token request error ({attempt}/{MAX_ATTEMPTS}): "
                    f"{detail} [{TOKEN_ENDPOINT}]"
                )
                if attempt < MAX_ATTEMPTS:
                    await asyncio.sleep(TOKEN_RETRY_DELAY * attempt)

        raise OverdriveError(
            f"Giving up after {MAX_ATTEMPTS} attempts.\nURL: {TOKEN_ENDPOINT}"
        )

    def _store_token(self, data: dict[str, Any]) -> tuple[str, int]:
        expires_in = float(data.get("expires_in", DEFAULT_TOKEN_LIFETIME))
        # Retire the token early, so it doesn't expire on an in-flight request.
        # Never treat it as valid for less than half its lifetime though, or a
        # surprisingly short-lived token would have us fetching a new one for
        # every single request.
        lifetime = max(expires_in - self._expiry_margin, expires_in / 2)
        self._token = str(data["access_token"])
        self._expires_at = time.monotonic() + lifetime
        self._generation += 1
        return self._token, self._generation


async def get_collection_token(
    http: httpx.AsyncClient,
    library_id: str,
    parent_library_id: str | None,
    use_consortial_plus_advantage_feed: bool = False,
) -> str:
    variables = {
        "parent_library_id": parent_library_id,
        "library_id": library_id,
    }

    if parent_library_id:
        if use_consortial_plus_advantage_feed:
            endpoint = ADVANTAGE_ACCOUNTS_ENDPOINT % variables
            resp = await http.get(endpoint)
            raise_for_error(resp)
            accounts = resp.json()["advantageAccounts"]
            for account in accounts:
                if account["id"] == int(library_id):
                    return str(account["collectionToken"])

            raise OverdriveError(f"No Advantage account found for library {library_id}")
        else:
            endpoint = ADVANTAGE_LIBRARY_ENDPOINT
    else:
        endpoint = LIBRARY_ENDPOINT

    resp = await http.get(endpoint % variables)
    raise_for_error(resp)
    return resp.json()["collectionToken"]  # type: ignore[no-any-return]


def event_url(
    collection_token: str,
    sort: str = "popularity:desc",
    limit: int = 200,
    offset: int | None = None,
) -> str:
    url = EVENTS_ENDPOINT % {"collection_token": collection_token}
    params = {"sort": sort, "limit": limit}
    if offset is not None:
        params["offset"] = offset

    return url + "?" + "&".join(f"{k}={v}" for k, v in params.items())


def make_request(
    client: httpx.AsyncClient,
    urls: deque[str] | str,
    pending_requests: list[asyncio.Task[Response]],
) -> None:
    if isinstance(urls, str):
        url = urls
    else:
        url = urls.pop()
    req = client.get(url)
    task = asyncio.create_task(req)
    pending_requests.append(task)


def requests_per_product(fetch_metadata: bool, fetch_availability: bool) -> int:
    """How many requests follow each product a feed page lists.

    Metadata is one request; availability is two, v1 and v2. Kept next to the
    ``process_request`` branch that enqueues them, because a count that
    disagrees with the URLs actually made either strands products until the
    end of the harvest or releases them before their last response lands.
    """
    return (1 if fetch_metadata else 0) + (2 if fetch_availability else 0)


class PendingProducts:
    """Products that are still waiting on requests, and the ones that aren't.

    A page of the feed gives a product, and each of the metadata and
    availability requests that follow fills in a bit more of it. A large
    collection's worth of those is far too much to hold in memory at once, so
    a product is released the moment nothing more is coming for it and then
    dropped. What's left in here at any moment is only what's in flight.
    """

    def __init__(self, attachments_per_product: int) -> None:
        self._attachments = attachments_per_product
        self._products: dict[str, dict[str, Any]] = {}
        self._outstanding: dict[str, int] = {}
        self._finished: list[dict[str, Any]] = []
        # Ids are kept for the whole harvest, unlike the products themselves.
        # A title listed on two pages would otherwise be fetched and written
        # out twice, where collecting the feed in one dict deduplicated it.
        self._seen: set[str] = set()

    def add(self, product: dict[str, Any]) -> bool:
        """Start tracking a product listed by a feed page.

        Returns False for a product already listed by an earlier page, whose
        requests have been made already.
        """
        product_id = product["id"].lower()
        if product_id in self._seen:
            return False

        self._seen.add(product_id)
        if not self._attachments:
            self._finished.append(product)
        else:
            self._products[product_id] = product
            self._outstanding[product_id] = self._attachments
        return True

    def attach(self, product_id: str, key: str, data: Any) -> None:
        """Add a metadata or availability document to the product it belongs to."""
        self._products[product_id][key] = data
        self._settle(product_id)

    def give_up_on(self, product_id: str) -> None:
        """Stop waiting for a request that is never going to arrive."""
        if product_id in self._outstanding:
            self._settle(product_id)

    def _settle(self, product_id: str) -> None:
        self._outstanding[product_id] -= 1
        if self._outstanding[product_id] == 0:
            del self._outstanding[product_id]
            self._finished.append(self._products.pop(product_id))

    def take_finished(self) -> list[dict[str, Any]]:
        """The products nothing more is coming for, which we can now let go of."""
        finished, self._finished = self._finished, []
        return finished

    def take_remaining(self) -> list[dict[str, Any]]:
        """Everything still in hand, for a harvest that isn't going to finish."""
        remaining = self.take_finished() + list(self._products.values())
        self._products.clear()
        self._outstanding.clear()
        return remaining


def attached_product_id(url: str) -> str | None:
    """The product a metadata or availability URL belongs to, if it is one."""
    product_path, _, kind = URL(url).path.rpartition("/")
    if kind not in ("metadata", "availability"):
        return None
    return product_path.rpartition("/")[2].lower()


def process_request(
    response: Response,
    request_metadata: bool,
    request_availability: bool,
    base_url: str,
    events_path: str,
    pending: PendingProducts,
    urls: deque[str],
) -> None:
    data = response.raise_for_status().json()
    path = response.url.path
    if path == events_path:
        response_products = data["products"]
        for product in response_products:
            if not pending.add(product):
                continue
            if request_metadata:
                urls.append(product["links"]["metadata"]["href"].removeprefix(base_url))
            if request_availability:
                urls.append(
                    product["links"]["availability"]["href"].removeprefix(base_url)
                )
                urls.append(
                    product["links"]["availabilityV2"]["href"].removeprefix(base_url)
                )
    elif path.endswith("availability") and path.startswith("/v1/"):
        pending.attach(data["id"].lower(), "availability", data)
    elif path.endswith("availability") and path.startswith("/v2/"):
        pending.attach(data["reserveId"].lower(), "availabilityV2", data)
    elif path.endswith("metadata") and path.startswith("/v1/"):
        pending.attach(data["id"].lower(), "metadata", data)
    else:
        raise RuntimeError(f"Unknown URL: {response.url}")


async def fetch(
    base_url: str,
    client_key: str,
    client_secret: str,
    library_id: str,
    parent_library_id: str | None,
    fetch_metadata: bool,
    fetch_availability: bool,
    connections: int,
    skip_not_found: bool,
    use_consortial_plus_advantage_feed: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    """Harvest a collection, yielding each product once it is complete.

    A product is handed over as soon as the last of its requests comes back,
    so that a caller can write it out and let it go. Only the products with a
    request still in flight are held onto, which is a few thousand at most,
    rather than the whole collection.

    Raises ``HarvestAborted`` if the harvest fails, carrying the products that
    were still waiting on a request and so were never yielded. A cancellation
    is passed along untouched, so a Ctrl-C behaves like a Ctrl-C; what it
    costs is the products still in flight, everything before them having
    already been yielded.
    """
    per_product = requests_per_product(fetch_metadata, fetch_availability)
    pending = PendingProducts(per_product)
    pending_requests: list[asyncio.Task[Response]] = []

    try:
        async with HTTPXAsyncClient(
            auth=OverdriveAuth(client_key, client_secret),
            base_url=URL(base_url),
            timeout=Timeout(20.0, pool=None),
            limits=Limits(
                max_connections=connections,
                max_keepalive_connections=connections,
                keepalive_expiry=5,
            ),
        ) as client:
            collection_token = await get_collection_token(
                client,
                library_id,
                parent_library_id,
                use_consortial_plus_advantage_feed,
            )

            first_page = await client.get(event_url(collection_token))
            raise_for_error(first_page)
            first_page_data = first_page.json()

            items = first_page_data["totalItems"]
            items_per_page = first_page_data["limit"]
            pages = math.ceil(items / items_per_page)

            fetches = pages + items * per_product
            with Progress(
                SpinnerColumn(), *Progress.get_default_columns(), MofNCompleteColumn()
            ) as progress:
                download_task = progress.add_task(f"Downloading Feed", total=fetches)
                urls: deque[str] = deque()
                retried_requests: defaultdict[str, int] = defaultdict(int)

                for i in range(pages):
                    urls.append(event_url(collection_token, offset=i * items_per_page))

                for i in range(min(connections * 2, len(urls))):
                    make_request(client, urls, pending_requests)

                while pending_requests:
                    done, pending_tasks = await asyncio.wait(
                        pending_requests, return_when=asyncio.FIRST_COMPLETED
                    )

                    pending_requests = list(pending_tasks)
                    events_path = EVENTS_ENDPOINT % {
                        "collection_token": collection_token
                    }

                    for req in done:
                        response: Response | None = None
                        try:
                            response = await req
                            process_request(
                                response,
                                fetch_metadata,
                                fetch_availability,
                                base_url,
                                events_path,
                                pending,
                                urls,
                            )
                            progress.update(download_task, advance=1)
                        except (RequestError, HTTPStatusError, JSONDecodeError) as e:
                            if isinstance(e, (RequestError, HTTPStatusError)):
                                request_url = str(e.request.url)
                            else:
                                # JSONDecodeError: the await succeeded so response is set.
                                assert response is not None
                                request_url = str(response.url)
                            retried_requests[request_url] += 1
                            attempt = retried_requests[request_url]
                            print(
                                f"Request error ({attempt}/{MAX_ATTEMPTS}): {e} [{request_url}]"
                            )

                            if attempt >= MAX_ATTEMPTS:
                                raise OverdriveError(
                                    f"Giving up after {MAX_ATTEMPTS} attempts."
                                    f"\nURL: {request_url}"
                                ) from e

                            if (
                                skip_not_found
                                and isinstance(e, HTTPStatusError)
                                and e.response.status_code == 404
                            ):
                                print(f'url "{request_url}" NOT FOUND. Skipping...')
                                # Nothing more is coming for this product, so
                                # don't leave it waiting for a 404 forever.
                                skipped = attached_product_id(request_url)
                                if skipped is not None:
                                    pending.give_up_on(skipped)
                            else:
                                urls.appendleft(request_url)

                        for product in pending.take_finished():
                            yield product

                        if urls:
                            make_request(client, urls, pending_requests)

                # Nothing is in flight any more, so anything still waiting is
                # as complete as it is ever going to get.
                for product in pending.take_remaining():
                    yield product
    except Exception as e:
        # Cancellation is deliberately not caught here. It reaches us as a
        # Ctrl-C, and swallowing it would leave the harvest uncancellable and
        # cost the caller its KeyboardInterrupt. The products in flight go
        # with it; the rest of the feed has already been yielded and written.
        raise HarvestAborted(pending.take_remaining(), e) from e
    finally:
        # Requests still in flight when a harvest ends have nothing left to
        # deliver, and the client they were made with is already closed.
        for pending_request in pending_requests:
            pending_request.cancel()


async def fetch_url(
    client_key: str,
    client_secret: str,
    url: str,
) -> Any:
    async with HTTPXAsyncClient(
        auth=OverdriveAuth(client_key, client_secret),
        timeout=Timeout(20.0, pool=None),
    ) as client:
        response = await client.get(url)
        raise_for_error(response)

    return response.json()
