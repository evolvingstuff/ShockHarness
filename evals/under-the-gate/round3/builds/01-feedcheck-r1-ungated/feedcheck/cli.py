"""Command-line entry point for feedcheck."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .checker import HEALTHY, Checker
from .config import ConfigError, load_config

EXIT_OK = 0
EXIT_UNHEALTHY = 1
EXIT_ERROR = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="feedcheck", description="Check the health of JSON feeds and write a report.")
    parser.add_argument("--config", required=True, help="path to the feeds TOML file")
    parser.add_argument("--output", required=True, help="path to write the JSON report to")
    return parser


def main(argv: list[str] | None = None, checker_factory=Checker) -> int:
    args = build_parser().parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as e:
        print(f"feedcheck: {e}", file=sys.stderr)
        return EXIT_ERROR

    started = datetime.now(timezone.utc)
    results = checker_factory(config).check_all()
    healthy = all(r.status == HEALTHY for r in results)

    report = {
        "checked_at": started.isoformat(),
        "healthy": healthy,
        "summary": _summary(results),
        "feeds": [r.to_dict() for r in results],
    }
    try:
        Path(args.output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except OSError as e:
        print(f"feedcheck: cannot write report to {args.output}: {e.strerror or e}",
              file=sys.stderr)
        return EXIT_ERROR

    for r in results:
        line = f"{r.status:<11} {r.name}"
        if r.reason:
            line += f" ({r.reason})"
        print(line)

    return EXIT_OK if healthy else EXIT_UNHEALTHY


def _summary(results) -> dict:
    counts = {"total": len(results)}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    return counts


if __name__ == "__main__":
    sys.exit(main())
