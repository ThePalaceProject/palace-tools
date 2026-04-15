#
# Helpers for the `typer` package.
#
import sys
import traceback
from typing import Any

import typer


def run_typer_app_as_main(app: typer.Typer, *args: Any, **kwargs: Any) -> Any | None:
    """Run a typer app as the main function.

    Catch any uncaught exceptions and print them to stderr.
    """
    try:
        return app(*args, **kwargs)
    except typer.Exit as e:
        sys.exit(e.exit_code)
    except Exception:
        traceback.print_exc()

    return None
