from pydantic import BaseModel


class LibraryImportInfo(BaseModel):
    name: str
    short_name: str
    website_url: str
    patron_support_email: str
    large_collection_languages: list[str]
    small_collection_languages: list[str]
    facets_default_order: str
    enabled_entry_points: list[str]
