"""Build the JSON report."""

from collections.abc import Sequence
from datetime import datetime

from feedcheck.check import FeedResult, Status


def all_healthy(results: Sequence[FeedResult]) -> bool:
    return all(result.status is Status.HEALTHY for result in results)


def build_report(results: Sequence[FeedResult], checked_at: datetime) -> dict[str, object]:
    return {
        "checked_at": checked_at.isoformat(),
        "healthy": all_healthy(results),
        "feeds": [
            {
                "name": result.name,
                "url": result.url,
                "status": str(result.status),
                "reason": result.reason,
                "items": result.item_count,
                "attempts": result.attempts,
                "elapsed_seconds": result.elapsed_seconds,
            }
            for result in results
        ],
    }
