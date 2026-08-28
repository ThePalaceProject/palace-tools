"""Tests for the download_feed CLI tool."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from palace.tools.cli.download_feed import app
from palace.tools.feeds import overdrive

runner = CliRunner()

PRODUCTS = [{"id": "PID0000"}, {"id": "PID0001"}]


def overdrive_args(output_file: Path) -> list[str]:
    return [
        "overdrive",
        "-k",
        "client-key",
        "-s",
        "client-secret",
        "-l",
        "1234",
        str(output_file),
    ]


class TestDownloadOverdrive:
    def test_writes_the_harvested_feed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fetch(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
            return PRODUCTS

        monkeypatch.setattr(overdrive, "fetch", fetch)
        output_file = tmp_path / "feed.json"

        result = runner.invoke(app, overdrive_args(output_file))

        assert result.exit_code == 0
        assert json.loads(output_file.read_text()) == PRODUCTS

    def test_writes_the_partial_feed_when_the_harvest_is_aborted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A harvest takes hours; what it downloaded shouldn't die with it."""

        async def fetch(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
            raise overdrive.HarvestAborted(PRODUCTS, overdrive.OverdriveError("boom"))

        monkeypatch.setattr(overdrive, "fetch", fetch)
        output_file = tmp_path / "feed.json"

        result = runner.invoke(app, overdrive_args(output_file))

        # The failure is still a failure, and it still says what went wrong...
        assert result.exit_code != 0
        assert "boom" in result.output
        # ...but the feed downloaded up to that point is on disk.
        assert json.loads(output_file.read_text()) == PRODUCTS
        assert f"Wrote 2 partially harvested products to {output_file}" in result.output


class TestDownloadOverdriveUrl:
    def test_reports_an_error_without_a_traceback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fetch_url(*args: Any, **kwargs: Any) -> Any:
            raise overdrive.OverdriveError("Error: 404")

        monkeypatch.setattr(overdrive, "fetch_url", fetch_url)

        result = runner.invoke(
            app,
            [
                "overdrive-url",
                "-k",
                "client-key",
                "-s",
                "client-secret",
                "https://api.overdrive.com/v1/anything",
            ],
        )

        assert result.exit_code != 0
        assert "Error: 404" in result.output
        assert "Traceback" not in result.output
