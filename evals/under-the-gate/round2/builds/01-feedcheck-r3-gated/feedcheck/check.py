"""Decide the health of each feed."""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from feedcheck import http_status
from feedcheck.config import Config, Feed
from feedcheck.fetch import Answer, NoAnswer, fetch_once

HEALTHY = "healthy"
UNHEALTHY = "unhealthy"
UNREACHABLE = "unreachable"
STALE = "stale"
FIRST_ATTEMPT = 1


@dataclass(frozen=True)
class Verdict:
    status: str
    reason: str | None
    items: int | None


@dataclass(frozen=True)
class FeedResult:
    name: str
    url: str
    status: str
    reason: str | None
    items: int | None
    attempts: int
    duration_seconds: float


class _BodyError(Exception):
    """The feed answered 200 but its body is not a healthy feed document."""


def check_all(config: Config, now: datetime, sleep: Callable[[float], None]) -> tuple[FeedResult, ...]:
    """Check every feed in config order. `now` (timezone-aware) is the reference time for staleness."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return tuple(check_feed(feed, config, now, sleep) for feed in config.feeds)


def check_feed(feed: Feed, config: Config, now: datetime, sleep: Callable[[float], None]) -> FeedResult:
    started = time.monotonic()
    outcome, attempts = _fetch_with_retries(feed, config, sleep)
    verdict = _judge(outcome, feed, now)
    return FeedResult(
        name=feed.name,
        url=feed.url,
        status=verdict.status,
        reason=verdict.reason,
        items=verdict.items,
        attempts=attempts,
        duration_seconds=time.monotonic() - started,
    )


def _fetch_with_retries(feed: Feed, config: Config, sleep: Callable[[float], None]) -> tuple[Answer | NoAnswer, int]:
    """Retry a feed that does not answer or answers 5xx; each later attempt waits longer than the one before."""
    attempt = FIRST_ATTEMPT
    outcome = fetch_once(feed.url, config.timeout_seconds)
    while _worth_retrying(outcome) and attempt < config.attempts:
        sleep(config.retry_backoff_seconds * attempt)
        attempt += 1
        outcome = fetch_once(feed.url, config.timeout_seconds)
    return outcome, attempt


def _worth_retrying(outcome: Answer | NoAnswer) -> bool:
    if isinstance(outcome, NoAnswer):
        return True
    return http_status.is_server_error(outcome.status)


def _judge(outcome: Answer | NoAnswer, feed: Feed, now: datetime) -> Verdict:
    if isinstance(outcome, NoAnswer):
        return Verdict(status=UNREACHABLE, reason=outcome.reason, items=None)
    if outcome.status != http_status.OK:
        return Verdict(status=UNHEALTHY, reason=f"HTTP status {outcome.status}", items=None)
    document = _decode(outcome.body)
    if isinstance(document, _BodyError):
        return Verdict(status=UNHEALTHY, reason=str(document), items=None)
    if not isinstance(document, dict):
        return Verdict(status=UNHEALTHY, reason="body is not a JSON object", items=None)
    if "items" not in document or not isinstance(document["items"], list):
        return Verdict(status=UNHEALTHY, reason="body has no 'items' list", items=None)
    items = document["items"]
    if feed.max_age_hours is None:
        return Verdict(status=HEALTHY, reason=None, items=len(items))
    return _judge_freshness(items, timedelta(hours=feed.max_age_hours), now)


def _decode(body: bytes) -> object:
    """The parsed JSON document, or a _BodyError saying why the body is not JSON."""
    # Boundary (declared in .shockharness.toml): one decode of external input.
    try:
        document = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return _BodyError(f"body is not valid JSON: {exc}")
    return document


def _judge_freshness(items: list[object], max_age: timedelta, now: datetime) -> Verdict:
    if not items:
        return Verdict(status=STALE, reason="feed has no items, so no newest item within max_age_hours", items=0)
    published = [_published(item, index) for index, item in enumerate(items)]
    errors = [value for value in published if isinstance(value, _BodyError)]
    if errors:
        return Verdict(status=UNHEALTHY, reason=str(errors[0]), items=len(items))
    newest = max(published)
    age = now - newest
    if age > max_age:
        return Verdict(status=STALE, reason=f"newest item published {newest.isoformat()} is older than {max_age}", items=len(items))
    return Verdict(status=HEALTHY, reason=None, items=len(items))


def _published(item: object, index: int) -> datetime | _BodyError:
    """The item's `published` time; a time without an offset is taken as UTC."""
    if not isinstance(item, dict) or "published" not in item or not isinstance(item["published"], str):
        return _BodyError(f"items[{index}] has no 'published' string")
    text = item["published"]
    # Boundary (declared in .shockharness.toml): one parse of external input.
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        return _BodyError(f"items[{index}] published {text!r} is not ISO 8601: {exc}")
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment
