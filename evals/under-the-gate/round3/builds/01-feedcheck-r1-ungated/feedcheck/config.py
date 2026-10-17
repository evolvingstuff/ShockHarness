"""Loading and validating the feedcheck config file."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

TOP_LEVEL_KEYS = {"timeout_seconds", "attempts", "backoff_seconds", "feeds"}
FEED_KEYS = {"name", "url", "max_age_hours"}

DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = 1.0


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


def load_config(path: str | Path) -> Config:
    path = Path(path)
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}") from None
    except IsADirectoryError:
        raise ConfigError(f"config path is a directory: {path}") from None
    except OSError as e:
        raise ConfigError(f"cannot read config file {path}: {e.strerror or e}") from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"config file {path} is not valid TOML: {e}") from None
    return parse_config(data, source=str(path))


def parse_config(data: dict, source: str = "config") -> Config:
    def fail(msg: str) -> ConfigError:
        return ConfigError(f"invalid config {source}: {msg}")

    unknown = set(data) - TOP_LEVEL_KEYS
    if unknown:
        raise fail(f"unknown key(s): {', '.join(sorted(unknown))}")

    timeout = data.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    if not _is_number(timeout) or timeout <= 0:
        raise fail("'timeout_seconds' must be a positive number")

    attempts = data.get("attempts", DEFAULT_ATTEMPTS)
    if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 1:
        raise fail("'attempts' must be an integer of at least 1")

    backoff = data.get("backoff_seconds", DEFAULT_BACKOFF_SECONDS)
    if not _is_number(backoff) or backoff < 0:
        raise fail("'backoff_seconds' must be a non-negative number")

    raw_feeds = data.get("feeds")
    if raw_feeds is None:
        raise fail("no feeds defined (add one or more [[feeds]] tables)")
    if not isinstance(raw_feeds, list) or not raw_feeds:
        raise fail("'feeds' must be a non-empty list of [[feeds]] tables")

    feeds: list[Feed] = []
    seen: set[str] = set()
    for i, raw in enumerate(raw_feeds, start=1):
        where = f"feed #{i}"
        if not isinstance(raw, dict):
            raise fail(f"{where} must be a table")
        unknown = set(raw) - FEED_KEYS
        if unknown:
            raise fail(f"{where} has unknown key(s): {', '.join(sorted(unknown))}")

        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            raise fail(f"{where} needs a non-empty string 'name'")
        where = f"feed {name!r}"
        if name in seen:
            raise fail(f"duplicate feed name {name!r}")
        seen.add(name)

        url = raw.get("url")
        if not isinstance(url, str) or not url.strip():
            raise fail(f"{where} needs a non-empty string 'url'")
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise fail(f"{where} has an invalid url {url!r} (must be http or https)")

        max_age = raw.get("max_age_hours")
        if max_age is not None and (not _is_number(max_age) or max_age <= 0):
            raise fail(f"{where} 'max_age_hours' must be a positive number")

        feeds.append(Feed(name=name, url=url,
                          max_age_hours=float(max_age) if max_age is not None else None))

    return Config(feeds=feeds, timeout_seconds=float(timeout),
                  attempts=attempts, backoff_seconds=float(backoff))
