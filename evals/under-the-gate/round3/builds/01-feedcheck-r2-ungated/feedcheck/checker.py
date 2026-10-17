"""Fetching feeds and deciding their health."""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from feedcheck.config import Config, FeedConfig

HEALTHY = "healthy"
UNHEALTHY = "unhealthy"
UNREACHABLE = "unreachable"
STALE = "stale"

USER_AGENT = "feedcheck/1.0"


@dataclass
class FeedResult:
    name: str
    url: str
    status: str
    items: int | None
    duration_seconds: float
    attempts: int
    reason: str | None = None
    http_status: int | None = None
    newest_item: str | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "url": self.url,
            "status": self.status,
            "reason": self.reason,
            "items": self.items,
            "duration_seconds": round(self.duration_seconds, 3),
            "attempts": self.attempts,
            "http_status": self.http_status,
            "newest_item": self.newest_item,
        }


class _Retryable(Exception):
    """A failure worth another attempt: a 5xx answer or no answer at all."""

    def __init__(self, reason: str, http_status: int | None = None):
        super().__init__(reason)
        self.reason = reason
        self.http_status = http_status


def _fetch(url: str, timeout: float) -> tuple[int, bytes]:
    """Return (status, body). Raise _Retryable for 5xx or no answer."""
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        with e:
            if 500 <= e.code <= 599:
                raise _Retryable(f"server error: HTTP {e.code}", e.code) from None
            return e.code, b""
    except urllib.error.URLError as e:
        reason = e.reason
        if isinstance(reason, (TimeoutError, socket.timeout)):
            raise _Retryable(f"timed out after {timeout:g}s") from None
        raise _Retryable(f"connection failed: {reason}") from None
    except (TimeoutError, socket.timeout):
        raise _Retryable(f"timed out after {timeout:g}s") from None
    except (ConnectionError, OSError) as e:
        # Includes connections dropped mid-response (e.g. RemoteDisconnected).
        raise _Retryable(f"connection failed: {e}") from None
    except Exception as e:  # http.client.HTTPException and friends
        raise _Retryable(f"bad response: {e.__class__.__name__}: {e}") from None


def parse_timestamp(value: object) -> datetime | None:
    """Parse an ISO 8601 timestamp; naive values are taken as UTC."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _evaluate(
    feed: FeedConfig, status: int, body: bytes, now: datetime
) -> tuple[str, str | None, int | None, str | None]:
    """Return (status, reason, item_count, newest_item) for an answered request."""
    if status != 200:
        return UNHEALTHY, f"expected HTTP 200, got {status}", None, None
    try:
        doc = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        return UNHEALTHY, f"response is not valid JSON: {e}", None, None
    if not isinstance(doc, dict):
        return UNHEALTHY, "response is not a JSON object", None, None
    if "items" not in doc:
        return UNHEALTHY, "response has no 'items'", None, None
    items = doc["items"]
    if not isinstance(items, list):
        return UNHEALTHY, "'items' is not a list", None, None

    count = len(items)
    if feed.max_age_hours is None:
        return HEALTHY, None, count, None
    if not items:
        return STALE, "feed has no items", count, None

    newest: datetime | None = None
    for i, item in enumerate(items):
        raw = item.get("published") if isinstance(item, dict) else None
        ts = parse_timestamp(raw)
        if ts is None:
            return (
                UNHEALTHY,
                f"item {i} has no valid ISO 8601 'published' timestamp",
                count,
                None,
            )
        if newest is None or ts > newest:
            newest = ts
    assert newest is not None
    newest_text = newest.isoformat()
    age = now - newest
    if age > timedelta(hours=feed.max_age_hours):
        hours = age.total_seconds() / 3600
        return (
            STALE,
            f"newest item is {hours:.1f}h old (max {feed.max_age_hours:g}h)",
            count,
            newest_text,
        )
    return HEALTHY, None, count, newest_text


def check_feed(
    feed: FeedConfig,
    config: Config,
    *,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> FeedResult:
    start = time.monotonic()
    last: _Retryable | None = None
    attempt = 0
    for attempt in range(1, config.attempts + 1):
        if attempt > 1:
            # Wait a little longer before each retry: b, 2b, 4b, ...
            sleep(config.backoff_seconds * 2 ** (attempt - 2))
        try:
            http_status, body = _fetch(feed.url, config.timeout_seconds)
        except _Retryable as e:
            last = e
            continue
        status, reason, count, newest = _evaluate(feed, http_status, body, now())
        return FeedResult(
            name=feed.name,
            url=feed.url,
            status=status,
            reason=reason,
            items=count,
            duration_seconds=time.monotonic() - start,
            attempts=attempt,
            http_status=http_status,
            newest_item=newest,
        )

    assert last is not None
    suffix = "attempt" if attempt == 1 else "attempts"
    # A server that keeps answering 5xx did answer: it is up but unhealthy.
    status = UNHEALTHY if last.http_status is not None else UNREACHABLE
    return FeedResult(
        name=feed.name,
        url=feed.url,
        status=status,
        reason=f"{last.reason} (after {attempt} {suffix})",
        items=None,
        duration_seconds=time.monotonic() - start,
        attempts=attempt,
        http_status=last.http_status,
    )


def check_feeds(config: Config, **kwargs) -> list[FeedResult]:
    return [check_feed(feed, config, **kwargs) for feed in config.feeds]
