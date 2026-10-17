"""Command-line interface: ``contactclean input.csv --output X --report Y``."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile

from .core import INPUT_COLUMNS, OUTPUT_COLUMNS, clean

EXIT_OK = 0
EXIT_ISSUES = 1
EXIT_UNREADABLE = 2


class InputError(Exception):
    """The input file cannot be read as a contacts CSV."""


def read_contacts(path: str) -> tuple[list[tuple[int, dict[str, str]]], list[dict]]:
    """Read the CSV at ``path``.

    Returns ``(records, rejected)``. Row numbers count the header as row 1, as
    a spreadsheet would; blank lines are skipped but still counted. Rows whose
    field count does not match the header are rejected.
    """
    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.reader(fh))
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise InputError(str(exc)) from exc

    if not rows:
        raise InputError("file is empty")
    header = [h.strip().lower() for h in rows[0]]
    if "name" not in header:
        raise InputError("missing required column 'name'")
    duplicates = {h for h in header if h and header.count(h) > 1}
    if duplicates:
        raise InputError(f"duplicate columns: {', '.join(sorted(duplicates))}")

    records, rejected = [], []
    for row_number, values in enumerate(rows[1:], start=2):
        if not values:
            continue
        if len(values) != len(header):
            rejected.append({
                "row": row_number,
                "reason": f"expected {len(header)} fields, found {len(values)}",
            })
            continue
        record = dict(zip(header, values))
        records.append((row_number, {col: record.get(col, "") for col in INPUT_COLUMNS}))
    return records, rejected


def _write_atomic(path: str, write) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".contactclean-")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as fh:
            write(fh)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="contactclean", description="Clean a CSV export of contacts.")
    parser.add_argument("input", help="contacts CSV to read")
    parser.add_argument("--output", required=True, help="where to write the cleaned CSV")
    parser.add_argument("--report", required=True, help="where to write the JSON report")
    args = parser.parse_args(argv)

    try:
        records, malformed = read_contacts(args.input)
    except InputError as exc:
        print(f"contactclean: cannot read {args.input}: {exc}", file=sys.stderr)
        return EXIT_UNREADABLE

    contacts, report = clean(records)
    report.rows_read += len(malformed)
    report.rejected = sorted(report.rejected + malformed, key=lambda r: r["row"])

    def write_csv(fh):
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(c.as_row() for c in contacts)

    def write_report(fh):
        json.dump(report.to_dict(), fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    try:
        _write_atomic(args.output, write_csv)
        _write_atomic(args.report, write_report)
    except OSError as exc:
        print(f"contactclean: cannot write output: {exc}", file=sys.stderr)
        return EXIT_UNREADABLE

    return EXIT_ISSUES if report.has_issues else EXIT_OK
