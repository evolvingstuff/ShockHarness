"""Command-line entry point: feedcheck --config feeds.toml --output report.json."""

import argparse
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from feedcheck.config import Config, ConfigError, load_config
from feedcheck.report import all_healthy, check_feeds, write_report

EXIT_HEALTHY = 0
EXIT_UNHEALTHY = 1
EXIT_CONFIG_ERROR = 2  # shockharness: ignore[MAGIC001] reason="same status argparse uses for an invalid invocation (Python docs, ArgumentParser.error)"


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="feedcheck", description="Check JSON feeds and write a health report.")
    parser.add_argument("--config", required=True, type=Path, help="TOML file listing the feeds")
    parser.add_argument("--output", required=True, type=Path, help="where to write the JSON report")
    args = parser.parse_args(argv)
    config = _load(args.config)
    results = check_feeds(config, time.sleep)
    write_report(args.output, results)
    if all_healthy(results):
        return EXIT_HEALTHY
    return EXIT_UNHEALTHY


def _load(path: Path) -> Config:
    # Boundary (declared in .shockharness.toml): a bad config stops the tool with a message.
    try:
        config = load_config(path)
    except ConfigError as exc:
        sys.stderr.write(f"feedcheck: {exc}\n")
        raise SystemExit(EXIT_CONFIG_ERROR) from exc
    return config


def entry_point() -> None:
    sys.exit(main(sys.argv[1:]))
