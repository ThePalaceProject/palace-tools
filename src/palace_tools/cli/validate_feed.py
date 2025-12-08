import json
import logging
from collections.abc import Callable
from pathlib import Path

import typer

from palace.manager.opds import opds2
from palace.manager.opds.odl import odl

from palace_tools.feeds import opds
from palace_tools.utils.typer import run_typer_app_as_main
from palace_tools.validation.opds import validate_opds_feeds, validate_opds_publications

app = typer.Typer()


def validate[**P](
    output_file: Path | None,
    validation_func: Callable[P, list[str]],
    *args: P.args,
    **kwargs: P.kwargs,
) -> None:
    logging.basicConfig(level=logging.ERROR)
    results = validation_func(*args, **kwargs)

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
    no_warnings: bool = typer.Option(
        False, "--no-warnings", help="Disable capturing and displaying parser warnings."
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
    validate(
        output_file,
        validate_opds_feeds,
        feeds,
        odl.Opds2OrOpds2WithOdlPublication,
        ignore,
        diff,
        capture_warnings=not no_warnings,
    )


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
    no_warnings: bool = typer.Option(
        False, "--no-warnings", help="Disable capturing and displaying parser warnings."
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
    validate(
        output_file,
        validate_opds_feeds,
        feeds,
        opds2.Publication,
        ignore_errors=ignore,
        display_diff=diff,
        capture_warnings=not no_warnings,
    )


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
    no_warnings: bool = typer.Option(
        False, "--no-warnings", help="Disable capturing and displaying parser warnings."
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
    validate(
        output_file,
        validate_opds_feeds,
        feeds,
        opds2.Publication,
        ignore_errors=ignore,
        display_diff=diff,
        capture_warnings=not no_warnings,
    )


@app.command("opds2-publications")
def validate_opds2_publications(
    ignore: list[str] = typer.Option(
        [],
        help="Ignore these errors (Can be specified multiple times)",
        metavar="ERROR",
    ),
    diff: bool = typer.Option(
        False, "--diff", "-d", help="Show a diff between the parsed and original JSON."
    ),
    no_warnings: bool = typer.Option(
        False, "--no-warnings", help="Disable capturing and displaying parser warnings."
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
    """Validate OPDS 2 publications from a file.

    The file should contain an array of publication objects, like the "publications" field in an OPDS 2 feed.
    This matches the format output by the `download-feed opds2` command.
    """
    with input_file.open("r") as file:
        data = json.load(file)
    validate(
        output_file,
        validate_opds_publications,
        data,
        opds2.Publication,
        ignore_errors=ignore,
        display_diff=diff,
        capture_warnings=not no_warnings,
    )


def main() -> None:
    run_typer_app_as_main(app, prog_name="validate-feed")


if __name__ == "__main__":
    main()
