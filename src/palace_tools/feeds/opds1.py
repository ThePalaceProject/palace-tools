import sys
from pathlib import Path
from xml.etree import ElementTree

import httpx
from rich.progress import MofNCompleteColumn, Progress, SpinnerColumn

from palace_tools.feeds.opds import AuthType, OAuthAuth, OpdsLinkTuple, error_and_exit


def parse_links(feed: str) -> dict[str, OpdsLinkTuple]:
    feed_element = ElementTree.fromstring(feed)
    return {
        rel: OpdsLinkTuple(type=link_type, href=href, rel=rel)
        for link in feed_element.findall("{http://www.w3.org/2005/Atom}link")
        if (rel := link.get("rel")) is not None
        and (link_type := link.get("type")) is not None
        and (href := link.get("href")) is not None
    }


def make_request(session: httpx.Client, url: str) -> str:
    response = session.get(url)
    if response.status_code != 200:
        error_and_exit(response)
    return response.text


def fetch(
    url: str,
    username: str | None,
    password: str | None,
    auth_type: AuthType,
    output_file: Path,
) -> None:
    # Create a session to fetch the documents
    client = httpx.Client()

    client.headers.update(
        {
            "Accept": "application/atom+xml;profile=opds-catalog;kind=acquisition,application/atom+xml;q=0.9,application/xml;q=0.8,*/*;q=0.1",
            "User-Agent": "Palace",
        }
    )
    client.timeout = httpx.Timeout(30.0)

    if username and password:
        if auth_type == AuthType.BASIC:
            client.auth = httpx.BasicAuth(username, password)
        elif auth_type == AuthType.OAUTH:
            client.auth = OAuthAuth(
                username, password, feed_url=url, parse_links=parse_links
            )
    elif auth_type != AuthType.NONE:
        print("Username and password are required for authentication")
        sys.exit(-1)

    next_url: str | None = url
    with output_file.open("w") as file:
        with Progress(
            SpinnerColumn(), *Progress.get_default_columns(), MofNCompleteColumn()
        ) as progress:
            download_task = progress.add_task(f"Downloading Feed", total=None)
            while next_url is not None:
                response = make_request(client, next_url)
                file.write(response)
                links = parse_links(response)
                next_url = links.get("next") and links["next"].href
                progress.update(download_task, advance=1)
