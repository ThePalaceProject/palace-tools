import json
import logging
import textwrap
from difflib import context_diff
from typing import Any

from pydantic import TypeAdapter, ValidationError

from palace.manager.opds.opds2 import PublicationFeedNoValidation

from palace_tools.utils.logging import LogCapture

# Logger name for capturing OPDS parsing warnings
OPDS_LOGGER_NAME = "palace.manager.opds"


def _should_ignore_error(error: ValidationError, ignore_errors: list[str]) -> bool:
    if not ignore_errors:
        return False

    for ignored in ignore_errors:
        if ignored in str(error):
            return True

    return False


def _diff_original_parsed(
    feed: dict[str, Any], publication_feed: PublicationFeedNoValidation
) -> list[str]:
    return list(
        context_diff(
            json.dumps(
                feed,
                indent=2,
                sort_keys=True,
            ).splitlines(),
            json.dumps(
                publication_feed.model_dump(
                    mode="json", exclude_unset=True, by_alias=True
                ),
                indent=2,
                sort_keys=True,
            ).splitlines(),
            fromfile="original",
            tofile="parsed",
            lineterm="",
        )
    )


def _publication_issues(
    publication_dict: dict[str, Any],
    url: str | None,
    *,
    errors: str | None = None,
    warnings: str | None = None,
    diff: str | None = None,
) -> list[str]:
    issues = []
    metadata_dict = publication_dict.get("metadata", {})

    # Extract any information we can from metadata_dict, to help with error message
    identifier = metadata_dict.get("identifier", "<unknown>")
    title = metadata_dict.get("title", "<unknown>")
    authors = metadata_dict.get("author", "<unknown>")

    links = publication_dict.get("links", [])
    self_url = next(
        (
            link["href"]
            for link in links
            if link.get("rel") == "self" and link.get("href") is not None
        ),
        "<unknown>",
    )

    issue_types = []

    if errors:
        issue_types.append("ERROR")
    if warnings:
        issue_types.append("WARNING")
    if diff:
        issue_types.append("DIFF")

    issues.append(
        f"Validation failed for publication. Issues: {', '.join(issue_types)}"
    )
    issues.append(f"  Identifier: {identifier}")
    issues.append(f"  Title: {title!r}")
    issues.append(f"  Author(s): {authors!r}")
    if url:
        issues.append(f"  Feed page: {url}")
    issues.append(f"  Self URL: {self_url}")
    if errors:
        issues.append(f"  Errors:")
        issues.append(textwrap.indent(errors, "    "))
    if warnings:
        issues.append(f"  Warnings:")
        issues.append(textwrap.indent(warnings, "    "))
    if diff:
        issues.append(f"  Publication JSON differs from parsed model:")
        issues.append(textwrap.indent(diff, "    "))
    issues.append(f"  Publication JSON:")
    issues.append(textwrap.indent(str(json.dumps(publication_dict, indent=2)), "    "))
    return issues


def _setup_log_capture() -> LogCapture:
    logger = logging.getLogger(OPDS_LOGGER_NAME)
    handler = LogCapture(logging.WARNING)
    handler.setFormatter(logging.Formatter("%(message)s"))

    for handler in logger.handlers:
        logger.removeHandler(handler)

    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    return handler


def validate_opds_publications(
    publications: list[dict[str, Any]],
    publication_cls: Any,
    *,
    url: str | None = None,
    ignore_errors: list[str],
    display_diff: bool,
) -> list[str]:
    publication_adapter = TypeAdapter(publication_cls)
    errors = []

    log_capture = _setup_log_capture()

    for publication_dict in publications:
        log_capture.clear()

        try:
            publication = publication_adapter.validate_python(publication_dict)

            # Check for captured warnings during parsing
            warnings = "".join(log_capture.get_messages())

            if display_diff:
                diff = "\n".join(_diff_original_parsed(publication_dict, publication))
            else:
                diff = None

            if diff or warnings:
                errors.extend(
                    _publication_issues(
                        publication_dict,
                        url,
                        warnings=warnings,
                        diff=diff,
                    )
                )
        except ValidationError as e:
            if _should_ignore_error(e, ignore_errors):
                continue

            errors.extend(_publication_issues(publication_dict, url, errors=str(e)))

    return errors


def validate_opds_feeds(
    feeds: dict[str, dict[str, Any]],
    publication_cls: Any,
    ignore_errors: list[str],
    display_diff: bool,
) -> list[str]:
    errors = []

    for url, feed in feeds.items():
        try:
            publication_feed = PublicationFeedNoValidation.model_validate(feed)

            if display_diff:
                diff = _diff_original_parsed(feed, publication_feed)
                if diff:
                    errors.append(f"Feed JSON differs from parsed model:")
                    errors.append(f"  URL: {url}")
                    errors.append(
                        "\n".join(textwrap.indent(line, "    ") for line in diff)
                    )
        except ValidationError as e:
            if not _should_ignore_error(e, ignore_errors):
                # If the error is not in the ignore list, we log it
                errors.append(f"Error validating feed page.")
                errors.append(f"  URL: {url}")
                errors.append(f"  Errors:")
                errors.append(textwrap.indent(str(e), "    "))
            continue

        errors.extend(
            validate_opds_publications(
                publication_feed.publications,
                publication_cls,
                url=url,
                ignore_errors=ignore_errors,
                display_diff=display_diff,
            )
        )

    return errors
