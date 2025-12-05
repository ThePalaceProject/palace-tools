"""Tests for OPDS validation functions."""

from typing import Any

import pytest

from palace.manager.opds.opds2 import Publication

from palace_tools.validation.opds import validate_opds_feeds, validate_opds_publications


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
