"""Command line: contactclean input.csv --output clean.csv --report report.json"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from contactclean.clean import clean_rows
from contactclean.csvfiles import read_rows, write_outputs
from contactclean.errors import InputError
from contactclean.normalize import load_phone_rules

EXIT_OK = 0
EXIT_ROWS_REPORTED = 1
EXIT_UNREADABLE = 2  # shockharness: ignore[MAGIC001] reason="SPEC.md: exit 2 when the input cannot be read"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="contactclean", description="Clean a CSV export of contacts.")
    parser.add_argument("input", type=Path, help="contacts CSV with name,email,phone,birthday,country")
    parser.add_argument("--output", type=Path, required=True, help="where to write the cleaned CSV")
    parser.add_argument("--report", type=Path, required=True, help="where to write the JSON report")
    return parser


def main(argv: Sequence[str]) -> int:
    if sys.flags.optimize:
        raise SystemExit("do not run contactclean with python -O: its invariants are asserts")
    args = _parser().parse_args(argv)
    # Boundary (declared in .shockharness.toml): unreadable input exits with EXIT_UNREADABLE.
    try:
        rows = read_rows(args.input)
    except InputError as exc:
        print(f"contactclean: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_UNREADABLE) from exc
    result = clean_rows(rows, load_phone_rules())
    write_outputs(result, args.output, args.report)
    if result.every_row_usable:
        return EXIT_OK
    return EXIT_ROWS_REPORTED


def run() -> None:
    sys.exit(main(sys.argv[1:]))
