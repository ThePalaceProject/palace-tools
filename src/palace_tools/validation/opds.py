import json
import logging
import textwrap
from typing import Any

from pydantic import TypeAdapter, ValidationError

from palace.manager.opds.opds2 import PublicationFeedNoValidation


def validate_opds_feeds(
    feeds: dict[str, dict[str, Any]], publication_cls: Any
) -> list[str]:
    errors = []

    # disable logging, we don't want its output to clutter the validation output
    logging.disable(logging.ERROR)
    publication_adapter = TypeAdapter(publication_cls)

    for url, feed in feeds.items():
        try:
            publication_feed = PublicationFeedNoValidation.model_validate(feed)
        except ValidationError as e:
            errors.append(f"Error validating feed page.")
            errors.append(f"  URL: {url}")
            errors.append(f"  Errors:")
            errors.append(textwrap.indent(str(e), "    "))
            continue

        for publication_dict in publication_feed.publications:
            try:
                publication_adapter.validate_python(publication_dict)
            except ValidationError as e:
                metadata_dict = publication_dict.get("metadata", {})

                # Extract any information we can from metadata_dict, to help with error message
                identifier = metadata_dict.get("identifier", "<unknown>")
                title = metadata_dict.get("title", "<unknown>")
                authors = metadata_dict.get("author", "<unknown>")

                errors.append(f"Error validating publication.")
                errors.append(f"  URL: {url}")
                errors.append(f"  Identifier: {identifier}")
                errors.append(f"  Title: {title!r}")
                errors.append(f"  Author(s): {authors!r}")
                errors.append(f"  Errors:")
                errors.append(textwrap.indent(str(e), "    "))
                errors.append(f"  Publication JSON:")
                errors.append(
                    textwrap.indent(str(json.dumps(publication_dict, indent=2)), "    ")
                )

    return errors
