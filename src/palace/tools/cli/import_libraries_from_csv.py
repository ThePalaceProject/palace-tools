import csv
import traceback
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

import requests
import typer
from pydantic import BaseModel, PositiveInt, ValidationError
from requests import Response

from palace.tools.utils.typer import run_typer_app_as_main

# The audiences a library can filter out. These mirror Classifier.AUDIENCES in
# the circulation manager, and the import endpoint rejects anything else.
VALID_AUDIENCES: tuple[str, ...] = (
    "Adult",
    "Adults Only",
    "All Ages",
    "Children",
    "Research",
    "Young Adult",
)

# The admin interface labels the "Default Availability" options differently from
# the values the API stores, so accept either spelling. Keys are compared
# lower-cased; values are what gets sent to the circulation manager.
AVAILABILITY_BY_NAME: Mapping[str, str] = MappingProxyType(
    {
        "now": "now",
        "available now": "now",
        "all": "all",
        "always": "always",
        "yours to keep": "always",
    }
)

# Shown in --help so an operator knows what a category looks like. There are
# well over a hundred of them, so this is a sample, not the whole list.
EXAMPLE_CATEGORIES: tuple[str, ...] = (
    "Erotica",
    "Horror",
    "Poetry",
    "Romance",
    "Science Fiction",
)

# CSV columns holding a comma-separated list rather than a single value.
LIST_COLUMNS: tuple[str, ...] = (
    "large_collection_languages",
    "small_collection_languages",
    "enabled_entry_points",
    "filtered_audiences",
    "filtered_categories",
)


class CsvRowError(Exception):
    """A row in the CSV could not be turned into a library."""


class LibraryImportInfo(BaseModel):
    """One library, as the circulation manager's import endpoint expects it.

    Fields that default to ``None`` are optional. They are left out of the
    uploaded JSON entirely, so the circulation manager applies its own default
    for any setting the CSV does not mention.
    """

    name: str
    short_name: str
    website_url: str
    patron_support_email: str
    large_collection_languages: list[str]
    small_collection_languages: list[str]
    facets_default_order: str
    enabled_entry_points: list[str]
    featured_lane_size: PositiveInt | None = None
    facets_default_available: str | None = None
    filtered_audiences: list[str] | None = None
    filtered_categories: list[str] | None = None


app = typer.Typer()


def upload_library_to_palace(
    base_url: str,
    username: str,
    password: str,
    library: LibraryImportInfo,
    verbose: bool = False,
) -> Response:
    """Upload CSV rows as JSON to Palace import-libraries-from-csv endpoint."""
    import_url = f"{base_url.rstrip('/')}/admin/libraries/import"

    if verbose:
        typer.echo(f"Importing {library.name} to {import_url}...")

    # I'm sending these one by one because the import operation currently takes several seconds for each
    # library due to the database intensive default lane creation operation. Since there can be over a hundred
    # libraries on a CM, it's better to import the libraries one at a time.
    response = requests.post(
        url=import_url,
        json={"libraries": [library.model_dump(exclude_none=True)]},
        auth=(username, password),
        headers={"Content-Type": "application/json"},
    )
    return response


REQUIRED_COLUMNS: tuple[str, ...] = (
    "name",
    "short_name",
    "website_url",
    "patron_support_email",
    "large_collection_languages",
    "small_collection_languages",
    "enabled_entry_points",
    "facets_default_order",
)


def _build_help() -> str:
    """Describe the CSV columns, so --help is enough to write one."""
    availability = ", ".join(sorted(set(AVAILABILITY_BY_NAME)))
    return "\n\n".join(
        [
            "Import libraries from a CSV file into a Palace circulation manager.",
            "Required columns: " + ", ".join(REQUIRED_COLUMNS) + ".",
            "Optional columns, under 'Lanes & Filters' and 'Content Filtering' in"
            " the admin interface. Leaving one out, or leaving its cell blank,"
            " keeps the circulation manager's own default for that setting:",
            "featured_lane_size - \"Maximum number of books in the 'featured'"
            ' lanes". A whole number greater than zero, for example 35.',
            'facets_default_available - "Default Availability". One of: '
            + availability
            + ".",
            'filtered_audiences - "Filtered audiences". Each value must be one of: '
            + ", ".join(VALID_AUDIENCES)
            + ".",
            'filtered_categories - "Filtered categories". Fiction genres and'
            " non-fiction subjects, for example: "
            + ", ".join(EXAMPLE_CATEGORIES)
            + ". There are many more. The full list is the one offered under"
            " Content Filtering in the admin interface, and the circulation"
            " manager checks every value in this column against it.",
            "Columns holding a list (languages, entry points, audiences and"
            ' categories) are comma-separated, for example "Adult,Young Adult".',
        ]
    )


@app.command(help=_build_help())
def import_libraries(
    username: str = typer.Option(
        ..., "--username", "-u", help="Palace username for authentication"
    ),
    password: str = typer.Option(
        ..., "--password", "-p", help="Palace password for authentication"
    ),
    palace_base_url: str = typer.Option(
        ..., "--palace-base-url", "-b", help="Palace base URL"
    ),
    csv_file: Path = typer.Argument(
        ...,
        help="Path to the library CSV file to process.",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Enable verbose output"
    ),
) -> None:
    if verbose:
        typer.echo(f"Processing CSV file: {csv_file}")
        typer.echo(f"Username: {username}")
        typer.echo(f"Palace Base URL: {palace_base_url}")

    try:
        _import_csv_async(username, password, palace_base_url, csv_file, verbose)

    except Exception as e:
        typer.echo(f"Error importing CSV file: {e}", err=True)
        if verbose:
            typer.echo(f"stack trace: {traceback.format_exc()}")
        raise typer.Exit(1)


