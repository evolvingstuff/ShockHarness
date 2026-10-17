"""Fetching feeds and deciding whether they are healthy."""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from .config import Config, Feed

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
    items: int | None = None
    duration_seconds: float = 0.0
    attempts: int = 0
    reason: str | None = None
    newest_item: str | None = None

    def to_dict(self) -> dict:
        d = {
            "name": self.name,
            "url": self.url,
            "status": self.status,
            "items": self.items,
            "duration_seconds": round(self.duration_seconds, 3),
            "attempts": self.attempts,
        }
        if self.reason is not None:
            d["reason"] = self.reason
        if self.newest_item is not None:
            d["newest_item"] = self.newest_item
        return d


@dataclass
class _Response:
    status: int | None  # None when the server did not answer
    body: bytes = b""
    error: str | None = None


@dataclass
class Checker:
    config: Config
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], datetime] = field(default=lambda: datetime.now(timezone.utc))

    def check_all(self) -> list[FeedResult]:
        return [self.check(feed) for feed in self.config.feeds]

    def check(self, feed: Feed) -> FeedResult:
        start = time.monotonic()
        response, attempts = self._fetch_with_retries(feed.url)
        result = self._evaluate(feed, response)
        result.attempts = attempts
        result.duration_seconds = time.monotonic() - start
        return result

    def backoff_delay(self, attempt: int) -> float:
        """Delay before the given attempt (1-based); grows with each retry."""
        if attempt <= 1:
            return 0.0
        return self.config.backoff_seconds * (2 ** (attempt - 2))

    def _fetch_with_retries(self, url: str) -> tuple[_Response, int]:
        response = _Response(status=None, error="not attempted")
        for attempt in range(1, self.config.attempts + 1):
            delay = self.backoff_delay(attempt)
            if delay > 0:
                self.sleep(delay)
            response = self._fetch_once(url)
            if response.status is not None and response.status < 500:
                return response, attempt
        return response, self.config.attempts

    def _fetch_once(self, url: str) -> _Response:
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as resp:
                return _Response(status=resp.status, body=resp.read())
        except urllib.error.HTTPError as e:
            try:
                body = e.read()
            except Exception:
                body = b""
            return _Response(status=e.code, body=body)
        except urllib.error.URLError as e:
            reason = e.reason
            if isinstance(reason, (TimeoutError, socket.timeout)):
                return _Response(status=None, error=f"timed out after {self.config.timeout_seconds:g}s")
            return _Response(status=None, error=f"connection failed: {reason}")
        except (TimeoutError, socket.timeout):
            return _Response(status=None, error=f"timed out after {self.config.timeout_seconds:g}s")
        except (ConnectionError, OSError) as e:
            return _Response(status=None, error=f"connection failed: {e}")
        except Exception as e:  # e.g. http.client.IncompleteRead, RemoteDisconnected
            return _Response(status=None, error=f"connection failed: {type(e).__name__}: {e}")

    def _evaluate(self, feed: Feed, response: _Response) -> FeedResult:
        result = FeedResult(name=feed.name, url=feed.url, status=UNHEALTHY)

        if response.status is None:
            result.status = UNREACHABLE
            result.reason = response.error
            return result
        if response.status != 200:
            result.reason = f"HTTP {response.status}"
            return result

        try:
            data = json.loads(response.body)
        except (ValueError, UnicodeDecodeError) as e:
            result.reason = f"response is not valid JSON: {e}"
            return result
        if not isinstance(data, dict):
            result.reason = f"response is a JSON {_json_type(data)}, expected an object"
            return result
        if "items" not in data:
            result.reason = "response has no 'items' field"
            return result
        items = data["items"]
        if not isinstance(items, list):
            result.reason = f"'items' is a JSON {_json_type(items)}, expected a list"
            return result
        result.items = len(items)

        if feed.max_age_hours is not None:
            newest, error = _newest_published(items)
            if error:
                result.reason = error
                return result
            if newest is None:
                result.status = STALE
                result.reason = "feed has no items"
                return result
            result.newest_item = newest.isoformat()
            age = self.now() - newest
            if age > timedelta(hours=feed.max_age_hours):
                hours = age.total_seconds() / 3600
                result.status = STALE
                result.reason = (f"newest item is {hours:.1f} hours old "
                                 f"(max_age_hours = {feed.max_age_hours:g})")
                return result

        result.status = HEALTHY
        return result


def _newest_published(items: list) -> tuple[datetime | None, str | None]:
    newest: datetime | None = None
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            return None, f"item {i} is a JSON {_json_type(item)}, expected an object"
        published = item.get("published")
        if not isinstance(published, str):
            return None, f"item {i} has no 'published' timestamp"
        try:
            when = datetime.fromisoformat(published)
        except ValueError:
            return None, f"item {i} has an invalid 'published' timestamp: {published!r}"
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if newest is None or when > newest:
            newest = when
    return newest, None


def _json_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"
