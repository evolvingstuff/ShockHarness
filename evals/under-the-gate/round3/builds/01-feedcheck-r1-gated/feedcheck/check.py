"""Check each configured feed, retrying when the server answers 5xx or not at all."""

from __future__ import annotations

import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus

from feedcheck.config import Feed, Settings
from feedcheck.fetch import FeedUnreachable, Response, fetch_once
from feedcheck.health import Status, Verdict, evaluate

FIRST_ATTEMPT = 1


@dataclass(frozen=True)
class NoAnswer:
    """The server did not answer an attempt."""

    reason: str


@dataclass(frozen=True)
class FeedResult:
    feed: Feed
    status: Status
    reason: str | None
    item_count: int | None
    attempts: int
    elapsed_seconds: float


def check_feeds(settings: Settings, opener: urllib.request.OpenerDirector, sleep: Callable[[float], None]) -> tuple[FeedResult, ...]:
    return tuple(check_feed(feed, settings, opener, sleep) for feed in settings.feeds)


def check_feed(feed: Feed, settings: Settings, opener: urllib.request.OpenerDirector, sleep: Callable[[float], None]) -> FeedResult:
    started = time.monotonic()
    outcome, attempts = _fetch_with_retries(feed.url, settings, opener, sleep)
    verdict = _verdict(outcome, feed.max_age_hours)
    elapsed = time.monotonic() - started
    return FeedResult(
        feed=feed,
        status=verdict.status,
        reason=verdict.reason,
        item_count=verdict.item_count,
        attempts=attempts,
        elapsed_seconds=elapsed,
    )


def _fetch_with_retries(
    url: str, settings: Settings, opener: urllib.request.OpenerDirector, sleep: Callable[[float], None]
) -> tuple[Response | NoAnswer, int]:
    """Make up to settings.attempts attempts; the wait before attempt n+1 is n times the backoff."""
    attempt = FIRST_ATTEMPT
    outcome = _attempt(url, settings.timeout_seconds, opener)
    while _worth_retrying(outcome) and attempt < settings.attempts:
        sleep(settings.retry_backoff_seconds * attempt)
        attempt += 1
        outcome = _attempt(url, settings.timeout_seconds, opener)
    return outcome, attempt


def _attempt(url: str, timeout_seconds: float, opener: urllib.request.OpenerDirector) -> Response | NoAnswer:
    # Boundary (declared in .shockharness.toml): a feed that does not answer is an outcome to report.
    try:
        response = fetch_once(opener, url, timeout_seconds)
    except FeedUnreachable as exc:
        return NoAnswer(reason=exc.reason)
    return response


def _worth_retrying(outcome: Response | NoAnswer) -> bool:
    if isinstance(outcome, NoAnswer):
        return True
    return outcome.status >= HTTPStatus.INTERNAL_SERVER_ERROR


def _verdict(outcome: Response | NoAnswer, max_age_hours: float | None) -> Verdict:
    if isinstance(outcome, NoAnswer):
        return Verdict(status=Status.UNREACHABLE, reason=outcome.reason, item_count=None)
    if outcome.status != HTTPStatus.OK:
        return Verdict(status=Status.UNHEALTHY, reason=f"HTTP status {outcome.status}", item_count=None)
    return evaluate(outcome.body, max_age_hours, datetime.now(UTC))
