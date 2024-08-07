import asyncio
import json
from pathlib import Path
from xml.dom import minidom

import typer
import xmltodict

from palace_tools.feeds import axis, opds, opds1, overdrive
from palace_tools.utils.typer import run_typer_app_as_main

app = typer.Typer()


@app.command("axis")
def download_axis(
    username: str = typer.Option(..., "--username", "-u", help="Username"),
    password: str = typer.Option(..., "--password", "-p", help="Password"),
    library_id: str = typer.Option(..., "-l", "--library-id", help="Library ID"),
    output_json: bool = typer.Option(False, "-j", "--json", help="Output JSON file"),
    qa_endpoint: bool = typer.Option(False, "-q", "--qa", help="Use QA Endpoint"),
    output_file: Path = typer.Argument(
        ..., help="Output file", writable=True, file_okay=True, dir_okay=False
    ),
) -> None:
    """Download B&T Axis 360 feed."""

    # Find the base URL to use
    base_url = axis.PRODUCTION_BASE_URL if not qa_endpoint else axis.QA_BASE_URL

    # Fetch the document as XML
    xml = axis.availability(base_url, username, password, library_id)

    with output_file.open("w") as file:
        if output_json:
            xml_dict = xmltodict.parse(xml)
            file.write(json.dumps(xml_dict, indent=4))
        else:
            parsed = minidom.parseString(xml)
            file.write(parsed.toprettyxml())


@app.command("overdrive")
def download_overdrive(
    client_key: str = typer.Option(..., "-k", "--client-key", help="Client Key"),
    client_secret: str = typer.Option(
        ..., "-s", "--client-secret", help="Client Secret"
    ),
    library_id: str = typer.Option(..., "-l", "--library-id", help="Library ID"),
    parent_library_id: str = typer.Option(
        None,
        "-p",
        "--parent-library-id",
        help="Parent Library ID (for Advantage Accounts)",
    ),
    fetch_metadata: bool = typer.Option(
        False, "-m", "--metadata", help="Fetch metadata"
    ),
    fetch_availability: bool = typer.Option(
        False, "-a", "--availability", help="Fetch availability"
    ),
    qa_endpoint: bool = typer.Option(False, "-q", "--qa", help="Use QA Endpoint"),
    connections: int = typer.Option(
        20, "-c", "--connections", help="Number of connections to use"
    ),
    output_file: Path = typer.Argument(
        ..., help="Output file", writable=True, file_okay=True, dir_okay=False
    ),
) -> None:
    """Download Overdrive feed."""
    base_url = overdrive.QA_BASE_URL if qa_endpoint else overdrive.PROD_BASE_URL
    products = asyncio.run(
        overdrive.fetch(
            base_url,
            client_key,
            client_secret,
            library_id,
            parent_library_id,
            fetch_metadata,
            fetch_availability,
            connections,
        )
    )

    with output_file.open("w") as file:
        file.write(json.dumps(products, indent=4))


@app.command("opds2")
def download_opds(
    username: str = typer.Option(None, "--username", "-u", help="Username"),
    password: str = typer.Option(None, "--password", "-p", help="Password"),
    authentication: opds.AuthType = typer.Option(
        opds.AuthType.NONE, "--auth", "-a", help="Authentication type"
    ),
    url: str = typer.Argument(..., help="URL of feed", metavar="URL"),
    output_file: Path = typer.Argument(
        ..., help="Output file", writable=True, file_okay=True, dir_okay=False
    ),
) -> None:
    """Download OPDS 2 feed."""
    publications = opds.fetch(url, username, password, authentication)
    with output_file.open("w") as file:
        opds.write_json(file, publications)


@app.command("opds1")
def download_opds1(
    username: str = typer.Option(None, "--username", "-u", help="Username"),
    password: str = typer.Option(None, "--password", "-p", help="Password"),
    authentication: opds.AuthType = typer.Option(
        opds.AuthType.NONE, "--auth", "-a", help="Authentication type"
    ),
    url: str = typer.Argument(..., help="URL of feed", metavar="URL"),
    output_file: Path = typer.Argument(
        ..., help="Output file", writable=True, file_okay=True, dir_okay=False
    ),
) -> None:
    """Download OPDS 1.x feed."""
    opds1.fetch(url, username, password, authentication, output_file)


def main() -> None:
    run_typer_app_as_main(app, prog_name="download-feed")


if __name__ == "__main__":
    main()
