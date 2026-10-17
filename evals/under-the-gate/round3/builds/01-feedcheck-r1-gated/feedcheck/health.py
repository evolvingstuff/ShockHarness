"""Judge a feed's body: a JSON object whose items is a list, fresh enough when required."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class Status(StrEnum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNREACHABLE = "unreachable"
    STALE = "stale"


class InvalidFeed(Exception):
    """The body is not a healthy feed document; `reason` says why."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Verdict:
    status: Status
    reason: str | None
    item_count: int | None


def evaluate(body: bytes, max_age_hours: float | None, now: datetime) -> Verdict:
    """Judge a 200 response body; `now` must be timezone-aware."""
    # Boundary (declared in .shockharness.toml): InvalidFeed is the typed outcome of judging external data.
    try:
        items = feed_items(body)
    except InvalidFeed as exc:
        return Verdict(status=Status.UNHEALTHY, reason=exc.reason, item_count=None)
    try:
        verdict = judge_items(items, max_age_hours, now)
    except InvalidFeed as exc:
        return Verdict(status=Status.UNHEALTHY, reason=exc.reason, item_count=len(items))
    return verdict


def feed_items(body: bytes) -> list[object]:
    document = _decode_json(body)
    if not isinstance(document, dict):
        raise InvalidFeed("body is not a JSON object")
    if "items" not in document:
        raise InvalidFeed("JSON object has no items")
    items = document["items"]
    if not isinstance(items, list):
        raise InvalidFeed(f"items is a {type(items).__name__}, not a list")
    return items


def judge_items(items: list[object], max_age_hours: float | None, now: datetime) -> Verdict:
    count = len(items)
    if max_age_hours is None:
        return Verdict(status=Status.HEALTHY, reason=None, item_count=count)
    if not items:
        return Verdict(status=Status.STALE, reason="feed has no items, so nothing is newer than max_age_hours", item_count=count)
    newest = max(_published(item, index) for index, item in enumerate(items))
    if now - newest > timedelta(hours=max_age_hours):
        reason = f"newest item was published {newest.isoformat()}, more than {max_age_hours} hours ago"
        return Verdict(status=Status.STALE, reason=reason, item_count=count)
    return Verdict(status=Status.HEALTHY, reason=None, item_count=count)


def _decode_json(body: bytes) -> object:
    # Boundary (declared in .shockharness.toml): decoding the external body.
    try:
        document = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidFeed(f"body is not valid JSON: {exc}") from exc
    return document


def _published(item: object, index: int) -> datetime:
    if not isinstance(item, dict) or "published" not in item:
        raise InvalidFeed(f"items[{index}] has no published timestamp")
    value = item["published"]
    if not isinstance(value, str):
        raise InvalidFeed(f"items[{index}].published is not a string")
    stamp = _parse_timestamp(value, index)
    if stamp.tzinfo is None:
        raise InvalidFeed(f"items[{index}].published {value!r} has no UTC offset")
    return stamp


def _parse_timestamp(value: str, index: int) -> datetime:
    # Boundary (declared in .shockharness.toml): parsing an external timestamp.
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError as exc:
        raise InvalidFeed(f"items[{index}].published {value!r} is not ISO 8601") from exc
    return stamp
