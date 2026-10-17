"""Judge a feed's health from the outcome of fetching it."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from http import HTTPStatus

from feedcheck.config import Feed
from feedcheck.http_fetch import Answer, NoAnswer


class Status(StrEnum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNREACHABLE = "unreachable"
    STALE = "stale"


@dataclass(frozen=True)
class Verdict:
    """A feed's status; ``reason`` is None only when healthy, ``item_count`` None when no item list was read."""

    status: Status
    reason: str | None
    item_count: int | None


@dataclass(frozen=True)
class _Problem:
    reason: str


def judge(feed: Feed, outcome: Answer | NoAnswer, now: datetime) -> Verdict:
    """Classify ``outcome`` for ``feed``; ``now`` must be timezone-aware."""
    if isinstance(outcome, NoAnswer):
        return Verdict(Status.UNREACHABLE, f"{outcome.reason} (after {outcome.attempts} attempt(s))", None)
    if outcome.status != HTTPStatus.OK:
        return Verdict(Status.UNHEALTHY, _status_reason(outcome), None)
    document = _parse_json(outcome.body)
    if isinstance(document, _Problem):
        return Verdict(Status.UNHEALTHY, document.reason, None)
    if not isinstance(document, dict):
        return Verdict(Status.UNHEALTHY, f"body is a JSON {type(document).__name__}, not an object", None)
    if "items" not in document:
        return Verdict(Status.UNHEALTHY, "body has no 'items'", None)
    items = document["items"]
    if not isinstance(items, list):
        return Verdict(Status.UNHEALTHY, f"'items' is a {type(items).__name__}, not a list", None)
    if feed.max_age_hours is None:
        return Verdict(Status.HEALTHY, None, len(items))
    return _judge_freshness(items, timedelta(hours=feed.max_age_hours), now)


def _status_reason(answer: Answer) -> str:
    if answer.attempts > 1:
        return f"HTTP {answer.status} (after {answer.attempts} attempts)"
    return f"HTTP {answer.status}"


def _judge_freshness(items: list[object], max_age: timedelta, now: datetime) -> Verdict:
    count = len(items)
    if not items:
        return Verdict(Status.STALE, "no items, so no item is newer than the maximum age", count)
    newest: datetime | None = None
    for index, item in enumerate(items):
        published = _published(item, index)
        if isinstance(published, _Problem):
            return Verdict(Status.UNHEALTHY, published.reason, count)
        if newest is None or published > newest:
            newest = published
    age = now - newest
    if age > max_age:
        return Verdict(Status.STALE, f"newest item published {newest.isoformat()} is older than {max_age}", count)
    return Verdict(Status.HEALTHY, None, count)


def _published(item: object, index: int) -> datetime | _Problem:
    where = f"items[{index}]"
    if not isinstance(item, dict) or "published" not in item:
        return _Problem(f"{where} has no 'published'")
    raw = item["published"]
    if not isinstance(raw, str):
        return _Problem(f"{where}.published is not a string")
    published = _parse_timestamp(raw)
    if isinstance(published, _Problem):
        return _Problem(f"{where}.published: {published.reason}")
    if published.tzinfo is None:
        return _Problem(f"{where}.published {raw!r} has no timezone offset")
    return published


def _parse_json(body: bytes) -> object | _Problem:
    # Boundary (declared in .shockharness.toml): parsing an external body.
    try:
        document = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return _Problem(f"body is not valid JSON: {exc}")
    return document


def _parse_timestamp(raw: str) -> datetime | _Problem:
    # Boundary (declared in .shockharness.toml): parsing an external timestamp.
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        return _Problem(f"{raw!r} is not an ISO 8601 timestamp: {exc}")
    return parsed
