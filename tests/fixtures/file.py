from pathlib import Path


class FixtureFile:
    """Fixture factory that returns a Path to a file in the fixtures directory.

    Usage:
        def test_something(file_fixture: FixtureFile):
            manifest_path = file_fixture('manifest.json')
            data_path = file_fixture('data.csv')
    """

    def __init__(self, base_path: Path) -> None:
        """Initialize the fixture file factory.

        Args:
            base_path: Base path to the fixtures directory
        """
        self.base_path = base_path

    def __call__(self, filename: str) -> Path:
        """Get the path to a fixture file.

        Args:
            filename: Name of the file in the fixtures/files directory

        Returns:
            Path to the fixture file
        """
        return self.base_path / "fixtures" / "files" / filename
