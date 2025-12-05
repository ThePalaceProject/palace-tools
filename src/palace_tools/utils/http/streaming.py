from collections.abc import Callable, Sequence
from typing import Any, BinaryIO, ContextManager, TypeVar

import rich.progress
from httpx import AsyncClient, Response

from palace_tools.utils.http.async_client import HTTPXAsyncClient

DEFAULT_PROGRESS_BAR_TASK_NAME = ""


def default_progress_bar() -> rich.progress.Progress:
    return rich.progress.Progress(
        "{task.description} [progress.percentage]{task.percentage:>3.0f}%",
        rich.progress.BarColumn(bar_width=None),
        rich.progress.DownloadColumn(),
        rich.progress.TransferSpeedColumn(),
    )


T = TypeVar("T")


def _to_list(value: Sequence[T] | T | None) -> list[T]:
    """Ensure that we end up with our own copy as a list.

    :param value: The value from which we'll create our list.
    :return: A list.

    If we get a sequence (e.g., tuple, list, etc.), we'll return a new list from it.
    If we get a scalar, we put it in a list and return that list.
    If we get None, we'll return an empty list.
    """
    if isinstance(value, Sequence):
        return list(value)
    return [] if value is None else [value]


async def streaming_fetch(
    url: str,
    /,
    into_files: BinaryIO | Sequence[BinaryIO] | None = None,
    content_callbacks: (
        Callable[[bytes], Any] | Sequence[Callable[[bytes], Any]] | None
    ) = None,
    total_setters: Callable[[int], Any] | Sequence[Callable[[int], Any]] | None = None,
    progress_updaters: (
        Callable[[int], Any] | Sequence[Callable[[int], Any]] | None
    ) = None,
    http_client: AsyncClient | None = None,
    raise_for_status: bool = False,
) -> Response:
    async with HTTPXAsyncClient.with_existing_client(http_client) as client:
        async with client.stream("GET", url=url) as response:
            if raise_for_status:
                response.raise_for_status()
            if response.headers.get("Content-Length"):
                for setter in _to_list(total_setters):
                    setter(int(response.headers["Content-Length"]))
            if into_files or content_callbacks or progress_updaters:
                async for chunk in response.aiter_bytes():
                    for f in _to_list(into_files):
                        f.write(chunk)
                    for callback in _to_list(content_callbacks):
                        callback(chunk)
                    for updater in _to_list(progress_updaters):
                        updater(response.num_bytes_downloaded)
    return response


async def streaming_fetch_with_progress(
    url: str,
    /,
    into_files: BinaryIO | list[BinaryIO] | None = None,
    content_callbacks: (
        Callable[[bytes], Any] | list[Callable[[bytes], Any]] | None
    ) = None,
    progress_bar: rich.progress.Progress | bool = True,
    auto_connect: bool = False,
    task_label: str | None = None,
    total_setters: Callable[[int], Any] | list[Callable[[int], Any]] | None = None,
    progress_updaters: Callable[[int], Any] | list[Callable[[int], Any]] | None = None,
    http_client: AsyncClient | None = None,
    raise_for_status: bool = False,
) -> Response:
    _progress_bar: ContextManager[rich.progress.Progress] | None = None
    _task_label: str | None = None
    if isinstance(progress_bar, rich.progress.Progress):
        _progress_bar = progress_bar
        _connect = auto_connect
        ...
    elif isinstance(progress_bar, bool) and progress_bar:
        _progress_bar = default_progress_bar()
        _connect = True
    else:
        # Not using a progress bar, so we'll just hand off to the streaming fetcher.
        return await streaming_fetch(
            url,
            into_files=into_files,
            http_client=http_client,
            content_callbacks=content_callbacks,
            total_setters=total_setters,
            progress_updaters=progress_updaters,
            raise_for_status=raise_for_status,
        )

    with _progress_bar as progress:
        task = progress.add_task(task_label or DEFAULT_PROGRESS_BAR_TASK_NAME)
        # If we're connecting our progress bar here, then ensure callbacks are in the lists.
        if _connect:
            total_setters = [lambda t: progress.update(task, total=t)] + _to_list(
                total_setters
            )
            progress_updaters = [
                lambda count: progress.update(task, completed=count)
            ] + _to_list(progress_updaters)
        return await streaming_fetch(
            url,
            into_files=into_files,
            http_client=http_client,
            content_callbacks=content_callbacks,
            total_setters=total_setters,
            progress_updaters=progress_updaters,
            raise_for_status=raise_for_status,
        )