def _import_csv_async(
    username: str, password: str, palace_base_url: str, csv_file: Path, verbose: bool
) -> None:
    """Async implementation of CSV import."""
    # Step 1: Parse CSV file
    typer.echo("Parsing CSV file...")

    libraries = _parse_csv_file(csv_file, verbose)

    typer.echo(f"Successfully parsed {len(libraries)} rows from CSV")
    if verbose:
        if libraries:
            typer.echo(f"Columns: {list(libraries[0].__dict__.keys())}")

    for library in libraries:
        response = upload_library_to_palace(
            palace_base_url, username, password, library, verbose
        )

        if response.status_code in [200, 201, 207]:
            typer.echo(
                f"✅ Successfully imported library {library.name} from CSV file!"
            )
            if verbose and response.text:
                typer.echo(f"Response: {response.text}")
        else:
            typer.echo(f"❌ Failed to import libraries. Status: {response.status_code}")
            typer.echo(f"Error: {response.text}")
            raise typer.Exit(1)


def _convert_string_value_to_list(d: dict[str, Any], field_name: str) -> None:
    """Split a comma-separated cell into a list, dropping blank entries.

    A column that is missing or blank is left as None, so that a required field
    is reported as missing and an optional one falls back to the circulation
    manager's default.
    """
    raw = d.get(field_name)
    if raw is None:
        d[field_name] = None
        return
    d[field_name] = [item.strip() for item in raw.split(",") if item.strip()] or None


def _validate_featured_lane_size(value: str | None) -> None:
    """Reject a featured lane size that isn't a whole number above zero."""
    if value is None:
        return
    try:
        size = int(value)
    except ValueError:
        raise CsvRowError(
            f"'featured_lane_size' must be a whole number, not {value!r}."
        )
    if size < 1:
        raise CsvRowError(f"'featured_lane_size' must be greater than 0, not {size}.")


def _normalize_availability(value: str | None) -> str | None:
    """Turn a "Default Availability" cell into the value the API expects."""
    if value is None:
        return None
    normalized = AVAILABILITY_BY_NAME.get(value.strip().lower())
    if normalized is None:
        options = ", ".join(sorted(set(AVAILABILITY_BY_NAME)))
        raise CsvRowError(
            f"'facets_default_available' must be one of: {options}. Got {value!r}."
        )
    return normalized


def _validate_audiences(values: list[str] | None) -> None:
    """Reject audiences the circulation manager doesn't know about."""
    if not values:
        return
    invalid = [audience for audience in values if audience not in VALID_AUDIENCES]
    if invalid:
        raise CsvRowError(
            f"'filtered_audiences' contains invalid values: {', '.join(invalid)}. "
            f"Valid values are: {', '.join(VALID_AUDIENCES)}."
        )


def _row_to_library(row: dict[str, Any]) -> LibraryImportInfo:
    """Clean up one CSV row and turn it into a library, or raise CsvRowError."""
    # A row with more cells than headers puts the surplus under a None key, and
    # a short row leaves missing cells as None. Drop both, then blank out any
    # cell that holds only whitespace.
    cleaned_row: dict[str, Any] = {
        key: (value.strip() or None)
        for key, value in row.items()
        if key is not None and isinstance(value, str)
    }

    for column in LIST_COLUMNS:
        _convert_string_value_to_list(cleaned_row, column)

    _validate_featured_lane_size(cleaned_row.get("featured_lane_size"))
    cleaned_row["facets_default_available"] = _normalize_availability(
        cleaned_row.get("facets_default_available")
    )
    _validate_audiences(cleaned_row.get("filtered_audiences"))

    # Categories are checked by the circulation manager, which compares them
    # against the genres stored in its database. There are too many to repeat
    # here, and the list can change without this tool being updated.

    try:
        return LibraryImportInfo(**cleaned_row)
    except ValidationError as e:
        raise CsvRowError(str(e))


def _parse_csv_file(csv_file: Path, verbose: bool = False) -> list[LibraryImportInfo]:
    """Parse CSV file and return the libraries it describes.

    Every row is checked before anything is uploaded, so a bad value late in the
    file doesn't leave a half-finished import behind.
    """
    rows: list[LibraryImportInfo] = []
    errors: list[str] = []

    with csv_file.open("r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        for row in reader:
            try:
                rows.append(_row_to_library(row))
            except CsvRowError as e:
                # reader.line_num is the line in the file, counting the header.
                errors.append(f"Line {reader.line_num}: {e}")

    if errors:
        for error in errors:
            typer.echo(f"❌ {error}", err=True)
        raise CsvRowError(
            f"{len(errors)} of {len(errors) + len(rows)} rows are invalid. "
            f"Nothing was imported."
        )

    return rows


def main() -> None:
    run_typer_app_as_main(app, prog_name="import-libraries-from-csv")


if __name__ == "__main__":
    main()
