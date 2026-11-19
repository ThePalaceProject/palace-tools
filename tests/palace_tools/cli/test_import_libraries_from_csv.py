"""Tests for the import-libraries-from-csv CLI tool."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import requests
from typer.testing import CliRunner

from palace.tools.cli.import_libraries_from_csv import (
    EXAMPLE_CATEGORIES,
    IGNORED_COLUMNS,
    REQUIRED_COLUMNS,
    VALID_AUDIENCES,
    CsvFileError,
    LibraryImportInfo,
    UploadError,
    UploadResult,
    _parse_csv_file,
    _report_upload,
    app,
)

runner = CliRunner()

REQUIRED_ROW = {
    "name": "Test Library",
    "short_name": "test",
    "website_url": "https://library.example.com",
    "patron_support_email": "support@example.com",
    "large_collection_languages": "English",
    "small_collection_languages": "Spanish",
    "enabled_entry_points": "All,Book,Audio",
    "facets_default_order": "added",
}

OPTIONAL_COLUMNS_UNDER_TEST = (
    "featured_lane_size",
    "facets_default_available",
    "filtered_audiences",
    "filtered_categories",
)

CLI_CONNECTION_ARGS = ["-u", "user", "-p", "secret", "-b", "https://cm.example.com"]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> Path:
    """Write rows to a CSV file, using the union of their keys as the header."""
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    if not fieldnames:
        fieldnames = list(REQUIRED_ROW)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def library_row(**overrides: Any) -> dict[str, Any]:
    """A valid CSV row, with any column overridden or added."""
    return {**REQUIRED_ROW, **overrides}


def required_row_csv(path: Path, *extra_lines: str) -> Path:
    """Write a CSV by hand, for headers DictWriter can't produce."""
    header = ",".join(REQUIRED_ROW)
    values = ",".join(value.replace(",", ";") for value in REQUIRED_ROW.values())
    path.write_text("\n".join([header, values, *extra_lines]) + "\n")
    return path


def parse(path: Path) -> list[LibraryImportInfo]:
    """The libraries in a CSV, without its column list."""
    libraries, _ = _parse_csv_file(path)
    return libraries


def model_kwargs() -> dict[str, Any]:
    """The arguments for a valid LibraryImportInfo."""
    return {
        "name": "Test Library",
        "short_name": "test",
        "website_url": "https://library.example.com",
        "patron_support_email": "support@example.com",
        "large_collection_languages": ["English"],
        "small_collection_languages": ["Spanish"],
        "facets_default_order": "added",
        "enabled_entry_points": ["All"],
    }


def make_response(
    status_code: int = 200, body: Any = None, text: str | None = None
) -> requests.Response:
    """A real Response, so the code under test does its own JSON decoding."""
    response = requests.Response()
    response.status_code = status_code
    payload = text if text is not None else json.dumps(body)
    response._content = payload.encode("utf-8")
    response.headers["Content-Type"] = "application/json"
    return response


def cm_response(
    created: int = 0, skipped: int = 0, errors: list[str] | None = None
) -> requests.Response:
    """A response shaped like the import endpoint's, for one library."""
    error_list = [{"index": 0, "error": message} for message in (errors or [])]
    return make_response(
        # The endpoint answers 207 when a library was rejected, 200 otherwise.
        status_code=207 if error_list else 200,
        body={
            # Note that the endpoint says "success" even when nothing worked.
            "result": "success",
            "created": [{"short_name": "test"}] * created,
            "skipped": [{"short_name": "test"}] * skipped,
            "errors": error_list,
        },
    )


def run_import(csv_path: Path, responses: list[Any], *extra_args: str) -> Any:
    """Run the CLI end to end with canned responses from the circulation manager."""
    with patch.object(requests, "post", side_effect=responses):
        return runner.invoke(app, [*CLI_CONNECTION_ARGS, str(csv_path), *extra_args])


