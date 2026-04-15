import logging


class LogCapture(logging.Handler):
    """A logging handler that captures log records for later retrieval."""

    def __init__(self, level: int = logging.WARNING) -> None:
        super().__init__(level)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def clear(self) -> None:
        self.records.clear()

    def get_messages(self) -> list[str]:
        """Return formatted messages from captured records."""
        return [self.format(record) for record in self.records]
