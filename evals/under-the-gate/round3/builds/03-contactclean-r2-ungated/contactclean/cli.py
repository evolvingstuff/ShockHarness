"""Command-line interface: contactclean input.csv --output clean.csv --report report.json"""

from __future__ import annotations

import argparse
import csv
import json
import sys

from contactclean.clean import OUTPUT_FIELDS, clean_rows

EXIT_OK = 0
EXIT_ISSUES = 1
EXIT_UNREADABLE = 2


class InputError(Exception):
    pass


def read_rows(path: str) -> list[dict[str, str]]:
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                raise InputError("input is empty")
            reader.fieldnames = [h.strip().lower() for h in reader.fieldnames]
            if "name" not in reader.fieldnames:
                raise InputError("input has no 'name' column")
            return list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as err:
        raise InputError(str(err)) from err


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="contactclean", description=__doc__)
    parser.add_argument("input", help="contacts CSV export")
    parser.add_argument("--output", required=True, help="path for the cleaned CSV")
    parser.add_argument("--report", required=True, help="path for the JSON report")
    args = parser.parse_args(argv)

    try:
        rows = read_rows(args.input)
    except InputError as err:
        print(f"contactclean: cannot read {args.input}: {err}", file=sys.stderr)
        return EXIT_UNREADABLE

    result = clean_rows(rows)

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(c.as_output() for c in result.contacts)
    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(result.report(), f, indent=2, ensure_ascii=False)
        f.write("\n")

    return EXIT_OK if result.all_usable else EXIT_ISSUES
