from __future__ import annotations

import sys
from contextlib import nullcontext
from typing import Any

from httpx import AsyncClient, Headers, Response
from httpx._types import HeaderTypes

from palace.tools.constants import DEFAULT_USER_AGENT

if sys.version_info < (3, 11):
    from typing_extensions import Self
else:
    from typing import Self


class HTTPXAsyncClient(AsyncClient):
    """An ``AsyncClient`` that identifies itself as Palace on every request."""

    def __init__(
        self,
        user_agent: str = DEFAULT_USER_AGENT,
        *,
        headers: HeaderTypes | None = None,
        **kwargs: Any,
    ) -> None:
        # The User-Agent is a client default rather than something added by an
        # overridden request(), because httpx merges client headers into every
        # request it builds. That covers stream() and send() too, neither of
        # which goes through request().
        client_headers = Headers({"User-Agent": user_agent})
        client_headers.update(headers)
        super().__init__(headers=client_headers, **kwargs)
        self.user_agent = user_agent

    @classmethod
    def with_existing_client(
        cls, *args: Any, existing_client: AsyncClient | None = None, **kwargs: Any
    ) -> Self:
        """Return an instance of our self.

        :param existing_client: A client to use instead of creating a new one.
        :return: A client instance.

        If `client` is provided, it will be returned.
        If not, a new one will be instantiated, using the provided arguments.
        """
        if existing_client:
            return nullcontext(enter_result=existing_client)  # type: ignore[return-value]
        else:
            return cls(*args, **kwargs)


def validate_response(response: Response, raise_for_status: bool = True) -> Response:
    if raise_for_status:
        response.raise_for_status()
    return response
