"""Command-line entry point: ``feedcheck --config feeds.toml --output report.json``."""

import argparse
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from feedcheck.checker import check_all
from feedcheck.config import load_config

EXIT_ALL_HEALTHY = 0
EXIT_NOT_ALL_HEALTHY = 1
REPORT_INDENT = "  "


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="feedcheck", description="Check whether JSON feeds are healthy.")
    parser.add_argument("--config", required=True, type=Path, help="TOML file listing the feeds")
    parser.add_argument("--output", required=True, type=Path, help="where to write the JSON report")
    return parser


def main(argv: Sequence[str]) -> int:
    """Run the check and return the exit code; a bad config raises ConfigError (a SystemExit)."""
    arguments = build_parser().parse_args(argv)
    config = load_config(arguments.config)
    report = check_all(config, time.sleep)
    text = json.dumps(report.to_json(), indent=REPORT_INDENT)
    arguments.output.write_text(text + "\n", encoding="utf-8")
    if report.all_healthy:
        return EXIT_ALL_HEALTHY
    return EXIT_NOT_ALL_HEALTHY


def run() -> None:
    sys.exit(main(sys.argv[1:]))
