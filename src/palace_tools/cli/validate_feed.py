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
    username: str,
    password: str,
    authentication: opds.AuthType,
    url: str,
    output_file: Path | None,
    publication_cls: Any,
) -> None:
    # disable logging, we don't want its output to clutter the validation output
    logging.disable(logging.ERROR)

    feeds = opds.fetch(url, username, password, authentication)
    results = validate_opds_feeds(feeds, publication_cls)

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
    validate(
        username,
        password,
        authentication,
        url,
        output_file,
        odl.Opds2OrOpds2WithOdlPublication,
    )


@app.command("opds2")
def validate_opds2(
    username: str = typer.Option(None, "--username", "-u", help="Username"),
    password: str = typer.Option(None, "--password", "-p", help="Password"),
    authentication: opds.AuthType = typer.Option(
        opds.AuthType.NONE.value, "--auth", "-a", help="Authentication type"
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
    validate(username, password, authentication, url, output_file, opds2.Publication)


def main() -> None:
    run_typer_app_as_main(app, prog_name="validate-feed")


if __name__ == "__main__":
    main()
