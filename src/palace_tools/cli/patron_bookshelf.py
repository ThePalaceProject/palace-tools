#!/usr/bin/env python3

import asyncio
import json

import httpx
import typer

from palace_tools.constants import DEFAULT_REGISTRY_URL, OpdsEnum
from palace_tools.models.api.opds2 import OPDS2Feed
from palace_tools.models.internal.bookshelf import print_bookshelf_summary
from palace_tools.roles.patron import authenticate
from palace_tools.utils.http.async_client import HTTPXAsyncClient
from palace_tools.utils.typer import run_typer_app_as_main

app = typer.Typer(rich_markup_mode="rich")


def main() -> None:
    run_typer_app_as_main(app)


def conflicts_with_as_json(
    ctx: typer.Context, param: typer.Option, value: bool
) -> bool:
    """Check for conflicts with the `as_json` option.

    Setting the `as_json` option to True is valid only with OPDSv2 feeds and
    when a dump of the full bookshelf feed has NOT been requested.
    """
    if (option := param.name) != "as_json":
        raise ValueError(
            "Programming error: This callback should be specified only for the 'as_json' option."
        )
    if value is False:
        return value
    if ctx.params.get("as_dump") is True:
        raise ValueError("The '--json' option cannot be used with the '--dump' option.")
    if ctx.params.get("opds") != OpdsEnum.OPDS_2:
        raise ValueError("The '--json' option can only be used with OPDSv2 feeds.")
    return value


@app.command(
    help="Print a patron's bookshelf.",
    epilog="[red]Use options from only one of the three numbered option groups.[/red]",
    no_args_is_help=True,
)
def patron_bookshelf(
    *,
    username: str = typer.Option(..., "--username", "-u", help="Username or barcode."),
    password: str = typer.Option(None, "--password", "-p", help="Password or PIN."),
    auth_doc_url: str = typer.Option(
        None,
        "--auth_doc",
        metavar="URL",
        help="An authentication document URL.",
        rich_help_panel="Group 1: Authentication Document",
    ),
    library: str = typer.Option(
        None,
        "--library",
        help="Name of the library in the registry.",
        metavar="FULL_NAME",
        rich_help_panel="Group 2: Library from Registry",
    ),
    registry_url: str = typer.Option(
        DEFAULT_REGISTRY_URL,
        "--registry-url",
        envvar="PALACE_REGISTRY_URL",
        show_default=True,
        metavar="URL",
        help="URL of the library registry.",
        rich_help_panel="Group 2: Library from Registry",
    ),
    allow_hidden_libraries: bool = typer.Option(
        False,
        "--include-hidden",
        "-a",
        is_flag=True,
        flag_value=True,
        help="Include hidden libraries from the library registry.",
        rich_help_panel="Group 2: Library from Registry",
    ),
    opds_server: str = typer.Option(
        None,
        "--opds-server",
        metavar="URL",
        help="An OPDS server endpoint URL.",
        rich_help_panel="Group 3: OPDS Server Heuristic",
    ),
    opds: OpdsEnum = typer.Option(
        OpdsEnum.OPDS_2,
        "--opds",
        help="Output format.",
        rich_help_panel="Output",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        "-j",
        is_flag=True,
        help="Output bookshelf as JSON. Incompatible with `--opds 1` and `--dump`.",
        callback=conflicts_with_as_json,
        rich_help_panel="Output",
    ),
    as_dump: bool = typer.Option(
        False,
        "--dump",
        is_flag=True,
        help="Output raw bookshelf response content.",
        rich_help_panel="Output",
    ),
) -> None:
    response = asyncio.run(
        fetch_bookshelf(
            username=username,
            password=password,
            registry_url=registry_url,
            library=library,
            opds_server=opds_server,
            auth_doc_url=auth_doc_url,
            allow_hidden_libraries=allow_hidden_libraries,
            opds=opds,
        )
    )
    # For the moment, OPDS v1 feeds can only be dumped. So, requesting either
    # and OPDSv1 feed or a dump will produce only a dump.
    if as_dump or opds == OpdsEnum.OPDS_1:
        print(response.text)
        return
    # If we get this far, we have an OPDSv2 feed and should validate it.
    bookshelf = OPDS2Feed.model_validate(response.json())
    if as_json:
        print(json.dumps(bookshelf.model_dump(), indent=2))
    else:
        print_bookshelf_summary(bookshelf)


async def fetch_bookshelf(
    *,
    username: str | None = None,
    password: str | None = None,
    registry_url: str = DEFAULT_REGISTRY_URL,
    library: str | None = None,
    opds_server: str | None = None,
    auth_doc_url: str | None = None,
    allow_hidden_libraries: bool = False,
    opds: OpdsEnum = OpdsEnum.OPDS_2,
) -> httpx.Response:
    async with HTTPXAsyncClient() as client:
        patron = await authenticate(
            username=username,
            password=password,
            auth_doc_url=auth_doc_url,
            library=library,
            registry_url=registry_url,
            allow_hidden_libraries=allow_hidden_libraries,
            opds_server=opds_server,
            http_client=client,
        )
        return await patron.fetch_patron_bookshelf(
            accept=opds.content_type(), http_client=client
        )


if __name__ == "__main__":
    main()
