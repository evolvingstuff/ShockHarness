"""A rendered page, cached on disk."""

from collections.abc import Callable
from pathlib import Path


def read_cached(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def page(path: Path, render: Callable[[], str]) -> str:
    text = read_cached(path)
    if text == "":
        return render()
    return text
