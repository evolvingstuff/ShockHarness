"""Command-line entry point: feedcheck --config feeds.toml --output report.json"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from feedcheck.checker import HEALTHY, build_report, check_all
from feedcheck.config import ConfigError, load_config

EXIT_OK = 0
EXIT_UNHEALTHY = 1
EXIT_ERROR = 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="feedcheck", description="Check whether a set of JSON feeds is healthy."
    )
    parser.add_argument("--config", required=True, help="path to the TOML config file")
    parser.add_argument("--output", required=True, help="path to write the JSON report to")
    return parser


def _write_report(report: dict, output: Path) -> None:
    """Write the report atomically so a failed run never leaves half a file."""
    directory = output.parent if str(output.parent) else Path(".")
    fd, tmp = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
            handle.write("\n")
        os.replace(tmp, output)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"feedcheck: error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    output = Path(args.output)
    if not output.parent.is_dir():
        print(f"feedcheck: error: output directory does not exist: {output.parent}", file=sys.stderr)
        return EXIT_ERROR

    checked_at = datetime.now(timezone.utc)
    results = check_all(config)
    report = build_report(results, checked_at)

    try:
        _write_report(report, output)
    except OSError as exc:
        print(f"feedcheck: error: cannot write report {output}: {exc.strerror or exc}", file=sys.stderr)
        return EXIT_ERROR

    for result in results:
        line = f"{result.status:<11} {result.name}"
        if result.reason:
            line += f": {result.reason}"
        print(line)

    return EXIT_OK if all(r.status == HEALTHY for r in results) else EXIT_UNHEALTHY


if __name__ == "__main__":
    sys.exit(main())
