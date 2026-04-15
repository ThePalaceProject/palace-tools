from __future__ import annotations

from collections.abc import Sequence

from palace.tools.models.api.opds2 import OPDS2Link
from palace.tools.models.api.util import ApiBaseModel


class ContentKey(ApiBaseModel):
    algorithm: str
    encrypted_value: str


class UserKey(ApiBaseModel):
    algorithm: str
    text_hint: str
    key_check: str


class Encryption(ApiBaseModel):
    profile: str
    content_key: ContentKey
    user_key: UserKey


class Rights(ApiBaseModel):
    print: int
    start: str
    end: str


class Signature(ApiBaseModel):
    certificate: str
    value: str
    algorithm: str


class User(ApiBaseModel):
    id: str


class LCPLicenseDocument(ApiBaseModel):
    provider: str
    id: str
    issued: str
    updated: str
    encryption: Encryption
    links: Sequence[OPDS2Link]
    user: User
    rights: Rights
    signature: Signature
