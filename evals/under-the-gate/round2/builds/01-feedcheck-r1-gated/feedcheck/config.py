"""Load and validate the feedcheck configuration file."""

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

FIRST_ATTEMPT = 1
ALLOWED_SCHEMES = frozenset({"http", "https"})
TOP_LEVEL_KEYS = frozenset({"timeout_seconds", "attempts", "retry_backoff_seconds", "feeds"})
FEED_REQUIRED_KEYS = frozenset({"name", "url"})
FEED_OPTIONAL_KEYS = frozenset({"max_age_hours"})


class ConfigError(Exception):
    """The configuration file is missing, unreadable or invalid."""


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
    """Read, parse and validate the configuration at path; any problem raises ConfigError."""
    text = _read_text(path)
    raw = _parse_toml(path, text)
    return _build_config(path, raw)


def _read_text(path: Path) -> str:
    # Boundary (declared in .shockharness.toml): one file read.
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"cannot read config file {path}: {exc}") from exc
    return text


def _parse_toml(path: Path, text: str) -> dict[str, object]:
    # Boundary (declared in .shockharness.toml): one TOML parse of external input.
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"config file {path} is not valid TOML: {exc}") from exc
    return raw


def _build_config(path: Path, raw: Mapping[str, object]) -> Config:
    _reject_unknown_keys(f"config file {path}", raw, TOP_LEVEL_KEYS)
    _require_keys(f"config file {path}", raw, TOP_LEVEL_KEYS)
    timeout = _positive_number(path, "timeout_seconds", raw["timeout_seconds"])
    attempts = raw["attempts"]
    if not _is_int(attempts) or attempts < FIRST_ATTEMPT:
        raise ConfigError(f"config file {path}: attempts must be an integer of at least 1, got {attempts!r}")
    backoff = raw["retry_backoff_seconds"]
    if not _is_number(backoff) or backoff < 0:
        raise ConfigError(
            f"config file {path}: retry_backoff_seconds must be a number of at least 0, got {backoff!r}"
        )
    feeds = _build_feeds(path, raw["feeds"])
    return Config(
        timeout_seconds=timeout,
        attempts=attempts,
        retry_backoff_seconds=float(backoff),
        feeds=feeds,
    )


def _build_feeds(path: Path, raw_feeds: object) -> tuple[Feed, ...]:
    if not isinstance(raw_feeds, list) or not raw_feeds:
        raise ConfigError(f"config file {path}: feeds must be a non-empty list of [[feeds]] tables")
    feeds = tuple(_build_feed(path, index, raw_feed) for index, raw_feed in enumerate(raw_feeds))
    names = [feed.name for feed in feeds]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ConfigError(f"config file {path}: feed names must be unique, repeated: {', '.join(duplicates)}")
    return feeds


def _build_feed(path: Path, index: int, raw_feed: object) -> Feed:
    where = f"config file {path}: feeds[{index}]"
    if not isinstance(raw_feed, dict):
        raise ConfigError(f"{where} must be a table")
    _reject_unknown_keys(where, raw_feed, FEED_REQUIRED_KEYS | FEED_OPTIONAL_KEYS)
    _require_keys(where, raw_feed, FEED_REQUIRED_KEYS)
    name = raw_feed["name"]
    if not isinstance(name, str) or not name.strip():
        raise ConfigError(f"{where}: name must be a non-empty string, got {name!r}")
    url = raw_feed["url"]
    if not isinstance(url, str) or urlsplit(url).scheme not in ALLOWED_SCHEMES or not urlsplit(url).netloc:
        raise ConfigError(f"{where} ({name}): url must be an http or https URL, got {url!r}")
    max_age_hours = None
    if "max_age_hours" in raw_feed:
        max_age_hours = _positive_number(path, f"feeds[{index}].max_age_hours", raw_feed["max_age_hours"])
    return Feed(name=name, url=url, max_age_hours=max_age_hours)


def _positive_number(path: Path, key: str, value: object) -> float:
    if not _is_number(value) or value <= 0:
        raise ConfigError(f"config file {path}: {key} must be a positive number, got {value!r}")
    return float(value)


def _reject_unknown_keys(where: str, raw: Mapping[str, object], allowed: frozenset[str]) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ConfigError(f"{where}: unknown key(s): {', '.join(unknown)}")


def _require_keys(where: str, raw: Mapping[str, object], required: frozenset[str]) -> None:
    missing = sorted(required - set(raw))
    if missing:
        raise ConfigError(f"{where}: missing required key(s): {', '.join(missing)}")


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
