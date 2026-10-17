"""Fetching feeds and deciding whether they are healthy."""

from __future__ import annotations

import http.client
import json
import socket
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from feedcheck import __version__
from feedcheck.config import Config, Feed

HEALTHY = "healthy"
UNHEALTHY = "unhealthy"
UNREACHABLE = "unreachable"
STALE = "stale"

USER_AGENT = f"feedcheck/{__version__}"
MAX_WORKERS = 8


@dataclass
class FeedResult:
    name: str
    url: str
    status: str
    reason: str | None
    items: int | None
    duration_seconds: float
    attempts: int

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "url": self.url,
            "status": self.status,
            "reason": self.reason,
            "items": self.items,
            "duration_seconds": round(self.duration_seconds, 3),
            "attempts": self.attempts,
        }


class _Unreachable(Exception):
    """The server did not answer (connection failed, timed out, dropped)."""


@dataclass
class _Response:
    status: int
    body: bytes


def _fetch_once(url: str, timeout: float) -> _Response:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return _Response(response.status, response.read())
    except urllib.error.HTTPError as exc:
        # The server answered, just not with 2xx. The body is irrelevant.
        exc.close()
        return _Response(exc.code, b"")
    except urllib.error.URLError as exc:
        raise _Unreachable(_describe_network_error(exc.reason)) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise _Unreachable(f"timed out after {timeout:g}s") from exc
    except (OSError, http.client.HTTPException) as exc:
        raise _Unreachable(_describe_network_error(exc)) from exc


def _describe_network_error(reason: object) -> str:
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return "timed out"
    if isinstance(reason, BaseException):
        return str(reason) or type(reason).__name__
    return str(reason)


def parse_timestamp(value: object) -> datetime | None:
    """Parse an ISO 8601 timestamp; naive values are taken as UTC."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def evaluate_body(body: bytes, feed: Feed, now: datetime) -> tuple[str, str | None, int | None]:
    """Judge a 200 response body. Returns (status, reason, item count)."""
    try:
        document = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return UNHEALTHY, "response is not valid JSON", None
    if not isinstance(document, dict):
        return UNHEALTHY, f"response is a JSON {type(document).__name__}, not an object", None
    if "items" not in document:
        return UNHEALTHY, "response has no 'items' field", None
    items = document["items"]
    if not isinstance(items, list):
        return UNHEALTHY, "'items' is not a list", None

    count = len(items)
    if feed.max_age_hours is None:
        return HEALTHY, None, count

    newest: datetime | None = None
    for index, item in enumerate(items):
        if not isinstance(item, dict) or "published" not in item:
            continue
        published = parse_timestamp(item["published"])
        if published is None:
            return (
                UNHEALTHY,
                f"item {index} has an invalid 'published' timestamp: {item['published']!r}",
                count,
            )
        if newest is None or published > newest:
            newest = published

    if newest is None:
        if count == 0:
            return STALE, "feed has no items", count
        return UNHEALTHY, "no item has a 'published' timestamp to check age against", count

    age = now - newest
    if age > timedelta(hours=feed.max_age_hours):
        hours = age.total_seconds() / 3600
        return (
            STALE,
            f"newest item is {hours:.1f}h old (max_age_hours = {feed.max_age_hours:g})",
            count,
        )
    return HEALTHY, None, count


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
    status, reason, items = UNREACHABLE, None, None

    while attempt < config.attempts:
        if attempt > 0:
            # Each retry waits twice as long as the one before it.
            sleep(config.backoff_seconds * 2 ** (attempt - 1))
        attempt += 1
        try:
            response = _fetch_once(feed.url, config.timeout_seconds)
        except _Unreachable as exc:
            status, reason, items = UNREACHABLE, str(exc), None
            continue

        if 500 <= response.status <= 599:
            status, reason, items = UNHEALTHY, f"HTTP {response.status}", None
            continue
        if response.status != 200:
            status, reason, items = UNHEALTHY, f"HTTP {response.status}", None
            break
        status, reason, items = evaluate_body(response.body, feed, now())
        break
    else:
        if config.attempts > 1:
            reason = f"{reason} (after {attempt} attempts)"

    return FeedResult(
        name=feed.name,
        url=feed.url,
        status=status,
        reason=reason,
        items=items,
        duration_seconds=clock() - started,
        attempts=attempt,
    )


def check_all(config: Config, **kwargs) -> list[FeedResult]:
    """Check every feed (concurrently), returning results in config order."""
    workers = min(MAX_WORKERS, len(config.feeds))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda feed: check_feed(feed, config, **kwargs), config.feeds))


def build_report(results: list[FeedResult], checked_at: datetime) -> dict:
    counts = {HEALTHY: 0, UNHEALTHY: 0, UNREACHABLE: 0, STALE: 0}
    for result in results:
        counts[result.status] += 1
    return {
        "checked_at": checked_at.isoformat(timespec="seconds"),
        "healthy": counts[HEALTHY] == len(results),
        "summary": {"total": len(results), **counts},
        "feeds": [result.to_dict() for result in results],
    }
