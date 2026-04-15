from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, TypeVar

from pydantic import Field

from palace.tools.constants import (
    OPDS_ACQ_OPEN_ACCESS_REL,
    OPDS_ACQ_STANDARD_REL,
    OPDS_REVOKE_REL,
)
from palace.tools.models.api.util import ApiBaseModel
from palace.tools.utils.misc import ensure_list

"""
https://drafts.opds.io/opds-2.0.html

A JSON Schema for OPDS 2.0 is available under version control at
    https://github.com/opds-community/drafts/tree/master/schema

For the purpose of validating an OPDS 2.0 catalog, use the following JSON Schema resources:

    OPDS 2.0 Feed: https://drafts.opds.io/schema/feed.schema.json
    OPDS 2.0 Publication: https://drafts.opds.io/schema/publication.schema.json
"""


class OPDS2Link(ApiBaseModel):
    href: str
    rel: str | list[str]
    type: str | None = None
    title: str | None = None
    properties: Mapping[str, Any] | None = None
    templated: bool = False

    @property
    def is_acquisition(self) -> bool:
        """Is this an acquisition link?"""
        return any(
            rel in [OPDS_ACQ_STANDARD_REL, OPDS_ACQ_OPEN_ACCESS_REL]
            for rel in ensure_list(self.rel)
        )

    @property
    def has_indirect_acquisition(self) -> bool:
        """Does link have one or more indirect acquisition links?"""
        return bool(self.indirect_acquisition_links)

    @property
    def indirect_acquisition_links(self) -> Sequence[Mapping[str, Any]]:
        """Indirect acquisition link, if any."""
        return vars(self).get("properties", {}).get("indirectAcquisition", [])  # type: ignore[no-any-return]


class OPDS2(ApiBaseModel):
    catalogs: list[Any] = []
    links: list[OPDS2Link] = []
    metadata: Mapping[str, Any]


class Publisher(ApiBaseModel):
    name: str


class SubjectInfo(ApiBaseModel):
    name: str
    scheme: str | None = None
    sortAs: str | None = None


class Contributor(ApiBaseModel):
    name: str
    links: list[OPDS2Link] = []


class PublicationMetadata(ApiBaseModel):
    type: str = Field(..., alias="@type")
    title: str
    identifier: str
    sortAs: str | None = None
    language: str | None = None
    modified: str | None = None
    published: str | None = None
    description: str | None = None
    publisher: Publisher | None = None
    subject: list[SubjectInfo] = []
    duration: float | None = None
    author: Contributor | list[Contributor] = []
    narrator: Contributor | list[Contributor] = []


class Availability(ApiBaseModel):
    state: str | None = None
    since: str | None = None
    until: str | None = None


class IndirectAcquisitionItem(ApiBaseModel):
    type: str


class Properties(ApiBaseModel):
    availability: Availability | None = None
    indirectAcquisition: list[IndirectAcquisitionItem] = []
    lcp_hashed_passphrase: str | None = None


class Image(ApiBaseModel):
    href: str
    rel: str
    type: str


class Publication(ApiBaseModel):
    metadata: PublicationMetadata
    links: list[OPDS2Link]
    images: list[Image] = []

    @property
    def acquisition_links(self) -> list[OPDS2Link]:
        return match_links(
            self.links,
            lambda link: link.rel in [OPDS_ACQ_STANDARD_REL, OPDS_ACQ_OPEN_ACCESS_REL],
        )

    @property
    def revoke_links(self) -> list[OPDS2Link]:
        return match_links(self.links, lambda link: link.rel == OPDS_REVOKE_REL)

    @property
    def is_loan(self) -> bool:
        """A loan has at least one acquisition link."""
        return bool(self.acquisition_links)


class FeedMetadata(ApiBaseModel):
    title: str


class OPDS2Feed(ApiBaseModel):
    publications: list[Publication] = []
    catalogs: list[Any] = []
    links: list[OPDS2Link] = []
    metadata: Mapping[str, Any]
    facets: list[Any]


L = TypeVar("L", bound=Mapping[str, str] | OPDS2Link)


def match_links(links: Iterable[L], matcher: Callable[[L], bool]) -> list[L]:
    """Generate matching links.

    :param links: The links from which matches will be picked.
    :param matcher: The function that will perform the matching.
    """
    return [link for link in links if matcher(link)]
