from __future__ import annotations

import asyncio
import json
import math
import sys
from collections import defaultdict, deque
from typing import Any

import httpx
from httpx import URL, HTTPStatusError, Limits, RequestError, Response, Timeout
from rich.progress import MofNCompleteColumn, Progress, SpinnerColumn

QA_BASE_URL = "https://integration.api.overdrive.com"
PROD_BASE_URL = "https://api.overdrive.com"

TOKEN_ENDPOINT = "https://oauth.overdrive.com/token"
EVENTS_ENDPOINT = "/v1/collections/%(collection_token)s/products"
LIBRARY_ENDPOINT = "/v1/libraries/%(library_id)s"
ADVANTAGE_LIBRARY_ENDPOINT = (
    "/v1/libraries/%(parent_library_id)s/advantageAccounts/%(library_id)s"
)
ADVANTAGE_ACCOUNTS_ENDPOINT = (
    "/v1/libraries/%(parent_library_id)s/advantageAccounts"
)


def handle_error(resp: Response) -> None:
    if resp.status_code == 200:
        return
    print(f"URL: {resp.url}")
    print(f"Error: {resp.status_code}")
    print(f"Headers: {json.dumps(dict(resp.headers), indent=4)}")
    print(resp.text)
    sys.exit(-1)


async def get_auth_token(
    http: httpx.AsyncClient, client_key: str, client_secret: str
) -> str:
    auth = (client_key, client_secret)
    resp = await http.post(
        TOKEN_ENDPOINT, auth=auth, data=dict(grant_type="client_credentials")
    )
    handle_error(resp)
    return resp.json()["access_token"]  # type: ignore[no-any-return]


def get_headers(auth_token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + auth_token, "User-Agent": "Palace"}


async def get_collection_token(
    http: httpx.AsyncClient, library_id: str, parent_library_id: str | None,
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
                   return account["collectionToken"]

            print(f"No Advantage account found for library {library_id}")
            sys.exit(-1)
        else:
            endpoint = ADVANTAGE_LIBRARY_ENDPOINT
    else:
        endpoint = LIBRARY_ENDPOINT

    endpoint = ADVANTAGE_LIBRARY_ENDPOINT if parent_library_id else LIBRARY_ENDPOINT

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
    async with httpx.AsyncClient(
        timeout=Timeout(20.0, pool=None),
        limits=Limits(
            max_connections=connections,
            max_keepalive_connections=connections,
            keepalive_expiry=5,
        ),
    ) as client:
        auth_token = await get_auth_token(client, client_key, client_secret)

        client.headers.update(get_headers(auth_token))
        client.base_url = URL(base_url)

        collection_token = await get_collection_token(
            client, library_id, parent_library_id,use_consortial_plus_advantage_feed
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
                    except (RequestError, HTTPStatusError) as e:
                        print(f"Request error: {e}")
                        print(f"URL: {e.request.url}")
                        request_url = str(e.request.url)
                        retried_requests[request_url] += 1

                        if retried_requests[request_url] > 3:
                            print("Too many retries. Exiting.")
                            sys.exit(-1)
                        else:
                            if skip_not_found and ("404 Not Found") in str(e):
                                print(f'url "{e.request.url}" NOT FOUND. Skipping...')
                            else:
                                print(
                                    f"Retrying request (attempt {retried_requests[request_url]}/3)"
                                )
                                urls.appendleft(request_url)
                    if urls:
                        make_request(client, urls, pending_requests)

    return list(products.values())


async def fetch_url(
    client_key: str,
    client_secret: str,
    url: str,
) -> Any:
    async with httpx.AsyncClient(
        timeout=Timeout(20.0, pool=None),
    ) as client:
        auth_token = await get_auth_token(client, client_key, client_secret)

        client.headers.update(get_headers(auth_token))
        response = await client.get(url)
        handle_error(response)

    return response.json()
