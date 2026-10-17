"""Fetching feeds and judging their health."""

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
    http_status: int | None
    attempts: int
    duration_seconds: float

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "url": self.url,
            "status": self.status,
            "reason": self.reason,
            "items": self.items,
            "http_status": self.http_status,
            "attempts": self.attempts,
            "duration_seconds": round(self.duration_seconds, 3),
        }


class _NoAnswer(Exception):
    """The server did not answer (connection failure, timeout, broken response)."""


def _fetch_once(url: str, timeout: float) -> tuple[int, bytes]:
    """Return (status, body). Raise _NoAnswer when the server gives no usable answer."""
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        # The server answered, just not with 2xx.
        with exc:
            return exc.code, b""
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, (TimeoutError, socket.timeout)):
            raise _NoAnswer(f"timed out after {timeout:g}s") from None
        raise _NoAnswer(f"connection failed: {reason}") from None
    except (TimeoutError, socket.timeout):
        raise _NoAnswer(f"timed out after {timeout:g}s") from None
    except (http.client.HTTPException, OSError) as exc:
        raise _NoAnswer(f"connection failed: {exc.__class__.__name__}: {exc}".rstrip(": ")) from None


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def evaluate(feed: Feed, status: int, body: bytes, now: datetime) -> tuple[str, str | None, int | None]:
    """Judge a feed's answer. Return (status, reason, item count)."""
    if status != 200:
        return UNHEALTHY, f"HTTP {status}", None

    try:
        document = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return UNHEALTHY, f"response is not valid JSON: {exc}", None
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
        published = item["published"]
        if not isinstance(published, str):
            return UNHEALTHY, f"item {index}: 'published' is not a string", count
        try:
            stamp = _parse_timestamp(published)
        except ValueError:
            return UNHEALTHY, f"item {index}: 'published' is not ISO 8601: {published!r}", count
        if newest is None or stamp > newest:
            newest = stamp

    if newest is None:
        return STALE, "no item has a 'published' date", count
    age = now - newest
    if age > timedelta(hours=feed.max_age_hours):
        hours = age.total_seconds() / 3600
        return (
            STALE,
            f"newest item is {hours:.1f}h old (max {feed.max_age_hours:g}h)",
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
    while True:
        attempt += 1
        if attempt > 1:
            # Exponential backoff: backoff, 2*backoff, 4*backoff, ...
            sleep(config.backoff_seconds * 2 ** (attempt - 2))
        try:
            http_status, body = _fetch_once(feed.url, config.timeout_seconds)
        except _NoAnswer as exc:
            if attempt < config.attempts:
                continue
            return FeedResult(
                name=feed.name,
                url=feed.url,
                status=UNREACHABLE,
                reason=f"{exc} (after {attempt} attempt{'s' if attempt != 1 else ''})",
                items=None,
                http_status=None,
                attempts=attempt,
                duration_seconds=clock() - started,
            )
        if 500 <= http_status <= 599 and attempt < config.attempts:
            continue
        status, reason, count = evaluate(feed, http_status, body, now())
        if status == UNHEALTHY and 500 <= http_status <= 599 and attempt > 1:
            reason = f"{reason} (after {attempt} attempts)"
        return FeedResult(
            name=feed.name,
            url=feed.url,
            status=status,
            reason=reason,
            items=count,
            http_status=http_status,
            attempts=attempt,
            duration_seconds=clock() - started,
        )


def check_all(config: Config, **kwargs) -> list[FeedResult]:
    """Check every feed concurrently; results keep the config order."""
    workers = min(MAX_WORKERS, len(config.feeds))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda feed: check_feed(feed, config, **kwargs), config.feeds))


def build_report(results: list[FeedResult], checked_at: datetime) -> dict:
    summary = {status: 0 for status in (HEALTHY, UNHEALTHY, STALE, UNREACHABLE)}
    for result in results:
        summary[result.status] += 1
    return {
        "checked_at": checked_at.isoformat(timespec="seconds"),
        "all_healthy": all(r.status == HEALTHY for r in results),
        "summary": {"total": len(results), **summary},
        "feeds": [r.to_dict() for r in results],
    }
