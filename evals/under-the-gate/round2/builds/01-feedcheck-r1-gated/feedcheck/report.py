"""Check every configured feed and write the JSON report."""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from feedcheck.config import Config, Feed
from feedcheck.fetch import RetryPolicy, fetch
from feedcheck.health import Status, Verdict, evaluate

REPORT_INDENT = "  "


@dataclass(frozen=True)
class FeedResult:
    feed: Feed
    verdict: Verdict
    duration_seconds: float


def check_feeds(config: Config, sleep: Callable[[float], None]) -> tuple[FeedResult, ...]:
    policy = RetryPolicy(
        timeout_seconds=config.timeout_seconds,
        attempts=config.attempts,
        retry_backoff_seconds=config.retry_backoff_seconds,
    )
    return tuple(check_feed(feed, policy, sleep) for feed in config.feeds)


def check_feed(feed: Feed, policy: RetryPolicy, sleep: Callable[[float], None]) -> FeedResult:
    started = time.monotonic()
    outcome = fetch(feed.url, policy, sleep)
    verdict = evaluate(outcome, feed.max_age_hours, datetime.now(UTC))
    return FeedResult(feed=feed, verdict=verdict, duration_seconds=time.monotonic() - started)


def all_healthy(results: tuple[FeedResult, ...]) -> bool:
    return all(result.verdict.status is Status.HEALTHY for result in results)


def write_report(path: Path, results: tuple[FeedResult, ...]) -> None:
    report = {
        "healthy": all_healthy(results),
        "feeds": [_feed_entry(result) for result in results],
    }
    path.write_text(json.dumps(report, indent=REPORT_INDENT) + "\n", encoding="utf-8")


def _feed_entry(result: FeedResult) -> dict[str, object]:
    return {
        "name": result.feed.name,
        "url": result.feed.url,
        "status": str(result.verdict.status),
        "reason": result.verdict.reason,
        "items": result.verdict.item_count,
        "duration_seconds": result.duration_seconds,
    }
