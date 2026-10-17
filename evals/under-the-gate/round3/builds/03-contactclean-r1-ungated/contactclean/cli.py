"""Command-line interface.

Exit codes: 0 every row was usable, 1 some rows were rejected or had invalid
fields reported, 2 the input could not be read (or the outputs not written).
Row numbers in the report are spreadsheet rows: the header is row 1.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys

from .core import OUTPUT_COLUMNS, clean

EXIT_OK, EXIT_REPORTED, EXIT_UNREADABLE = 0, 1, 2


def read_rows(path: str) -> list[tuple[int, dict[str, str | None]]]:
    """Read the input CSV; raise ``ValueError``/``OSError`` if unusable."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("input is empty (no header row)")
        headers = {h.strip().lower(): h for h in reader.fieldnames if h is not None}
        if "name" not in headers:
            raise ValueError("input has no 'name' column")
        rows = []
        for index, raw in enumerate(reader, start=2):
            rows.append((index, {key: raw.get(orig) for key, orig in headers.items()}))
        return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="contactclean", description="Clean a CSV export of contacts.")
    parser.add_argument("input", help="input CSV file")
    parser.add_argument("--output", required=True, help="where to write the cleaned CSV")
    parser.add_argument("--report", required=True, help="where to write the JSON report")
    args = parser.parse_args(argv)

    try:
        rows = read_rows(args.input)
    except (OSError, UnicodeDecodeError, csv.Error, ValueError) as exc:
        print(f"contactclean: cannot read {args.input}: {exc}", file=sys.stderr)
        return EXIT_UNREADABLE

    result = clean(rows)

    try:
        with open(args.output, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
            writer.writeheader()
            for contact in result.contacts:
                writer.writerow(contact.as_output())
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(result.report(), f, indent=2, ensure_ascii=False)
            f.write("\n")
    except OSError as exc:
        print(f"contactclean: cannot write output: {exc}", file=sys.stderr)
        return EXIT_UNREADABLE

    return EXIT_OK if result.all_rows_usable else EXIT_REPORTED
