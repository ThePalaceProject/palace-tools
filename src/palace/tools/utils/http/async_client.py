from __future__ import annotations

import sys
from contextlib import nullcontext
from typing import Any

from httpx import AsyncClient, Response

from palace.tools.constants import DEFAULT_USER_AGENT

if sys.version_info < (3, 11):
    from typing_extensions import Self
else:
    from typing import Self


class HTTPXAsyncClient(AsyncClient):
    def __init__(self, user_agent: str = DEFAULT_USER_AGENT, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.user_agent = user_agent

    async def request(self, method: str, url: str, *, headers: dict[str, str] | None = None, **kwargs: Any) -> Response:  # type: ignore[override]
        headers = {"User-Agent": self.user_agent} | (headers or {})
        return await super().request(method, url, headers=headers, **kwargs)

    async def post(self, *args: Any, **kwargs: Any) -> Response:
        return await self.request("POST", *args, **kwargs)

    async def get(self, *args: Any, **kwargs: Any) -> Response:
        return await self.request("GET", *args, **kwargs)

    @classmethod
    def with_existing_client(
        cls, *args: Any, existing_client: Self | None = None, **kwargs: Any
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
