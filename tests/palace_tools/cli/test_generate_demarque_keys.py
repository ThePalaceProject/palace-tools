"""Tests for generate_demarque_keys CLI tool."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from palace_tools.cli.generate_demarque_keys import DEFAULT_KID_PREFIX, app

runner = CliRunner()


class TestGenerateDemarqueKeys:
    """Tests for the generate-demarque-keys command."""

    def test_help(self) -> None:
        """Test that help text is displayed."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Generate Ed25519 key pair for DeMarque webreader" in result.output
        assert "--public-key" in result.output
        assert "--private-key" in result.output
        assert "--kid" in result.output

    def test_default_output_to_stdout(self) -> None:
        """Test default behavior prints keys to stdout."""
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        assert "=== PUBLIC KEY ===" in result.output
        assert "=== PRIVATE KEY ===" in result.output

        # Verify output contains valid JSON keys
        lines = result.output.split("\n")
        public_key_start = lines.index("=== PUBLIC KEY ===") + 1
        private_key_start = lines.index("=== PRIVATE KEY ===") + 1

        # Extract and parse public key JSON
        public_key_lines = []
        for line in lines[public_key_start:]:
            if line == "":
                break
            public_key_lines.append(line)
        public_key = json.loads("\n".join(public_key_lines))

        # Verify public key structure
        assert public_key["kty"] == "OKP"
        assert public_key["crv"] == "Ed25519"
        assert public_key["kid"].startswith(DEFAULT_KID_PREFIX)
        assert "x" in public_key
        assert "d" not in public_key  # Private component should not be in public key

    def test_default_kid_format(self) -> None:
        """Test that default kid uses the expected prefix with UUID."""
        result = runner.invoke(app, [])
        assert result.exit_code == 0

        # Extract public key from output
        lines = result.output.split("\n")
        public_key_start = lines.index("=== PUBLIC KEY ===") + 1
        public_key_lines = []
        for line in lines[public_key_start:]:
            if line == "":
                break
            public_key_lines.append(line)
        public_key = json.loads("\n".join(public_key_lines))

        # Verify kid format
        assert public_key["kid"].startswith(DEFAULT_KID_PREFIX)
        # The UUID portion should be 36 characters (with hyphens)
        uuid_part = public_key["kid"][len(DEFAULT_KID_PREFIX) :]
        assert len(uuid_part) == 36

    def test_custom_kid(self) -> None:
        """Test that custom kid can be specified."""
        custom_kid = "http://example.com/my-custom-key-id"
        result = runner.invoke(app, ["--kid", custom_kid])
        assert result.exit_code == 0

        # Extract public key from output
        lines = result.output.split("\n")
        public_key_start = lines.index("=== PUBLIC KEY ===") + 1
        public_key_lines = []
        for line in lines[public_key_start:]:
            if line == "":
                break
            public_key_lines.append(line)
        public_key = json.loads("\n".join(public_key_lines))

        assert public_key["kid"] == custom_kid

    def test_output_public_key_to_file(self, tmp_path: Path) -> None:
        """Test outputting public key to a file."""
        public_key_file = tmp_path / "public.json"
        result = runner.invoke(app, ["--public-key", str(public_key_file)])
        assert result.exit_code == 0

        # Verify file was created and contains valid key
        assert public_key_file.exists()
        public_key = json.loads(public_key_file.read_text())
        assert public_key["kty"] == "OKP"
        assert public_key["crv"] == "Ed25519"
        assert "d" not in public_key

        # Verify confirmation message
        assert f"Public key written to: {public_key_file}" in result.output

        # Private key should still be printed to stdout
        assert "=== PRIVATE KEY ===" in result.output

    def test_output_private_key_to_file(self, tmp_path: Path) -> None:
        """Test outputting private key to a file."""
        private_key_file = tmp_path / "private.json"
        result = runner.invoke(app, ["--private-key", str(private_key_file)])
        assert result.exit_code == 0

        # Verify file was created and contains valid key
        assert private_key_file.exists()
        private_key = json.loads(private_key_file.read_text())
        assert private_key["kty"] == "OKP"
        assert private_key["crv"] == "Ed25519"
        assert "d" in private_key  # Private component should be present

        # Verify file permissions are 600 (owner read/write only)
        file_mode = private_key_file.stat().st_mode & 0o777
        assert file_mode == 0o600

        # Verify confirmation message
        assert f"Private key written to: {private_key_file}" in result.output

        # Public key should still be printed to stdout
        assert "=== PUBLIC KEY ===" in result.output

    def test_output_both_keys_to_files(self, tmp_path: Path) -> None:
        """Test outputting both keys to files."""
        public_key_file = tmp_path / "public.json"
        private_key_file = tmp_path / "private.json"
        result = runner.invoke(
            app,
            [
                "--public-key",
                str(public_key_file),
                "--private-key",
                str(private_key_file),
            ],
        )
        assert result.exit_code == 0

        # Verify both files exist
        assert public_key_file.exists()
        assert private_key_file.exists()

        # Verify keys are valid
        public_key = json.loads(public_key_file.read_text())
        private_key = json.loads(private_key_file.read_text())

        assert public_key["kty"] == "OKP"
        assert private_key["kty"] == "OKP"
        assert "d" not in public_key
        assert "d" in private_key

        # Both keys should have the same kid
        assert public_key["kid"] == private_key["kid"]

        # Verify confirmation messages
        assert f"Public key written to: {public_key_file}" in result.output
        assert f"Private key written to: {private_key_file}" in result.output

        # Neither key should be printed to stdout
        assert "=== PUBLIC KEY ===" not in result.output
        assert "=== PRIVATE KEY ===" not in result.output

    def test_keys_are_valid_ed25519(self) -> None:
        """Test that generated keys are valid Ed25519 keys."""
        from jwcrypto import jwk

        result = runner.invoke(app, [])
        assert result.exit_code == 0

        # Extract private key from output
        lines = result.output.split("\n")
        private_key_start = lines.index("=== PRIVATE KEY ===") + 1
        private_key_lines = []
        for line in lines[private_key_start:]:
            if line.strip() == "":
                continue
            private_key_lines.append(line)
        private_key_json = "\n".join(private_key_lines)
        private_key_dict = json.loads(private_key_json)

        # Verify we can load the key back into jwcrypto
        key = jwk.JWK(**private_key_dict)
        assert key["kty"] == "OKP"
        assert key["crv"] == "Ed25519"

    def test_short_options(self, tmp_path: Path) -> None:
        """Test that short option flags work."""
        public_key_file = tmp_path / "public.json"
        private_key_file = tmp_path / "private.json"
        custom_kid = "http://example.com/short-test"

        result = runner.invoke(
            app,
            [
                "-p",
                str(public_key_file),
                "-s",
                str(private_key_file),
                "-k",
                custom_kid,
            ],
        )
        assert result.exit_code == 0

        public_key = json.loads(public_key_file.read_text())
        assert public_key["kid"] == custom_kid
