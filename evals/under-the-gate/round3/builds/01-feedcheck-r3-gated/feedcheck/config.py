"""Load and validate the feedcheck configuration file (TOML)."""

import tomllib
import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

ALLOWED_SCHEMES = frozenset({"http", "https"})
TOP_LEVEL_KEYS = frozenset({"timeout_seconds", "attempts", "retry_delay_seconds", "feeds"})
FEED_REQUIRED_KEYS = frozenset({"name", "url"})
FEED_OPTIONAL_KEYS = frozenset({"max_age_hours"})
MIN_ATTEMPTS = 1


class ConfigError(Exception):
    """The configuration file is missing, unreadable or invalid."""


@dataclass(frozen=True)
class FeedConfig:
    name: str
    url: str
    max_age_hours: float | None


@dataclass(frozen=True)
class Config:
    timeout_seconds: float
    attempts: int
    retry_delay_seconds: float
    feeds: tuple[FeedConfig, ...]


def load_config(path: Path) -> Config:
    """Read, parse and validate the configuration at `path`; raise ConfigError on any problem."""
    # Boundary (declared in .shockharness.toml): reading the file.
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read config file {path}: {exc.strerror}") from exc
    except UnicodeDecodeError as exc:
        raise ConfigError(f"config file {path} is not valid UTF-8") from exc
    # Boundary (declared in .shockharness.toml): parsing external TOML.
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"config file {path} is not valid TOML: {exc}") from exc
    return parse_config(raw, path)


def parse_config(raw: Mapping[str, object], path: Path) -> Config:
    """Validate the parsed TOML document `raw` read from `path`."""
    _check_keys(raw, TOP_LEVEL_KEYS, TOP_LEVEL_KEYS, f"config file {path}")
    timeout = _positive_number(raw["timeout_seconds"], "timeout_seconds")
    attempts = raw["attempts"]
    if not _is_int(attempts) or attempts < MIN_ATTEMPTS:
        raise ConfigError(f"attempts must be an integer of at least {MIN_ATTEMPTS}, got {attempts!r}")
    delay = raw["retry_delay_seconds"]
    if not _is_number(delay) or delay < 0:
        raise ConfigError(f"retry_delay_seconds must be a number not below 0, got {delay!r}")
    feeds_raw = raw["feeds"]
    if not isinstance(feeds_raw, list) or not feeds_raw:
        raise ConfigError("feeds must be a non-empty list of [[feeds]] tables")
    feeds = tuple(_parse_feed(entry, index) for index, entry in enumerate(feeds_raw, start=1))
    names = [feed.name for feed in feeds]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ConfigError(f"feed names must be unique, repeated: {', '.join(duplicates)}")
    return Config(
        timeout_seconds=float(timeout),
        attempts=attempts,
        retry_delay_seconds=float(delay),
        feeds=feeds,
    )


def _parse_feed(entry: object, index: int) -> FeedConfig:
    where = f"feed #{index}"
    if not isinstance(entry, dict):
        raise ConfigError(f"{where} must be a table with name and url")
    _check_keys(entry, FEED_REQUIRED_KEYS, FEED_REQUIRED_KEYS | FEED_OPTIONAL_KEYS, where)
    name = entry["name"]
    if not isinstance(name, str) or not name.strip():
        raise ConfigError(f"{where}: name must be a non-empty string")
    url = entry["url"]
    if not isinstance(url, str) or urllib.parse.urlsplit(url).scheme not in ALLOWED_SCHEMES:
        raise ConfigError(f"feed {name!r}: url must be an http or https URL, got {url!r}")
    if not urllib.parse.urlsplit(url).netloc:
        raise ConfigError(f"feed {name!r}: url has no host: {url!r}")
    max_age: float | None = None
    if "max_age_hours" in entry:
        max_age = float(_positive_number(entry["max_age_hours"], f"feed {name!r}: max_age_hours"))
    return FeedConfig(name=name, url=url, max_age_hours=max_age)


def _check_keys(table: Mapping[str, object], required: frozenset[str], allowed: frozenset[str], where: str) -> None:
    missing = sorted(required - table.keys())
    if missing:
        raise ConfigError(f"{where} is missing required key(s): {', '.join(missing)}")
    unknown = sorted(table.keys() - allowed)
    if unknown:
        raise ConfigError(f"{where} has unknown key(s): {', '.join(unknown)}")


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: object) -> bool:
    return _is_int(value) or isinstance(value, float)


def _positive_number(value: object, label: str) -> float:
    if not _is_number(value) or value <= 0:
        raise ConfigError(f"{label} must be a positive number, got {value!r}")
    return float(value)
