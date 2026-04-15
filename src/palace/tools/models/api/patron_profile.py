from pydantic import Field

from palace.tools.models.api.opds2 import OPDS2Link
from palace.tools.models.api.util import ApiBaseModel


class Settings(ApiBaseModel):
    simplified_synchronize_annotations: bool = Field(
        ..., alias="simplified:synchronize_annotations"
    )


class DrmItem(ApiBaseModel):
    drm_vendor: str = Field(..., alias="drm:vendor")
    drm_clientToken: str = Field(..., alias="drm:clientToken")
    drm_scheme: str = Field(..., alias="drm:scheme")


class PatronProfileDocument(ApiBaseModel):
    simplified_authorization_identifier: str = Field(
        ..., alias="simplified:authorization_identifier"
    )
    settings: Settings
    links: list[OPDS2Link]
    drm: list[DrmItem]
