from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any
from urllib.parse import urljoin

import httpx
from httpx import Limits, Timeout
from rich.progress import MofNCompleteColumn, Progress, SpinnerColumn

from palace.opds.odl.info import LicenseInfo

from palace.tools.feeds import opds
from palace.tools.feeds.retry import request_with_retry_async

LICENSE_DOCUMENT_KEY = "license_document"


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

    auth = opds.build_auth(username, password, auth_type, feed_url=base_url)

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
            warmup_license[LICENSE_DOCUMENT_KEY] = await request_with_retry_async(
                client, warmup_url
            )
            progress.update(task_id, advance=1)

            semaphore = asyncio.Semaphore(connections)

            async def worker(license_: dict[str, Any], href: str) -> None:
                async with semaphore:
                    full_url = urljoin(base_url, href)
                    license_[LICENSE_DOCUMENT_KEY] = await request_with_retry_async(
                        client, full_url
                    )
                    progress.update(task_id, advance=1)

            await asyncio.gather(*(worker(lic, href) for _, lic, href in targets[1:]))
