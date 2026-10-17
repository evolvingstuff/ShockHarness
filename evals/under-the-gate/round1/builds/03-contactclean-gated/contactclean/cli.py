"""Command line entry point."""

import argparse
import csv
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from contactclean.cleaning import CleanResult, clean
from contactclean.reader import InputUnreadable, read_records

EXIT_OK = 0
EXIT_REPORTED = 1
EXIT_UNREADABLE = EXIT_REPORTED + 1  # sysexits-style: 0 ok, 1 reported, next code for unreadable input

OUTPUT_COLUMNS = ("name", "email", "phone", "phone_status", "birthday", "country")


def write_output(result: CleanResult, path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(OUTPUT_COLUMNS)
        for contact in result.contacts:
            writer.writerow([getattr(contact, column) for column in OUTPUT_COLUMNS])


def write_report(result: CleanResult, rows_read: int, path: Path) -> None:
    report = {
        "rows_read": rows_read,
        "rows_written": len(result.contacts),
        "issues": [asdict(issue) for issue in result.issues],
        "merged": [
            {"kept_row": merge.kept_row, "rows": list(merge.rows)} for merge in result.merges
        ],
    }
    path.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="contactclean", description="Clean a contacts CSV export.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    try:
        records = read_records(args.input)
    except InputUnreadable as exc:
        print(f"contactclean: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_UNREADABLE) from exc
    result = clean(records)
    write_output(result, args.output)
    write_report(result, len(records), args.report)
    if result.issues:
        return EXIT_REPORTED
    return EXIT_OK
