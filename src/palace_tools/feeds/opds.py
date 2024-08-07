from __future__ import annotations

import json
import math
import sys
from base64 import b64encode
from collections.abc import Callable, Generator, Mapping
from enum import Enum
from typing import Any, NamedTuple, TextIO

import httpx
from rich.progress import MofNCompleteColumn, Progress, SpinnerColumn


class AuthType(Enum):
    BASIC = "basic"
    OAUTH = "oauth"
    NONE = "none"


class OpdsLinkTuple(NamedTuple):
    type: str
    href: str
    rel: str


class OAuthAuth(httpx.Auth):
    # Implementation of OPDS auth document OAuth client credentials flow for httpx
    # See:
    #   - https://www.python-httpx.org/advanced/authentication/#custom-authentication-schemes
    #   - https://drafts.opds.io/authentication-for-opds-1.0.html

    requires_response_body = True

    def __init__(
        self,
        username: str,
        password: str,
        *,
        feed_url: str,
        parse_links: Callable[[str], dict[str, OpdsLinkTuple]] | None = None,
    ) -> None:
        self.username = username
        self.password = password
        self.feed_url = feed_url
        self.parse_links = parse_links

        self.token: str | None = None
        self.oauth_url: str | None = None

    @staticmethod
    def _get_oauth_url_from_auth_document(auth_document: Mapping[str, Any]) -> str:
        auth_types: list[dict[str, Any]] = auth_document.get("authentication", [])
        try:
            [links] = [
                tlinks
                for t in auth_types
                if t.get("type") == "http://opds-spec.org/auth/oauth/client_credentials"
                and (tlinks := t.get("links")) is not None
            ]
        except (ValueError, TypeError):
            print("Unable to find supported authentication type")
            print(f"Auth document: {json.dumps(auth_document, indent=2)}")
            sys.exit(-1)

        try:
            [auth_link] = [
                lhref
                for l in links
                if l.get("rel") == "authenticate"
                and (lhref := l.get("href")) is not None
            ]
        except (ValueError, TypeError):
            print("Unable to find valid authentication link")
            print(f"Auth document: {json.dumps(auth_document, indent=2)}")
            sys.exit(-1)
        return auth_link  # type: ignore[no-any-return]

    @staticmethod
    def _oauth_token_request(url: str, username: str, password: str) -> httpx.Request:
        userpass = ":".join((username, password))
        token = b64encode(userpass.encode()).decode()
        headers = {"Authorization": f"Basic {token}"}
        return httpx.Request(
            "POST", url, headers=headers, data={"grant_type": "client_credentials"}
        )

    def refresh_auth_url(self) -> Generator[httpx.Request, httpx.Response, None]:
        response = yield httpx.Request("GET", self.feed_url)
        if response.status_code == 200 and self.parse_links is not None:
            links = self.parse_links(response.text)
            auth_doc_url = links.get("http://opds-spec.org/auth/document")
            if auth_doc_url is None:
                print("No auth document link found")
                print(links)
                sys.exit(-1)
            auth_doc_response = yield httpx.Request("GET", auth_doc_url.href)
            if auth_doc_response.status_code != 200:
                error_and_exit(auth_doc_response)
        elif response.status_code == 401:
            auth_doc_response = response
        else:
            error_and_exit(response)

        if (
            auth_doc_response.headers.get("Content-Type")
            != "application/vnd.opds.authentication.v1.0+json"
        ):
            error_and_exit(auth_doc_response, "Invalid content type")

        self.oauth_url = self._get_oauth_url_from_auth_document(
            auth_doc_response.json()
        )

    def refresh_token(self) -> Generator[httpx.Request, httpx.Response, None]:
        if self.oauth_url is None:
            yield from self.refresh_auth_url()

        # This should never happen, but we assert for sanity and mypy
        assert self.oauth_url is not None

        response = yield self._oauth_token_request(
            self.oauth_url, self.username, self.password
        )
        if response.status_code != 200:
            error_and_exit(response)
        if (access_token := response.json().get("access_token")) is None:
            print("No access token in response")
            print(response.text)
            sys.exit(-1)
        self.token = access_token

    def auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response, None]:
        token_refreshed = False
        if self.oauth_url is None or self.token is None:
            yield from self.refresh_token()
            token_refreshed = True

        # This should never happen, but we assert it for mypy and our sanity
        assert self.token is not None

        request.headers["Authorization"] = f"Bearer {self.token}"
        response = yield request

        if response.status_code == 401 and not token_refreshed:
            yield from self.refresh_token()
            request.headers["Authorization"] = f"Bearer {self.token}"
            yield request


def error_and_exit(response: httpx.Response, detail: str = "") -> None:
    print(f"Error: {detail}")
    print(f"Request: {response.request.method} {response.request.url}")
    print(f"Status code: {response.status_code}")
    print(f"Headers: {json.dumps(dict(response.headers), indent=4)}")
    print(f"Body: {response.text}")
    sys.exit(-1)


def make_request(session: httpx.Client, url: str) -> dict[str, Any]:
    response = session.get(url)
    if response.status_code != 200:
        error_and_exit(response)
    return response.json()  # type: ignore[no-any-return]


def write_json(file: TextIO, data: list[dict[str, Any]]) -> None:
    file.write(json.dumps(data, indent=4))


def fetch(
    url: str, username: str | None, password: str | None, auth_type: AuthType
) -> list[dict[str, Any]]:
    # Create a session to fetch the documents
    client = httpx.Client()

    client.headers.update(
        {
            "Accept": "application/opds+json, application/json;q=0.9, */*;q=0.1",
            "User-Agent": "Palace",
        }
    )
    client.timeout = httpx.Timeout(30.0)

    if username and password:
        if auth_type == AuthType.BASIC:
            client.auth = httpx.BasicAuth(username, password)
        elif auth_type == AuthType.OAUTH:
            client.auth = OAuthAuth(username, password, feed_url=url)
    elif auth_type != AuthType.NONE:
        print("Username and password are required for authentication")
        sys.exit(-1)

    publications = []

    # Get the first page
    response = make_request(client, url)
    items = response.get("metadata", {}).get("numberOfItems")
    items_per_page = response.get("metadata", {}).get("itemsPerPage")

    if items is None or items_per_page is None:
        pages = None
    else:
        pages = math.ceil(items / items_per_page)

    # Fetch the rest of the pages:
    next_url: str | None = url
    with Progress(
        SpinnerColumn(), *Progress.get_default_columns(), MofNCompleteColumn()
    ) as progress:
        download_task = progress.add_task(f"Downloading Feed", total=pages)
        while next_url is not None:
            response = make_request(client, next_url)
            publications.extend(response["publications"])
            next_url = None
            for link in response["links"]:
                if link["rel"] == "next":
                    next_url = link["href"]
                    break
            progress.update(download_task, advance=1)

    return publications
