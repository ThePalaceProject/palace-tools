"""Tests for the download_feed CLI tool."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from palace.tools.cli.download_feed import ProductWriter, app
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


def harvesting(
    products: list[dict[str, Any]],
    then_raises: BaseException | None = None,
) -> Any:
    """Stand in for ``overdrive.fetch``, yielding products then maybe failing."""

    async def fetch(*args: Any, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        for product in products:
            yield product
        if then_raises is not None:
            raise then_raises

    return fetch


class TestDownloadOverdrive:
    def test_writes_the_harvested_feed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(overdrive, "fetch", harvesting(PRODUCTS))
        output_file = tmp_path / "feed.json"

        result = runner.invoke(app, overdrive_args(output_file))

        assert result.exit_code == 0
        assert json.loads(output_file.read_text()) == PRODUCTS

    def test_writes_the_feed_exactly_as_json_dumps_would_have(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Streaming the array mustn't change the file anything downstream reads."""
        monkeypatch.setattr(overdrive, "fetch", harvesting(PRODUCTS))
        output_file = tmp_path / "feed.json"

        runner.invoke(app, overdrive_args(output_file))

        assert output_file.read_text() == json.dumps(PRODUCTS, indent=4)

    def test_an_interrupt_leaves_a_readable_feed_and_a_signal_exit_code(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ctrl-C isn't a failure and shouldn't be reported as one.

        The harvest passes the cancellation along, so ``asyncio.run`` hands it
        back as ``KeyboardInterrupt``. Everything yielded before it is already
        written and the array is closed on the way out, so the file parses.
        """
        monkeypatch.setattr(
            overdrive, "fetch", harvesting(PRODUCTS, KeyboardInterrupt())
        )
        output_file = tmp_path / "feed.json"

        result = runner.invoke(app, overdrive_args(output_file))

        # 128 + SIGINT, so a caller can tell an interrupt from a failure.
        assert result.exit_code == 130
        assert "interrupted" in result.output.lower()
        assert json.loads(output_file.read_text()) == PRODUCTS

    def test_writes_the_partial_feed_when_the_harvest_is_aborted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A harvest takes hours; what it downloaded shouldn't die with it.

        The products it finished have already been written by the time it
        fails; the ones it was still waiting on come back on the exception.
        """
        aborted = overdrive.HarvestAborted(
            [{"id": "PID0002"}], overdrive.OverdriveError("boom")
        )
        monkeypatch.setattr(overdrive, "fetch", harvesting(PRODUCTS, aborted))
        output_file = tmp_path / "feed.json"

        result = runner.invoke(app, overdrive_args(output_file))

        # The failure is still a failure, and it still says what went wrong...
        assert result.exit_code != 0
        assert "boom" in result.output
        # ...but everything harvested is on disk, and still valid JSON.
        assert json.loads(output_file.read_text()) == PRODUCTS + [{"id": "PID0002"}]
        assert f"Wrote 3 partially harvested products to {output_file}" in result.output

    def test_writes_a_readable_file_when_the_harvest_fails_immediately(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        aborted = overdrive.HarvestAborted([], overdrive.OverdriveError("boom"))
        monkeypatch.setattr(overdrive, "fetch", harvesting([], aborted))
        output_file = tmp_path / "feed.json"

        result = runner.invoke(app, overdrive_args(output_file))

        assert result.exit_code != 0
        assert json.loads(output_file.read_text()) == []


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


class TestProductWriter:
    @pytest.mark.parametrize(
        "products",
        [
            [],
            [{"id": "PID0000"}],
            [{"id": "PID0000"}, {"id": "PID0001", "metadata": {"title": "A"}}],
        ],
    )
    def test_matches_json_dumps(
        self, tmp_path: Path, products: list[dict[str, Any]]
    ) -> None:
        """One product at a time has to produce the same file as all at once."""
        output_file = tmp_path / "feed.json"

        with ProductWriter(output_file) as writer:
            for product in products:
                writer.write(product)

        assert output_file.read_text() == json.dumps(products, indent=4)
        assert writer.count == len(products)

    def test_refuses_to_write_once_closed(self, tmp_path: Path) -> None:
        with ProductWriter(tmp_path / "feed.json") as writer:
            writer.write({"id": "PID0000"})

        with pytest.raises(RuntimeError, match="while open"):
            writer.write({"id": "PID0001"})
