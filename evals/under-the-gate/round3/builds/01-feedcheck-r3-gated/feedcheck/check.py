"""Check every configured feed and write the JSON report."""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from feedcheck.config import Config, FeedConfig
from feedcheck.fetch import fetch_with_retries
from feedcheck.health import Status, Verdict, judge

REPORT_INDENT = "  "


@dataclass(frozen=True)
class FeedResult:
    feed: FeedConfig
    verdict: Verdict
    duration_seconds: float


@dataclass(frozen=True)
class Clocks:
    """Time sources, injected so tests can control them."""

    sleep: Callable[[float], None]
    monotonic: Callable[[], float]
    now: Callable[[], datetime]


def check_feed(feed: FeedConfig, config: Config, clocks: Clocks) -> FeedResult:
    started = clocks.monotonic()
    outcome = fetch_with_retries(
        feed.url,
        timeout_seconds=config.timeout_seconds,
        attempts=config.attempts,
        retry_delay_seconds=config.retry_delay_seconds,
        sleep=clocks.sleep,
    )
    verdict = judge(outcome, feed.max_age_hours, clocks.now())
    return FeedResult(feed=feed, verdict=verdict, duration_seconds=clocks.monotonic() - started)


def check_feeds(config: Config, clocks: Clocks) -> tuple[FeedResult, ...]:
    results = tuple(check_feed(feed, config, clocks) for feed in config.feeds)
    if len(results) != len(config.feeds):
        raise AssertionError(f"checked {len(results)} feeds, configured {len(config.feeds)}")
    return results


def all_healthy(results: Sequence[FeedResult]) -> bool:
    return all(result.verdict.status is Status.HEALTHY for result in results)


def build_report(results: Sequence[FeedResult], checked_at: datetime) -> dict[str, object]:
    return {
        "checked_at": checked_at.isoformat(),
        "healthy": all_healthy(results),
        "feeds": [
            {
                "name": result.feed.name,
                "url": result.feed.url,
                "status": result.verdict.status.value,
                "reason": result.verdict.reason,
                "items": result.verdict.item_count,
                "duration_seconds": result.duration_seconds,
            }
            for result in results
        ],
    }


def write_report(report: dict[str, object], path: Path) -> None:
    path.write_text(json.dumps(report, indent=REPORT_INDENT) + "\n", encoding="utf-8")
