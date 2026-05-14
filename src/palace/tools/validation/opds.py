import json
import logging
import textwrap
from copy import deepcopy
from difflib import context_diff
from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError

from palace.opds.odl.info import LicenseInfo
from palace.opds.opds2 import PublicationFeedNoValidation

from palace.tools.feeds.odl import LICENSE_DOCUMENT_KEY
from palace.tools.utils.logging import LogCapture

# Logger name for capturing OPDS parsing warnings
OPDS_LOGGER_NAME = "palace.opds"


def _should_ignore_error(error: ValidationError, ignore_errors: list[str]) -> bool:
    if not ignore_errors:
        return False

    for ignored in ignore_errors:
        if ignored in str(error):
            return True

    return False


def _strip_embedded_license_documents(data: dict[str, Any]) -> dict[str, Any]:
    """
    Return a deep copy of ``data`` without embedded License Info Documents.
    """
    data = deepcopy(data)
    for license_ in data.get("licenses") or []:
        license_.pop(LICENSE_DOCUMENT_KEY, None)
    return data


def _diff_original_parsed(original: dict[str, Any], parsed: BaseModel) -> list[str]:
    return list(
        context_diff(
            json.dumps(original, indent=2, sort_keys=True).splitlines(),
            json.dumps(
                parsed.model_dump(mode="json", exclude_unset=True, by_alias=True),
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
    log_capture = LogCapture(logging.WARNING)
    log_capture.setFormatter(logging.Formatter("%(message)s"))

    for existing_handler in logger.handlers:
        logger.removeHandler(existing_handler)

    logger.addHandler(log_capture)
    logger.setLevel(logging.WARNING)
    logger.propagate = False  # Don't propagate to root logger
    return log_capture


def _license_info_url(license_dict: dict[str, Any]) -> str:
    info_content_type = LicenseInfo.content_type()
    for link in license_dict.get("links") or []:
        if (
            link.get("rel") == "self"
            and link.get("type") == info_content_type
            and link.get("href")
        ):
            return link["href"]  # type: ignore[no-any-return]
    return "<unknown>"


def _license_issues(
    publication_dict: dict[str, Any],
    license_dict: dict[str, Any],
    license_doc: dict[str, Any],
    info_url: str,
    *,
    errors: str | None = None,
    warnings: str | None = None,
    diff: str | None = None,
) -> list[str]:
    issues: list[str] = []
    pub_metadata = publication_dict.get("metadata") or {}
    pub_identifier = pub_metadata.get("identifier", "<unknown>")
    pub_title = pub_metadata.get("title", "<unknown>")
    license_metadata = license_dict.get("metadata") or {}
    license_identifier = license_metadata.get("identifier", "<unknown>")

    issue_types = []
    if errors:
        issue_types.append("ERROR")
    if warnings:
        issue_types.append("WARNING")
    if diff:
        issue_types.append("DIFF")

    issues.append(
        f"Validation failed for License Info Document. Issues: {', '.join(issue_types)}"
    )
    issues.append(f"  Publication identifier: {pub_identifier}")
    issues.append(f"  Publication title: {pub_title!r}")
    issues.append(f"  License identifier: {license_identifier}")
    issues.append(f"  Info-doc URL: {info_url}")
    if errors:
        issues.append("  Errors:")
        issues.append(textwrap.indent(errors, "    "))
    if warnings:
        issues.append("  Warnings:")
        issues.append(textwrap.indent(warnings, "    "))
    if diff:
        issues.append("  License Info Document JSON differs from parsed model:")
        issues.append(textwrap.indent(diff, "    "))
    issues.append("  License Info Document JSON:")
    issues.append(textwrap.indent(json.dumps(license_doc, indent=2), "    "))
    return issues


def _validate_license_document(
    publication_dict: dict[str, Any],
    license_dict: dict[str, Any],
    license_doc: dict[str, Any],
    license_info_adapter: TypeAdapter[LicenseInfo],
    *,
    log_capture: LogCapture | None,
    ignore_errors: list[str],
    display_diff: bool,
) -> list[str]:
    info_url = _license_info_url(license_dict)

    if log_capture:
        log_capture.clear()

    try:
        parsed = license_info_adapter.validate_python(license_doc)
    except ValidationError as e:
        if _should_ignore_error(e, ignore_errors):
            return []
        return _license_issues(
            publication_dict,
            license_dict,
            license_doc,
            info_url,
            errors=str(e),
        )

    warnings = "".join(log_capture.get_messages()) if log_capture else None

    if display_diff:
        diff_lines = _diff_original_parsed(license_doc, parsed)
        diff = "\n".join(diff_lines) if diff_lines else None
    else:
        diff = None

    if diff or warnings:
        return _license_issues(
            publication_dict,
            license_dict,
            license_doc,
            info_url,
            warnings=warnings,
            diff=diff,
        )
    return []


def validate_opds_publications(
    publications: list[dict[str, Any]],
    publication_cls: Any,
    *,
    url: str | None = None,
    ignore_errors: list[str],
    display_diff: bool,
    capture_warnings: bool = True,
) -> list[str]:
    publication_adapter = TypeAdapter(publication_cls)
    license_info_adapter: TypeAdapter[LicenseInfo] = TypeAdapter(LicenseInfo)
    errors = []

    log_capture = _setup_log_capture() if capture_warnings else None

    for publication_dict in publications:
        if log_capture:
            log_capture.clear()

        try:
            publication = publication_adapter.validate_python(publication_dict)

            # Check for captured warnings during parsing
            warnings = "".join(log_capture.get_messages()) if log_capture else None

            if display_diff:
                diff = "\n".join(
                    _diff_original_parsed(
                        _strip_embedded_license_documents(publication_dict), publication
                    )
                )
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
            if not _should_ignore_error(e, ignore_errors):
                errors.extend(_publication_issues(publication_dict, url, errors=str(e)))

        # Validate any embedded License Info Documents on this publication.
        # Inert for plain OPDS 2 (no `licenses`) and for ODL feeds where the
        # docs weren't fetched (no `license_document` key).
        for license_ in publication_dict.get("licenses") or []:
            license_doc = license_.get(LICENSE_DOCUMENT_KEY)
            if license_doc is None:
                continue
            errors.extend(
                _validate_license_document(
                    publication_dict,
                    license_,
                    license_doc,
                    license_info_adapter,
                    log_capture=log_capture,
                    ignore_errors=ignore_errors,
                    display_diff=display_diff,
                )
            )

    return errors


def validate_opds_feeds(
    feeds: dict[str, dict[str, Any]],
    publication_cls: Any,
    ignore_errors: list[str],
    display_diff: bool,
    capture_warnings: bool = True,
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
                capture_warnings=capture_warnings,
            )
        )

    return errors
