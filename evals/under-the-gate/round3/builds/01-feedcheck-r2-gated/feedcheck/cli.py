"""Command-line entry point: feedcheck --config feeds.toml --output report.json"""

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from feedcheck.check import check_feed
from feedcheck.config import Config, load_config
from feedcheck.errors import FeedcheckError, ReportWriteError
from feedcheck.report import all_healthy, build_report

EXIT_HEALTHY = 0
EXIT_NOT_HEALTHY = 1
REPORT_INDENT = "  "


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="feedcheck", description="Check that JSON feeds are healthy.")
    parser.add_argument("--config", required=True, type=Path, help="TOML file listing the feeds")
    parser.add_argument("--output", required=True, type=Path, help="where to write the JSON report")
    return parser


def run(config_path: Path, output_path: Path) -> int:
    """Check every feed and write the report; raises FeedcheckError on a config or write failure."""
    config: Config = load_config(config_path)
    checked_at = datetime.now(timezone.utc)
    results = [check_feed(feed, config, checked_at) for feed in config.feeds]
    text = json.dumps(build_report(results, checked_at), indent=REPORT_INDENT) + "\n"
    # Boundary (declared in .shockharness.toml): one file write.
    try:
        output_path.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise ReportWriteError(f"cannot write report {output_path}: {exc}") from exc
    if all_healthy(results):
        return EXIT_HEALTHY
    return EXIT_NOT_HEALTHY


def main(argv: Sequence[str]) -> int:
    arguments = _parser().parse_args(argv)
    # Boundary (declared in .shockharness.toml): a typed failure stops the tool with its message.
    try:
        status = run(arguments.config, arguments.output)
    except FeedcheckError as exc:
        raise SystemExit(f"feedcheck: {exc}") from exc
    return status


def entry_point() -> None:
    sys.exit(main(sys.argv[1:]))
