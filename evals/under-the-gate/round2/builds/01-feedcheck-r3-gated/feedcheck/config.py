"""Load and validate the feedcheck config file."""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from feedcheck.errors import ConfigError

TOP_LEVEL_KEYS = frozenset({"timeout_seconds", "attempts", "retry_backoff_seconds", "feeds"})
REQUIRED_FEED_KEYS = frozenset({"name", "url"})
OPTIONAL_FEED_KEYS = frozenset({"max_age_hours"})
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
    """Read and validate the config at `path`; any problem raises ConfigError."""
    raw = parse_config(read_config_text(path), path)
    return validate_config(raw, path)


def read_config_text(path: Path) -> str:
    # Boundary (declared in .shockharness.toml): one file read.
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"cannot read config file {path}: {exc}") from exc
    return text


def parse_config(text: str, path: Path) -> dict[str, object]:
    # Boundary (declared in .shockharness.toml): one TOML decode of external input.
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"config file {path} is not valid TOML: {exc}") from exc
    return raw


def validate_config(raw: dict[str, object], path: Path) -> Config:
    unknown = set(raw) - TOP_LEVEL_KEYS
    if unknown:
        raise ConfigError(f"config file {path}: unknown keys {sorted(unknown)}")
    missing = TOP_LEVEL_KEYS - set(raw)
    if missing:
        raise ConfigError(f"config file {path}: missing required keys {sorted(missing)}")
    timeout = _number(raw["timeout_seconds"], "timeout_seconds", path)
    if timeout <= 0:
        raise ConfigError(f"config file {path}: timeout_seconds must be positive, got {timeout}")
    attempts = raw["attempts"]
    if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < MIN_ATTEMPTS:
        raise ConfigError(f"config file {path}: attempts must be an integer of at least {MIN_ATTEMPTS}, got {attempts!r}")
    backoff = _number(raw["retry_backoff_seconds"], "retry_backoff_seconds", path)
    if backoff < 0:
        raise ConfigError(f"config file {path}: retry_backoff_seconds must not be negative, got {backoff}")
    feeds = _feeds(raw["feeds"], path)
    return Config(timeout_seconds=timeout, attempts=attempts, retry_backoff_seconds=backoff, feeds=feeds)


def _number(value: object, key: str, path: Path) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ConfigError(f"config file {path}: {key} must be a number, got {value!r}")
    return float(value)


def _feeds(value: object, path: Path) -> tuple[Feed, ...]:
    if not isinstance(value, list) or not value:
        raise ConfigError(f"config file {path}: feeds must be a non-empty list of [[feeds]] tables")
    feeds = tuple(_feed(entry, index, path) for index, entry in enumerate(value))
    names = [feed.name for feed in feeds]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ConfigError(f"config file {path}: feed names must be unique, repeated: {duplicates}")
    return feeds


def _feed(entry: object, index: int, path: Path) -> Feed:
    where = f"config file {path}: feeds[{index}]"
    if not isinstance(entry, dict):
        raise ConfigError(f"{where} must be a table")
    _check_feed_keys(entry, where)
    name = entry["name"]
    if not isinstance(name, str) or not name.strip():
        raise ConfigError(f"{where}: name must be a non-empty string")
    url = entry["url"]
    if not _is_http_url(url):
        raise ConfigError(f"{where} ({name}): url must be an http or https URL, got {url!r}")
    return Feed(name=name, url=url, max_age_hours=_max_age_hours(entry, f"feeds[{index}] ({name})", path))


def _check_feed_keys(entry: dict[str, object], where: str) -> None:
    unknown = set(entry) - REQUIRED_FEED_KEYS - OPTIONAL_FEED_KEYS
    if unknown:
        raise ConfigError(f"{where}: unknown keys {sorted(unknown)}")
    missing = REQUIRED_FEED_KEYS - set(entry)
    if missing:
        raise ConfigError(f"{where}: missing required keys {sorted(missing)}")


def _is_http_url(url: object) -> bool:
    if not isinstance(url, str):
        return False
    parts = urlsplit(url)
    return parts.scheme in URL_SCHEMES and bool(parts.netloc)


def _max_age_hours(entry: dict[str, object], where: str, path: Path) -> float | None:
    """The feed's freshness limit, or None when the feed sets none (staleness is then not checked)."""
    if "max_age_hours" not in entry:
        return None
    max_age_hours = _number(entry["max_age_hours"], f"{where} max_age_hours", path)
    if max_age_hours <= 0:
        raise ConfigError(f"config file {path}: {where} max_age_hours must be positive, got {max_age_hours}")
    return max_age_hours
