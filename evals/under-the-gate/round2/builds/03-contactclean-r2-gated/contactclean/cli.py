"""Command line entry point: contactclean input.csv --output clean.csv --report report.json."""

import argparse
import csv
import io
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from contactclean.clean import COLUMNS, CleanResult, clean
from contactclean.phone import load_phone_rules

EXIT_ALL_USABLE = 0
EXIT_ROWS_REPORTED = 1
EXIT_INPUT_UNREADABLE = 2  # shockharness: ignore[MAGIC001] reason="SPEC.md: exit 2 when the input cannot be read"
INPUT_ENCODING = "utf-8-sig"
OUTPUT_ENCODING = "utf-8"
OUTPUT_COLUMNS = ("name", "email", "phone", "phone_status", "birthday", "country")
JSON_INDENT = "  "


def _unreadable(message: str) -> SystemExit:
    """Report why the input cannot be used; the caller raises the returned exit."""
    print(f"contactclean: {message}", file=sys.stderr)
    return SystemExit(EXIT_INPUT_UNREADABLE)


def _read_text(path: Path) -> str:
    # Boundary (declared in .shockharness.toml): one file read.
    try:
        text = path.read_text(encoding=INPUT_ENCODING)
    except (OSError, UnicodeDecodeError) as exc:
        raise _unreadable(f"cannot read {path}: {exc}") from exc
    return text


def _csv_rows(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text, newline="")))


def _parse_csv(path: Path, text: str) -> list[list[str]]:
    # Boundary (declared in .shockharness.toml): one CSV decode of external input.
    try:
        rows = _csv_rows(text)
    except csv.Error as exc:
        raise _unreadable(f"{path} is not valid CSV: {exc}") from exc
    return rows


def _record(header: Sequence[str], row: Sequence[str]) -> dict[str, str | None]:
    """Name the cells of a row; a column past the end of a short row is None."""
    return {column: row[index] if index < len(row) else None for index, column in enumerate(header)}


def read_records(path: Path) -> list[dict[str, str | None]]:
    """Read the contacts CSV; exit with EXIT_INPUT_UNREADABLE when it cannot be used at all."""
    if not path.is_file():
        raise _unreadable(f"cannot read {path}: not a file")
    rows = _parse_csv(path, _read_text(path))
    if not rows:
        raise _unreadable(f"{path} is empty")
    header = [column.strip() for column in rows[0]]
    missing = [column for column in COLUMNS if column not in header]
    if missing:
        raise _unreadable(f"{path} lacks the column(s) {', '.join(missing)}")
    return [_record(header, row) for row in rows[1:] if row]


def write_contacts(path: Path, result: CleanResult) -> None:
    with path.open("w", encoding=OUTPUT_ENCODING, newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(OUTPUT_COLUMNS)
        for contact in result.contacts:
            writer.writerow([getattr(contact, column) for column in OUTPUT_COLUMNS])


def build_report(result: CleanResult) -> dict[str, object]:
    return {
        "rows_read": result.rows_read,
        "rows_written": len(result.contacts),
        "rejected": [asdict(rejected) for rejected in result.rejected],
        "invalid_fields": [asdict(invalid) for invalid in result.invalid_fields],
        "merged": [{"kept_row": merge.kept_row, "rows": list(merge.rows)} for merge in result.merges],
    }


def write_report(path: Path, result: CleanResult) -> None:
    path.write_text(json.dumps(build_report(result), indent=JSON_INDENT) + "\n", encoding=OUTPUT_ENCODING)


def _arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="contactclean", description="Clean a CSV export of contacts.")
    parser.add_argument("input", type=Path, help="contacts CSV to read")
    parser.add_argument("--output", type=Path, required=True, help="where to write the cleaned CSV")
    parser.add_argument("--report", type=Path, required=True, help="where to write the JSON report")
    return parser.parse_args(argv)


def run(argv: Sequence[str]) -> int:
    arguments = _arguments(argv)
    records = read_records(arguments.input)
    result = clean(records, load_phone_rules())
    write_contacts(arguments.output, result)
    write_report(arguments.report, result)
    if result.all_rows_usable:
        return EXIT_ALL_USABLE
    return EXIT_ROWS_REPORTED


def main() -> int:
    if sys.flags.optimize:
        raise SystemExit("do not run contactclean with python -O: invariants are asserts")
    return run(sys.argv[1:])
