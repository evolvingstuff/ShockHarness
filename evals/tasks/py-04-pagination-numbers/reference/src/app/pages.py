"""Pagination: page size and page cap are required, validated settings."""

from collections.abc import Mapping
from dataclasses import dataclass

MIN_PAGE_SIZE = 1
MIN_MAX_PAGES = 1


@dataclass(frozen=True)
class PageSettings:
    page_size: int
    max_pages: int


def load_page_settings(raw: Mapping[str, str]) -> PageSettings:
    page_size = int(raw["PAGE_SIZE"])
    max_pages = int(raw["MAX_PAGES"])
    if page_size < MIN_PAGE_SIZE:
        raise ValueError(f"PAGE_SIZE must be at least {MIN_PAGE_SIZE}, got {page_size}")
    if max_pages < MIN_MAX_PAGES:
        raise ValueError(f"MAX_PAGES must be at least {MIN_MAX_PAGES}, got {max_pages}")
    return PageSettings(page_size=page_size, max_pages=max_pages)


def paginate(items: list[str], settings: PageSettings) -> list[list[str]]:
    pages: list[list[str]] = []
    for start in range(0, len(items), settings.page_size):
        pages.append(items[start : start + settings.page_size])
    if len(pages) > settings.max_pages:
        raise ValueError(f"{len(pages)} pages exceed MAX_PAGES = {settings.max_pages}")
    return pages


def last_item(items: list[str]) -> str:
    if len(items) == 0:
        raise IndexError("last_item of an empty list")
    return items[len(items) - 1]
