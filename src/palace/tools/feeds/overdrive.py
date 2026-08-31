from __future__ import annotations

import asyncio
import json
import math
import sys
import time
from collections import defaultdict, deque
from collections.abc import AsyncGenerator
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


def handle_error(resp: Response) -> None:
    if resp.status_code == 200:
        return
    print(f"URL: {resp.url}")
    print(f"Error: {resp.status_code}")
    print(f"Headers: {json.dumps(dict(resp.headers), indent=4)}")
    print(resp.text)
    sys.exit(-1)


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
                        # retrying, so let handle_error report and exit.
                        handle_error(response)
                        return self._store_token(response.json())
                    detail = f"HTTP {response.status_code}"

                print(
                    f"Token request error ({attempt}/{MAX_ATTEMPTS}): "
                    f"{detail} [{TOKEN_ENDPOINT}]"
                )
                if attempt < MAX_ATTEMPTS:
                    await asyncio.sleep(TOKEN_RETRY_DELAY * attempt)

        print(f"Giving up after {MAX_ATTEMPTS} attempts.")
        print(f"URL: {TOKEN_ENDPOINT}")
        sys.exit(-1)

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
            handle_error(resp)
            accounts = resp.json()["advantageAccounts"]
            for account in accounts:
                if account["id"] == int(library_id):
                    return str(account["collectionToken"])

            print(f"No Advantage account found for library {library_id}")
            sys.exit(-1)
        else:
            endpoint = ADVANTAGE_LIBRARY_ENDPOINT
    else:
        endpoint = LIBRARY_ENDPOINT

    resp = await http.get(endpoint % variables)
    handle_error(resp)
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


def process_request(
    response: Response,
    request_metadata: bool,
    request_availability: bool,
    base_url: str,
    events_path: str,
    products: dict[str, Any],
    urls: deque[str],
) -> None:
    data = response.raise_for_status().json()
    path = response.url.path
    if path == events_path:
        response_products = data["products"]
        for product in response_products:
            if request_metadata:
                urls.append(product["links"]["metadata"]["href"].removeprefix(base_url))
            if request_availability:
                urls.append(
                    product["links"]["availability"]["href"].removeprefix(base_url)
                )
                urls.append(
                    product["links"]["availabilityV2"]["href"].removeprefix(base_url)
                )
            products[product["id"].lower()] = product
    elif path.endswith("availability") and path.startswith("/v1/"):
        products[data["id"].lower()]["availability"] = data
    elif path.endswith("availability") and path.startswith("/v2/"):
        products[data["reserveId"].lower()]["availabilityV2"] = data
    elif path.endswith("metadata") and path.startswith("/v1/"):
        products[data["id"].lower()]["metadata"] = data
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
) -> list[dict[str, Any]]:
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
            client, library_id, parent_library_id, use_consortial_plus_advantage_feed
        )

        first_page = await client.get(event_url(collection_token))
        handle_error(first_page)
        first_page_data = first_page.json()

        items = first_page_data["totalItems"]
        items_per_page = first_page_data["limit"]
        pages = math.ceil(items / items_per_page)

        fetches = (
            pages
            + (items if fetch_metadata else 0)
            + (items * 2 if fetch_availability else 0)
        )
        with Progress(
            SpinnerColumn(), *Progress.get_default_columns(), MofNCompleteColumn()
        ) as progress:
            download_task = progress.add_task(f"Downloading Feed", total=fetches)
            urls: deque[str] = deque()
            pending_requests: list[asyncio.Task[Response]] = []
            products: dict[str, Any] = {}
            retried_requests: defaultdict[str, int] = defaultdict(int)

            for i in range(pages):
                urls.append(event_url(collection_token, offset=i * items_per_page))

            for i in range(min(connections * 2, len(urls))):
                make_request(client, urls, pending_requests)

            while pending_requests:
                done, pending = await asyncio.wait(
                    pending_requests, return_when=asyncio.FIRST_COMPLETED
                )

                pending_requests = list(pending)
                events_path = EVENTS_ENDPOINT % {"collection_token": collection_token}

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
                            products,
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
                            print(f"Giving up after {MAX_ATTEMPTS} attempts.")
                            sys.exit(-1)

                        if (
                            skip_not_found
                            and isinstance(e, HTTPStatusError)
                            and e.response.status_code == 404
                        ):
                            print(f'url "{request_url}" NOT FOUND. Skipping...')
                        else:
                            urls.appendleft(request_url)
                    if urls:
                        make_request(client, urls, pending_requests)

    return list(products.values())


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
        handle_error(response)

    return response.json()
