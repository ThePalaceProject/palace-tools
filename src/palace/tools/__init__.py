__version__: str | None
try:
    from palace.tools._version import __version__
except ImportError:
    # This should only ever happen if uv sync wasn't run, but it's good
    # to have a reasonable fallback in this case.
    __version__ = None

__all__ = ["__version__"]
