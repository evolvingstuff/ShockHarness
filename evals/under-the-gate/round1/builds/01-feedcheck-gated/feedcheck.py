"""feedcheck: check whether a set of JSON feeds is healthy and write a report."""

import argparse
import http.client
import json
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from pathlib import Path

EXIT_OK = 0
EXIT_UNHEALTHY = 1
EXIT_CONFIG = 2  # shockharness: ignore[MAGIC001] reason="2 is the conventional usage/configuration error exit status (argparse, POSIX shells)"

URL_SCHEMES = frozenset({"http", "https"})
STATUS_HEALTHY = "healthy"
STATUS_UNHEALTHY = "unhealthy"
STATUS_UNREACHABLE = "unreachable"
STATUS_STALE = "stale"


class ConfigError(Exception):
    """The configuration file is missing, unreadable or invalid."""


class FeedFailure(Exception):
    """A feed could not be judged healthy; the message is the reason."""


class Unreachable(FeedFailure):
    """The server did not answer or answered 5xx: worth another attempt."""


class Unhealthy(FeedFailure):
    """The server answered, but not with a healthy feed: retrying will not help."""


@dataclass(frozen=True)
class Settings:
    timeout_seconds: float
    attempts: int
    backoff_seconds: float


@dataclass(frozen=True)
class Feed:
    name: str
    url: str
    max_age_hours: float | None


@dataclass(frozen=True)
class Config:
    settings: Settings
    feeds: tuple[Feed, ...]


@dataclass(frozen=True)
class FeedResult:
    name: str
    status: str
    reason: str | None
    items: int | None
    elapsed_seconds: float


def _require(table: Mapping[str, object], key: str, kind: type, where: str) -> object:
    if key not in table:
        raise ConfigError(f"{where}: missing required key '{key}'")
    value = table[key]
    if isinstance(value, bool) or not isinstance(value, kind):
        raise ConfigError(f"{where}: '{key}' must be of type {kind.__name__}")
    return value


def _require_number(table: Mapping[str, object], key: str, where: str) -> float:
    value = _require(table, key, (int, float), where)
    assert isinstance(value, (int, float))
    return float(value)


def _parse_settings(raw: Mapping[str, object]) -> Settings:
    table = _require(raw, "settings", dict, "config")
    assert isinstance(table, dict)
    where = "[settings]"
    timeout = _require_number(table, "timeout_seconds", where)
    backoff = _require_number(table, "backoff_seconds", where)
    attempts = _require(table, "attempts", int, where)
    assert isinstance(attempts, int)
    if timeout <= 0:
        raise ConfigError(f"{where}: 'timeout_seconds' must be positive")
    if backoff < 0:
        raise ConfigError(f"{where}: 'backoff_seconds' must not be negative")
    if attempts < 1:
        raise ConfigError(f"{where}: 'attempts' must be at least 1")
    return Settings(timeout_seconds=timeout, attempts=attempts, backoff_seconds=backoff)


def _parse_feed(table: object, index: int) -> Feed:
    where = f"[[feeds]] entry {index + 1}"
    if not isinstance(table, dict):
        raise ConfigError(f"{where}: must be a table")
    name = _require(table, "name", str, where)
    url = _require(table, "url", str, where)
    assert isinstance(name, str) and isinstance(url, str)
    if urllib.parse.urlsplit(url).scheme not in URL_SCHEMES:
        raise ConfigError(f"{where}: 'url' must be an http or https URL")
    max_age: float | None = None
    if "max_age_hours" in table:
        max_age = _require_number(table, "max_age_hours", where)
        if max_age <= 0:
            raise ConfigError(f"{where}: 'max_age_hours' must be positive")
    return Feed(name=name, url=url, max_age_hours=max_age)


def parse_config(text: str) -> Config:
    raw = _decode_toml(text)
    settings = _parse_settings(raw)
    feeds_raw = _require(raw, "feeds", list, "config")
    assert isinstance(feeds_raw, list)
    feeds = tuple(_parse_feed(table, index) for index, table in enumerate(feeds_raw))
    names = [feed.name for feed in feeds]
    if len(set(names)) != len(names):
        raise ConfigError("config: feed names must be unique")
    return Config(settings=settings, feeds=feeds)


def _decode_toml(text: str) -> dict[str, object]:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"config is not valid TOML: {exc}") from exc


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc


def load_config(path: Path) -> Config:
    return parse_config(_read_text(path))


def _open(url: str, timeout: float) -> urllib.request.addinfourl:
    try:
        return urllib.request.urlopen(url, timeout=timeout)
    except urllib.error.HTTPError as exc:
        exc.close()
        raise _status_failure(exc.code) from exc
    except (OSError, http.client.HTTPException) as exc:
        raise Unreachable(f"no answer: {exc}") from exc


