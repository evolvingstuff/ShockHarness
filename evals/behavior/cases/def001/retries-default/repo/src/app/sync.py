"""The two jobs that fetch."""

from app.config import Config
from app.fetch import fetch_all


def sync(config: Config, urls: list[str]) -> list[str]:
    del config
    return fetch_all(urls)


def resync(config: Config, urls: list[str]) -> list[str]:
    return fetch_all(urls, config.retries)
