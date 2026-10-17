"""Write the feedcheck report as JSON."""

import json
from datetime import datetime
from pathlib import Path

from feedcheck.check import HEALTHY, FeedResult


def all_healthy(results: tuple[FeedResult, ...]) -> bool:
    return all(result.status == HEALTHY for result in results)


def build_report(results: tuple[FeedResult, ...], checked_at: datetime) -> dict[str, object]:
    return {
        "checked_at": checked_at.isoformat(),
        "healthy": all_healthy(results),
        "feeds": [
            {
                "name": result.name,
                "url": result.url,
                "status": result.status,
                "reason": result.reason,
                "items": result.items,
                "attempts": result.attempts,
                "duration_seconds": result.duration_seconds,
            }
            for result in results
        ],
    }


def write_report(report: dict[str, object], output: Path) -> None:
    output.write_text(json.dumps(report, indent="  ") + "\n", encoding="utf-8")
