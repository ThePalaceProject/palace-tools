from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import Field

from palace.opds.opds2 import Link
from palace.opds.types.link import CompactCollection

from palace.tools.constants import PATRON_BOOKSHELF_REL, PATRON_PROFILE_REL
from palace.tools.models.api.util import ApiBaseModel


class Labels(ApiBaseModel):
    login: str
    password: str


# TODO: Some placeholders.
# class Login(ApiBaseModel):
#     keyboard: str
#
#
# class Password(ApiBaseModel):
#     keyboard: str
#
#
# class Inputs(ApiBaseModel):
#     login: Login
#     password: Password
#
#
# class WebColorScheme(ApiBaseModel):
#     primary: str
#     secondary: str
#     background: str
#     foreground: str


class InputMethod(ApiBaseModel):
    keyboard: str


class AuthenticationMechanism(ApiBaseModel):
    description: str
    labels: Labels
    inputs: Mapping[str, InputMethod]
    links: CompactCollection[Link] = Field(default_factory=CompactCollection)
    type: str


class PublicKey(ApiBaseModel):
    type: str
    value: str


class Features(ApiBaseModel):
    enabled: list[str] = []
    disabled: list[str] = []


class AuthenticationDocument(ApiBaseModel):
    id: str
    title: str
    authentication: list[AuthenticationMechanism]
    features: Features
    links: CompactCollection[Link]
    announcements: list[Any]
    service_description: str
    public_key: PublicKey
    # color_scheme: str
    # web_color_scheme: WebColorScheme

    @property
    def patron_profile_links(self) -> CompactCollection[Link]:
        return self.links.get_collection(rel=PATRON_PROFILE_REL)

    @property
    def patron_bookshelf_links(self) -> CompactCollection[Link]:
        return self.links.get_collection(rel=PATRON_BOOKSHELF_REL)
