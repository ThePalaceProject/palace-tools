from collections.abc import Sequence
from typing import TypeVar

T = TypeVar("T")


def ensure_list(value: T | Sequence[T] | None) -> list[T]:
    """Ensure that we end up with our value as a list or list member.

    :param value: The value from which we'll create our list.
    :return: A list.

    If we get a sequence (e.g., tuple, list, etc.), we'll return a new list from it.
    If we get a scalar, we put it in a list and return that list.
    If we get None, we'll return an empty list.
    """
    if isinstance(value, Sequence):
        return list(value)
    return [] if value is None else [value]
