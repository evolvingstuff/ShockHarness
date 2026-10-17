"""Command line: contactclean input.csv --output clean.csv --report report.json"""

import argparse
import csv
import io
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import NoReturn

from contactclean.cleaning import OUTPUT_COLUMNS, CleanResult, clean_records, missing_columns
from contactclean.normalize import PHONE_PLANS_FILE, load_phone_plans

EXIT_ALL_USABLE = 0
EXIT_ROWS_REPORTED = 1
EXIT_INPUT_UNREADABLE = 2  # shockharness: ignore[MAGIC001] reason="exit status for unreadable input, defined in SPEC.md"
# utf-8-sig accepts the byte order mark spreadsheet exports often begin with.
INPUT_ENCODING = "utf-8-sig"
OUTPUT_ENCODING = "utf-8"
JSON_INDENT = "  "


class InputUnreadableError(SystemExit):
    """The input cannot be read or used at all; the process exits with EXIT_INPUT_UNREADABLE."""

    def __init__(self, message: str) -> None:
        super().__init__(EXIT_INPUT_UNREADABLE)
        self.message = message


def fail_input(message: str) -> NoReturn:
    """Tell the user why the input is unusable, then exit with EXIT_INPUT_UNREADABLE."""
    print(f"contactclean: {message}", file=sys.stderr)
    raise InputUnreadableError(message)


def parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="contactclean", description="Clean a CSV export of contacts.")
    parser.add_argument("input", type=Path, help="contacts CSV to clean")
    parser.add_argument("--output", type=Path, required=True, help="where to write the cleaned CSV")
    parser.add_argument("--report", type=Path, required=True, help="where to write the JSON report")
    return parser.parse_args(argv)


def read_text(path: Path) -> str:
    # Boundary (declared in .shockharness.toml): one file read.
    try:
        text = path.read_text(encoding=INPUT_ENCODING)
    except (OSError, UnicodeDecodeError) as exc:
        fail_input(f"cannot read {path}: {exc}")
        raise AssertionError("fail_input does not return") from exc
    return text


def parse_csv(text: str, path: Path) -> list[list[str]]:
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    # Boundary (declared in .shockharness.toml): one pass of the CSV parser over the input.
    try:
        records = list(reader)
    except csv.Error as exc:
        fail_input(f"cannot parse {path} as CSV: {exc}")
        raise AssertionError("fail_input does not return") from exc
    return records


def read_records(path: Path) -> list[list[str]]:
    """The CSV records of the input, header first; exits with EXIT_INPUT_UNREADABLE when unusable."""
    records = parse_csv(read_text(path), path)
    if not records:
        fail_input(f"{path} is empty: no header row")
    missing = missing_columns(records[0])
    if missing:
        fail_input(f"{path} header lacks column(s): {', '.join(missing)}")
    return records


def build_report(result: CleanResult, input_path: Path) -> dict[str, object]:
    return {
        "input": str(input_path),
        "row_numbering": "the header is row 1; the first contact is row 2",
        "rows_read": result.rows_read,
        "contacts_written": len(result.contacts),
        "rejected": [asdict(rejection) for rejection in result.rejected],
        "invalid_fields": [asdict(problem) for problem in result.invalid_fields],
        "merged": [
            {"kept_row": merge.kept_row, "merged_rows": list(merge.merged_rows), "reason": merge.reason}
            for merge in result.merges
        ],
    }


def write_output(path: Path, result: CleanResult) -> None:
    with path.open("w", encoding=OUTPUT_ENCODING, newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(contact.as_output_row() for contact in result.contacts)


def write_report(path: Path, report: dict[str, object]) -> None:
    path.write_text(json.dumps(report, indent=JSON_INDENT, ensure_ascii=False) + "\n", encoding=OUTPUT_ENCODING)


def main(argv: Sequence[str]) -> int:
    """Run contactclean; returns the exit status, or raises InputUnreadableError (a SystemExit)."""
    if sys.flags.optimize:
        raise SystemExit("do not run contactclean with python -O: its invariants are asserts")
    arguments = parse_arguments(argv)
    plans = load_phone_plans(PHONE_PLANS_FILE)
    header, *data = read_records(arguments.input)
    result = clean_records(header, data, plans)
    write_output(arguments.output, result)
    write_report(arguments.report, build_report(result, arguments.input))
    if result.every_row_usable:
        return EXIT_ALL_USABLE
    return EXIT_ROWS_REPORTED
