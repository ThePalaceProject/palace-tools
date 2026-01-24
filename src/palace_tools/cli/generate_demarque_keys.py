from __future__ import annotations

import json
import stat
import uuid
from pathlib import Path

import typer
from jwcrypto import jwk

from palace_tools.utils.typer import run_typer_app_as_main

app = typer.Typer()


DEFAULT_KID_PREFIX = "http://palaceproject.io/terms/keys/demarque/webreader/"


def main() -> None:
    run_typer_app_as_main(app, prog_name="generate-demarque-keys")


@app.command()
def command(
    public_key_file: Path | None = typer.Option(
        None,
        "--public-key",
        "-p",
        help="Output file for the public key. If not specified, prints to stdout.",
        writable=True,
        file_okay=True,
        dir_okay=False,
    ),
    private_key_file: Path | None = typer.Option(
        None,
        "--private-key",
        "-s",
        help="Output file for the private key. If not specified, prints to stdout.",
        writable=True,
        file_okay=True,
        dir_okay=False,
    ),
    kid: str | None = typer.Option(
        None,
        "--kid",
        "-k",
        help=f"Key ID (kid) for the key pair. Defaults to '{DEFAULT_KID_PREFIX}<uuid>'.",
    ),
) -> None:
    """Generate Ed25519 key pair for DeMarque webreader integration."""
    # Generate an Ed25519 key pair
    key = jwk.JWK.generate(kty="OKP", crv="Ed25519")

    # Set the key ID
    if kid is None:
        kid = f"{DEFAULT_KID_PREFIX}{uuid.uuid4()}"
    key["kid"] = kid

    # Export keys
    public_key = key.export_public(as_dict=True)
    private_key = key.export_private(as_dict=True)

    public_key_json = json.dumps(public_key, indent=2)
    private_key_json = json.dumps(private_key, indent=2)

    # Output public key
    if public_key_file is not None:
        public_key_file.write_text(public_key_json)
        typer.echo(f"Public key written to: {public_key_file}")
    else:
        typer.echo("=== PUBLIC KEY ===")
        typer.echo(public_key_json)
        typer.echo()

    # Output private key
    if private_key_file is not None:
        private_key_file.write_text(private_key_json)
        private_key_file.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600
        typer.echo(f"Private key written to: {private_key_file}")
    else:
        typer.echo("=== PRIVATE KEY ===")
        typer.echo(private_key_json)


if __name__ == "__main__":
    main()
