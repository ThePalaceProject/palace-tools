import base64
import json
import traceback
from pathlib import Path
from typing import Any

import requests
import typer
from pydantic import ValidationError

from palace.manager.integration.patron_auth.saml.configuration.model import (
    SAMLWebSSOAuthSettings,
)

from palace_tools.utils.typer import run_typer_app_as_main

app = typer.Typer()


def _load_json_input(json_input: str | Path) -> dict[str, Any]:
    """Load JSON from string or file."""
    if isinstance(json_input, Path):
        if not json_input.exists():
            raise typer.BadParameter(f"JSON file not found: {json_input}")
        if not json_input.is_file():
            raise typer.BadParameter(f"Path is not a file: {json_input}")
        with json_input.open("r", encoding="utf-8") as f:
            try:
                return json.load(f)  # type: ignore[no-any-return]
            except json.JSONDecodeError as e:
                raise typer.BadParameter(f"Invalid JSON in file: {e}")
    else:
        # It's a JSON string
        try:
            return json.loads(json_input)  # type: ignore[no-any-return]
        except json.JSONDecodeError as e:
            raise typer.BadParameter(f"Invalid JSON string: {e}")


def _validate_and_convert_to_saml_settings(
    data: dict[str, Any], verbose: bool = False
) -> Any:
    try:
        if verbose:
            typer.echo("Validating JSON data against SAMLWebSSOAuthSettings model...")

        # Convert dict to SAMLWebSSOAuthSettings using Pydantic model_validate
        saml_settings = SAMLWebSSOAuthSettings.model_validate(data)

        if verbose:
            typer.echo("✅ Successfully validated JSON data")

        return saml_settings
    except ValidationError as e:
        error_msg = f"Failed to validate JSON as SAMLWebSSOAuthSettings: {e}"
        if verbose:
            error_msg += f"\n\nStack trace:\n{traceback.format_exc()}"
        raise typer.BadParameter(error_msg)


def _post_to_palace(
    base_url: str,
    username: str,
    password: str,
    saml_settings: Any,
    verbose: bool = False,
) -> requests.Response:
    """POST SAML settings to Palace patron_auth_services endpoint."""
    endpoint = f"{base_url.rstrip('/')}/admin/cli/patron_auth_services"

    # Create Basic Auth header
    credentials = f"{username}:{password}"
    encoded_credentials = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
    headers = {
        "Authorization": f"Basic {encoded_credentials}",
        "Content-Type": "application/json",
    }

    # Serialize the SAMLWebSSOAuthSettings to JSON
    json_data = (
        saml_settings.model_dump_json()
        if hasattr(saml_settings, "model_dump_json")
        else json.dumps(saml_settings.model_dump())
    )

    if verbose:
        typer.echo(f"Posting to: {endpoint}")
        typer.echo(f"Request payload: {json_data}")

    try:
        response = requests.post(endpoint, headers=headers, data=json_data, timeout=30)
        return response
    except requests.exceptions.RequestException as e:
        error_msg = f"Failed to POST to Palace service: {e}"
        if verbose:
            error_msg += f"\n\nStack trace:\n{traceback.format_exc()}"
        raise typer.BadParameter(error_msg)


@app.command("validate")
def validate_patron_auth_service(
    json_input: str = typer.Option(
        ...,
        "--json",
        "-j",
        help="JSON string or path to JSON file containing SAMLWebSSOAuthSettings",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Enable verbose output"
    ),
) -> None:
    """Validate JSON input can be converted to SAMLWebSSOAuthSettings."""

    try:
        # Step 1: Load JSON input (from string or file)
        if verbose:
            typer.echo(f"Loading JSON input: {json_input}")

        # Check if json_input is a file path
        json_path = Path(json_input)
        json_data = _load_json_input(json_path if json_path.exists() else json_input)

        if verbose:
            typer.echo(f"Successfully loaded JSON data with {len(json_data)} keys")
            typer.echo(f"JSON keys: {list(json_data.keys())}")

        # Step 2: Validate and convert to SAMLWebSSOAuthSettings
        saml_settings = _validate_and_convert_to_saml_settings(json_data, verbose)

        # Step 3: Report success
        typer.echo(
            "✅ JSON input is valid and can be converted to SAMLWebSSOAuthSettings"
        )

        if verbose:
            # Show the validated settings structure
            typer.echo("\nValidated SAMLWebSSOAuthSettings structure:")
            if hasattr(saml_settings, "model_dump"):
                typer.echo(json.dumps(saml_settings.model_dump(), indent=2))
            else:
                typer.echo(str(saml_settings))

    except typer.BadParameter as e:
        typer.echo(f"❌ Validation error: {e}", err=True)
        raise typer.Exit(1)


@app.command("create")
def create_patron_auth_service(
    username: str = typer.Option(..., "--username", "-u", help="Palace username"),
    password: str = typer.Option(..., "--password", "-p", help="Palace password"),
    palace_base_url: str = typer.Option(
        ..., "--palace-base-url", "-b", help="Palace base URL"
    ),
    json_input: str = typer.Option(
        ...,
        "--json",
        "-j",
        help="JSON string or path to JSON file containing SAMLWebSSOAuthSettings",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Enable verbose output"
    ),
) -> None:
    """Create patron auth service by posting SAMLWebSSOAuthSettings to Palace service."""

    if verbose:
        typer.echo(f"Palace Base URL: {palace_base_url}")
        typer.echo(f"Username: {username}")

    try:
        # Step 1: Load JSON input (from string or file)
        if verbose:
            typer.echo(f"Loading JSON input: {json_input}")

        # Check if json_input is a file path
        json_path = Path(json_input)
        json_data = _load_json_input(json_path if json_path.exists() else json_input)

        if verbose:
            typer.echo(f"Successfully loaded JSON data with {len(json_data)} keys")

        # Step 2: Validate and convert to SAMLWebSSOAuthSettings
        saml_settings = _validate_and_convert_to_saml_settings(json_data, verbose)

        # Step 3: POST to Palace service
        if verbose:
            typer.echo("Posting SAML settings to Palace service...")

        response = _post_to_palace(
            palace_base_url, username, password, saml_settings, verbose
        )

        # Step 4: Log response
        typer.echo(f"Response Status: {response.status_code}")
        typer.echo(f"Response Headers: {dict(response.headers)}")

        try:
            response_json = response.json()
            typer.echo(f"Response Body (JSON):")
            typer.echo(json.dumps(response_json, indent=2))
        except ValueError:
            # Not JSON, just echo the text
            typer.echo(f"Response Body (Text):")
            typer.echo(response.text)

        if response.status_code in [200, 201]:
            typer.echo("✅ Successfully created patron auth service!")
        else:
            typer.echo(
                f"❌ Failed to create patron auth service. Status: {response.status_code}"
            )
            raise typer.Exit(1)

    except typer.BadParameter as e:
        error_msg = f"❌ Validation error: {e}"
        if verbose:
            error_msg += f"\n\nStack trace:\n{traceback.format_exc()}"
        typer.echo(error_msg, err=True)
        raise typer.Exit(1)


def main() -> None:
    run_typer_app_as_main(app, prog_name="create-patron-auth-service")


if __name__ == "__main__":
    main()
