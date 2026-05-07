from __future__ import annotations

import asyncio
import sys
from collections.abc import Iterator
from json import JSONDecodeError
from typing import Any
from urllib.parse import urljoin

import httpx
from httpx import Limits, Timeout
from rich.progress import MofNCompleteColumn, Progress, SpinnerColumn

from palace.opds.odl.info import LicenseInfo

from palace.tools.feeds import opds

LICENSE_DOCUMENT_KEY = "license_document"
_RETRY_LIMIT = 3


def iter_license_info_links(
    publications: list[dict[str, Any]],
) -> Iterator[tuple[dict[str, Any], dict[str, Any], str]]:
    """Yield ``(publication, license, info_url)`` for every License Info self link."""
    info_content_type = LicenseInfo.content_type()
    for publication in publications:
        licenses = publication.get("licenses")
        if not licenses:
            continue
        for license_ in licenses:
            for link in license_.get("links", []):
                if (
                    link.get("rel") == "self"
                    and link.get("type") == info_content_type
                    and link.get("href")
                ):
                    yield publication, license_, link["href"]
                    break


async def _fetch_one(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    last_error: str = ""
    for attempt in range(1, _RETRY_LIMIT + 1):
        try:
            response = await client.get(url)
        except httpx.RequestError as e:
            last_error = f"Request error: {e}"
            print(f"License Info fetch error ({attempt}/{_RETRY_LIMIT}): {e} [{url}]")
            continue

        if response.status_code != 200:
            last_error = f"Status code: {response.status_code}\nBody: {response.text}"
            print(
                f"License Info fetch error ({attempt}/{_RETRY_LIMIT}): "
                f"{response.status_code} [{url}]"
            )
            continue

        try:
            return response.json()  # type: ignore[no-any-return]
        except JSONDecodeError as e:
            last_error = f"JSON decode error: {e}\nBody: {response.text}"
            print(
                f"License Info JSON decode error ({attempt}/{_RETRY_LIMIT}): "
                f"{e} [{url}]"
            )
            continue

    print(f"Failed to fetch License Info Document after {_RETRY_LIMIT} attempts.")
    print(f"URL: {url}")
    print(last_error)
    sys.exit(-1)


async def fetch_license_documents(
    publications: list[dict[str, Any]],
    *,
    username: str | None,
    password: str | None,
    auth_type: opds.AuthType,
    connections: int,
    base_url: str,
) -> None:
    """
    Fetch the License Info Document for every license and embed each parsed
    body in place on the license dict under :data:`LICENSE_DOCUMENT_KEY`.

    Publications without a ``licenses`` field (plain OPDS 2 publications mixed
    into an OPDS2+ODL feed) are skipped.
    """
    targets = list(iter_license_info_links(publications))
    if not targets:
        return

    auth: httpx.Auth | None = None
    if username and password:
        if auth_type == opds.AuthType.BASIC:
            auth = httpx.BasicAuth(username, password)
        elif auth_type == opds.AuthType.OAUTH:
            auth = opds.OAuthAuth(username, password, feed_url=base_url)
    elif auth_type != opds.AuthType.NONE:
        print("Username and password are required for authentication")
        sys.exit(-1)

    headers = {
        "Accept": f"{LicenseInfo.content_type()}, application/json;q=0.9, */*;q=0.1",
        "User-Agent": "Palace",
    }

    async with httpx.AsyncClient(
        auth=auth,
        headers=headers,
        timeout=Timeout(30.0),
        limits=Limits(
            max_connections=connections,
            max_keepalive_connections=connections,
        ),
    ) as client:
        with Progress(
            SpinnerColumn(), *Progress.get_default_columns(), MofNCompleteColumn()
        ) as progress:
            task_id = progress.add_task(
                "Fetching License Info Documents", total=len(targets)
            )

            # Warm up auth with a single sequential request so concurrent
            # workers don't all race to refresh the token.
            warmup_pub, warmup_license, warmup_href = targets[0]
            warmup_url = urljoin(base_url, warmup_href)
            warmup_license[LICENSE_DOCUMENT_KEY] = await _fetch_one(client, warmup_url)
            progress.update(task_id, advance=1)

            semaphore = asyncio.Semaphore(connections)

            async def worker(license_: dict[str, Any], href: str) -> None:
                async with semaphore:
                    full_url = urljoin(base_url, href)
                    license_[LICENSE_DOCUMENT_KEY] = await _fetch_one(client, full_url)
                    progress.update(task_id, advance=1)

            await asyncio.gather(*(worker(lic, href) for _, lic, href in targets[1:]))
