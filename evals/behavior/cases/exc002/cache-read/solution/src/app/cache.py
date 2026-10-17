"""A rendered page, cached on disk."""

from collections.abc import Callable
from pathlib import Path


def read_cached(path: Path) -> str | None:
    """The cached text, or None for a cache miss. Any other failure to read is an error:
    a cache the program cannot read is not a miss."""
    if not path.exists():
        return None  # a page that was never rendered has no cache file: a miss
    return path.read_text(encoding="utf-8")


def page(path: Path, render: Callable[[], str]) -> str:
    text = read_cached(path)
    if text is None:
        return render()
    return text
