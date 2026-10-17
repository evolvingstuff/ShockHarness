"""Command-line entry point: contactclean input.csv --output clean.csv --report report.json"""

from __future__ import annotations

import argparse
import csv
import json
import sys

from .core import OUTPUT_FIELDS, clean

EXIT_OK = 0
EXIT_ISSUES = 1
EXIT_UNREADABLE = 2


class InputError(Exception):
    pass


def read_records(path: str) -> list[dict[str, str]]:
    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                raise InputError("input is empty")
            reader.fieldnames = [f.strip().lower() for f in reader.fieldnames]
            if "name" not in reader.fieldnames:
                raise InputError("input has no 'name' column")
            return list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise InputError(str(exc)) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="contactclean", description=__doc__)
    parser.add_argument("input", help="contacts CSV to clean")
    parser.add_argument("--output", required=True, help="where to write the cleaned CSV")
    parser.add_argument("--report", required=True, help="where to write the JSON report")
    args = parser.parse_args(argv)

    try:
        records = read_records(args.input)
    except InputError as exc:
        print(f"contactclean: cannot read {args.input}: {exc}", file=sys.stderr)
        return EXIT_UNREADABLE

    result = clean(records)

    with open(args.output, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(c.as_row() for c in result.contacts)
    with open(args.report, "w", encoding="utf-8") as fh:
        json.dump(result.report(), fh, indent=2)
        fh.write("\n")

    return EXIT_OK if result.clean else EXIT_ISSUES


if __name__ == "__main__":
    sys.exit(main())
