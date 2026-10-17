"""Command line: contactclean input.csv --output clean.csv --report report.json"""

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Sequence

from contactclean.clean import clean, report
from contactclean.csvio import read_rows, write_contacts, write_report
from contactclean.errors import InputUnreadable
from contactclean.plans import load_phone_rules

EXIT_CLEAN = 0
EXIT_REPORTED = 1
EXIT_UNREADABLE = 2  # shockharness: ignore[MAGIC001] reason="SPEC.md: exit 2 when the input cannot be read"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="contactclean", description="Clean a CSV export of contacts.")
    parser.add_argument("input", type=Path, help="contacts CSV with a name column")
    parser.add_argument("--output", type=Path, required=True, help="where to write the cleaned CSV")
    parser.add_argument("--report", type=Path, required=True, help="where to write the JSON report")
    return parser


def run(argv: Sequence[str], today: date) -> int:
    """Clean the input; exit status EXIT_CLEAN or EXIT_REPORTED, or SystemExit(EXIT_UNREADABLE)."""
    arguments = _parser().parse_args(argv)
    # Boundary (declared in .shockharness.toml): an unreadable input ends the process with its exit status.
    try:
        rows = read_rows(arguments.input)
    except InputUnreadable as exc:
        print(f"contactclean: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_UNREADABLE) from exc
    result = clean(rows, load_phone_rules(), today)
    write_contacts(arguments.output, result.contacts)
    write_report(arguments.report, report(result))
    if result.every_row_usable():
        return EXIT_CLEAN
    return EXIT_REPORTED


def main() -> int:
    if sys.flags.optimize:
        raise SystemExit("do not run contactclean with python -O: invariants are asserts")
    return run(sys.argv[1:], date.today())
