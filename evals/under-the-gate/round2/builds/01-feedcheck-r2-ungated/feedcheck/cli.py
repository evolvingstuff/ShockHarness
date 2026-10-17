"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

from feedcheck.checker import HEALTHY, check_all
from feedcheck.config import ConfigError, load_config

EXIT_OK = 0
EXIT_UNHEALTHY = 1
EXIT_ERROR = 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="feedcheck",
        description="Check whether a set of JSON feeds is healthy and write a report.",
    )
    parser.add_argument("--config", required=True, help="path to the feeds TOML file")
    parser.add_argument("--output", required=True, help="path to write the JSON report")
    return parser


def _write_report(path: str, report: dict) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".feedcheck-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"feedcheck: error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    output_dir = os.path.dirname(os.path.abspath(args.output))
    if not os.path.isdir(output_dir):
        print(f"feedcheck: error: output directory does not exist: {output_dir}",
              file=sys.stderr)
        return EXIT_ERROR

    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    results = check_all(config)
    all_healthy = all(r.status == HEALTHY for r in results)

    report = {
        "checked_at": checked_at,
        "healthy": all_healthy,
        "summary": {
            "total": len(results),
            **{
                status: sum(1 for r in results if r.status == status)
                for status in ("healthy", "unhealthy", "stale", "unreachable")
            },
        },
        "feeds": [r.to_dict() for r in results],
    }
    try:
        _write_report(args.output, report)
    except OSError as exc:
        print(f"feedcheck: error: cannot write report {args.output}: "
              f"{exc.strerror or exc}", file=sys.stderr)
        return EXIT_ERROR

    for r in results:
        line = f"{r.status:<11} {r.name}"
        if r.reason:
            line += f" ({r.reason})"
        print(line)

    return EXIT_OK if all_healthy else EXIT_UNHEALTHY
