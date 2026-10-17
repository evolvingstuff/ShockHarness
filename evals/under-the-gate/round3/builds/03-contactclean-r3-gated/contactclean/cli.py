"""Command line: contactclean input.csv --output clean.csv --report report.json"""

import argparse
import csv
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from contactclean import fields
from contactclean.clean import CleanResult, clean
from contactclean.phone import load_phone_plans
from contactclean.reader import InputError, read_records

EXIT_ALL_USABLE = 0
EXIT_ROWS_REPORTED = 1
EXIT_UNREADABLE_INPUT = 2  # shockharness: ignore[MAGIC001] reason="SPEC.md: exit 2 when the input cannot be read"
REPORT_INDENT = True  # json.dumps treats True as an indent of one space per level


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="contactclean", description="Clean a CSV export of contacts.")
    parser.add_argument("input", type=Path, help="contacts CSV to read")
    parser.add_argument("--output", type=Path, required=True, help="where to write the cleaned CSV")
    parser.add_argument("--report", type=Path, required=True, help="where to write the JSON report")
    return parser


def clean_file(input_path: Path) -> CleanResult:
    """Read and clean the input; raise InputError when it cannot be read."""
    return clean(read_records(input_path), load_phone_plans())


def write_outputs(result: CleanResult, output_path: Path, report_path: Path) -> None:
    with output_path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields.OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(contact.as_output() for contact in result.contacts)
    report_path.write_text(json.dumps(result.report(), indent=REPORT_INDENT) + "\n", encoding="utf-8")


def main(argv: Sequence[str]) -> int:
    """Return the exit status; an unreadable input raises SystemExit(EXIT_UNREADABLE_INPUT)."""
    if sys.flags.optimize:
        raise SystemExit("do not run contactclean with python -O: invariants are asserts")
    args = _parser().parse_args(argv)
    # Boundary (declared in .shockharness.toml): one call that reads the input.
    try:
        result = clean_file(args.input)
    except InputError as exc:
        print(f"contactclean: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_UNREADABLE_INPUT) from exc
    write_outputs(result, args.output, args.report)
    if result.all_rows_usable():
        return EXIT_ALL_USABLE
    return EXIT_ROWS_REPORTED


def entry_point() -> None:
    sys.exit(main(sys.argv[1:]))
