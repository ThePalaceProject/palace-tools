#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import json
import zipfile
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, TextIO

import typer

from palace.tools.constants import LCP_AUDIOBOOK_TYPE, LCP_LICENSE_PUBLICATION_REL
from palace.tools.models.api.opds2 import match_links
from palace.tools.models.api.readium_lcp_license_v1 import LCPLicenseDocument
from palace.tools.utils.http.async_client import HTTPXAsyncClient
from palace.tools.utils.http.auth_token import BaseAuthorizationToken, BasicAuthToken
from palace.tools.utils.http.streaming import streaming_fetch_with_progress
from palace.tools.utils.typer import run_typer_app_as_main

STDOUT = 1
app = typer.Typer()


def main() -> None:
    run_typer_app_as_main(app, prog_name="fetch-lcp")


@app.command()
def files(
    fulfillment_url: str = typer.Argument(..., help="LCP audiobook fulfillment URL"),
    output_dir: Path = typer.Argument(
        ...,
        dir_okay=True,
        file_okay=False,
        help="Manifest output file.",
    ),
    username: str = typer.Option(..., "--username", "-u", help="Username or barcode."),
    password: str = typer.Option(None, "--password", "-p", help="Password or PIN."),
) -> None:
    asyncio.run(
        process_files_command(
            fulfillment_url=fulfillment_url,
            output_dir=output_dir,
            username=username,
            password=password,
        )
    )


async def process_files_command(
    fulfillment_url: str,
    output_dir: Path,
    username: str,
    password: str | None,
) -> None:
    if not output_dir.exists():
        print(f"Creating directory {output_dir}.")
        output_dir.mkdir(parents=True)

    license_file = output_dir / "license.lcpl"
    lcp_file = output_dir / "audiobook.lcp"

    with (
        open(license_file, "w") as license_file_io,
        open(lcp_file, "wb") as lcp_file_io,
    ):
        await process_command(
            fulfillment_url, license_file_io, lcp_file_io, username, password
        )


@app.command()
def audiobook_manifest(
    fulfillment_url: str = typer.Argument(..., help="LCP audiobook fulfillment URL"),
    manifest_file: Path = typer.Option(
        ...,
        "--output_file",
        "-o",
        allow_dash=True,
        dir_okay=False,
        help="Manifest output file.",
    ),
    username: str = typer.Option(..., "--username", "-u", help="Username or barcode."),
    password: str = typer.Option(None, "--password", "-p", help="Password or PIN."),
    pretty_print: bool = typer.Option(
        False,
        "--pretty-print",
        "--pp",
        is_flag=True,
        flag_value=True,
        help="Pretty print the result.",
    ),
) -> None:
    asyncio.run(
        process_audiobook_manifest_command(
            fulfillment_url=fulfillment_url,
            manifest_file=STDOUT if manifest_file == Path("-") else manifest_file,
            username=username,
            password=password,
            pretty_print=pretty_print,
        )
    )


async def process_audiobook_manifest_command(
    fulfillment_url: str,
    manifest_file: Path | str | int,
    username: str,
    password: str | None,
    manifest_member_name: str = "manifest.json",
    pretty_print: bool = False,
) -> None:
    file = BytesIO()

    await process_command(fulfillment_url, None, file, username, password)

    zf = zipfile.ZipFile(file)
    manifest = zf.read(name=manifest_member_name)
    print(f"Sending output to {manifest_file}.")
    with open(manifest_file, "w") as f:
        if pretty_print:
            json.dump(json.loads(manifest, strict=False), f, indent=2)
        else:
            f.write(manifest.decode("utf-8"))


async def process_command(
    fulfillment_url: str,
    license_file: TextIO | None,
    lcp_file: BinaryIO,
    username: str,
    password: str | None,
) -> None:
    client_headers = {"User-Agent": "Palace"}
    token: BaseAuthorizationToken = BasicAuthToken.from_username_and_password(
        username, password
    )

    async with HTTPXAsyncClient(headers=client_headers) as client:
        response = await client.get(fulfillment_url, headers=token.as_http_headers)
        response.raise_for_status()

        if license_file:
            license_file.write(response.text)

        lcp_license = LCPLicenseDocument.model_validate(response.json())
        lcp_audiobook_links = match_links(
            lcp_license.links,
            lambda lnk: lnk.rel == LCP_LICENSE_PUBLICATION_REL
            and lnk.type == LCP_AUDIOBOOK_TYPE,
        )
        if not lcp_audiobook_links:
            return
        lcp_audiobook_url = lcp_audiobook_links[0].href

        lcp_audiobook_response = await streaming_fetch_with_progress(
            str(lcp_audiobook_url),
            lcp_file,
            task_label="Downloading audiobook zip...",
            http_client=client,
        )
        lcp_audiobook_response.raise_for_status()


if __name__ == "__main__":
    main()
