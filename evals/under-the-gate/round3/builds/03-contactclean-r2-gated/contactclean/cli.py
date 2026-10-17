"""Command line: contactclean input.csv --output clean.csv --report report.json"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from contactclean.clean import InputFormatError, clean_records
from contactclean.csvio import UnreadableInputError, read_records, write_contacts, write_report
from contactclean.normalize import load_phone_rules

EXIT_ALL_USABLE = 0
EXIT_ROWS_REPORTED = 1
EXIT_UNREADABLE_INPUT = 2  # shockharness: ignore[MAGIC001] reason="SPEC.md: exit 2 when the input cannot be read"


def parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="contactclean", description="Clean a CSV export of contacts.")
    parser.add_argument("input", type=Path, help="contacts CSV with a name column")
    parser.add_argument("--output", type=Path, required=True, help="where to write the cleaned CSV")
    parser.add_argument("--report", type=Path, required=True, help="where to write the JSON report")
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    """Return the exit status; an unreadable input raises SystemExit with EXIT_UNREADABLE_INPUT."""
    arguments = parse_arguments(argv)
    rules = load_phone_rules()
    # Boundary (declared in .shockharness.toml): one read of the input file.
    try:
        records = read_records(arguments.input)
    except UnreadableInputError as exc:
        print(f"contactclean: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_UNREADABLE_INPUT) from exc
    # Boundary (declared in .shockharness.toml): one check of the input's structure.
    try:
        result = clean_records(records, rules)
    except InputFormatError as exc:
        print(f"contactclean: {arguments.input}: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_UNREADABLE_INPUT) from exc
    write_contacts(arguments.output, result)
    write_report(arguments.report, result)
    if result.all_rows_usable():
        return EXIT_ALL_USABLE
    return EXIT_ROWS_REPORTED


def run() -> None:
    raise SystemExit(main(sys.argv[1:]))
