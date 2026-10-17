"""Fetching a feed and judging its health."""

from __future__ import annotations

import http.client
import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from feedcheck import __version__
from feedcheck.config import Config, Feed

HEALTHY = "healthy"
UNHEALTHY = "unhealthy"
UNREACHABLE = "unreachable"
STALE = "stale"

MAX_BODY_BYTES = 10 * 1024 * 1024
_CHUNK = 64 * 1024


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


class _Retryable(Exception):
    """The server answered 5xx or did not answer at all."""

    def __init__(self, status: str, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


class _Final(Exception):
    """A definitive (non-retryable) failure."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _fetch(url: str, timeout: float) -> bytes:
    """Return the body of a 200 response, or raise _Retryable / _Final."""
    deadline = time.monotonic() + timeout
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": f"feedcheck/{__version__}",
        },
    )
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        exc.close()
        if 500 <= exc.code <= 599:
            raise _Retryable(UNHEALTHY, f"HTTP {exc.code}") from None
        raise _Final(f"HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, (TimeoutError, socket.timeout)):
            raise _Retryable(UNREACHABLE, f"timed out after {timeout:g}s") from None
        raise _Retryable(UNREACHABLE, f"connection failed: {reason}") from None
    except (TimeoutError, socket.timeout):
        raise _Retryable(UNREACHABLE, f"timed out after {timeout:g}s") from None
    except (ConnectionError, http.client.HTTPException, OSError) as exc:
        raise _Retryable(UNREACHABLE, f"connection failed: {exc}") from None

    with response:
        status = response.status
        if status != 200:
            # urlopen only returns non-error codes here (e.g. 204, 3xx it
            # could not follow); none of them is a healthy answer.
            raise _Final(f"HTTP {status}")
        chunks: list[bytes] = []
        size = 0
        try:
            while True:
                if time.monotonic() > deadline:
                    raise _Retryable(UNREACHABLE, f"timed out after {timeout:g}s")
                chunk = response.read(_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_BODY_BYTES:
                    raise _Final(f"response body larger than {MAX_BODY_BYTES} bytes")
                chunks.append(chunk)
        except (TimeoutError, socket.timeout):
            raise _Retryable(UNREACHABLE, f"timed out after {timeout:g}s") from None
        except (ConnectionError, http.client.HTTPException, OSError) as exc:
            raise _Retryable(UNREACHABLE, f"connection dropped while reading: {exc}") from None
        return b"".join(chunks)


def _parse_published(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    # Python 3.11's fromisoformat accepts "Z", but be explicit for clarity.
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def evaluate(body: bytes, feed: Feed, now: datetime) -> tuple[str, str | None, int | None]:
    """Judge a 200 response body. Returns (status, reason, item_count)."""
    try:
        document = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        return UNHEALTHY, f"response is not valid JSON: {exc}", None
    if not isinstance(document, dict):
        return UNHEALTHY, "response is not a JSON object", None
    if "items" not in document:
        return UNHEALTHY, "response has no 'items' field", None
    items = document["items"]
    if not isinstance(items, list):
        return UNHEALTHY, "'items' is not a list", None
    count = len(items)

    if feed.max_age_hours is None:
        return HEALTHY, None, count

    newest: datetime | None = None
    for item in items:
        published = _parse_published(item.get("published")) if isinstance(item, dict) else None
        if published is not None and (newest is None or published > newest):
            newest = published
    if newest is None:
        if not items:
            return STALE, "feed has no items", count
        return STALE, "no item has a valid 'published' timestamp", count

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
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> FeedResult:
    started = time.monotonic()
    attempt = 0
    status, reason, items = UNREACHABLE, None, None
    while attempt < config.attempts:
        if attempt > 0:
            # Wait a little longer before each further attempt.
            sleep(config.backoff_seconds * (2 ** (attempt - 1)))
        attempt += 1
        try:
            body = _fetch(feed.url, config.timeout_seconds)
        except _Retryable as exc:
            status, reason, items = exc.status, exc.reason, None
            continue
        except _Final as exc:
            status, reason, items = UNHEALTHY, exc.reason, None
            break
        status, reason, items = evaluate(body, feed, now())
        break

    if status in (UNHEALTHY, UNREACHABLE) and attempt > 1 and reason:
        reason = f"{reason} (after {attempt} attempts)"
    return FeedResult(
        name=feed.name,
        url=feed.url,
        status=status,
        reason=reason,
        items=items,
        duration_seconds=time.monotonic() - started,
        attempts=attempt,
    )


def check_all(config: Config, **kwargs) -> list[FeedResult]:
    return [check_feed(feed, config, **kwargs) for feed in config.feeds]
