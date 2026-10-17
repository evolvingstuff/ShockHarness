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
from feedcheck.check import HEALTHY, build_report, check_all
from feedcheck.config import ConfigError, load_config

EXIT_OK = 0
EXIT_UNHEALTHY = 1
EXIT_ERROR = 2


def _write_report(report: dict, output: Path) -> None:
    """Write the report atomically so a failed run never leaves a half-written file."""
    directory = output.parent if str(output.parent) else Path(".")
    fd, tmp_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
            handle.write("\n")
        os.replace(tmp_name, output)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="feedcheck",
        description="Check whether a set of JSON feeds is healthy and write a report.",
    )
    parser.add_argument("--config", required=True, type=Path, help="path to the TOML config file")
    parser.add_argument("--output", required=True, type=Path, help="path to write the JSON report")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"feedcheck: error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    checked_at = datetime.now(timezone.utc)
    results = check_all(config)
    report = build_report(results, checked_at)

    try:
        _write_report(report, args.output)
    except OSError as exc:
        print(
            f"feedcheck: error: cannot write report to {args.output}: {exc.strerror or exc}",
            file=sys.stderr,
        )
        return EXIT_ERROR

    for result in results:
        line = f"{result.status:<11} {result.name}"
        if result.reason:
            line += f": {result.reason}"
        print(line)

    return EXIT_OK if all(r.status == HEALTHY for r in results) else EXIT_UNHEALTHY