class TestImportLibrariesFromCsv:
    """Tests for the import-libraries-from-csv command."""

    # ------------------------------------------------------------------
    # Help text
    # ------------------------------------------------------------------

    def test_help_lists_every_audience(self) -> None:
        """The help text names all the audiences that can be filtered."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        # Typer wraps help text, so compare without the line breaks.
        help_text = " ".join(result.output.split())
        for audience in VALID_AUDIENCES:
            assert audience in help_text

    def test_help_gives_category_examples_not_the_whole_list(self) -> None:
        """The help text samples categories rather than listing all of them."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        help_text = " ".join(result.output.split())
        for category in EXAMPLE_CATEGORIES:
            assert category in help_text
        assert 4 <= len(EXAMPLE_CATEGORIES) <= 5
        # The full list lives in the admin interface, and the help says so.
        assert "admin interface" in help_text

    def test_help_lists_the_new_columns(self) -> None:
        """The help text documents each optional column."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        help_text = " ".join(result.output.split())
        for column in OPTIONAL_COLUMNS_UNDER_TEST:
            assert column in help_text

    def test_help_says_existing_libraries_are_left_alone(self) -> None:
        """The help warns that these settings only apply to new libraries."""
        result = runner.invoke(app, ["--help"])
        help_text = " ".join(result.output.split())
        assert "do not exist yet" in help_text
        assert "already taken" in help_text

    def test_documented_required_columns_match_the_model(self) -> None:
        """The columns --help calls required are the ones the model demands."""
        model_required = {
            name
            for name, field in LibraryImportInfo.model_fields.items()
            if field.is_required()
        }
        assert set(REQUIRED_COLUMNS) == model_required
        assert set(REQUIRED_ROW) == model_required

    def test_documented_optional_columns_match_the_model(self) -> None:
        """The columns --help calls optional are the ones that default to None."""
        model_optional = {
            name
            for name, field in LibraryImportInfo.model_fields.items()
            if not field.is_required()
        }
        assert set(OPTIONAL_COLUMNS_UNDER_TEST) == model_optional

    # ------------------------------------------------------------------
    # Reading the optional columns
    # ------------------------------------------------------------------

    def test_parse_optional_columns(self, tmp_path: Path) -> None:
        """The optional columns are read into the library."""
        csv_file = write_csv(
            tmp_path / "libraries.csv",
            [
                library_row(
                    featured_lane_size="35",
                    facets_default_available="Available now",
                    filtered_audiences="Research,Adults Only",
                    filtered_categories="Erotica,Horror",
                )
            ],
        )

        libraries = parse(csv_file)

        assert len(libraries) == 1
        library = libraries[0]
        assert library.featured_lane_size == 35
        assert library.facets_default_available == "now"
        assert library.filtered_audiences == ["Research", "Adults Only"]
        assert library.filtered_categories == ["Erotica", "Horror"]

    def test_parse_without_optional_columns(self, tmp_path: Path) -> None:
        """A CSV with only the required columns still parses."""
        csv_file = write_csv(tmp_path / "libraries.csv", [library_row()])

        libraries = parse(csv_file)

        assert len(libraries) == 1
        for column in OPTIONAL_COLUMNS_UNDER_TEST:
            assert getattr(libraries[0], column) is None

    def test_blank_optional_columns_are_treated_as_absent(self, tmp_path: Path) -> None:
        """A blank cell means "use the circulation manager's default"."""
        csv_file = write_csv(
            tmp_path / "libraries.csv",
            [
                library_row(
                    featured_lane_size="",
                    facets_default_available="   ",
                    filtered_audiences="",
                    filtered_categories="",
                )
            ],
        )

        libraries = parse(csv_file)

        for column in OPTIONAL_COLUMNS_UNDER_TEST:
            assert getattr(libraries[0], column) is None

    def test_unset_optional_columns_are_left_out_of_the_upload(self) -> None:
        """Fields the CSV didn't set are not sent, so the server default wins."""
        library = LibraryImportInfo(**model_kwargs())

        payload = library.model_dump(exclude_none=True)

        for column in OPTIONAL_COLUMNS_UNDER_TEST:
            assert column not in payload

    @pytest.mark.parametrize(
        "value,expected",
        [
            pytest.param("now", "now", id="api_value"),
            pytest.param("Available now", "now", id="admin_label"),
            pytest.param("AVAILABLE NOW", "now", id="admin_label_shouting"),
            pytest.param("all", "all", id="all"),
            pytest.param("always", "always", id="always"),
            pytest.param("Yours to keep", "always", id="open_access_label"),
        ],
    )
    def test_availability_accepts_api_value_or_admin_label(
        self, tmp_path: Path, value: str, expected: str
    ) -> None:
        """Default Availability can be given as the API value or the UI label."""
        csv_file = write_csv(
            tmp_path / "libraries.csv",
            [library_row(facets_default_available=value)],
        )

        assert parse(csv_file)[0].facets_default_available == expected

    def test_list_columns_are_trimmed(self, tmp_path: Path) -> None:
        """Spaces around comma-separated values are ignored."""
        csv_file = write_csv(
            tmp_path / "libraries.csv",
            [library_row(filtered_audiences="Research , Adults Only ,")],
        )

        assert parse(csv_file)[0].filtered_audiences == ["Research", "Adults Only"]

    def test_every_audience_is_accepted(self, tmp_path: Path) -> None:
        """All the documented audiences are legal values."""
        csv_file = write_csv(
            tmp_path / "libraries.csv",
            [library_row(filtered_audiences=",".join(VALID_AUDIENCES))],
        )

        assert parse(csv_file)[0].filtered_audiences == list(VALID_AUDIENCES)

    # ------------------------------------------------------------------
    # Rejecting bad values
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        "column,value",
        [
            pytest.param("featured_lane_size", "many", id="lane_size_not_a_number"),
            pytest.param("featured_lane_size", "0", id="lane_size_zero"),
            pytest.param("featured_lane_size", "-5", id="lane_size_negative"),
            pytest.param(
                "facets_default_available", "whenever", id="availability_unknown"
            ),
            pytest.param(
                "filtered_audiences", "Adult,Grown-ups", id="audience_unknown"
            ),
            pytest.param("filtered_audiences", "adult", id="audience_wrong_case"),
            pytest.param("name", "", id="missing_required_value"),
        ],
    )
    def test_invalid_values_are_rejected(
        self, tmp_path: Path, column: str, value: str
    ) -> None:
        """A bad cell stops the import before anything is uploaded."""
        csv_file = write_csv(
            tmp_path / "libraries.csv", [library_row(**{column: value})]
        )

        with pytest.raises(CsvFileError) as excinfo:
            parse(csv_file)

        assert "Nothing was imported" in str(excinfo.value)

    @pytest.mark.parametrize(
        "value",
        ["35_000", "٣٥", "3.5", "+35"],
        ids=["underscores", "arabic_digits", "fractional", "signed"],
    )
    def test_lane_size_is_not_silently_reinterpreted(
        self, tmp_path: Path, value: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """int() would take some of these and change the number; this doesn't."""
        csv_file = write_csv(
            tmp_path / "libraries.csv", [library_row(featured_lane_size=value)]
        )

        with pytest.raises(CsvFileError):
            parse(csv_file)

        assert "must be a whole number" in capsys.readouterr().err

    def test_invalid_audience_error_lists_the_valid_values(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The error an operator sees names the audiences they can use."""
        csv_file = write_csv(
            tmp_path / "libraries.csv", [library_row(filtered_audiences="Grown-ups")]
        )

        with pytest.raises(CsvFileError):
            parse(csv_file)

        reported = capsys.readouterr().err
        assert "Grown-ups" in reported
        for audience in VALID_AUDIENCES:
            assert audience in reported

    def test_nothing_is_imported_when_a_later_row_is_bad(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """One bad row stops the whole file, so no half-finished import."""
        csv_file = write_csv(
            tmp_path / "libraries.csv",
            [
                library_row(name="Good One", short_name="good1"),
                library_row(
                    name="Bad One", short_name="bad", filtered_audiences="Grown-ups"
                ),
                library_row(name="Good Two", short_name="good2"),
            ],
        )

        with pytest.raises(CsvFileError) as excinfo:
            parse(csv_file)

        assert "1 of 3 rows are invalid" in str(excinfo.value)
        # The header is line 1, so the bad row is line 3.
        assert "Line 3" in capsys.readouterr().err

    def test_every_bad_row_is_reported(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """All the problems are listed at once, not just the first."""
        csv_file = write_csv(
            tmp_path / "libraries.csv",
            [
                library_row(short_name="a", filtered_audiences="Grown-ups"),
                library_row(short_name="b", featured_lane_size="lots"),
            ],
        )

        with pytest.raises(CsvFileError) as excinfo:
            parse(csv_file)

        assert "2 of 2 rows are invalid" in str(excinfo.value)
        reported = capsys.readouterr().err
        assert "Line 2" in reported
        assert "Line 3" in reported

    # ------------------------------------------------------------------
    # The shape of the file itself
    # ------------------------------------------------------------------

    def test_byte_order_mark_is_ignored(self, tmp_path: Path) -> None:
        """A CSV saved by Excel or Google Sheets parses normally."""
        csv_path = required_row_csv(tmp_path / "excel.csv")
        # Exactly what Excel's "CSV UTF-8 (Comma delimited)" writes.
        csv_path.write_bytes(csv_path.read_text().encode("utf-8-sig"))

        libraries = parse(csv_path)

        assert len(libraries) == 1
        assert libraries[0].name == "Test Library"

    def test_empty_file_is_an_error(self, tmp_path: Path) -> None:
        """An empty file is a mistake, not a successful import of nothing."""
        csv_path = tmp_path / "empty.csv"
        csv_path.write_text("")

        with pytest.raises(CsvFileError) as excinfo:
            parse(csv_path)

        assert "no header row" in str(excinfo.value)

    def test_header_only_file_is_an_error(self, tmp_path: Path) -> None:
        """A file with no libraries under the header is a mistake too."""
        csv_path = write_csv(tmp_path / "header.csv", [])

        with pytest.raises(CsvFileError) as excinfo:
            parse(csv_path)

        assert "no libraries" in str(excinfo.value)

    @pytest.mark.parametrize(
        "header",
        [
            pytest.param(" featured_lane_size", id="leading_space"),
            pytest.param("featured_lane_size ", id="trailing_space"),
        ],
    )
    def test_header_whitespace_is_ignored(self, tmp_path: Path, header: str) -> None:
        """A stray space in a heading doesn't lose the column."""
        csv_file = write_csv(
            tmp_path / "libraries.csv", [library_row(**{header: "35"})]
        )

        assert parse(csv_file)[0].featured_lane_size == 35

    @pytest.mark.parametrize(
        "header",
        [
            pytest.param("Featured_Lane_Size", id="wrong_case"),
            pytest.param("featured_lane_sizes", id="misspelled"),
            pytest.param("filtered_genres", id="server_side_name"),
        ],
    )
    def test_unrecognised_column_is_an_error(self, tmp_path: Path, header: str) -> None:
        """A misspelled heading is refused rather than quietly ignored."""
        csv_file = write_csv(
            tmp_path / "libraries.csv", [library_row(**{header: "35"})]
        )

        with pytest.raises(CsvFileError) as excinfo:
            parse(csv_file)

        assert header in str(excinfo.value)
        assert "not recognised" in str(excinfo.value)

    def test_description_column_is_allowed(self, tmp_path: Path) -> None:
        """A notes column kept for human readers doesn't have to be removed."""
        csv_file = write_csv(
            tmp_path / "libraries.csv",
            [library_row(description="A library for testing")],
        )

        libraries = parse(csv_file)

        assert len(libraries) == 1
        assert "description" not in libraries[0].model_dump()
        assert IGNORED_COLUMNS == ("description",)

    def test_missing_required_column_is_an_error(self, tmp_path: Path) -> None:
        """A required column that isn't there at all is named."""
        row = {k: v for k, v in REQUIRED_ROW.items() if k != "patron_support_email"}
        csv_file = write_csv(tmp_path / "libraries.csv", [row])

        with pytest.raises(CsvFileError) as excinfo:
            parse(csv_file)

        assert "patron_support_email" in str(excinfo.value)
        assert "missing" in str(excinfo.value)

    def test_duplicate_column_is_an_error(self, tmp_path: Path) -> None:
        """A repeated heading is refused: only the last of them would be read."""
        csv_path = tmp_path / "libraries.csv"
        header = ",".join(REQUIRED_ROW) + ",filtered_audiences,filtered_audiences"
        values = (
            ",".join(v.replace(",", ";") for v in REQUIRED_ROW.values()) + ",Research,"
        )
        csv_path.write_text(f"{header}\n{values}\n")

        with pytest.raises(CsvFileError) as excinfo:
            parse(csv_path)

        assert "filtered_audiences" in str(excinfo.value)
        assert "more than once" in str(excinfo.value)

    def test_blank_required_list_cell_means_an_empty_list(self, tmp_path: Path) -> None:
        """A library with no small-collection languages can be imported."""
        csv_file = write_csv(
            tmp_path / "libraries.csv", [library_row(small_collection_languages="")]
        )

        library = parse(csv_file)[0]

        assert library.small_collection_languages == []
        # An empty list is a real value, so it is sent rather than left out.
        payload = library.model_dump(exclude_none=True)
        assert payload["small_collection_languages"] == []

    def test_extra_cells_are_ignored(self, tmp_path: Path) -> None:
        """A row with more cells than headers doesn't break parsing."""
        csv_path = tmp_path / "libraries.csv"
        header = ",".join(REQUIRED_ROW)
        values = ",".join(v.replace(",", ";") for v in REQUIRED_ROW.values())
        csv_path.write_text(f"{header}\n{values},surplus\n")

        libraries = parse(csv_path)

        assert len(libraries) == 1
        assert libraries[0].name == "Test Library"

    def test_short_row_reports_the_missing_field(self, tmp_path: Path) -> None:
        """A row with fewer cells than headers is an error, not a crash."""
        csv_path = tmp_path / "libraries.csv"
        csv_path.write_text(",".join(REQUIRED_ROW) + "\nOnly A Name\n")

        with pytest.raises(CsvFileError) as excinfo:
            parse(csv_path)

        assert "Nothing was imported" in str(excinfo.value)

    def test_shipped_sample_csv_parses(self) -> None:
        """The sample CSV in ./samples/ stays in step with the columns."""
        sample = Path(__file__).parents[3] / "samples" / "sample_library_import.csv"
        assert sample.exists()

        libraries = parse(sample)

        assert len(libraries) == 2
        # The first row sets every optional column, the second sets none, so the
        # sample shows both ways of writing a row.
        assert libraries[0].featured_lane_size is not None
        assert libraries[0].facets_default_available is not None
        assert libraries[0].filtered_audiences
        assert libraries[0].filtered_categories
        for column in OPTIONAL_COLUMNS_UNDER_TEST:
            assert getattr(libraries[1], column) is None

    # ------------------------------------------------------------------
    # What the circulation manager says back
    # ------------------------------------------------------------------

    def test_created_library_is_reported_as_created(self) -> None:
        """A library the endpoint created counts as created."""
        library = LibraryImportInfo(**model_kwargs())

        assert _report_upload(library, cm_response(created=1)) is UploadResult.CREATED

    def test_rejected_library_is_not_reported_as_success(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A 207 means the library was refused, however cheerful the body is."""
        library = LibraryImportInfo(**model_kwargs())
        response = cm_response(errors=["'Filtered categories' contains invalid values"])

        # The body still says "result": "success" -- that is the whole trap.
        assert response.json()["result"] == "success"
        assert _report_upload(library, response) is UploadResult.FAILED
        assert "Filtered categories" in capsys.readouterr().err

    def test_existing_library_is_reported_as_skipped(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An already-present library is not reported as imported."""
        library = LibraryImportInfo(**model_kwargs())

        assert _report_upload(library, cm_response(skipped=1)) is UploadResult.SKIPPED
        out = capsys.readouterr().out
        assert "already exists" in out
        assert "left unchanged" in out

    @pytest.mark.parametrize("status", [401, 403, 500, 502])
    def test_http_error_stops_the_run(self, status: int) -> None:
        """A transport-level failure is not something to keep pushing through."""
        library = LibraryImportInfo(**model_kwargs())

        with pytest.raises(UploadError) as excinfo:
            _report_upload(library, make_response(status, text="nope"))

        assert str(status) in str(excinfo.value)

    def test_non_json_response_is_an_error(self) -> None:
        """An HTML error page from a proxy is not a successful import."""
        library = LibraryImportInfo(**model_kwargs())

        with pytest.raises(UploadError) as excinfo:
            _report_upload(library, make_response(200, text="<html>"))

        assert "expected JSON" in str(excinfo.value)

    def test_empty_body_is_an_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """A body naming neither a created nor a skipped library is a failure."""
        library = LibraryImportInfo(**model_kwargs())
        response = make_response(
            200, body={"result": "success", "created": [], "skipped": []}
        )

        assert _report_upload(library, response) is UploadResult.FAILED
        assert "neither a created nor a skipped" in capsys.readouterr().err

    # ------------------------------------------------------------------
    # End to end
    # ------------------------------------------------------------------

    def test_successful_run_exits_zero(self, tmp_path: Path) -> None:
        """Two libraries created is a clean run."""
        csv_file = write_csv(
            tmp_path / "libraries.csv",
            [library_row(short_name="a"), library_row(short_name="b")],
        )

        result = run_import(csv_file, [cm_response(created=1)] * 2)

        assert result.exit_code == 0
        assert "Created 2 libraries." in result.output

    def test_server_rejection_exits_nonzero(self, tmp_path: Path) -> None:
        """A library the circulation manager refuses fails the run."""
        csv_file = write_csv(tmp_path / "libraries.csv", [library_row()])

        result = run_import(
            csv_file, [cm_response(errors=["'Filtered categories' is wrong"])]
        )

        assert result.exit_code == 1
        assert "Filtered categories" in result.output
        assert "Created 0 libraries." in result.output
        assert "Successfully imported" not in result.output

    def test_skipped_library_exits_zero_but_says_so(self, tmp_path: Path) -> None:
        """Re-running a file isn't a failure, but nothing is claimed either."""
        csv_file = write_csv(tmp_path / "libraries.csv", [library_row()])

        result = run_import(csv_file, [cm_response(skipped=1)])

        assert result.exit_code == 0
        assert "already exists" in result.output
        assert "were not applied" in result.output
        assert "Created 0 libraries." in result.output

    def test_run_stops_and_says_what_was_created(self, tmp_path: Path) -> None:
        """A hard failure part-way through admits the import is incomplete."""
        csv_file = write_csv(
            tmp_path / "libraries.csv",
            [
                library_row(short_name="a"),
                library_row(short_name="b"),
                library_row(short_name="c"),
            ],
        )

        result = run_import(
            csv_file,
            [cm_response(created=1), make_response(500, text="boom")],
        )

        assert result.exit_code == 1
        assert "Created 1 library." in result.output
        assert "2 libraries left to try" in result.output
        # The deliberate exit is not reported as an unexpected crash.
        assert "Error importing CSV file" not in result.output

    def test_connection_failure_is_reported_plainly(self, tmp_path: Path) -> None:
        """An unreachable circulation manager says so, without a traceback."""
        csv_file = write_csv(tmp_path / "libraries.csv", [library_row()])

        result = run_import(csv_file, [requests.ConnectionError("no route to host")])

        assert result.exit_code == 1
        assert "could not reach" in result.output
        assert "no route to host" in result.output

    def test_request_carries_a_timeout(self, tmp_path: Path) -> None:
        """A stalled circulation manager can't hang the run forever."""
        csv_file = write_csv(tmp_path / "libraries.csv", [library_row()])

        with patch.object(
            requests, "post", return_value=cm_response(created=1)
        ) as post:
            runner.invoke(app, [*CLI_CONNECTION_ARGS, str(csv_file), "--timeout", "12"])

        connect_timeout, read_timeout = post.call_args.kwargs["timeout"]
        assert connect_timeout > 0
        assert read_timeout == 12

    def test_upload_sends_what_the_csv_said(self, tmp_path: Path) -> None:
        """The payload matches the row, with unset columns left out."""
        csv_file = write_csv(
            tmp_path / "libraries.csv",
            [
                library_row(
                    featured_lane_size="35",
                    facets_default_available="Available now",
                    filtered_categories="Horror",
                )
            ],
        )

        with patch.object(
            requests, "post", return_value=cm_response(created=1)
        ) as post:
            runner.invoke(app, [*CLI_CONNECTION_ARGS, str(csv_file)])

        sent = post.call_args.kwargs["json"]["libraries"][0]
        assert sent["featured_lane_size"] == 35
        assert sent["facets_default_available"] == "now"
        assert sent["filtered_categories"] == ["Horror"]
        assert "filtered_audiences" not in sent

    def test_verbose_lists_the_csvs_own_columns(self, tmp_path: Path) -> None:
        """The Columns: line reflects the file, not the model's fields."""
        csv_file = write_csv(tmp_path / "libraries.csv", [library_row()])

        result = run_import(csv_file, [cm_response(created=1)], "-v")

        columns_line = result.output.split("Columns:")[1].splitlines()[0]
        assert "facets_default_order" in columns_line
        # The CSV has no filtered_audiences column, so it must not be listed.
        assert "filtered_audiences" not in columns_line
