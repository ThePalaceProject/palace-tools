"""Tests for the import-libraries-from-csv CLI tool."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from palace.tools.cli.import_libraries_from_csv import (
    EXAMPLE_CATEGORIES,
    REQUIRED_COLUMNS,
    VALID_AUDIENCES,
    CsvRowError,
    LibraryImportInfo,
    _parse_csv_file,
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

OPTIONAL_COLUMNS = (
    "featured_lane_size",
    "facets_default_available",
    "filtered_audiences",
    "filtered_categories",
)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> Path:
    """Write rows to a CSV file, using the union of their keys as the header."""
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def library_row(**overrides: Any) -> dict[str, Any]:
    """A valid CSV row, with any column overridden or added."""
    return {**REQUIRED_ROW, **overrides}


class TestImportLibrariesFromCsv:
    """Tests for the import-libraries-from-csv command."""

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
        for column in OPTIONAL_COLUMNS:
            assert column in help_text

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

        libraries = _parse_csv_file(csv_file)

        assert len(libraries) == 1
        library = libraries[0]
        assert library.featured_lane_size == 35
        assert library.facets_default_available == "now"
        assert library.filtered_audiences == ["Research", "Adults Only"]
        assert library.filtered_categories == ["Erotica", "Horror"]

    def test_parse_without_optional_columns(self, tmp_path: Path) -> None:
        """A CSV with only the required columns still parses."""
        csv_file = write_csv(tmp_path / "libraries.csv", [library_row()])

        libraries = _parse_csv_file(csv_file)

        assert len(libraries) == 1
        library = libraries[0]
        for column in OPTIONAL_COLUMNS:
            assert getattr(library, column) is None

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

        libraries = _parse_csv_file(csv_file)

        for column in OPTIONAL_COLUMNS:
            assert getattr(libraries[0], column) is None

    def test_unset_optional_columns_are_left_out_of_the_upload(self) -> None:
        """Fields the CSV didn't set are not sent, so the server default wins."""
        library = LibraryImportInfo(
            name="Test Library",
            short_name="test",
            website_url="https://library.example.com",
            patron_support_email="support@example.com",
            large_collection_languages=["English"],
            small_collection_languages=["Spanish"],
            facets_default_order="added",
            enabled_entry_points=["All"],
        )

        payload = library.model_dump(exclude_none=True)

        for column in OPTIONAL_COLUMNS:
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

        libraries = _parse_csv_file(csv_file)

        assert libraries[0].facets_default_available == expected

    def test_list_columns_are_trimmed(self, tmp_path: Path) -> None:
        """Spaces around comma-separated values are ignored."""
        csv_file = write_csv(
            tmp_path / "libraries.csv",
            [library_row(filtered_audiences="Research , Adults Only ,")],
        )

        libraries = _parse_csv_file(csv_file)

        assert libraries[0].filtered_audiences == ["Research", "Adults Only"]

    def test_every_audience_is_accepted(self, tmp_path: Path) -> None:
        """All the documented audiences are legal values."""
        csv_file = write_csv(
            tmp_path / "libraries.csv",
            [library_row(filtered_audiences=",".join(VALID_AUDIENCES))],
        )

        libraries = _parse_csv_file(csv_file)

        assert libraries[0].filtered_audiences == list(VALID_AUDIENCES)

    @pytest.mark.parametrize(
        "column,value,expected_in_error",
        [
            pytest.param(
                "featured_lane_size",
                "many",
                "whole number",
                id="lane_size_not_a_number",
            ),
            pytest.param(
                "featured_lane_size", "0", "greater than 0", id="lane_size_zero"
            ),
            pytest.param(
                "featured_lane_size", "-5", "greater than 0", id="lane_size_negative"
            ),
            pytest.param(
                "featured_lane_size", "3.5", "whole number", id="lane_size_fractional"
            ),
            pytest.param(
                "facets_default_available",
                "whenever",
                "facets_default_available",
                id="availability_unknown",
            ),
            pytest.param(
                "filtered_audiences",
                "Adult,Grown-ups",
                "Grown-ups",
                id="audience_unknown",
            ),
            pytest.param(
                "filtered_audiences", "adult", "adult", id="audience_wrong_case"
            ),
            pytest.param("name", "", "name", id="missing_required_field"),
        ],
    )
    def test_invalid_values_are_rejected(
        self, tmp_path: Path, column: str, value: str, expected_in_error: str
    ) -> None:
        """A bad cell stops the import and says which column is wrong."""
        csv_file = write_csv(
            tmp_path / "libraries.csv", [library_row(**{column: value})]
        )

        with pytest.raises(CsvRowError) as excinfo:
            _parse_csv_file(csv_file)

        assert "Nothing was imported" in str(excinfo.value)

    def test_invalid_audience_error_lists_the_valid_values(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The error an operator sees names the audiences they can use."""
        csv_file = write_csv(
            tmp_path / "libraries.csv",
            [library_row(filtered_audiences="Grown-ups")],
        )

        with pytest.raises(CsvRowError):
            _parse_csv_file(csv_file)

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

        with pytest.raises(CsvRowError) as excinfo:
            _parse_csv_file(csv_file)

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

        with pytest.raises(CsvRowError) as excinfo:
            _parse_csv_file(csv_file)

        assert "2 of 2 rows are invalid" in str(excinfo.value)
        reported = capsys.readouterr().err
        assert "Line 2" in reported
        assert "Line 3" in reported

    def test_short_row_reports_the_missing_field(self, tmp_path: Path) -> None:
        """A row with fewer cells than headers is an error, not a crash."""
        csv_path = tmp_path / "libraries.csv"
        csv_path.write_text(
            "name,short_name,website_url\nOnly A Name\n", encoding="utf-8"
        )

        with pytest.raises(CsvRowError) as excinfo:
            _parse_csv_file(csv_path)

        assert "Nothing was imported" in str(excinfo.value)

    def test_extra_cells_are_ignored(self, tmp_path: Path) -> None:
        """A row with more cells than headers doesn't break parsing."""
        csv_path = tmp_path / "libraries.csv"
        header = ",".join(REQUIRED_ROW)
        values = ",".join(value.replace(",", ";") for value in REQUIRED_ROW.values())
        csv_path.write_text(f"{header}\n{values},surplus\n", encoding="utf-8")

        libraries = _parse_csv_file(csv_path)

        assert len(libraries) == 1
        assert libraries[0].name == "Test Library"

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
        assert set(OPTIONAL_COLUMNS) == model_optional

    def test_shipped_sample_csv_parses(self) -> None:
        """The sample CSV in ./samples/ stays in step with the columns."""
        sample = Path(__file__).parents[3] / "samples" / "sample_library_import.csv"
        assert sample.exists()

        libraries = _parse_csv_file(sample)

        assert len(libraries) == 2
        # The first row sets every optional column, the second sets none, so the
        # sample shows both ways of writing a row.
        assert libraries[0].featured_lane_size is not None
        assert libraries[0].facets_default_available is not None
        assert libraries[0].filtered_audiences
        assert libraries[0].filtered_categories
        for column in OPTIONAL_COLUMNS:
            assert getattr(libraries[1], column) is None
