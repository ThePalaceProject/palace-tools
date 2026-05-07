"""Tests for OPDS validation functions."""

from typing import Any

import pytest

from palace.opds.opds2 import Publication

from palace.tools.feeds.odl import LICENSE_DOCUMENT_KEY, iter_license_info_links
from palace.tools.validation.opds import (
    validate_license_documents,
    validate_opds_feeds,
    validate_opds_publications,
)


class OpdsValidationFixture:
    def valid_publication_dict(
        self,
        identifier: str = "urn:isbn:1234567890",
        title: str = "Test Book",
    ) -> dict[str, Any]:
        """Create a valid publication dictionary for testing."""
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
        }

    def invalid_publication_dict(
        self,
        identifier: str = "urn:isbn:invalid",
        title: str = "Invalid Book",
    ) -> dict[str, Any]:
        """Create an invalid publication dictionary for testing (missing required fields)."""
        return {
            "metadata": {
                "title": title,
                "identifier": identifier,
            },
        }

    def valid_feed_dict(
        self, publications: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """Create a valid feed dictionary for testing."""
        return {
            "metadata": {"title": "Test Feed"},
            "links": [
                {
                    "href": "http://example.com/feed.json",
                    "rel": "self",
                    "type": "application/opds+json",
                }
            ],
            "publications": publications or [],
        }


@pytest.fixture()
def opds_validation_fixture() -> OpdsValidationFixture:
    """Fixture providing helper methods for OPDS validation tests."""
    return OpdsValidationFixture()


class TestValidateOpdsPublications:
    def test_valid_publications_returns_empty_list(
        self, opds_validation_fixture: OpdsValidationFixture
    ) -> None:
        """Valid publications should return no errors."""
        publications = [
            opds_validation_fixture.valid_publication_dict(
                "urn:isbn:1111111111", "Book One"
            ),
            opds_validation_fixture.valid_publication_dict(
                "urn:isbn:2222222222", "Book Two"
            ),
        ]

        errors = validate_opds_publications(
            publications,
            Publication,
            ignore_errors=[],
            display_diff=False,
        )

        assert errors == []

    def test_invalid_publication_returns_errors(
        self, opds_validation_fixture: OpdsValidationFixture
    ) -> None:
        """Invalid publications should return validation errors."""
        publications = [opds_validation_fixture.invalid_publication_dict()]

        errors = validate_opds_publications(
            publications,
            Publication,
            ignore_errors=[],
            display_diff=False,
        )

        assert len(errors) > 0
        assert any("Validation failed for publication" in e for e in errors)
        assert any("urn:isbn:invalid" in e for e in errors)

    def test_mixed_valid_invalid_publications(
        self, opds_validation_fixture: OpdsValidationFixture
    ) -> None:
        """Mix of valid and invalid publications should only report errors for invalid ones."""
        publications = [
            opds_validation_fixture.valid_publication_dict(
                "urn:isbn:1111111111", "Valid Book"
            ),
            opds_validation_fixture.invalid_publication_dict(
                "urn:isbn:invalid", "Invalid Book"
            ),
        ]

        errors = validate_opds_publications(
            publications,
            Publication,
            ignore_errors=[],
            display_diff=False,
        )

        assert len(errors) > 0
        assert any("urn:isbn:invalid" in e for e in errors)
        assert not any("urn:isbn:1111111111" in e for e in errors)

    def test_ignore_errors_filters_matching_errors(
        self, opds_validation_fixture: OpdsValidationFixture
    ) -> None:
        """Errors matching ignore_errors patterns should be filtered out."""
        publications = [opds_validation_fixture.invalid_publication_dict()]

        # Without ignore - should have errors
        errors_without_ignore = validate_opds_publications(
            publications,
            Publication,
            ignore_errors=[],
            display_diff=False,
        )
        assert len(errors_without_ignore) > 0

        # With ignore matching the error - should have no errors
        errors_with_ignore = validate_opds_publications(
            publications,
            Publication,
            ignore_errors=["@type"],
            display_diff=False,
        )
        assert len(errors_with_ignore) == 0

    def test_url_included_in_error_when_provided(
        self, opds_validation_fixture: OpdsValidationFixture
    ) -> None:
        """When url is provided, it should appear in error messages."""
        publications = [opds_validation_fixture.invalid_publication_dict()]
        feed_url = "http://example.com/feed.json"

        errors = validate_opds_publications(
            publications,
            Publication,
            url=feed_url,
            ignore_errors=[],
            display_diff=False,
        )

        assert any(feed_url in e for e in errors)

    def test_url_not_included_when_not_provided(
        self, opds_validation_fixture: OpdsValidationFixture
    ) -> None:
        """When url is not provided, 'Feed page:' should not appear in errors."""
        publications = [opds_validation_fixture.invalid_publication_dict()]

        errors = validate_opds_publications(
            publications,
            Publication,
            ignore_errors=[],
            display_diff=False,
        )

        assert not any("Feed page:" in e for e in errors)

    def test_empty_publications_list(self) -> None:
        """Empty publications list should return no errors."""
        errors = validate_opds_publications(
            [],
            Publication,
            ignore_errors=[],
            display_diff=False,
        )

        assert errors == []


class TestValidateOpdsFeeds:
    def test_valid_feed_returns_empty_list(
        self, opds_validation_fixture: OpdsValidationFixture
    ) -> None:
        """Valid feed with valid publications should return no errors."""
        feeds = {
            "http://example.com/feed.json": opds_validation_fixture.valid_feed_dict(
                [opds_validation_fixture.valid_publication_dict()]
            )
        }

        errors = validate_opds_feeds(
            feeds,
            Publication,
            ignore_errors=[],
            display_diff=False,
        )

        assert errors == []

    def test_invalid_feed_structure_returns_errors(self) -> None:
        """Invalid feed structure should return validation errors."""
        feeds = {
            "http://example.com/feed.json": {
                "invalid_field": "this is not a valid feed",
            }
        }

        errors = validate_opds_feeds(
            feeds,
            Publication,
            ignore_errors=[],
            display_diff=False,
        )

        assert len(errors) > 0
        assert any("Error validating feed page" in e for e in errors)

    def test_feed_with_invalid_publication_returns_errors(
        self, opds_validation_fixture: OpdsValidationFixture
    ) -> None:
        """Valid feed structure with invalid publication should return publication errors."""
        feeds = {
            "http://example.com/feed.json": opds_validation_fixture.valid_feed_dict(
                [opds_validation_fixture.invalid_publication_dict()]
            )
        }

        errors = validate_opds_feeds(
            feeds,
            Publication,
            ignore_errors=[],
            display_diff=False,
        )

        assert len(errors) > 0
        assert any("Validation failed for publication" in e for e in errors)

    def test_empty_feeds_dict(self) -> None:
        """Empty feeds dict should return no errors."""
        errors = validate_opds_feeds(
            {},
            Publication,
            ignore_errors=[],
            display_diff=False,
        )

        assert errors == []

    def test_feed_url_included_in_publication_errors(
        self, opds_validation_fixture: OpdsValidationFixture
    ) -> None:
        """Feed URL should be included in publication validation errors."""
        feed_url = "http://example.com/my-feed.json"
        feeds = {
            feed_url: opds_validation_fixture.valid_feed_dict(
                [opds_validation_fixture.invalid_publication_dict()]
            )
        }

        errors = validate_opds_feeds(
            feeds,
            Publication,
            ignore_errors=[],
            display_diff=False,
        )

        assert any(feed_url in e for e in errors)


def _odl_publication(
    *,
    identifier: str = "urn:isbn:9999999999",
    title: str = "Some ODL Book",
    license_identifier: str = "license-1",
    info_url: str = "https://example.com/licenses/1/info",
    license_document: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """An OPDS2+ODL publication dict, optionally pre-loaded with a fetched License Info Document."""
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


class TestIterLicenseInfoLinks:
    def test_yields_self_link_for_odl_publication(self) -> None:
        publication = _odl_publication()

        results = list(iter_license_info_links([publication]))

        assert len(results) == 1
        pub, license_, info_url = results[0]
        assert pub is publication
        assert license_ is publication["licenses"][0]
        assert info_url == "https://example.com/licenses/1/info"

    def test_skips_plain_opds2_publications(
        self, opds_validation_fixture: OpdsValidationFixture
    ) -> None:
        plain_pub = opds_validation_fixture.valid_publication_dict()
        odl_pub = _odl_publication()

        results = list(iter_license_info_links([plain_pub, odl_pub]))

        assert len(results) == 1
        assert results[0][0] is odl_pub

    def test_skips_license_without_self_info_link(self) -> None:
        publication = _odl_publication()
        publication["licenses"][0]["links"] = [
            {
                "rel": "http://opds-spec.org/acquisition/borrow",
                "href": "https://example.com/licenses/1/checkout",
                "type": "application/vnd.readium.license.status.v1.0+json",
            }
        ]

        assert list(iter_license_info_links([publication])) == []

    def test_skips_self_link_with_wrong_content_type(self) -> None:
        publication = _odl_publication()
        publication["licenses"][0]["links"][0]["type"] = "application/json"

        assert list(iter_license_info_links([publication])) == []

    def test_handles_empty_licenses_array(self) -> None:
        publication = _odl_publication()
        publication["licenses"] = []

        assert list(iter_license_info_links([publication])) == []


class TestValidateLicenseDocuments:
    def test_valid_license_info_returns_no_errors(self) -> None:
        publication = _odl_publication(license_document=_valid_license_info())

        errors = validate_license_documents(
            [publication],
            ignore_errors=[],
            display_diff=False,
        )

        assert errors == []

    def test_invalid_license_info_returns_errors(self) -> None:
        invalid = {"identifier": "license-1", "status": "available"}
        publication = _odl_publication(license_document=invalid)

        errors = validate_license_documents(
            [publication],
            ignore_errors=[],
            display_diff=False,
        )

        assert len(errors) > 0
        assert any("Validation failed for License Info Document" in e for e in errors)
        assert any("License identifier: license-1" in e for e in errors)
        assert any(
            "Info-doc URL: https://example.com/licenses/1/info" in e for e in errors
        )
        assert any("Publication identifier: urn:isbn:9999999999" in e for e in errors)

    def test_ignore_errors_filters_matching_errors(self) -> None:
        invalid = {"identifier": "license-1", "status": "available"}
        publication = _odl_publication(license_document=invalid)

        errors = validate_license_documents(
            [publication],
            ignore_errors=["checkouts"],
            display_diff=False,
        )

        assert errors == []

    def test_publication_without_licenses_is_noop(
        self, opds_validation_fixture: OpdsValidationFixture
    ) -> None:
        plain_pub = opds_validation_fixture.valid_publication_dict()

        errors = validate_license_documents(
            [plain_pub],
            ignore_errors=[],
            display_diff=False,
        )

        assert errors == []

    def test_license_without_embedded_document_is_skipped(self) -> None:
        publication = _odl_publication()  # no license_document set

        errors = validate_license_documents(
            [publication],
            ignore_errors=[],
            display_diff=False,
        )

        assert errors == []

    def test_mixed_valid_invalid_license_docs(self) -> None:
        valid_pub = _odl_publication(
            identifier="urn:isbn:1111111111",
            license_identifier="license-valid",
            info_url="https://example.com/licenses/valid/info",
            license_document=_valid_license_info("license-valid"),
        )
        invalid_pub = _odl_publication(
            identifier="urn:isbn:2222222222",
            license_identifier="license-invalid",
            info_url="https://example.com/licenses/invalid/info",
            license_document={"identifier": "license-invalid", "status": "available"},
        )

        errors = validate_license_documents(
            [valid_pub, invalid_pub],
            ignore_errors=[],
            display_diff=False,
        )

        assert any("license-invalid" in e for e in errors)
        assert not any("urn:isbn:1111111111" in e for e in errors)
