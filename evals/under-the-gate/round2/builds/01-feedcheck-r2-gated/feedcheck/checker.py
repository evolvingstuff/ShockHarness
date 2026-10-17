"""Check every configured feed and build the report."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from feedcheck.config import Config, Feed
from feedcheck.health import Status, Verdict, judge
from feedcheck.http_fetch import fetch


@dataclass(frozen=True)
class FeedResult:
    feed: Feed
    verdict: Verdict
    duration_seconds: float


@dataclass(frozen=True)
class Report:
    checked_at: datetime
    results: tuple[FeedResult, ...]

    @property
    def all_healthy(self) -> bool:
        return all(result.verdict.status is Status.HEALTHY for result in self.results)

    def to_json(self) -> dict[str, object]:
        return {
            "checked_at": self.checked_at.isoformat(),
            "all_healthy": self.all_healthy,
            "feeds": [
                {
                    "name": result.feed.name,
                    "url": result.feed.url,
                    "status": str(result.verdict.status),
                    "reason": result.verdict.reason,
                    "items": result.verdict.item_count,
                    "duration_seconds": result.duration_seconds,
                }
                for result in self.results
            ],
        }


def check_all(config: Config, sleep: Callable[[float], None]) -> Report:
    checked_at = datetime.now(UTC)
    results = tuple(check_feed(feed, config, sleep) for feed in config.feeds)
    if len(results) != len(config.feeds):
        raise AssertionError("the report must list every configured feed")
    return Report(checked_at=checked_at, results=results)


def check_feed(feed: Feed, config: Config, sleep: Callable[[float], None]) -> FeedResult:
    started = time.monotonic()
    outcome = fetch(feed.url, config.retry, sleep)
    verdict = judge(feed, outcome, datetime.now(UTC))
    return FeedResult(feed=feed, verdict=verdict, duration_seconds=time.monotonic() - started)
