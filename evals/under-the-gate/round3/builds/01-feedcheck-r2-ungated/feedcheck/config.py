"""Loading and validating the TOML config file."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from urllib.parse import urlparse

DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = 0.5


class ConfigError(Exception):
    """The config file is missing, unreadable or invalid."""


@dataclass(frozen=True)
class FeedConfig:
    name: str
    url: str
    max_age_hours: float | None = None


@dataclass(frozen=True)
class Config:
    feeds: list[FeedConfig] = field(default_factory=list)
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    attempts: int = DEFAULT_ATTEMPTS
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def load_config(path: str) -> Config:
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}") from None
    except IsADirectoryError:
        raise ConfigError(f"config path is a directory, not a file: {path}") from None
    except OSError as e:
        raise ConfigError(f"cannot read config file {path}: {e.strerror or e}") from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"config file {path} is not valid TOML: {e}") from None
    try:
        return parse_config(data)
    except ConfigError as e:
        raise ConfigError(f"invalid config file {path}: {e}") from None


def parse_config(data: dict) -> Config:
    known = {"timeout_seconds", "attempts", "backoff_seconds", "feeds"}
    unknown = sorted(set(data) - known)
    if unknown:
        raise ConfigError(f"unknown top-level key(s): {', '.join(unknown)}")

    timeout = data.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    if not _is_number(timeout) or timeout <= 0:
        raise ConfigError("'timeout_seconds' must be a positive number")

    attempts = data.get("attempts", DEFAULT_ATTEMPTS)
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1:
        raise ConfigError("'attempts' must be an integer of at least 1")

    backoff = data.get("backoff_seconds", DEFAULT_BACKOFF_SECONDS)
    if not _is_number(backoff) or backoff < 0:
        raise ConfigError("'backoff_seconds' must be a non-negative number")

    if "feeds" not in data:
        raise ConfigError("no feeds listed (add one or more [[feeds]] tables)")
    raw_feeds = data["feeds"]
    if not isinstance(raw_feeds, list) or not raw_feeds:
        raise ConfigError("'feeds' must be a non-empty list of [[feeds]] tables")

    feeds: list[FeedConfig] = []
    seen: set[str] = set()
    for i, raw in enumerate(raw_feeds, start=1):
        where = f"feed #{i}"
        if not isinstance(raw, dict):
            raise ConfigError(f"{where} must be a table")
        unknown = sorted(set(raw) - {"name", "url", "max_age_hours"})
        if unknown:
            raise ConfigError(f"{where}: unknown key(s): {', '.join(unknown)}")
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"{where}: 'name' must be a non-empty string")
        where = f"feed {name!r}"
        if name in seen:
            raise ConfigError(f"{where}: duplicate name")
        seen.add(name)
        url = raw.get("url")
        if not isinstance(url, str) or not url.strip():
            raise ConfigError(f"{where}: 'url' must be a non-empty string")
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ConfigError(f"{where}: 'url' must be an http(s) URL, got {url!r}")
        max_age = raw.get("max_age_hours")
        if max_age is not None and (not _is_number(max_age) or max_age <= 0):
            raise ConfigError(f"{where}: 'max_age_hours' must be a positive number")
        feeds.append(
            FeedConfig(
                name=name,
                url=url,
                max_age_hours=float(max_age) if max_age is not None else None,
            )
        )

    return Config(
        feeds=feeds,
        timeout_seconds=float(timeout),
        attempts=attempts,
        backoff_seconds=float(backoff),
    )
