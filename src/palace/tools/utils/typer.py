#
# Helpers for the `typer` package.
#
import sys
import traceback
from typing import Any

import click
import typer

from palace.tools import __version__


def _version_callback(ctx: click.Context, param: click.Parameter, value: bool) -> None:
    if not value or ctx.resilient_parsing:
        return
    click.echo(__version__ if __version__ is not None else "unknown")
    ctx.exit()


def run_typer_app_as_main(app: typer.Typer, *args: Any, **kwargs: Any) -> Any | None:
    """Run a typer app as the main function.

    Adds a global ``--version`` option to the app and catches any uncaught
    exceptions, printing them to stderr.
    """
    cmd = typer.main.get_command(app)
    cmd.params.append(
        click.Option(
            ["--version"],
            is_flag=True,
            is_eager=True,
            expose_value=False,
            callback=_version_callback,
            help="Show the version and exit.",
        )
    )
    try:
        return cmd(*args, **kwargs)
    except typer.Exit as e:
        sys.exit(e.exit_code)
    except Exception:
        traceback.print_exc()

    return None
