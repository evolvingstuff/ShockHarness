"""Loading and validating the feeds config file."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from urllib.parse import urlparse

DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = 1.0

_TOP_LEVEL_KEYS = {"timeout_seconds", "attempts", "backoff_seconds", "feeds"}
_FEED_KEYS = {"name", "url", "max_age_hours"}


class ConfigError(Exception):
    """The config file is missing, unreadable or invalid."""


@dataclass(frozen=True)
class Feed:
    name: str
    url: str
    max_age_hours: float | None = None


@dataclass(frozen=True)
class Config:
    feeds: list[Feed]
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    attempts: int = DEFAULT_ATTEMPTS
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _positive_number(table: dict, key: str, where: str, default):
    if key not in table:
        return default
    value = table[key]
    if not _is_number(value) or value <= 0:
        raise ConfigError(f"{where}'{key}' must be a positive number, got {value!r}")
    return float(value)


def load_config(path: str) -> Config:
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}") from None
    except IsADirectoryError:
        raise ConfigError(f"config path is a directory: {path}") from None
    except OSError as exc:
        raise ConfigError(f"cannot read config file {path}: {exc.strerror or exc}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"config file {path} is not valid TOML: {exc}") from None
    except UnicodeDecodeError:
        raise ConfigError(f"config file {path} is not valid UTF-8") from None
    try:
        return parse_config(data)
    except ConfigError as exc:
        raise ConfigError(f"invalid config file {path}: {exc}") from None


def parse_config(data: dict) -> Config:
    unknown = sorted(set(data) - _TOP_LEVEL_KEYS)
    if unknown:
        raise ConfigError(f"unknown key(s): {', '.join(unknown)}")

    timeout = _positive_number(data, "timeout_seconds", "", DEFAULT_TIMEOUT_SECONDS)
    backoff = data.get("backoff_seconds", DEFAULT_BACKOFF_SECONDS)
    if not _is_number(backoff) or backoff < 0:
        raise ConfigError(f"'backoff_seconds' must be a non-negative number, got {backoff!r}")

    attempts = data.get("attempts", DEFAULT_ATTEMPTS)
    if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 1:
        raise ConfigError(f"'attempts' must be an integer of at least 1, got {attempts!r}")

    raw_feeds = data.get("feeds")
    if raw_feeds is None:
        raise ConfigError("no feeds defined (add one or more [[feeds]] tables)")
    if not isinstance(raw_feeds, list) or not raw_feeds:
        raise ConfigError("'feeds' must be a non-empty array of tables ([[feeds]])")

    feeds: list[Feed] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_feeds, start=1):
        where = f"feed #{index}: "
        if not isinstance(raw, dict):
            raise ConfigError(f"{where}must be a table with 'name' and 'url'")
        unknown = sorted(set(raw) - _FEED_KEYS)
        if unknown:
            raise ConfigError(f"{where}unknown key(s): {', '.join(unknown)}")

        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"{where}'name' must be a non-empty string")
        where = f"feed {name!r}: "
        if name in seen:
            raise ConfigError(f"{where}duplicate feed name")
        seen.add(name)

        url = raw.get("url")
        if not isinstance(url, str) or not url.strip():
            raise ConfigError(f"{where}'url' must be a non-empty string")
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ConfigError(f"{where}'url' must be an http(s) URL, got {url!r}")

        max_age = _positive_number(raw, "max_age_hours", where, None)
        feeds.append(Feed(name=name, url=url, max_age_hours=max_age))

    return Config(
        feeds=feeds,
        timeout_seconds=timeout,
        attempts=attempts,
        backoff_seconds=float(backoff),
    )
