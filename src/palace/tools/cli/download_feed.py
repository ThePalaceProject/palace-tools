from __future__ import annotations

import asyncio
import json
import textwrap
from pathlib import Path
from typing import Any, TextIO
from xml.dom import minidom

import typer
import xmltodict

from palace.tools.feeds import axis, odl, opds, opds1, overdrive
from palace.tools.utils.typer import run_typer_app_as_main

app = typer.Typer()


class ProductWriter:
    """Writes products into a JSON array one at a time.

    The file is what ``json.dumps(products, indent=4)`` would have produced,
    written without ever holding the whole list, so that a harvest of a large
    collection doesn't have to fit in memory to be saved.
    """

    def __init__(self, output_file: Path) -> None:
        self._output_file = output_file
        self._file: TextIO | None = None
        self.count = 0

    def __enter__(self) -> ProductWriter:
        self._file = self._output_file.open("w")
        self._file.write("[")
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._file is None:
            return
        # An array is only valid once it's closed, and an aborted harvest
        # leaves a file behind that still has to be readable.
        self._file.write("\n]" if self.count else "]")
        self._file.close()
        self._file = None

    def write(self, product: dict[str, Any]) -> None:
        if self._file is None:
            raise RuntimeError("ProductWriter can only be written to while open.")
        self._file.write(",\n" if self.count else "\n")
        self._file.write(textwrap.indent(json.dumps(product, indent=4), "    "))
        self.count += 1


@app.command("axis")
def download_axis(
    username: str = typer.Option(..., "--username", "-u", help="Username"),
    password: str = typer.Option(..., "--password", "-p", help="Password"),
    library_id: str = typer.Option(..., "-l", "--library-id", help="Library ID"),
    output_json: bool = typer.Option(False, "-j", "--json", help="Output JSON file"),
    qa_endpoint: bool = typer.Option(False, "-q", "--qa", help="Use QA Endpoint"),
    no_pretty_print: bool = typer.Option(
        False, "--no-pretty-print", help="Don't pretty print XML output"
    ),
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
            if not no_pretty_print:
                # Pretty print the XML
                parsed = minidom.parseString(xml)
                xml = parsed.toprettyxml()
            file.write(xml)


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
    use_consortial_plus_advantage_feed: bool = typer.Option(
        False,
        "-U",
        "--consortial-plus-advantage",
        help="Fetch consortial plus advantage feed when using --parent-library-id",
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
    skip_not_found: bool = typer.Option(
        False, "-z", "--skip-not-found", help="Skip any urls that are not found (404)"
    ),
) -> None:
    """Download Overdrive feed."""
    base_url = overdrive.QA_BASE_URL if qa_endpoint else overdrive.PROD_BASE_URL

    async def harvest(writer: ProductWriter) -> None:
        async for product in overdrive.fetch(
            base_url,
            client_key,
            client_secret,
            library_id,
            parent_library_id,
            fetch_metadata,
            fetch_availability,
            connections,
            skip_not_found,
            use_consortial_plus_advantage_feed,
        ):
            writer.write(product)

    with ProductWriter(output_file) as writer:
        try:
            asyncio.run(harvest(writer))
        except overdrive.HarvestAborted as e:
            # A harvest takes hours. Everything it finished is already on
            # disk, so all that's left is the products it was still waiting
            # on when it died.
            print(e)
            for product in e.products:
                writer.write(product)
            print(
                f"Wrote {writer.count} partially harvested products to {output_file}."
            )
            raise typer.Exit(code=-1)


@app.command("overdrive-url")
def download_overdrive_url(
    client_key: str = typer.Option(..., "-k", "--client-key", help="Client Key"),
    client_secret: str = typer.Option(
        ..., "-s", "--client-secret", help="Client Secret"
    ),
    url: str = typer.Argument(..., help="URL to fetch"),
) -> None:
    """Output Overdrive feed data by URL (metadata, availability, etc)."""
    try:
        results = asyncio.run(overdrive.fetch_url(client_key, client_secret, url))
    except overdrive.OverdriveError as e:
        print(e)
        raise typer.Exit(code=-1)

    print(json.dumps(results, indent=4))


@app.command("opds2")
def download_opds(
    username: str = typer.Option(None, "--username", "-u", help="Username"),
    password: str = typer.Option(None, "--password", "-p", help="Password"),
    authentication: opds.AuthType = typer.Option(
        opds.AuthType.NONE.value, "--auth", "-a", help="Authentication type"
    ),
    url: str = typer.Argument(..., help="URL of feed", metavar="URL"),
    output_file: Path = typer.Argument(
        ..., help="Output file", writable=True, file_okay=True, dir_okay=False
    ),
) -> None:
    """Download OPDS 2 feed."""
    feeds = opds.fetch(url, username, password, authentication)
    publications = opds.all_publications(feeds)

    with output_file.open("w") as file:
        opds.write_json(file, publications)


@app.command("opds2-odl")
def download_opds2_odl(
    username: str = typer.Option(None, "--username", "-u", help="Username"),
    password: str = typer.Option(None, "--password", "-p", help="Password"),
    authentication: opds.AuthType = typer.Option(
        opds.AuthType.NONE.value, "--auth", "-a", help="Authentication type"
    ),
    license_documents: bool = typer.Option(
        True,
        "--license-documents/--no-license-documents",
        help=(
            "Fetch the License Info Document for each license and embed it "
            "under a 'license_document' key on the license."
        ),
    ),
    connections: int = typer.Option(
        20,
        "-c",
        "--connections",
        help="Number of concurrent connections used to fetch License Info Documents.",
    ),
    url: str = typer.Argument(..., help="URL of feed", metavar="URL"),
    output_file: Path = typer.Argument(
        ..., help="Output file", writable=True, file_okay=True, dir_okay=False
    ),
) -> None:
    """Download OPDS 2 + ODL feed including License Info Documents."""
    feeds = opds.fetch(url, username, password, authentication)
    publications = opds.all_publications(feeds)

    if license_documents:
        asyncio.run(
            odl.fetch_license_documents(
                publications,
                username=username,
                password=password,
                auth_type=authentication,
                connections=connections,
                base_url=url,
            )
        )

    with output_file.open("w") as file:
        opds.write_json(file, publications)


@app.command("opds1")
def download_opds1(
    username: str = typer.Option(None, "--username", "-u", help="Username"),
    password: str = typer.Option(None, "--password", "-p", help="Password"),
    authentication: opds.AuthType = typer.Option(
        opds.AuthType.NONE.value, "--auth", "-a", help="Authentication type"
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
