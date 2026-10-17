"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

from feedcheck.checker import HEALTHY, check_feeds
from feedcheck.config import ConfigError, load_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="feedcheck", description="Check whether a set of JSON feeds is healthy."
    )
    parser.add_argument("--config", required=True, help="path to the TOML config file")
    parser.add_argument("--output", required=True, help="path to write the JSON report")
    return parser


def write_report(path: str, report: dict) -> None:
    """Write atomically so a failed run never leaves a half-written report."""
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".feedcheck-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as e:
        print(f"feedcheck: error: {e}", file=sys.stderr)
        return 2

    checked_at = datetime.now(timezone.utc)
    results = check_feeds(config)
    all_healthy = all(r.status == HEALTHY for r in results)
    summary: dict[str, int] = {}
    for r in results:
        summary[r.status] = summary.get(r.status, 0) + 1
    report = {
        "checked_at": checked_at.isoformat(),
        "healthy": all_healthy,
        "summary": summary,
        "feeds": [r.to_dict() for r in results],
    }
    try:
        write_report(args.output, report)
    except OSError as e:
        print(f"feedcheck: error: cannot write report {args.output}: {e}", file=sys.stderr)
        return 2

    for r in results:
        line = f"{r.status:<11} {r.name}"
        if r.reason:
            line += f" - {r.reason}"
        print(line)
    return 0 if all_healthy else 1


if __name__ == "__main__":
    sys.exit(main())
