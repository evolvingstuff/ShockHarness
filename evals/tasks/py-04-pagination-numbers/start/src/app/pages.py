"""Pagination (starting point: policy numbers baked into the code)."""

MAX_PAGES = 100


def paginate(items: list[str], page_size: int = 10) -> list[list[str]]:
    pages = []
    for start in range(0, len(items), page_size):
        pages.append(items[start : start + page_size])
    if len(pages) > MAX_PAGES:
        raise ValueError("too many pages")
    return pages


def last_item(items: list[str]) -> str:
    return items[-1]
