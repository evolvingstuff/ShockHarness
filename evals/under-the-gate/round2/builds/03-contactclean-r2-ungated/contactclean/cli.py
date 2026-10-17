"""Command-line entry point."""

from __future__ import annotations

import argparse
import csv
import json
import sys

from .clean import OUTPUT_FIELDS, clean_rows

EXIT_OK = 0
EXIT_REPORTED = 1
EXIT_UNREADABLE = 2


class InputError(Exception):
    pass


def read_rows(path: str) -> list[dict]:
    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                raise InputError("input is empty")
            reader.fieldnames = [(name or "").strip().lower() for name in reader.fieldnames]
            if "name" not in reader.fieldnames:
                raise InputError("input has no 'name' column")
            return list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise InputError(str(exc)) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="contactclean", description="Clean a CSV export of contacts."
    )
    parser.add_argument("input", help="contacts CSV to clean")
    parser.add_argument("--output", required=True, help="where to write the cleaned CSV")
    parser.add_argument("--report", required=True, help="where to write the JSON report")
    args = parser.parse_args(argv)

    try:
        rows = read_rows(args.input)
    except InputError as exc:
        print(f"contactclean: cannot read {args.input}: {exc}", file=sys.stderr)
        return EXIT_UNREADABLE

    result = clean_rows(rows)

    try:
        with open(args.output, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=OUTPUT_FIELDS)
            writer.writeheader()
            writer.writerows(c.as_output() for c in result.contacts)
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(result.report(), fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    except OSError as exc:
        print(f"contactclean: cannot write output: {exc}", file=sys.stderr)
        return EXIT_UNREADABLE

    return EXIT_OK if result.all_usable else EXIT_REPORTED
