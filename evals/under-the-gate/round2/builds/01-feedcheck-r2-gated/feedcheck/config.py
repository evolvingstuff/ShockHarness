"""Load and validate the feedcheck configuration file (TOML)."""

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

TOP_LEVEL_KEYS = frozenset({"timeout_seconds", "attempts", "retry_delay_seconds", "feeds"})
FEED_KEYS = frozenset({"name", "url", "max_age_hours"})
URL_SCHEMES = frozenset({"http", "https"})
MIN_ATTEMPTS = 1


class ConfigError(SystemExit):
    """The configuration file is missing, unreadable or invalid.

    It is a SystemExit: unhandled, it stops the tool with exit code 1 and
    prints its message, before any feed is fetched.
    """

    def __init__(self, message: str) -> None:
        super().__init__(f"feedcheck: {message}")
        self.message = message


@dataclass(frozen=True)
class Feed:
    name: str
    url: str
    max_age_hours: float | None


@dataclass(frozen=True)
class RetryPolicy:
    """How long to wait for a feed and how often to try it.

    Attempt ``n`` (counting from 0) waits ``n * retry_delay_seconds`` first,
    so each attempt after the first waits a little longer than the one before.
    """

    timeout_seconds: float
    attempts: int
    retry_delay_seconds: float


@dataclass(frozen=True)
class Config:
    retry: RetryPolicy
    feeds: tuple[Feed, ...]


def load_config(path: Path) -> Config:
    """Read, parse and validate ``path``; any problem raises ConfigError."""
    if not path.exists():
        raise ConfigError(f"config file {path} does not exist")
    data = _read_bytes(path)
    text = _decode(path, data)
    document = _parse(path, text)
    return _validate(path, document)


def _read_bytes(path: Path) -> bytes:
    # Boundary (declared in .shockharness.toml): one file read.
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ConfigError(f"cannot read config file {path}: {exc.strerror}") from exc
    return data


def _decode(path: Path, data: bytes) -> str:
    # Boundary (declared in .shockharness.toml): decoding external bytes.
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigError(f"config file {path} is not valid UTF-8: {exc.reason}") from exc
    return text


def _parse(path: Path, text: str) -> dict[str, object]:
    # Boundary (declared in .shockharness.toml): parsing external TOML.
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"config file {path} is not valid TOML: {exc}") from exc
    return document


def _validate(path: Path, document: Mapping[str, object]) -> Config:
    where = str(path)
    _reject_unknown_keys(document, TOP_LEVEL_KEYS, where)
    timeout = _number(document, "timeout_seconds", where)
    if timeout <= 0:
        raise ConfigError(f"{where}: timeout_seconds must be positive, got {timeout}")
    attempts = _integer(document, "attempts", where)
    if attempts < MIN_ATTEMPTS:
        raise ConfigError(f"{where}: attempts must be at least {MIN_ATTEMPTS}, got {attempts}")
    delay = _number(document, "retry_delay_seconds", where)
    if delay < 0:
        raise ConfigError(f"{where}: retry_delay_seconds must not be negative, got {delay}")
    feeds = _feeds(document, where)
    retry = RetryPolicy(timeout_seconds=timeout, attempts=attempts, retry_delay_seconds=delay)
    return Config(retry=retry, feeds=feeds)


def _feeds(document: Mapping[str, object], where: str) -> tuple[Feed, ...]:
    raw_feeds = _require(document, "feeds", where)
    if not isinstance(raw_feeds, list) or not raw_feeds:
        raise ConfigError(f"{where}: feeds must be a non-empty list of [[feeds]] tables")
    feeds = tuple(_feed(raw, f"{where}: feeds[{index}]") for index, raw in enumerate(raw_feeds))
    names = [feed.name for feed in feeds]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ConfigError(f"{where}: feed names must be unique, repeated: {', '.join(duplicates)}")
    return feeds


def _feed(raw: object, where: str) -> Feed:
    if not isinstance(raw, dict):
        raise ConfigError(f"{where} must be a table with name and url")
    _reject_unknown_keys(raw, FEED_KEYS, where)
    name = _string(raw, "name", where)
    url = _string(raw, "url", where)
    parts = urlsplit(url)
    if parts.scheme not in URL_SCHEMES or not parts.netloc:
        raise ConfigError(f"{where}: url must be an absolute http or https URL, got {url!r}")
    if "max_age_hours" in raw:
        max_age_hours = _number(raw, "max_age_hours", where)
        if max_age_hours <= 0:
            raise ConfigError(f"{where}: max_age_hours must be positive, got {max_age_hours}")
        return Feed(name=name, url=url, max_age_hours=max_age_hours)
    return Feed(name=name, url=url, max_age_hours=None)


def _reject_unknown_keys(table: Mapping[str, object], allowed: frozenset[str], where: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ConfigError(f"{where}: unknown key(s): {', '.join(unknown)}")


def _require(table: Mapping[str, object], key: str, where: str) -> object:
    if key not in table:
        raise ConfigError(f"{where}: missing required key '{key}'")
    return table[key]


def _number(table: Mapping[str, object], key: str, where: str) -> float:
    value = _require(table, key, where)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{where}: {key} must be a number, got {value!r}")
    return float(value)


def _integer(table: Mapping[str, object], key: str, where: str) -> int:
    value = _require(table, key, where)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{where}: {key} must be an integer, got {value!r}")
    return value


def _string(table: Mapping[str, object], key: str, where: str) -> str:
    value = _require(table, key, where)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where}: {key} must be a non-empty string, got {value!r}")
    return value
