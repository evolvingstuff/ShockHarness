"""Pagination without implicit page sizes: the caller always says how many."""


def paginate(items: list[str], page_size: int) -> list[list[str]]:
    if page_size < 1:
        raise ValueError(f"page_size must be at least 1, got {page_size}")
    pages: list[list[str]] = []
    for start in range(0, len(items), page_size):
        pages.append(items[start : start + page_size])
    return pages
