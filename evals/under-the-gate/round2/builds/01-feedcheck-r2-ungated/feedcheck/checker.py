"""Fetching feeds and judging their health."""

from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from feedcheck.config import Config, Feed

HEALTHY = "healthy"
UNHEALTHY = "unhealthy"
UNREACHABLE = "unreachable"
STALE = "stale"

# Refuse to buffer absurdly large responses.
MAX_BODY_BYTES = 10 * 1024 * 1024
USER_AGENT = "feedcheck/0.1"


@dataclass
class FeedResult:
    name: str
    url: str
    status: str
    item_count: int | None
    duration_seconds: float
    attempts: int
    reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "url": self.url,
            "status": self.status,
            "reason": self.reason,
            "item_count": self.item_count,
            "duration_seconds": round(self.duration_seconds, 3),
            "attempts": self.attempts,
        }


class _Retryable(Exception):
    """A failure worth another attempt (5xx or no answer)."""

    def __init__(self, reason: str, answered: bool):
        super().__init__(reason)
        self.reason = reason
        self.answered = answered


class _Final(Exception):
    """A failure that another attempt will not fix."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _fetch_once(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            body = response.read(MAX_BODY_BYTES + 1)
    except urllib.error.HTTPError as exc:
        exc.close()
        if 500 <= exc.code <= 599:
            raise _Retryable(f"HTTP {exc.code}", answered=True) from None
        raise _Final(f"HTTP {exc.code}") from None
    except (TimeoutError, urllib.error.URLError, http.client.HTTPException, OSError) as exc:
        raise _Retryable(_describe_network_error(exc, timeout), answered=False) from None

    if status != 200:
        raise _Final(f"HTTP {status} (expected 200)")
    if len(body) > MAX_BODY_BYTES:
        raise _Final(f"response larger than {MAX_BODY_BYTES} bytes")
    return body


def _describe_network_error(exc: BaseException, timeout: float) -> str:
    if isinstance(exc, urllib.error.URLError) and not isinstance(exc.reason, str):
        exc = exc.reason
    if isinstance(exc, TimeoutError):
        return f"timed out after {timeout:g}s"
    if isinstance(exc, urllib.error.URLError):
        return f"connection failed: {exc.reason}"
    return f"connection failed: {exc}"


def _parse_published(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError
    parsed = datetime.fromisoformat(value.strip())
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _judge(body: bytes, feed: Feed, now: datetime) -> tuple[str, int | None, str | None]:
    try:
        document = json.loads(body.decode("utf-8-sig"))
    except UnicodeDecodeError:
        return UNHEALTHY, None, "response is not valid UTF-8"
    except json.JSONDecodeError as exc:
        return UNHEALTHY, None, f"response is not valid JSON: {exc.msg}"
    if not isinstance(document, dict):
        return UNHEALTHY, None, "response is not a JSON object"
    if "items" not in document:
        return UNHEALTHY, None, "response has no 'items'"
    items = document["items"]
    if not isinstance(items, list):
        return UNHEALTHY, None, "'items' is not a list"

    count = len(items)
    if feed.max_age_hours is None:
        return HEALTHY, count, None

    newest: datetime | None = None
    for index, item in enumerate(items):
        if not isinstance(item, dict) or "published" not in item:
            continue
        try:
            published = _parse_published(item["published"])
        except ValueError:
            return UNHEALTHY, count, (
                f"item {index} has an invalid 'published' date: {item['published']!r}"
            )
        if newest is None or published > newest:
            newest = published

    if newest is None:
        return STALE, count, "no item has a 'published' date"
    age = now - newest
    if age > timedelta(hours=feed.max_age_hours):
        hours = age.total_seconds() / 3600
        return STALE, count, (
            f"newest item is {hours:.1f}h old (max {feed.max_age_hours:g}h)"
        )
    return HEALTHY, count, None


def check_feed(
    feed: Feed,
    config: Config,
    *,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> FeedResult:
    started = clock()
    attempt = 0
    while True:
        attempt += 1
        try:
            body = _fetch_once(feed.url, config.timeout_seconds)
        except _Final as exc:
            status, count, reason = UNHEALTHY, None, exc.reason
            break
        except _Retryable as exc:
            if attempt < config.attempts:
                # Each retry waits longer than the one before.
                sleep(config.backoff_seconds * (2 ** (attempt - 1)))
                continue
            status = UNHEALTHY if exc.answered else UNREACHABLE
            count = None
            reason = exc.reason
            if attempt > 1:
                reason = f"{reason} (after {attempt} attempts)"
            break
        else:
            status, count, reason = _judge(body, feed, now())
            break

    return FeedResult(
        name=feed.name,
        url=feed.url,
        status=status,
        item_count=count,
        duration_seconds=clock() - started,
        attempts=attempt,
        reason=reason,
    )


def check_all(config: Config, **kwargs) -> list[FeedResult]:
    return [check_feed(feed, config, **kwargs) for feed in config.feeds]
