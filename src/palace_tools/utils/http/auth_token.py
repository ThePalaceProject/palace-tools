import datetime
import sys
from abc import ABC, abstractmethod
from base64 import b64encode
from collections.abc import Mapping
from functools import cached_property
from typing import Protocol

from palace_tools.models.api.util import ApiBaseModel
from palace_tools.utils.datetime import utc_now

if sys.version_info < (3, 11):
    from typing_extensions import Self
else:
    from typing import Self


def basic_auth_header(username: str, password: str) -> Mapping[str, str]:
    token = b64encode(bytes(f"{username}:{password}", "utf-8")).decode("ISO-8859-1")
    return {"Authorization": f"Basic {token}"}


class AuthorizationToken(Protocol):
    access_token: str
    token_type: str

    @property
    def is_valid(self) -> bool: ...

    @property
    def is_expired(self) -> bool: ...

    @property
    def as_http_headers(self) -> Mapping[str, str]: ...


class BaseAuthorizationToken(ABC, ApiBaseModel):
    access_token: str
    token_type: str

    @property
    def as_http_headers(self) -> Mapping[str, str]:
        """HTTP Authorization header."""
        return {"Authorization": f"{self.token_type} {self.access_token}"}

    @property
    @abstractmethod
    def is_valid(self) -> bool: ...

    @property
    @abstractmethod
    def is_expired(self) -> bool: ...


class BasicAuthToken(BaseAuthorizationToken):
    """A Basic Authorization token."""

    @classmethod
    def from_username_and_password(cls, username: str, password: str | None) -> Self:
        if password is None:
            password = ""
        token = b64encode(bytes(f"{username}:{password}", "utf-8")).decode("ISO-8859-1")
        return cls(access_token=token, token_type="Basic")

    @property
    def is_valid(self) -> bool:
        """The token is always valid."""
        return True

    @property
    def is_expired(self) -> bool:
        """The token never expires."""
        return False


class OAuthToken(BaseAuthorizationToken):
    """An OAuth Authorization token."""

    expires_in: int
    scope: str | None = None

    _creation_datetime: datetime.datetime = utc_now()

    @cached_property
    def expiration_datetime(self) -> datetime.datetime:
        # TODO: Our calculation of expiration time should be a little more
        #  conservative, but account for token duration (i.e., maybe
        #  a percentage of duration, but capped by a maximum).
        #  E.g., duration = self.expires_in - min(120, self.expires_in * 0.9)
        return self._creation_datetime + datetime.timedelta(seconds=self.expires_in)

    @property
    def is_valid(self) -> bool:
        """The token is valid if it's not expired and not just whitespace."""
        return self.access_token.strip() == "" and not self.is_expired

    @property
    def is_expired(self) -> bool:
        """Has the token expired?"""
        return utc_now() > self.expiration_datetime
