import csv
import traceback
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

import requests
import typer
from pydantic import BaseModel, PositiveInt, ValidationError
from requests import RequestException, Response

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

OPTIONAL_COLUMNS: tuple[str, ...] = (
    "featured_lane_size",
    "facets_default_available",
    "filtered_audiences",
    "filtered_categories",
)

# Columns the tool reads past without complaint. They are not sent anywhere;
# they are here so a spreadsheet that also carries notes for human readers
# doesn't have to be stripped down before it can be imported.
IGNORED_COLUMNS: tuple[str, ...] = ("description",)

# Required columns holding a comma-separated list. A blank cell in one of these
# means an empty list, which the circulation manager accepts.
REQUIRED_LIST_COLUMNS: tuple[str, ...] = (
    "large_collection_languages",
    "small_collection_languages",
    "enabled_entry_points",
)

# Optional columns holding a comma-separated list. A blank cell in one of these
# is left out of the upload, so the circulation manager's default applies.
OPTIONAL_LIST_COLUMNS: tuple[str, ...] = (
    "filtered_audiences",
    "filtered_categories",
)

KNOWN_COLUMNS: frozenset[str] = frozenset(
    REQUIRED_COLUMNS + OPTIONAL_COLUMNS + IGNORED_COLUMNS
)

# A stalled circulation manager shouldn't hang the run forever. Creating a
# library's default lanes takes a few seconds, so the read timeout is generous.
CONNECT_TIMEOUT_SECONDS = 10.0
DEFAULT_READ_TIMEOUT_SECONDS = 300.0


class CsvFileError(Exception):
    """The CSV file as a whole could not be used."""


class CsvRowError(Exception):
    """A row in the CSV could not be turned into a library."""


class UploadError(Exception):
    """A library could not be sent to the circulation manager at all."""


class UploadResult(StrEnum):
    """What the circulation manager did with one library."""

    CREATED = "created"
    # The short name was already taken, so the row was left alone. Expected
    # when a file is re-run to add a few libraries to a set already imported.
    SKIPPED = "skipped"
    FAILED = "failed"


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
    read_timeout: float = DEFAULT_READ_TIMEOUT_SECONDS,
) -> Response:
    """Upload CSV rows as JSON to Palace import-libraries-from-csv endpoint."""
    import_url = f"{base_url.rstrip('/')}/admin/libraries/import"

    if verbose:
        typer.echo(f"Importing {library.name} to {import_url}...")

    # I'm sending these one by one because the import operation currently takes several seconds for each
    # library due to the database intensive default lane creation operation. Since there can be over a hundred
    # libraries on a CM, it's better to import the libraries one at a time.
    try:
        response = requests.post(
            url=import_url,
            json={"libraries": [library.model_dump(exclude_none=True)]},
            auth=(username, password),
            headers={"Content-Type": "application/json"},
            timeout=(CONNECT_TIMEOUT_SECONDS, read_timeout),
        )
    except RequestException as e:
        raise UploadError(f"{library.name}: could not reach {import_url}: {e}")
    return response


def _report_upload(library: LibraryImportInfo, response: Response) -> UploadResult:
    """Say what the circulation manager did with one library.

    The endpoint answers 207 when the library in the payload was rejected, and
    its body says ``"result": "success"`` either way, so the status code on its
    own cannot be trusted; the ``errors``, ``skipped`` and ``created`` lists are
    what count.

    Raises UploadError when the request failed outright, which usually means
    every remaining row would fail the same way.
    """
    if response.status_code not in (200, 201, 207):
        raise UploadError(
            f"{library.name}: the circulation manager answered "
            f"{response.status_code}. {response.text}"
        )

    try:
        body = response.json()
    except ValueError:
        raise UploadError(
            f"{library.name}: expected JSON from the circulation manager, got "
            f"{response.text[:200]!r}"
        )
    if not isinstance(body, dict):
        raise UploadError(
            f"{library.name}: expected a JSON object from the circulation "
            f"manager, got {body!r}"
        )

    errors = body.get("errors") or []
    if errors:
        for error in errors:
            detail = error.get("error") if isinstance(error, dict) else error
            typer.echo(f"❌ {library.name}: {detail}", err=True)
        return UploadResult.FAILED

    if body.get("skipped"):
        # The endpoint leaves an existing library exactly as it is, so none of
        # the settings in this row were applied to it.
        typer.echo(
            f"⏭️  {library.name}: a library with the short name "
            f"'{library.short_name}' already exists. It was left unchanged."
        )
        return UploadResult.SKIPPED

    if body.get("created"):
        typer.echo(f"✅ Created library {library.name}.")
        return UploadResult.CREATED

    typer.echo(
        f"❌ {library.name}: the circulation manager reported neither a created "
        f"nor a skipped library. {response.text[:200]}",
        err=True,
    )
    return UploadResult.FAILED


