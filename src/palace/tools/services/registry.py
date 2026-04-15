from __future__ import annotations

from palace.tools.constants import OPDS_AUTH_DOC_REL, OPDS_AUTH_DOC_TYPE
from palace.tools.models.api.opds2 import match_links
from palace.tools.utils.http.async_client import HTTPXAsyncClient, validate_response


class LibraryRegistryService:
    def __init__(self, url: str, allow_hidden_libraries: bool = False):
        self.url = url.removesuffix("/")
        self.libraries_url = (
            f'{self.url}/libraries{"/qa" if allow_hidden_libraries else ""}'
        )

    async def library_auth_doc_url(
        self, library_name: str, *, http_client: HTTPXAsyncClient | None = None
    ) -> str | None:
        """Find the authentication document for a library in the registry."""
        async with HTTPXAsyncClient.with_existing_client(
            existing_client=http_client, no_close=True
        ) as client:
            libraries = (
                validate_response(await client.get(self.libraries_url))
                .json()
                .get("catalogs")
            )
            libraries_by_name = {
                for_lookup(lib["metadata"]["title"]): lib for lib in libraries
            }
            library = libraries_by_name.get(for_lookup(library_name))
            if library is None:
                raise ValueError(f"Library '{library_name}' not found.")
            [auth_doc_link] = match_links(
                library.get("links", []),
                lambda link: link.get("rel") == OPDS_AUTH_DOC_REL
                or link.get("type") == OPDS_AUTH_DOC_TYPE,
            )
            return auth_doc_link.get("href") if auth_doc_link is not None else None


def for_lookup(value: str) -> str:
    return value.lower().strip()
