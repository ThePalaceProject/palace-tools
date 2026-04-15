import collections
from collections.abc import Generator, Iterable, Iterator
from itertools import islice
from typing import TypeVar

# A useful utility based on an `itertools` recipe of the same name.
# See: https://docs.python.org/3/library/itertools.html#itertools-recipes
T = TypeVar("T")


def sliding_window(
    iterable: Iterable[T], size: int, *, nulls: int = 0
) -> Generator[tuple[T | None, ...], None, None]:
    """Yield data into overlapping fixed-length chunks or blocks.

    >>> list(sliding_window('ABCDEFG', 4))
    ```[('A', 'B', 'C', 'D'), ('B', 'C', 'D', 'E'), ('C', 'D', 'E', 'F'), ('D', 'E', 'F', 'G')]```

    >>> list(sliding_window('ABCDEFG', 4, nulls=2))
    ```
    [
     ('A', 'B', 'C', 'D'), ('B', 'C', 'D', 'E'), ('C', 'D', 'E', 'F'),
     ('D', 'E', 'F', 'G'), ('E', 'F', 'G', None), ('F', 'G', None, None),
    ]
    ```

    :param iterable: The iterable to iterate over.
    :param size: The size of the sliding window.
    :param nulls: The number of nulls to add to the end of the window.
    :yield: Tuples of `size` elements.
    """
    it: Iterator[T | None] = iter(iterable)
    # We can't have more nulls at the end of the sequence than the `size` of the window.
    nulls = min(size, nulls)
    window = collections.deque(islice(it, size - 1), maxlen=size)
    for x in it:
        window.append(x)
        yield tuple(window)
    for _ in range(nulls):
        window.append(None)
        yield tuple(window)
