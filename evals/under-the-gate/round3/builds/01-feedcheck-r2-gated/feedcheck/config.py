"""Load and validate the feeds config file (TOML)."""

import math
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from feedcheck.errors import ConfigError

TOP_LEVEL_KEYS = frozenset({"timeout_seconds", "attempts", "retry_backoff_seconds", "feeds"})
FEED_REQUIRED_KEYS = frozenset({"name", "url"})
FEED_OPTIONAL_KEYS = frozenset({"max_age_hours"})
URL_SCHEMES = frozenset({"http", "https"})
MIN_ATTEMPTS = 1


@dataclass(frozen=True)
class Feed:
    name: str
    url: str
    max_age_hours: float | None


@dataclass(frozen=True)
class Config:
    timeout_seconds: float
    attempts: int
    retry_backoff_seconds: float
    feeds: tuple[Feed, ...]


def load_config(path: Path) -> Config:
    """Read, parse and validate the config file; any problem raises ConfigError."""
    # Boundary (declared in .shockharness.toml): one file read.
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ConfigError(f"cannot read config file {path}: {exc}") from exc
    # Boundary: one decode.
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigError(f"config file {path} is not UTF-8: {exc}") from exc
    # Boundary: one parse.
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"config file {path} is not valid TOML: {exc}") from exc
    return parse_config(raw, str(path))


def parse_config(raw: Mapping[str, object], source: str) -> Config:
    """Validate a parsed config mapping; `source` names it in error messages."""
    _check_keys(raw, TOP_LEVEL_KEYS, frozenset(), source)
    timeout = _number(raw["timeout_seconds"], f"{source}: timeout_seconds")
    if timeout <= 0:
        raise ConfigError(f"{source}: timeout_seconds must be positive, got {timeout}")
    attempts = raw["attempts"]
    if isinstance(attempts, bool) or not isinstance(attempts, int):
        raise ConfigError(f"{source}: attempts must be an integer, got {attempts!r}")
    if attempts < MIN_ATTEMPTS:
        raise ConfigError(f"{source}: attempts must be at least {MIN_ATTEMPTS}, got {attempts}")
    backoff = _number(raw["retry_backoff_seconds"], f"{source}: retry_backoff_seconds")
    if backoff < 0:
        raise ConfigError(f"{source}: retry_backoff_seconds must not be negative, got {backoff}")
    feeds = _parse_feeds(raw["feeds"], source)
    return Config(
        timeout_seconds=timeout,
        attempts=attempts,
        retry_backoff_seconds=backoff,
        feeds=feeds,
    )


def _parse_feeds(value: object, source: str) -> tuple[Feed, ...]:
    if not isinstance(value, list) or not value:
        raise ConfigError(f"{source}: feeds must be a non-empty list of [[feeds]] tables")
    feeds = []
    names = set()
    for index, entry in enumerate(value):
        where = f"{source}: feeds[{index}]"
        if not isinstance(entry, dict):
            raise ConfigError(f"{where} must be a table, got {entry!r}")
        feed = _parse_feed(entry, where)
        if feed.name in names:
            raise ConfigError(f"{where}: duplicate feed name {feed.name!r}")
        names.add(feed.name)
        feeds.append(feed)
    return tuple(feeds)


def _parse_feed(entry: Mapping[str, object], where: str) -> Feed:
    _check_keys(entry, FEED_REQUIRED_KEYS, FEED_OPTIONAL_KEYS, where)
    name = entry["name"]
    if not isinstance(name, str) or not name.strip():
        raise ConfigError(f"{where}: name must be a non-empty string, got {name!r}")
    url = entry["url"]
    if not isinstance(url, str):
        raise ConfigError(f"{where}: url must be a string, got {url!r}")
    parts = urlsplit(url)
    if parts.scheme not in URL_SCHEMES or not parts.netloc:
        raise ConfigError(f"{where}: url must be an http or https URL, got {url!r}")
    max_age_hours = None
    if "max_age_hours" in entry:
        max_age_hours = _number(entry["max_age_hours"], f"{where}: max_age_hours")
        if max_age_hours <= 0:
            raise ConfigError(f"{where}: max_age_hours must be positive, got {max_age_hours}")
    return Feed(name=name, url=url, max_age_hours=max_age_hours)


def _check_keys(
    table: Mapping[str, object],
    required: frozenset[str],
    optional: frozenset[str],
    where: str,
) -> None:
    missing = sorted(required - table.keys())
    if missing:
        raise ConfigError(f"{where}: missing required key(s): {', '.join(missing)}")
    unknown = sorted(table.keys() - required - optional)
    if unknown:
        raise ConfigError(f"{where}: unknown key(s): {', '.join(unknown)}")


def _number(value: object, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{where} must be a number, got {value!r}")
    if not math.isfinite(value):
        raise ConfigError(f"{where} must be finite, got {value}")
    return float(value)