def _build_help() -> str:
    """Describe the CSV columns, so --help is enough to write one."""
    availability = ", ".join(sorted(set(AVAILABILITY_BY_NAME)))
    return "\n\n".join(
        [
            "Import libraries from a CSV file into a Palace circulation manager.",
            "Only libraries that do not exist yet are created. A row whose"
            " short_name is already taken is left exactly as it is, and none of"
            " the settings in that row are applied to it.",
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
            ' categories) are comma-separated, for example "Adult,Young Adult".'
            " Leaving a required list column blank means an empty list.",
            "A '" + "', '".join(IGNORED_COLUMNS) + "' column is allowed and"
            " ignored. Any other unrecognised column is an error, so that a"
            " misspelled heading is not quietly passed over.",
            "Every row is checked before anything is uploaded. The circulation"
            " manager checks some values itself, though, so a row it rejects can"
            " still stop a run part of the way through. The summary at the end"
            " says what was created.",
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
    read_timeout: float = typer.Option(
        DEFAULT_READ_TIMEOUT_SECONDS,
        "--timeout",
        help="Seconds to wait for the circulation manager to answer about one library.",
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
        _import_csv(
            username, password, palace_base_url, csv_file, verbose, read_timeout
        )
    except typer.Exit:
        # typer.Exit subclasses RuntimeError, so without this it would be caught
        # below and reported as an unexpected failure.
        raise
    except Exception as e:
        typer.echo(f"Error importing CSV file: {e}", err=True)
        if verbose:
            typer.echo(f"stack trace: {traceback.format_exc()}")
        raise typer.Exit(1)


def _import_csv(
    username: str,
    password: str,
    palace_base_url: str,
    csv_file: Path,
    verbose: bool,
    read_timeout: float = DEFAULT_READ_TIMEOUT_SECONDS,
) -> None:
    """Read the CSV and send each library it describes to the circulation manager."""
    typer.echo("Parsing CSV file...")

    libraries, columns = _parse_csv_file(csv_file)

    typer.echo(f"Successfully parsed {len(libraries)} rows from CSV")
    if verbose:
        typer.echo(f"Columns: {', '.join(columns)}")

    counts = {result: 0 for result in UploadResult}
    for position, library in enumerate(libraries):
        try:
            response = upload_library_to_palace(
                palace_base_url, username, password, library, verbose, read_timeout
            )
            result = _report_upload(library, response)
        except UploadError as e:
            # Something is wrong with the request or the server rather than with
            # this one row, so stop rather than failing the same way for every
            # library that is left.
            typer.echo(f"❌ {e}", err=True)
            _echo_summary(counts, remaining=len(libraries) - position)
            raise typer.Exit(1)

        counts[result] += 1
        if verbose and response.text:
            typer.echo(f"Response: {response.text}")

    _echo_summary(counts, remaining=0)
    if counts[UploadResult.FAILED]:
        raise typer.Exit(1)


def _echo_summary(counts: Mapping[UploadResult, int], remaining: int) -> None:
    """Say what actually happened, including anything left undone."""
    created = counts[UploadResult.CREATED]
    typer.echo(f"Created {created} librar{'y' if created == 1 else 'ies'}.")

    skipped = counts[UploadResult.SKIPPED]
    if skipped:
        typer.echo(
            f"{skipped} already existed and were left unchanged, so the settings "
            f"in those rows were not applied."
        )

    failed = counts[UploadResult.FAILED]
    if failed:
        typer.echo(
            f"{failed} refused by the circulation manager, listed above.", err=True
        )

    if remaining:
        typer.echo(
            f"Stopped with {remaining} librar{'y' if remaining == 1 else 'ies'} "
            f"left to try. Libraries already created stay created; running the "
            f"same file again leaves them alone.",
            err=True,
        )


def _split_list_cell(value: str | None) -> list[str]:
    """Split a comma-separated cell into a list, dropping blank entries."""
    if value is None:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _validate_featured_lane_size(value: str | None) -> None:
    """Reject a featured lane size that isn't a whole number above zero."""
    if value is None:
        return
    # Not int(): that also accepts "3_5" (as 35) and non-ASCII digits, so a typo
    # would either change the number quietly or fail later with a raw pydantic
    # error instead of this message.
    if not (value.isascii() and value.isdigit()):
        raise CsvRowError(
            f"'featured_lane_size' must be a whole number, not {value!r}."
        )
    if int(value) < 1:
        raise CsvRowError(f"'featured_lane_size' must be greater than 0, not {value}.")


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
    # A row with more cells than headers puts the surplus under a None key, and a
    # short row leaves missing cells as None. Drop both, then blank out any cell
    # that holds only whitespace. A column that isn't here at all stays absent,
    # so a required one is reported as missing rather than as the wrong type.
    cleaned_row: dict[str, Any] = {
        key: (value.strip() or None)
        for key, value in row.items()
        if key is not None and isinstance(value, str)
    }

    # A blank required list cell means an empty list, which the circulation
    # manager accepts. A blank optional one is left out, so its default applies.
    for column in REQUIRED_LIST_COLUMNS:
        if column in cleaned_row:
            cleaned_row[column] = _split_list_cell(cleaned_row[column])
    for column in OPTIONAL_LIST_COLUMNS:
        if column in cleaned_row:
            values = _split_list_cell(cleaned_row[column])
            if values:
                cleaned_row[column] = values
            else:
                del cleaned_row[column]

    _validate_featured_lane_size(cleaned_row.get("featured_lane_size"))
    if "facets_default_available" in cleaned_row:
        normalized = _normalize_availability(cleaned_row["facets_default_available"])
        if normalized is None:
            del cleaned_row["facets_default_available"]
        else:
            cleaned_row["facets_default_available"] = normalized
    _validate_audiences(cleaned_row.get("filtered_audiences"))

    # Categories are checked by the circulation manager, which compares them
    # against the genres stored in its database. There are too many to repeat
    # here, and the list can change without this tool being updated.

    try:
        return LibraryImportInfo(**cleaned_row)
    except ValidationError as e:
        raise CsvRowError(str(e))


def _check_columns(fieldnames: list[str]) -> None:
    """Make sure the header names a usable set of columns."""
    duplicates = sorted({name for name in fieldnames if fieldnames.count(name) > 1})
    if duplicates:
        raise CsvFileError(
            f"These columns appear more than once: {', '.join(duplicates)}. Only "
            f"the last of each would be read, so the rest would be lost."
        )

    missing = [name for name in REQUIRED_COLUMNS if name not in fieldnames]
    if missing:
        raise CsvFileError(f"These required columns are missing: {', '.join(missing)}.")

    unknown = sorted(name for name in fieldnames if name not in KNOWN_COLUMNS)
    if unknown:
        known = ", ".join(sorted(KNOWN_COLUMNS))
        raise CsvFileError(
            f"These columns are not recognised: {', '.join(unknown)}. The columns "
            f"this tool reads are: {known}."
        )


def _parse_csv_file(csv_file: Path) -> tuple[list[LibraryImportInfo], list[str]]:
    """Read the CSV and return the libraries it describes, with its columns.

    Every row is checked before any of them is uploaded, so a value this tool
    can reject doesn't leave a half-finished import behind. The circulation
    manager checks some values itself, so a row it rejects can still stop a run
    part of the way through.
    """
    rows: list[LibraryImportInfo] = []
    errors: list[str] = []

    # utf-8-sig, not utf-8: Excel and Google Sheets both write a byte order mark,
    # which would otherwise become part of the first column's name and make every
    # row fail for a missing 'name'.
    with csv_file.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)

        if reader.fieldnames is None:
            raise CsvFileError(f"{csv_file} is empty: it has no header row.")

        # Headers are no more immune to stray spaces than the cells beneath them.
        reader.fieldnames = [name.strip() for name in reader.fieldnames]
        columns = list(reader.fieldnames)
        _check_columns(columns)

        for row in reader:
            try:
                rows.append(_row_to_library(row))
            except CsvRowError as e:
                # reader.line_num is the line in the file, counting the header.
                errors.append(f"Line {reader.line_num}: {e}")

    if errors:
        for error in errors:
            typer.echo(f"❌ {error}", err=True)
        raise CsvFileError(
            f"{len(errors)} of {len(errors) + len(rows)} rows are invalid. "
            f"Nothing was imported."
        )

    if not rows:
        raise CsvFileError(
            f"{csv_file} has a header but no libraries under it. Nothing to import."
        )

    return rows, columns


def main() -> None:
    run_typer_app_as_main(app, prog_name="import-libraries-from-csv")


if __name__ == "__main__":
    main()
