import logging
from pathlib import Path
from typing import Any

import typer

from palace.manager.opds import opds2
from palace.manager.opds.odl import odl

from palace_tools.feeds import opds
from palace_tools.utils.typer import run_typer_app_as_main
from palace_tools.validation.opds import validate_opds_feeds

app = typer.Typer()


def validate(
    feeds: dict[str, dict[str, Any]],
    output_file: Path | None,
    publication_cls: Any,
    ignore_errors: list[str],
    diff: bool,
) -> None:
    # disable logging, we don't want its output to clutter the validation output
    logging.disable(logging.ERROR)
    results = validate_opds_feeds(feeds, publication_cls, ignore_errors, diff)

    if results:
        output_str = "\n".join(results)
        if output_file:
            with output_file.open("w") as file:
                file.write(output_str)
        print(output_str)
    else:
        print("Success! No validation errors found.")


@app.command("opds2-odl")
def validate_opds2_odl(
    username: str = typer.Option(None, "--username", "-u", help="Username"),
    password: str = typer.Option(None, "--password", "-p", help="Password"),
    authentication: opds.AuthType = typer.Option(
        opds.AuthType.NONE.value, "--auth", "-a", help="Authentication type"
    ),
    ignore: list[str] = typer.Option(
        [],
        help="Ignore these errors (Can be specified multiple times)",
        metavar="ERROR",
    ),
    diff: bool = typer.Option(
        False, "--diff", "-d", help="Show a diff between the parsed and original JSON."
    ),
    url: str = typer.Argument(..., help="URL of feed", metavar="URL"),
    output_file: Path = typer.Argument(
        None,
        help="Output the validation results to a file. If not given, the results will be printed to stdout.",
        metavar="FILE",
        writable=True,
        file_okay=True,
        dir_okay=False,
    ),
) -> None:
    """Validate OPDS 2 + ODL feed."""
    feeds = opds.fetch(url, username, password, authentication)
    validate(feeds, output_file, odl.Opds2OrOpds2WithOdlPublication, ignore, diff)


@app.command("opds2")
def validate_opds2(
    username: str = typer.Option(None, "--username", "-u", help="Username"),
    password: str = typer.Option(None, "--password", "-p", help="Password"),
    authentication: opds.AuthType = typer.Option(
        opds.AuthType.NONE.value, "--auth", "-a", help="Authentication type"
    ),
    ignore: list[str] = typer.Option(
        [],
        help="Ignore these errors (Can be specified multiple times)",
        metavar="ERROR",
    ),
    diff: bool = typer.Option(
        False, "--diff", "-d", help="Show a diff between the parsed and original JSON."
    ),
    url: str = typer.Argument(..., help="URL of feed", metavar="URL"),
    output_file: Path = typer.Argument(
        None,
        help="Output the validation results to a file. If not given, the results will be printed to stdout.",
        metavar="FILE",
        writable=True,
        file_okay=True,
        dir_okay=False,
    ),
) -> None:
    """Validate OPDS 2 feed."""
    feeds = opds.fetch(url, username, password, authentication)
    validate(feeds, output_file, opds2.Publication, ignore, diff)


@app.command("opds2-file")
def validate_opds2_file(
    ignore: list[str] = typer.Option(
        [],
        help="Ignore these errors (Can be specified multiple times)",
        metavar="ERROR",
    ),
    diff: bool = typer.Option(
        False, "--diff", "-d", help="Show a diff between the parsed and original JSON."
    ),
    input_file: Path = typer.Argument(
        ...,
        help="File containing the feed to validate",
        metavar="INPUT_FILE",
        exists=True,
        readable=True,
        file_okay=True,
        dir_okay=False,
    ),
    output_file: Path = typer.Argument(
        None,
        help="Output the validation results to a file. If not given, the results will be printed to stdout.",
        metavar="OUTPUT_FILE",
        writable=True,
        file_okay=True,
        dir_okay=False,
    ),
) -> None:
    """Validate OPDS 2 feed from a file."""
    feeds = opds.load(input_file)
    validate(feeds, output_file, opds2.Publication, ignore, diff)


def main() -> None:
    run_typer_app_as_main(app, prog_name="validate-feed")


if __name__ == "__main__":
    main()
