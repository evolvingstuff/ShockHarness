"""contactclean: clean a CSV export of contacts."""

from .core import clean
from .cli import main

__all__ = ["clean", "main"]
