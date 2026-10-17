"""Command-line entry point: feedcheck --config feeds.toml --output report.json."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from typing import NoReturn
from datetime import UTC, datetime
from pathlib import Path

from feedcheck.check import check_feeds
from feedcheck.config import ConfigError, load_settings
from feedcheck.fetch import build_opener
from feedcheck.report import all_healthy, build_report, write_report

EXIT_HEALTHY = 0
EXIT_UNHEALTHY = 1
EXIT_CONFIG_ERROR = 2  # shockharness: ignore[MAGIC001] reason="Same status argparse uses for usage errors (Python docs, argparse.ArgumentParser.error)"


def main(argv: Sequence[str]) -> int:
    """Run the checks; exit 0 when every feed is healthy, 1 otherwise, 2 on a bad config."""
    args = _parser().parse_args(argv)
    config_path = Path(args.config)
    # Boundary (declared in .shockharness.toml): a bad config stops the tool before any fetch.
    try:
        settings = load_settings(config_path)
    except ConfigError as exc:
        print(f"feedcheck: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_CONFIG_ERROR) from exc
    checked_at = datetime.now(UTC)
    results = check_feeds(settings, build_opener(), time.sleep)
    write_report(Path(args.output), build_report(results, checked_at))
    if all_healthy(results):
        return EXIT_HEALTHY
    return EXIT_UNHEALTHY


def run() -> NoReturn:
    """Console-script entry point."""
    sys.exit(main(sys.argv[1:]))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="feedcheck", description="Check that JSON feeds are healthy and write a report.")
    parser.add_argument("--config", required=True, help="TOML file listing the feeds and the retry policy")
    parser.add_argument("--output", required=True, help="where to write the JSON report")
    return parser
