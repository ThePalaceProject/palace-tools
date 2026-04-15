from __future__ import annotations

import datetime


def seconds_to_hms(seconds: int | float) -> str:
    """Converts the given number of seconds to a string of format HH:MM:SS."""
    time_delta = str(datetime.timedelta(seconds=seconds))

    # Unfortunately timedelta doesn't seem to have an easy way to format the string,
    # so we do a little hackery to get the format we want.
    rest, seconds_str = time_delta.rsplit(":", maxsplit=1)
    seconds_str = f"{float(seconds_str):#06.3f}".rstrip("0").rstrip(".")
    return f"{rest}:{seconds_str}"


def utc_now() -> datetime.datetime:
    """Get the current time in UTC.

    :return: datetime object
    """
    return datetime.datetime.now(tz=datetime.timezone.utc)