def _status_failure(status: int) -> FeedFailure:
    server_error = HTTPStatus.INTERNAL_SERVER_ERROR <= status <= HTTPStatus.NETWORK_AUTHENTICATION_REQUIRED
    if server_error:
        return Unreachable(f"server answered {status}")
    return Unhealthy(f"server answered {status}, expected {HTTPStatus.OK.value}")


def _read_body(response: urllib.request.addinfourl) -> bytes:
    try:
        return response.read()
    except (OSError, http.client.HTTPException) as exc:
        raise Unreachable(f"connection lost while reading: {exc}") from exc


def _fetch_once(url: str, timeout: float) -> bytes:
    with _open(url, timeout) as response:
        if response.status != HTTPStatus.OK:
            raise _status_failure(response.status)
        return _read_body(response)


def _fetch_with_retries(url: str, settings: Settings) -> bytes:
    failure: Unreachable | None = None
    for attempt in range(settings.attempts):
        if attempt > 0:
            time.sleep(settings.backoff_seconds * attempt)
        try:
            return _fetch_once(url, settings.timeout_seconds)
        except Unreachable as exc:
            failure = exc
    assert failure is not None, "attempts is at least 1"
    raise failure


def _decode_json(body: bytes) -> object:
    try:
        return json.loads(body)
    except ValueError as exc:
        raise Unhealthy(f"body is not valid JSON: {exc}") from exc


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise Unhealthy("an item has no 'published' timestamp")
    parsed = _parse_iso(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_iso(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise Unhealthy(f"'published' is not ISO 8601: {value}") from exc


def _items_of(document: object) -> list[object]:
    if not isinstance(document, dict):
        raise Unhealthy("feed is not a JSON object")
    if "items" not in document:
        raise Unhealthy("feed has no 'items'")
    items = document["items"]
    if not isinstance(items, list):
        raise Unhealthy("'items' is not a list")
    return items


def _newest(items: list[object]) -> datetime:
    if not items:
        raise Unhealthy("feed has no items, so its age is unknown")
    stamps = []
    for item in items:
        if not isinstance(item, dict) or "published" not in item:
            raise Unhealthy("an item has no 'published' timestamp")
        stamps.append(_parse_time(item["published"]))
    return max(stamps)


def _judge(feed: Feed, body: bytes, now: datetime) -> tuple[str, str | None, int]:
    """Return (status, reason, item count) for a feed that answered 200."""
    items = _items_of(_decode_json(body))
    if feed.max_age_hours is None:
        return STATUS_HEALTHY, None, len(items)
    age = now - _newest(items)
    limit = timedelta(hours=feed.max_age_hours)
    if age > limit:
        return STATUS_STALE, f"newest item is {age} old, limit is {limit}", len(items)
    return STATUS_HEALTHY, None, len(items)


def _fetch_and_judge(feed: Feed, settings: Settings, now: datetime) -> tuple[str, str | None, int | None]:
    body = _fetch_with_retries(feed.url, settings)
    return _judge(feed, body, now)


def check_feed(feed: Feed, settings: Settings, now: datetime) -> FeedResult:
    started = time.monotonic()
    try:
        status, reason, items = _fetch_and_judge(feed, settings, now)
    except Unreachable as exc:
        status, reason, items = STATUS_UNREACHABLE, str(exc), None
    except Unhealthy as exc:
        status, reason, items = STATUS_UNHEALTHY, str(exc), None
    elapsed = time.monotonic() - started
    return FeedResult(feed.name, status, reason, items, elapsed)


def run_checks(config: Config, now: datetime) -> tuple[FeedResult, ...]:
    return tuple(check_feed(feed, config.settings, now) for feed in config.feeds)


def report_of(results: Sequence[FeedResult]) -> dict[str, object]:
    return {
        "healthy": all(result.status == STATUS_HEALTHY for result in results),
        "feeds": [
            {
                "name": result.name,
                "status": result.status,
                "reason": result.reason,
                "items": result.items,
                "elapsed_seconds": result.elapsed_seconds,
            }
            for result in results
        ],
    }


def _write_report(path: Path, report: Mapping[str, object]) -> None:
    text = json.dumps(report, indent="\t") + "\n"
    try:
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot write report {path}: {exc}") from exc


def main(argv: Sequence[str]) -> int:
    if sys.flags.optimize:
        raise SystemExit("do not run with python -O: invariants are asserts")
    parser = argparse.ArgumentParser(prog="feedcheck", description="Check JSON feed health.")
    parser.add_argument("--config", required=True, type=Path, help="TOML file listing the feeds")
    parser.add_argument("--output", required=True, type=Path, help="where to write the JSON report")
    args = parser.parse_args(argv)
    config = _load_or_exit(args.config)
    results = run_checks(config, datetime.now(timezone.utc))
    report = report_of(results)
    _write_report(args.output, report)
    if report["healthy"]:
        return EXIT_OK
    return EXIT_UNHEALTHY


def _load_or_exit(path: Path) -> Config:
    try:
        return load_config(path)
    except ConfigError as exc:
        print(f"feedcheck: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_CONFIG) from exc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
