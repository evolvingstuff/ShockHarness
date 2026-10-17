"""Decide whether a fetched feed is healthy, unhealthy, stale or unreachable."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from http import HTTPStatus

from feedcheck.fetch import Answer, NoAnswer


class Status(StrEnum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    STALE = "stale"
    UNREACHABLE = "unreachable"


@dataclass(frozen=True)
class Verdict:
    status: Status
    reason: str | None
    item_count: int | None


@dataclass(frozen=True)
class Problem:
    reason: str


def evaluate(outcome: Answer | NoAnswer, max_age_hours: float | None, now: datetime) -> Verdict:
    """Judge one fetch outcome; now must be timezone-aware."""
    if isinstance(outcome, NoAnswer):
        return Verdict(status=Status.UNREACHABLE, reason=outcome.reason, item_count=None)
    if outcome.status != HTTPStatus.OK:
        return _unhealthy(f"HTTP status {outcome.status}", item_count=None)
    document = _parse_json(outcome.body)
    if isinstance(document, Problem):
        return _unhealthy(document.reason, item_count=None)
    if not isinstance(document, dict):
        return _unhealthy(f"body is a JSON {type(document).__name__}, not an object", item_count=None)
    if "items" not in document:
        return _unhealthy("body has no 'items'", item_count=None)
    items = document["items"]
    if not isinstance(items, list):
        return _unhealthy(f"'items' is a JSON {type(items).__name__}, not a list", item_count=None)
    if max_age_hours is None:
        return Verdict(status=Status.HEALTHY, reason=None, item_count=len(items))
    return _freshness(items, max_age_hours, now)


def _freshness(items: list[object], max_age_hours: float, now: datetime) -> Verdict:
    newest = _newest_published(items)
    if isinstance(newest, Problem):
        return _unhealthy(newest.reason, item_count=len(items))
    if newest is None:
        return Verdict(status=Status.STALE, reason="feed has no items", item_count=len(items))
    if now - newest > timedelta(hours=max_age_hours):
        reason = f"newest item published {newest.isoformat()}, older than {max_age_hours:g} hours"
        return Verdict(status=Status.STALE, reason=reason, item_count=len(items))
    return Verdict(status=Status.HEALTHY, reason=None, item_count=len(items))


def _newest_published(items: list[object]) -> datetime | None | Problem:
    """The latest 'published' time among items, None for no items, or the first problem found."""
    newest = None
    for index, item in enumerate(items):
        if not isinstance(item, dict) or "published" not in item or not isinstance(item["published"], str):
            return Problem(reason=f"items[{index}] has no 'published' string")
        published = _parse_timestamp(item["published"])
        if isinstance(published, Problem):
            return Problem(reason=f"items[{index}]: {published.reason}")
        if newest is None or published > newest:
            newest = published
    return newest


def _parse_json(body: bytes) -> object:
    # Boundary (declared in .shockharness.toml): one decode of external input.
    try:
        document = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return Problem(reason=f"body is not valid JSON: {exc}")
    return document


def _parse_timestamp(text: str) -> datetime | Problem:
    # Boundary (declared in .shockharness.toml): one parse of an external timestamp.
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        return Problem(reason=f"'published' is not ISO 8601: {exc}")
    if moment.tzinfo is None:
        return Problem(reason=f"'published' {text!r} has no timezone")
    return moment


def _unhealthy(reason: str, item_count: int | None) -> Verdict:
    return Verdict(status=Status.UNHEALTHY, reason=reason, item_count=item_count)
