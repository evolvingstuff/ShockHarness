"""Check one feed: fetch with retries, then judge the answer."""

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from http import HTTPStatus

from feedcheck.config import Config, Feed
from feedcheck.fetch import Answer, NoAnswer, fetch_once

# RFC 9110 section 15: the first digit of a status code is its class; 5xx is 500-599.
SERVER_ERROR_END = 600  # shockharness: ignore[MAGIC001] reason="RFC 9110 section 15.6: 5xx (Server Error) is 500-599"


class Status(StrEnum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNREACHABLE = "unreachable"
    STALE = "stale"


@dataclass(frozen=True)
class FeedResult:
    name: str
    url: str
    status: Status
    reason: str | None
    item_count: int | None
    attempts: int
    elapsed_seconds: float


@dataclass(frozen=True)
class _Verdict:
    status: Status
    reason: str | None
    item_count: int | None


def retry_delay(backoff_seconds: float, attempt_index: int) -> float:
    """Seconds to wait before attempt `attempt_index` (0 is the first, which does not wait)."""
    if attempt_index < 0:
        raise ValueError(f"attempt index must not be negative, got {attempt_index}")
    return backoff_seconds * attempt_index


def is_retryable(outcome: Answer | NoAnswer) -> bool:
    """A feed that does not answer, or answers 5xx, is worth another attempt."""
    if isinstance(outcome, NoAnswer):
        return True
    return HTTPStatus.INTERNAL_SERVER_ERROR <= outcome.status < SERVER_ERROR_END


def check_feed(feed: Feed, config: Config, now: datetime) -> FeedResult:
    """Fetch `feed` (retrying as configured) and judge it; staleness is measured against `now`."""
    started = time.monotonic()
    outcome, attempts = _fetch_with_retries(feed.url, config)
    verdict = _judge(outcome, feed, now)
    return FeedResult(
        name=feed.name,
        url=feed.url,
        status=verdict.status,
        reason=verdict.reason,
        item_count=verdict.item_count,
        attempts=attempts,
        elapsed_seconds=time.monotonic() - started,
    )


def _fetch_with_retries(url: str, config: Config) -> tuple[Answer | NoAnswer, int]:
    outcome = fetch_once(url, config.timeout_seconds)
    attempts = 1
    while is_retryable(outcome) and attempts < config.attempts:
        time.sleep(retry_delay(config.retry_backoff_seconds, attempts))
        outcome = fetch_once(url, config.timeout_seconds)
        attempts += 1
    return outcome, attempts


def _judge(outcome: Answer | NoAnswer, feed: Feed, now: datetime) -> _Verdict:
    if isinstance(outcome, NoAnswer):
        return _Verdict(Status.UNREACHABLE, outcome.reason, None)
    if outcome.status != HTTPStatus.OK:
        return _Verdict(Status.UNHEALTHY, f"HTTP status {outcome.status}", None)
    # Boundary (declared in .shockharness.toml): one decode of external data.
    try:
        document = json.loads(outcome.body)
    except ValueError as exc:
        return _Verdict(Status.UNHEALTHY, f"body is not valid JSON: {exc}", None)
    if not isinstance(document, dict):
        return _Verdict(Status.UNHEALTHY, "body is not a JSON object", None)
    if "items" not in document:
        return _Verdict(Status.UNHEALTHY, "body has no 'items'", None)
    items = document["items"]
    if not isinstance(items, list):
        return _Verdict(Status.UNHEALTHY, "'items' is not a list", None)
    if feed.max_age_hours is None:
        return _Verdict(Status.HEALTHY, None, len(items))
    return _judge_age(items, timedelta(hours=feed.max_age_hours), now)


def _judge_age(items: list[object], max_age: timedelta, now: datetime) -> _Verdict:
    count = len(items)
    if not items:
        return _Verdict(Status.STALE, "feed has no items, so no recent one", count)
    newest = None
    for index, item in enumerate(items):
        published = _published(item, index)
        if isinstance(published, str):
            return _Verdict(Status.UNHEALTHY, published, count)
        if newest is None or published > newest:
            newest = published
    age = now - newest
    if age > max_age:
        return _Verdict(Status.STALE, f"newest item is {age} old, more than {max_age}", count)
    return _Verdict(Status.HEALTHY, None, count)


def _published(item: object, index: int) -> datetime | str:
    """The item's timezone-aware `published` time, or a string saying why it has none."""
    if not isinstance(item, dict) or "published" not in item:
        return f"items[{index}] has no 'published'"
    value = item["published"]
    if not isinstance(value, str):
        return f"items[{index}].published is not a string"
    # Boundary (declared in .shockharness.toml): one parse of external data.
    try:
        published = datetime.fromisoformat(value)
    except ValueError as exc:
        return f"items[{index}].published is not ISO 8601: {exc}"
    if published.tzinfo is None:
        return f"items[{index}].published {value!r} has no timezone"
    return published
