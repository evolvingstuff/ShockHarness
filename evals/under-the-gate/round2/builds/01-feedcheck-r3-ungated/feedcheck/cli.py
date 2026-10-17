"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from feedcheck import __version__
from feedcheck.checker import HEALTHY, STALE, UNHEALTHY, UNREACHABLE, check_all
from feedcheck.config import ConfigError, load_config

EXIT_OK = 0
EXIT_UNHEALTHY = 1
EXIT_ERROR = 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="feedcheck",
        description="Check whether a set of JSON feeds is healthy and write a report.",
    )
    parser.add_argument("--config", required=True, help="path to the TOML config file")
    parser.add_argument("--output", required=True, help="path to write the JSON report to")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _write_report(path: Path, report: dict) -> None:
    # Write to a temp file and rename, so a crash never leaves a half report.
    directory = path.parent if str(path.parent) else Path(".")
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=directory)
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

    output = Path(args.output)
    if not output.parent.is_dir() and str(output.parent):
        print(
            f"feedcheck: error: output directory does not exist: {output.parent}",
            file=sys.stderr,
        )
        return EXIT_ERROR

    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    results = check_all(config)
    healthy = all(r.status == HEALTHY for r in results)
    report = {
        "checked_at": checked_at,
        "healthy": healthy,
        "summary": {
            "total": len(results),
            **{
                status: sum(r.status == status for r in results)
                for status in (HEALTHY, UNHEALTHY, UNREACHABLE, STALE)
            },
        },
        "feeds": [r.to_dict() for r in results],
    }

    try:
        _write_report(output, report)
    except OSError as exc:
        print(f"feedcheck: error: cannot write report to {output}: {exc}", file=sys.stderr)
        return EXIT_ERROR

    for r in results:
        line = f"{r.status:<11} {r.name}"
        if r.reason:
            line += f": {r.reason}"
        print(line, file=sys.stderr)

    return EXIT_OK if healthy else EXIT_UNHEALTHY
