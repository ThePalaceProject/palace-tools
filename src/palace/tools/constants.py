import sys

if sys.version_info < (3, 11):
    from backports.strenum import StrEnum
else:
    from enum import StrEnum


# Some defaults

DEFAULT_ASYNC_TIMEOUT = 30.0
DEFAULT_AUTH_DOC_PATH_SUFFIX = "authentication_document"
DEFAULT_REGISTRY_URL = "https://registry.thepalaceproject.org"
DEFAULT_USER_AGENT = "Palace"

# Some other constants.
LCP_AUDIOBOOK_TYPE = "application/audiobook+lcp"
LCP_LICENSE_PUBLICATION_REL = "publication"

OPDS_ACQ_STANDARD_REL = "http://opds-spec.org/acquisition"
OPDS_ACQ_OPEN_ACCESS_REL = "http://opds-spec.org/acquisition/open-access"
OPDS_AUTH_DOC_REL = "http://opds-spec.org/auth/document"
OPDS_AUTH_DOC_TYPE = "application/vnd.opds.authentication.v1.0+json"
OPDS_REVOKE_REL = "http://librarysimplified.org/terms/rel/revoke"
OPDS_1_TYPE = "application/atom+xml"
OPDS_2_TYPE = "application/opds+json"


PATRON_AUTH_BASIC_TOKEN_TYPE = "http://thepalaceproject.org/authtype/basic-token"
PATRON_AUTH_BASIC_TYPE = "http://opds-spec.org/auth/basic"
PATRON_BOOKSHELF_REL = "http://opds-spec.org/shelf"
PATRON_BOOKSHELF_TYPE = "application/atom+xml;profile=opds-catalog;kind=acquisition"
PATRON_PROFILE_REL = "http://librarysimplified.org/terms/rel/user-profile"
PATRON_PROFILE_TYPE = "vnd.librarysimplified/user-profile+json"


class OpdsEnum(StrEnum):
    OPDS_1 = "1"
    OPDS_2 = "2"

    def content_type(self) -> str:
        match self:
            case OpdsEnum.OPDS_1:
                return OPDS_1_TYPE
            case OpdsEnum.OPDS_2:
                return OPDS_2_TYPE
        # Make `mypy` happy, since it thinks the list isn't exhaustive.
        assert False
