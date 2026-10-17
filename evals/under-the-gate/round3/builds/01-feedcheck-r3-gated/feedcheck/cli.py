"""Command line entry point: feedcheck --config feeds.toml --output report.json"""

import argparse
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from feedcheck.check import Clocks, all_healthy, build_report, check_feeds, write_report
from feedcheck.config import ConfigError, load_config

EXIT_ALL_HEALTHY = 0
EXIT_NOT_ALL_HEALTHY = 1


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="feedcheck", description="Check that JSON feeds are healthy and write a report.")
    parser.add_argument("--config", required=True, type=Path, help="TOML file listing the feeds and fetch settings")
    parser.add_argument("--output", required=True, type=Path, help="where to write the JSON report")
    return parser


def main(argv: Sequence[str]) -> int:
    if sys.flags.optimize:
        raise SystemExit("feedcheck: do not run with python -O: invariants are asserts")
    args = _parser().parse_args(argv)
    # Boundary (declared in .shockharness.toml): an invalid config stops the tool before any fetch.
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        raise SystemExit(f"feedcheck: {exc}") from exc
    clocks = Clocks(sleep=time.sleep, monotonic=time.monotonic, now=_utc_now)
    checked_at = clocks.now()
    results = check_feeds(config, clocks)
    write_report(build_report(results, checked_at), args.output)
    if all_healthy(results):
        return EXIT_ALL_HEALTHY
    return EXIT_NOT_ALL_HEALTHY


def console_main() -> None:
    sys.exit(main(sys.argv[1:]))
