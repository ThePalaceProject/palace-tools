import csv
import traceback
from pathlib import Path
from typing import Any

import requests
import typer
from requests import Response

from palace.manager.api.admin.controller.library_settings import LibraryImportInfo

from palace_tools.utils.typer import run_typer_app_as_main

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
        json={"libraries": [library.__dict__]},
        auth=(username, password),
        headers={"Content-Type": "application/json"},
    )
    return response


@app.command()
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
        help="Path to the library CSV file to process: The CSV must contain the following headers: "
        "name, short_name, description, website_url, patron_support_email, large_collection_languages, "
        "small_collection_languages, enabled_entry_points, facets_default_order",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Enable verbose output"
    ),
) -> None:
    """Import libraries from CSV file to Palace service."""

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
            typer.echo(f"✅ Successfully imported library {library.name} from CSV file!")
            if verbose and response.text:
                typer.echo(f"Response: {response.text}")
        else:
            typer.echo(f"❌ Failed to import libraries. Status: {response.status_code}")
            typer.echo(f"Error: {response.text}")
            raise typer.Exit(1)


def _convert_string_value_to_list(d: dict[str, Any], field_name: str) -> None:
    d[field_name] = list(d[field_name].split(","))


def _parse_csv_file(csv_file: Path, verbose: bool = False) -> list[LibraryImportInfo]:
    """Parse CSV file and return list of dictionaries."""
    rows: list[LibraryImportInfo] = []

    with csv_file.open("r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        for row in reader:
            # Convert any empty strings to None for cleaner JSON
            cleaned_row = {k: (v if v.strip() else None) for k, v in row.items()}
            _convert_string_value_to_list(cleaned_row, "large_collection_languages")
            _convert_string_value_to_list(cleaned_row, "small_collection_languages")
            _convert_string_value_to_list(cleaned_row, "enabled_entry_points")
            library_info_info = LibraryImportInfo(**cleaned_row)

            rows.append(library_info_info)

    return rows


def main() -> None:
    run_typer_app_as_main(app, prog_name="import-libraries-from-csv")


if __name__ == "__main__":
    main()
