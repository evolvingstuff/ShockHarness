"""Judge a fetch outcome: healthy, unhealthy (with reason), unreachable or stale."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from http import HTTPStatus

from feedcheck.fetch import Answer, NoAnswer


class Status(StrEnum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNREACHABLE = "unreachable"
    STALE = "stale"


@dataclass(frozen=True)
class Verdict:
    """`reason` is None exactly when the feed is healthy; `item_count` is None when no item list was read."""

    status: Status
    reason: str | None
    item_count: int | None


@dataclass(frozen=True)
class _Problem:
    reason: str


def judge(outcome: Answer | NoAnswer, max_age_hours: float | None, now: datetime) -> Verdict:
    """Classify `outcome`; staleness is only judged when `max_age_hours` is set, relative to `now`."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if isinstance(outcome, NoAnswer):
        return Verdict(status=Status.UNREACHABLE, reason=outcome.reason, item_count=None)
    if outcome.status != HTTPStatus.OK:
        return _unhealthy(f"HTTP status {outcome.status}, expected {HTTPStatus.OK.value}")
    items = _read_items(outcome.body)
    if isinstance(items, _Problem):
        return _unhealthy(items.reason)
    if max_age_hours is None:
        return Verdict(status=Status.HEALTHY, reason=None, item_count=len(items))
    return _judge_age(items, max_age_hours, now)


def _read_items(body: bytes) -> list[object] | _Problem:
    # Boundary (declared in .shockharness.toml): decoding the external JSON body.
    try:
        document = json.loads(body)
    except ValueError as exc:
        return _Problem(reason=f"body is not valid JSON: {exc}")
    if not isinstance(document, dict):
        return _Problem(reason=f"body is a JSON {type(document).__name__}, expected an object")
    if "items" not in document:
        return _Problem(reason="body has no 'items'")
    items = document["items"]
    if not isinstance(items, list):
        return _Problem(reason=f"'items' is a JSON {type(items).__name__}, expected a list")
    return items


def _judge_age(items: list[object], max_age_hours: float, now: datetime) -> Verdict:
    if not items:
        return Verdict(status=Status.STALE, reason="feed has no items to date", item_count=0)
    newest = _newest_published(items)
    if isinstance(newest, _Problem):
        return Verdict(status=Status.UNHEALTHY, reason=newest.reason, item_count=len(items))
    age = now - newest
    if age > timedelta(hours=max_age_hours):
        hours = age / timedelta(hours=1)
        reason = f"newest item published {newest.isoformat()} is {hours:.1f} hours old, max_age_hours is {max_age_hours:g}"
        return Verdict(status=Status.STALE, reason=reason, item_count=len(items))
    return Verdict(status=Status.HEALTHY, reason=None, item_count=len(items))


def _newest_published(items: list[object]) -> datetime | _Problem:
    newest: datetime | None = None
    for index, item in enumerate(items):
        published = _published(item, index)
        if isinstance(published, _Problem):
            return published
        if newest is None or published > newest:
            newest = published
    assert newest is not None, "a non-empty item list yields a newest timestamp"
    return newest


def _published(item: object, index: int) -> datetime | _Problem:
    if not isinstance(item, dict) or "published" not in item:
        return _Problem(reason=f"item {index} has no 'published'")
    value = item["published"]
    if not isinstance(value, str):
        return _Problem(reason=f"item {index}: 'published' is not a string")
    # Boundary (declared in .shockharness.toml): parsing an external timestamp.
    try:
        published = datetime.fromisoformat(value)
    except ValueError as exc:
        return _Problem(reason=f"item {index}: 'published' is not ISO 8601: {exc}")
    if published.tzinfo is None:
        return _Problem(reason=f"item {index}: 'published' {value!r} has no time zone")
    return published


def _unhealthy(reason: str) -> Verdict:
    return Verdict(status=Status.UNHEALTHY, reason=reason, item_count=None)
