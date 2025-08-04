from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from httpx import Response

from palace_tools.constants import (
    DEFAULT_AUTH_DOC_PATH_SUFFIX,
    DEFAULT_REGISTRY_URL,
    OPDS_1_TYPE,
    OPDS_2_TYPE,
    PATRON_AUTH_BASIC_TOKEN_TYPE,
    PATRON_AUTH_BASIC_TYPE,
)
from palace_tools.models.api.authentication_document import (
    AuthenticationDocument,
    AuthenticationMechanism,
)
from palace_tools.models.api.opds2 import OPDS2Feed, match_links
from palace_tools.models.api.patron_profile import PatronProfileDocument
from palace_tools.services.registry import LibraryRegistryService
from palace_tools.utils.http.async_client import HTTPXAsyncClient, validate_response
from palace_tools.utils.http.auth_token import (
    AuthorizationToken,
    BasicAuthToken,
    OAuthToken,
)


class PatronAuthMechanism(str, Enum):
    BASIC = PATRON_AUTH_BASIC_TYPE
    BASIC_TOKEN = PATRON_AUTH_BASIC_TOKEN_TYPE


@dataclass
class PatronAuthorization:
    mechanism: AuthenticationMechanism
    token: AuthorizationToken


@dataclass
class AuthenticatedPatron(PatronAuthorization):
    authentication_document: AuthenticationDocument

    async def patron_profile_document(
        self, http_client: HTTPXAsyncClient | None = None
    ) -> PatronProfileDocument:
        [patron_profile_link] = self.authentication_document.patron_profile_links
        headers = dict(self.token.as_http_headers)
        async with HTTPXAsyncClient.with_existing_client(
            existing_client=http_client
        ) as client:
            profile = validate_response(
                await client.get(patron_profile_link.href, headers=headers)
            ).json()
        return PatronProfileDocument.model_validate(profile)

    async def fetch_patron_bookshelf(
        self, accept: str = OPDS_2_TYPE, http_client: HTTPXAsyncClient | None = None,
    ) -> Response:
        [patron_bookshelf_link] = self.authentication_document.patron_bookshelf_links
        headers = dict(self.token.as_http_headers) | {"Accept": accept}
        async with HTTPXAsyncClient.with_existing_client(
            existing_client=http_client
        ) as client:
            return await client.get(patron_bookshelf_link.href, headers=headers)


async def authenticate(
    *,
    username: str | None = None,
    password: str | None = None,
    auth_doc_url: str | None = None,
    registry_url: str = DEFAULT_REGISTRY_URL,
    library: str | None = None,
    opds_server: str | None = None,
    allow_hidden_libraries: bool = False,
    http_client: HTTPXAsyncClient | None = None,
) -> AuthenticatedPatron:
    """Login as a patron."""
    async with HTTPXAsyncClient.with_existing_client(
        existing_client=http_client
    ) as client:
        authentication_document_url = await get_auth_document_url(
            auth_doc_url=auth_doc_url,
            library=library,
            registry_url=registry_url,
            allow_hidden_libraries=allow_hidden_libraries,
            opds_server=opds_server,
            http_client=client,
        )

        if authentication_document_url is None:
            raise ValueError("Unable to determine authentication document URL.")
        authentication_document = await fetch_auth_document(
            url=authentication_document_url, http_client=client
        )
        authorization = await get_authorization(
            username=username,
            password=password,
            auth_mechanisms=authentication_document.authentication,
            http_client=client,
        )
        return AuthenticatedPatron(
            authentication_document=authentication_document,
            **vars(authorization),
        )


async def get_authorization(
    username: str | None = None,
    password: str | None = None,
    auth_mechanisms: Sequence[AuthenticationMechanism] | None = None,
    http_client: HTTPXAsyncClient | None = None,
) -> PatronAuthorization:
    """Return the authorization token.

    If there is not a patron, we raise an exception.
    """
    supported_mechanisms = [PATRON_AUTH_BASIC_TOKEN_TYPE, PATRON_AUTH_BASIC_TYPE]
    mechanisms = auth_mechanisms if auth_mechanisms is not None else []
    for mech in mechanisms:
        if mech.type in supported_mechanisms:
            token = await _get_patron_token(
                auth_mech=mech,
                username=username,
                password=password,
                http_client=http_client,
            )
            if token:
                return PatronAuthorization(token=token, mechanism=mech)

    raise ValueError(
        "Unable to authorize patron with available authentication mechanisms."
    )


async def _get_patron_token(
    auth_mech: AuthenticationMechanism,
    username: str | None = None,
    password: str | None = None,
    http_client: HTTPXAsyncClient | None = None,
) -> AuthorizationToken:
    """Return an authorization token."""
    match auth_mech.type:
        case PatronAuthMechanism.BASIC:
            if username is None:
                raise ValueError(
                    f"{auth_mech.labels.login} is required for the {auth_mech.type} authentication mechanism."
                )
            return BasicAuthToken.from_username_and_password(username, password)
        case PatronAuthMechanism.BASIC_TOKEN:
            if username is None:
                raise ValueError(
                    f"{auth_mech.labels.login} is required for the {auth_mech.type} authentication mechanism."
                )
            basic_auth_header = BasicAuthToken.from_username_and_password(
                username, password
            ).as_http_headers
            [authentication_link] = match_links(
                auth_mech.links,
                lambda link: link.rel == "authenticate",
            )
            async with HTTPXAsyncClient.with_existing_client(
                existing_client=http_client
            ) as client:
                token_obj = validate_response(
                    await client.post(
                        authentication_link.href, headers=basic_auth_header
                    )
                ).json()
            return OAuthToken.model_validate(token_obj)
        case _:
            raise NotImplementedError(
                f"Unsupported authentication mechanism: {auth_mech.type}"
            )


async def fetch_auth_document(
    url: str, *, http_client: HTTPXAsyncClient | None = None
) -> AuthenticationDocument:
    """Fetch the authentication document."""
    async with HTTPXAsyncClient.with_existing_client(
        existing_client=http_client
    ) as client:
        document = validate_response(await client.get(url)).json()
    return AuthenticationDocument.model_validate(document)


async def get_auth_document_url(
    *,
    auth_doc_url: str | None = None,
    library: str | None = None,
    registry_url: str = DEFAULT_REGISTRY_URL,
    opds_server: str | None = None,
    allow_hidden_libraries: bool = False,
    opds_auth_doc_suffix: str = DEFAULT_AUTH_DOC_PATH_SUFFIX,
    http_client: HTTPXAsyncClient | None = None,
) -> str | None:
    """Return the URL of the authentication document.

    If `auth_document_url` is specified, then it will be used. Otherwise, if a
    `library` name is specified, it will be looked up from a library registry.
    If a matching library is not found,  then if an `opds_server` is specified,
    the URL will be constructed
    by joining the `server_auth_doc_suffix` with the `opds_server`.
    """
    if auth_doc_url is not None:
        return auth_doc_url

    if library is not None and registry_url is not None:
        registry = LibraryRegistryService(
            registry_url, allow_hidden_libraries=allow_hidden_libraries
        )
        auth_doc_url = await registry.library_auth_doc_url(
            library, http_client=http_client
        )

    if auth_doc_url is None and opds_server is not None:
        auth_doc_url = opds_server.removesuffix("/") + "/" + opds_auth_doc_suffix

    return auth_doc_url
