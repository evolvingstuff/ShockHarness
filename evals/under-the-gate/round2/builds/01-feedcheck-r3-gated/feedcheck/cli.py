"""Command-line entry point: feedcheck --config feeds.toml --output report.json"""

import argparse
import sys
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from feedcheck.check import check_all
from feedcheck.config import Config, load_config
from feedcheck.errors import ConfigError
from feedcheck.report import all_healthy, build_report, write_report

EXIT_ALL_HEALTHY = 0
EXIT_NOT_ALL_HEALTHY = 1


def main(argv: Sequence[str]) -> int:
    if sys.flags.optimize:
        raise SystemExit("feedcheck: do not run with python -O: invariants are asserts")
    args = _parser().parse_args(argv)
    config = _load_or_exit(Path(args.config))
    checked_at = datetime.now(timezone.utc)
    results = check_all(config, checked_at, time.sleep)
    write_report(build_report(results, checked_at), Path(args.output))
    if all_healthy(results):
        return EXIT_ALL_HEALTHY
    return EXIT_NOT_ALL_HEALTHY


def run() -> None:
    """Console-script entry point."""
    sys.exit(main(sys.argv[1:]))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="feedcheck", description="Check whether JSON feeds are healthy.")
    parser.add_argument("--config", required=True, help="TOML file listing the feeds")
    parser.add_argument("--output", required=True, help="where to write the JSON report")
    return parser


def _load_or_exit(path: Path) -> Config:
    # Boundary (declared in .shockharness.toml): one config load.
    try:
        config = load_config(path)
    except ConfigError as exc:
        raise SystemExit(f"feedcheck: {exc}") from exc
    return config
