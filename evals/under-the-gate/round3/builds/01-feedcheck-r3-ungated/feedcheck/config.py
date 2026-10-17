"""Loading and validating the feedcheck TOML config."""

from __future__ import annotations

import tomllib
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

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
    # bool is a subclass of int; `timeout_seconds = true` is not a number.
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _positive_number(table: dict, key: str, where: str, default: float | None) -> float | None:
    if key not in table:
        return default
    value = table[key]
    if not _is_number(value) or not value > 0 or value == float("inf"):
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
        data = tomllib.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        raise ConfigError(f"config file {path} is not valid UTF-8") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"config file {path} is not valid TOML: {exc}") from None

    return parse_config(data, str(path))


def parse_config(data: dict, source: str = "config") -> Config:
    unknown = sorted(set(data) - _TOP_LEVEL_KEYS)
    if unknown:
        raise ConfigError(f"{source}: unknown setting(s): {', '.join(unknown)}")

    timeout = _positive_number(data, "timeout_seconds", source, DEFAULT_TIMEOUT_SECONDS)

    attempts = data.get("attempts", DEFAULT_ATTEMPTS)
    if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 1:
        raise ConfigError(f"{source}: 'attempts' must be an integer of at least 1, got {attempts!r}")

    backoff = data.get("backoff_seconds", DEFAULT_BACKOFF_SECONDS)
    if not _is_number(backoff) or not 0 <= backoff < float("inf"):
        raise ConfigError(f"{source}: 'backoff_seconds' must be a number >= 0, got {backoff!r}")

    if "feeds" not in data:
        raise ConfigError(f"{source}: no feeds defined (add one or more [[feeds]] tables)")
    feeds_raw = data["feeds"]
    if not isinstance(feeds_raw, list) or not feeds_raw:
        raise ConfigError(f"{source}: 'feeds' must be a non-empty list of [[feeds]] tables")

    feeds: list[Feed] = []
    seen: set[str] = set()
    for index, entry in enumerate(feeds_raw, start=1):
        where = f"{source}: feed #{index}"
        if not isinstance(entry, dict):
            raise ConfigError(f"{where} must be a table with 'name' and 'url'")
        unknown = sorted(set(entry) - _FEED_KEYS)
        if unknown:
            raise ConfigError(f"{where}: unknown key(s): {', '.join(unknown)}")

        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"{where}: 'name' must be a non-empty string")
        where = f"{source}: feed '{name}'"
        if name in seen:
            raise ConfigError(f"{where}: duplicate feed name")
        seen.add(name)

        url = entry.get("url")
        if not isinstance(url, str) or not url.strip():
            raise ConfigError(f"{where}: 'url' must be a non-empty string")
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ConfigError(f"{where}: 'url' must be an http:// or https:// URL, got {url!r}")

        max_age = _positive_number(entry, "max_age_hours", where, None)
        feeds.append(Feed(name=name, url=url, max_age_hours=max_age))

    return Config(
        feeds=feeds,
        timeout_seconds=timeout,
        attempts=attempts,
        backoff_seconds=float(backoff),
    )
