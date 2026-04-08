"""Stripped-down shim containing only LogLevel.

This is a vendored subset of palace.manager.service.logging.configuration,
providing just the LogLevel enum needed by the OPDS models. The full module
depends on boto3, watchtower, and pydantic_settings which are not needed here.
"""

import logging
from enum import StrEnum, auto


class LogLevel(StrEnum):
    """
    A helper class to represent log levels as an Enum.

    Since the logging module uses strings to represent log levels, the members of
    this enum can be passed directly to the logging module to set the log level.
    """

    @staticmethod
    def _generate_next_value_(
        name: str, start: int, count: int, last_values: list[str]
    ) -> str:
        """
        Return the upper-cased version of the member name.

        By default, StrEnum uses the lower-cased version of the member name as the value,
        but to match the logging module, we want to use the upper-cased version, so
        we override this method to make auto() generate the correct value.
        """
        return name.upper()

    debug = auto()
    info = auto()
    warning = auto()
    error = auto()

    @property
    def levelno(self) -> int:
        """
        Return the integer value used by the logging module for this log level.
        """
        return logging._nameToLevel[self.value]

    @classmethod
    def from_level(cls, level: int | str) -> "LogLevel":
        """
        Get a member of this enum from a string or integer log level.
        """
        if isinstance(level, int):
            parsed_level = logging.getLevelName(level)
        else:
            parsed_level = str(level).upper()

        try:
            return cls(parsed_level)
        except ValueError:
            raise ValueError(f"'{level}' is not a valid LogLevel") from None
