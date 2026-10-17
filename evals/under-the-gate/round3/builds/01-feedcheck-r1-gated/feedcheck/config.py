"""Load and validate the feedcheck configuration file."""

from __future__ import annotations

import math
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

SETTINGS_KEYS = frozenset({"timeout_seconds", "attempts", "retry_backoff_seconds", "feeds"})
REQUIRED_FEED_KEYS = frozenset({"name", "url"})
OPTIONAL_FEED_KEYS = frozenset({"max_age_hours"})
URL_SCHEMES = frozenset({"http", "https"})
MIN_ATTEMPTS = 1


class ConfigError(Exception):
    """The configuration file is missing, unreadable or invalid."""


@dataclass(frozen=True)
class Feed:
    name: str
    url: str
    max_age_hours: float | None


@dataclass(frozen=True)
class Settings:
    timeout_seconds: float
    attempts: int
    retry_backoff_seconds: float
    feeds: tuple[Feed, ...]


def load_settings(path: Path) -> Settings:
    """Read, parse and validate the config file at `path`; any problem raises ConfigError."""
    text = _read_text(path)
    # Boundary (declared in .shockharness.toml): parsing the external file.
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: not valid TOML: {exc}") from exc
    return parse_settings(raw, str(path))


def _read_text(path: Path) -> str:
    # Boundary (declared in .shockharness.toml): reading the external file.
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{path}: cannot read config file: {exc}") from exc
    return text


def parse_settings(raw: Mapping[str, object], source: str) -> Settings:
    """Validate a parsed config document; `source` names it in error messages."""
    _check_keys(raw, SETTINGS_KEYS, frozenset(), source)
    timeout = _number(raw["timeout_seconds"], "timeout_seconds", source)
    if timeout <= 0:
        raise ConfigError(f"{source}: timeout_seconds must be positive, got {timeout}")
    attempts = raw["attempts"]
    if not _is_integer(attempts) or attempts < MIN_ATTEMPTS:
        raise ConfigError(f"{source}: attempts must be an integer of at least {MIN_ATTEMPTS}, got {attempts!r}")
    backoff = _number(raw["retry_backoff_seconds"], "retry_backoff_seconds", source)
    if backoff < 0:
        raise ConfigError(f"{source}: retry_backoff_seconds must not be negative, got {backoff}")
    entries = raw["feeds"]
    if not isinstance(entries, list) or not entries:
        raise ConfigError(f"{source}: feeds must be a non-empty array of tables ([[feeds]])")
    feeds = tuple(_parse_feed(entry, f"{source}: feeds[{index}]") for index, entry in enumerate(entries))
    _check_unique_names(feeds, source)
    return Settings(timeout_seconds=timeout, attempts=attempts, retry_backoff_seconds=backoff, feeds=feeds)


def _parse_feed(entry: object, where: str) -> Feed:
    if not isinstance(entry, dict):
        raise ConfigError(f"{where} must be a table with name and url")
    _check_keys(entry, REQUIRED_FEED_KEYS, OPTIONAL_FEED_KEYS, where)
    name = entry["name"]
    if not isinstance(name, str) or not name.strip():
        raise ConfigError(f"{where}.name must be a non-empty string")
    url = entry["url"]
    if not isinstance(url, str) or not _is_http_url(url):
        raise ConfigError(f"{where}.url must be an http or https URL, got {url!r}")
    max_age_hours: float | None = None
    if "max_age_hours" in entry:
        max_age_hours = _number(entry["max_age_hours"], "max_age_hours", where)
        if max_age_hours <= 0:
            raise ConfigError(f"{where}.max_age_hours must be positive, got {max_age_hours}")
    return Feed(name=name, url=url, max_age_hours=max_age_hours)


def _check_keys(table: Mapping[str, object], required: frozenset[str], optional: frozenset[str], where: str) -> None:
    missing = sorted(required - table.keys())
    if missing:
        raise ConfigError(f"{where}: missing required key(s): {', '.join(missing)}")
    unknown = sorted(table.keys() - required - optional)
    if unknown:
        raise ConfigError(f"{where}: unknown key(s): {', '.join(unknown)}")


def _check_unique_names(feeds: tuple[Feed, ...], source: str) -> None:
    seen: set[str] = set()
    for feed in feeds:
        if feed.name in seen:
            raise ConfigError(f"{source}: feed name {feed.name!r} is used more than once")
        seen.add(feed.name)


def _is_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _number(value: object, key: str, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ConfigError(f"{where}: {key} must be a finite number, got {value!r}")
    return float(value)


def _is_http_url(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme in URL_SCHEMES and bool(parts.netloc)
