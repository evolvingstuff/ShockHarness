"""Fetching a batch of URLs."""


def fetch_all(urls: list[str], retries: int) -> list[str]:
    return [f"{url}#retries={retries}" for url in urls]
