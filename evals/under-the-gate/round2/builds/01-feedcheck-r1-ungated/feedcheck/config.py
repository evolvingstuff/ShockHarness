"""Loading and validating the TOML config file."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

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
    feeds: tuple[Feed, ...]
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    attempts: int = DEFAULT_ATTEMPTS
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS


def load_config(path: str | Path) -> Config:
    path = Path(path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}") from None
    except IsADirectoryError:
        raise ConfigError(f"config path is a directory: {path}") from None
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

    try:
        return parse_config(data)
    except ConfigError as exc:
        raise ConfigError(f"invalid config file {path}: {exc}") from None


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_unknown(keys: set[str], allowed: set[str], where: str) -> None:
    unknown = sorted(keys - allowed)
    if unknown:
        raise ConfigError(
            f"unknown key(s) {', '.join(repr(k) for k in unknown)} in {where}"
            f" (allowed: {', '.join(sorted(allowed))})"
        )


def parse_config(data: dict) -> Config:
    _check_unknown(set(data), _TOP_LEVEL_KEYS, "top level")

    timeout = data.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    if not _is_number(timeout) or timeout <= 0:
        raise ConfigError("'timeout_seconds' must be a positive number")

    attempts = data.get("attempts", DEFAULT_ATTEMPTS)
    if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 1:
        raise ConfigError("'attempts' must be an integer of at least 1")

    backoff = data.get("backoff_seconds", DEFAULT_BACKOFF_SECONDS)
    if not _is_number(backoff) or backoff < 0:
        raise ConfigError("'backoff_seconds' must be a number of at least 0")

    if "feeds" not in data:
        raise ConfigError("no feeds defined (add one or more [[feeds]] tables)")
    raw_feeds = data["feeds"]
    if not isinstance(raw_feeds, list) or not all(isinstance(f, dict) for f in raw_feeds):
        raise ConfigError("'feeds' must be an array of tables ([[feeds]])")
    if not raw_feeds:
        raise ConfigError("no feeds defined (add one or more [[feeds]] tables)")

    feeds = []
    seen_names: set[str] = set()
    for index, raw in enumerate(raw_feeds, start=1):
        where = f"feed #{index}"
        _check_unknown(set(raw), _FEED_KEYS, where)

        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"{where}: 'name' is required and must be a non-empty string")
        where = f"feed #{index} ({name!r})"
        if name in seen_names:
            raise ConfigError(f"{where}: duplicate feed name")
        seen_names.add(name)

        url = raw.get("url")
        if not isinstance(url, str) or not url.strip():
            raise ConfigError(f"{where}: 'url' is required and must be a non-empty string")
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ConfigError(f"{where}: 'url' must be an absolute http(s) URL, got {url!r}")

        max_age = raw.get("max_age_hours")
        if max_age is not None and (not _is_number(max_age) or max_age <= 0):
            raise ConfigError(f"{where}: 'max_age_hours' must be a positive number")

        feeds.append(
            Feed(
                name=name,
                url=url,
                max_age_hours=float(max_age) if max_age is not None else None,
            )
        )

    return Config(
        feeds=tuple(feeds),
        timeout_seconds=float(timeout),
        attempts=attempts,
        backoff_seconds=float(backoff),
    )
