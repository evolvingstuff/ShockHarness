"""Build and write the JSON report."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from feedcheck.check import FeedResult
from feedcheck.health import Status

JSON_INDENT = "  "


def all_healthy(results: tuple[FeedResult, ...]) -> bool:
    return all(result.status is Status.HEALTHY for result in results)


def build_report(results: tuple[FeedResult, ...], checked_at: datetime) -> dict[str, object]:
    return {
        "checked_at": checked_at.isoformat(),
        "healthy": all_healthy(results),
        "feeds": [_feed_entry(result) for result in results],
    }


def write_report(path: Path, report: dict[str, object]) -> None:
    path.write_text(json.dumps(report, indent=JSON_INDENT) + "\n", encoding="utf-8")


def _feed_entry(result: FeedResult) -> dict[str, object]:
    return {
        "name": result.feed.name,
        "url": result.feed.url,
        "status": str(result.status),
        "reason": result.reason,
        "items": result.item_count,
        "attempts": result.attempts,
        "elapsed_seconds": result.elapsed_seconds,
    }
