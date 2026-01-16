"""Shared pytest fixtures for all tests."""

from pathlib import Path

import pytest

from tests.fixtures.file import FixtureFile


@pytest.fixture()
def file_fixture() -> FixtureFile:
    """Fixture factory that returns a Path to a file in the fixtures directory."""
    return FixtureFile(Path(__file__).parent)
