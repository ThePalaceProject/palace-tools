import json
import textwrap
from difflib import context_diff
from typing import Any

from pydantic import TypeAdapter, ValidationError

from palace.manager.opds.opds2 import PublicationFeedNoValidation


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


def validate_opds_feeds(
    feeds: dict[str, dict[str, Any]],
    publication_cls: Any,
    ignore_errors: list[str],
    display_diff: bool,
) -> list[str]:
    errors = []
    publication_adapter = TypeAdapter(publication_cls)

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

        for publication_dict in publication_feed.publications:
            try:
                publication = publication_adapter.validate_python(publication_dict)

                if display_diff:
                    diff = _diff_original_parsed(publication_dict, publication)
                    if diff:
                        errors.append(f"Publication JSON differs from parsed model:")
                        errors.append(
                            f"  Identifier: {publication.metadata.identifier}"
                        )
                        errors.append(
                            "\n".join(textwrap.indent(line, "    ") for line in diff)
                        )
            except ValidationError as e:
                if _should_ignore_error(e, ignore_errors):
                    continue

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

                errors.append(f"Error validating publication.")
                errors.append(f"  Identifier: {identifier}")
                errors.append(f"  Title: {title!r}")
                errors.append(f"  Author(s): {authors!r}")
                errors.append(f"  Feed page: {url}")
                errors.append(f"  Self URL: {self_url}")
                errors.append(f"  Errors:")
                errors.append(textwrap.indent(str(e), "    "))
                errors.append(f"  Publication JSON:")
                errors.append(
                    textwrap.indent(str(json.dumps(publication_dict, indent=2)), "    ")
                )

    return errors
