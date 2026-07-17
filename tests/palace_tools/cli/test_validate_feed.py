"""Tests for the validate_feed CLI tool."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from palace.tools.cli.validate_feed import app
from palace.tools.feeds.odl import LICENSE_DOCUMENT_KEY

runner = CliRunner()


def _odl_publication(
    *,
    identifier: str = "urn:isbn:9999999999",
    title: str = "Some ODL Book",
    license_identifier: str = "license-1",
    info_url: str = "https://example.com/licenses/1/info",
    license_document: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """An OPDS2+ODL publication dict, optionally with an embedded License Info Document."""
    license_dict: dict[str, Any] = {
        "metadata": {
            "identifier": license_identifier,
            "format": "application/epub+zip",
            "created": "2024-01-01T00:00:00Z",
        },
        "links": [
            {
                "rel": "self",
                "href": info_url,
                "type": "application/vnd.odl.info+json",
            },
            {
                "rel": "http://opds-spec.org/acquisition/borrow",
                "href": "https://example.com/licenses/1/checkout",
                "type": "application/vnd.readium.license.status.v1.0+json",
            },
        ],
    }
    if license_document is not None:
        license_dict[LICENSE_DOCUMENT_KEY] = license_document

    return {
        "metadata": {
            "@type": "http://schema.org/Book",
            "title": title,
            "identifier": identifier,
        },
        "images": [{"href": "http://example.com/cover.jpg", "type": "image/jpeg"}],
        "links": [
            {
                "href": "http://example.com/book.epub",
                "type": "application/epub+zip",
                "rel": "http://opds-spec.org/acquisition/open-access",
            }
        ],
        "licenses": [license_dict],
    }


def _valid_license_info(identifier: str = "license-1") -> dict[str, Any]:
    return {
        "identifier": identifier,
        "status": "available",
        "checkouts": {"available": 5, "left": 10},
    }


def _write_publications(path: Path, publications: list[dict[str, Any]]) -> Path:
    path.write_text(json.dumps(publications))
    return path


class TestValidateOpds2OdlPublications:
    """Tests for the opds2-odl-publications command."""

    def test_help(self) -> None:
        result = runner.invoke(app, ["opds2-odl-publications", "--help"])
        assert result.exit_code == 0
        assert "OPDS 2 + ODL publications from a file" in result.output

    def test_valid_publications_succeed(self, tmp_path: Path) -> None:
        input_file = _write_publications(
            tmp_path / "pubs.json",
            [_odl_publication(license_document=_valid_license_info())],
        )

        result = runner.invoke(app, ["opds2-odl-publications", str(input_file)])

        assert result.exit_code == 0
        assert "Success! No validation errors found." in result.output

    def test_invalid_license_document_reports_error(self, tmp_path: Path) -> None:
        input_file = _write_publications(
            tmp_path / "pubs.json",
            [
                _odl_publication(
                    license_document={"identifier": "license-1", "status": "available"}
                )
            ],
        )

        result = runner.invoke(app, ["opds2-odl-publications", str(input_file)])

        assert result.exit_code == 0
        assert "Validation failed for License Info Document" in result.output
        assert "Info-doc URL: https://example.com/licenses/1/info" in result.output

    def test_ignore_filters_matching_errors(self, tmp_path: Path) -> None:
        input_file = _write_publications(
            tmp_path / "pubs.json",
            [
                _odl_publication(
                    license_document={"identifier": "license-1", "status": "available"}
                )
            ],
        )

        result = runner.invoke(
            app,
            ["opds2-odl-publications", "--ignore", "checkouts", str(input_file)],
        )

        assert result.exit_code == 0
        assert "Success! No validation errors found." in result.output

    def test_errors_written_to_output_file(self, tmp_path: Path) -> None:
        input_file = _write_publications(
            tmp_path / "pubs.json",
            [
                _odl_publication(
                    license_document={"identifier": "license-1", "status": "available"}
                )
            ],
        )
        output_file = tmp_path / "results.txt"

        result = runner.invoke(
            app,
            ["opds2-odl-publications", str(input_file), str(output_file)],
        )

        assert result.exit_code == 0
        assert output_file.exists()
        assert "Validation failed for License Info Document" in output_file.read_text()
