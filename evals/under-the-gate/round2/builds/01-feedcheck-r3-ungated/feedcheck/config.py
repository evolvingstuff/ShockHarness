"""Loading and validating the feedcheck TOML config."""

from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

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
    # bool is a subclass of int; `timeout_seconds = true` is not a number.
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _positive_number(table: dict, key: str, where: str, default: float | None) -> float | None:
    if key not in table:
        return default
    value = table[key]
    if not _is_number(value) or value <= 0:
        raise ConfigError(f"{where}: '{key}' must be a positive number, got {value!r}")
    return float(value)


def load_config(path: str | Path) -> Config:
    path = Path(path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}") from None
    except IsADirectoryError:
        raise ConfigError(f"config path is a directory, not a file: {path}") from None
    except OSError as exc:
        raise ConfigError(f"cannot read config file {path}: {exc.strerror or exc}") from None

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ConfigError(f"config file {path} is not valid UTF-8") from None

    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"config file {path} is not valid TOML: {exc}") from None

    return parse_config(data, str(path))


def parse_config(data: dict, where: str = "config") -> Config:
    known = {"timeout_seconds", "attempts", "backoff_seconds", "feeds"}
    unknown = sorted(set(data) - known)
    if unknown:
        raise ConfigError(f"{where}: unknown setting(s): {', '.join(unknown)}")

    timeout = _positive_number(data, "timeout_seconds", where, DEFAULT_TIMEOUT_SECONDS)

    attempts = data.get("attempts", DEFAULT_ATTEMPTS)
    if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 1:
        raise ConfigError(f"{where}: 'attempts' must be an integer >= 1, got {attempts!r}")

    backoff = DEFAULT_BACKOFF_SECONDS
    if "backoff_seconds" in data:
        backoff = data["backoff_seconds"]
        if not _is_number(backoff) or backoff < 0:
            raise ConfigError(
                f"{where}: 'backoff_seconds' must be a number >= 0, got {backoff!r}"
            )
        backoff = float(backoff)

    if "feeds" not in data:
        raise ConfigError(f"{where}: no feeds defined (expected one or more [[feeds]] tables)")
    raw_feeds = data["feeds"]
    if not isinstance(raw_feeds, list) or not raw_feeds:
        raise ConfigError(f"{where}: 'feeds' must be a non-empty array of [[feeds]] tables")

    feeds: list[Feed] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw_feeds, start=1):
        label = f"{where}: feed #{index}"
        if not isinstance(entry, dict):
            raise ConfigError(f"{label} must be a table")
        extra = sorted(set(entry) - {"name", "url", "max_age_hours"})
        if extra:
            raise ConfigError(f"{label}: unknown key(s): {', '.join(extra)}")

        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"{label}: 'name' is required and must be a non-empty string")
        label = f"{where}: feed {name!r}"
        if name in seen:
            raise ConfigError(f"{label}: duplicate feed name")
        seen.add(name)

        url = entry.get("url")
        if not isinstance(url, str) or not url.strip():
            raise ConfigError(f"{label}: 'url' is required and must be a non-empty string")
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ConfigError(f"{label}: 'url' must be an http(s) URL, got {url!r}")

        max_age = _positive_number(entry, "max_age_hours", label, None)
        feeds.append(Feed(name=name, url=url, max_age_hours=max_age))

    return Config(
        feeds=feeds,
        timeout_seconds=timeout,
        attempts=attempts,
        backoff_seconds=backoff,
    )
