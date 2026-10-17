"""Reading the input CSV and writing the cleaned CSV and the JSON report."""

import csv
import io
import json
from pathlib import Path

from contactclean.clean import CleanResult
from contactclean.errors import InputError, OutputError
from contactclean.model import COLUMNS, OUTPUT_COLUMNS, RawRow

HEADER_ROWS = 1
REPORT_INDENT = len("  ")


def read_rows(path: Path) -> tuple[RawRow, ...]:
    # Boundary (declared in .shockharness.toml): one file read.
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise InputError(f"cannot read {path}: {exc}") from exc
    reader = csv.reader(io.StringIO(text, newline=""))
    # Boundary (declared in .shockharness.toml): one CSV parse of external input.
    try:
        records = list(reader)
    except csv.Error as exc:
        raise InputError(f"{path} is not valid CSV: {exc}") from exc
    if not records:
        raise InputError(f"{path} is empty: it has no header row")
    header = tuple(column.strip().lower() for column in records[0])
    missing = [column for column in COLUMNS if column not in header]
    if missing:
        raise InputError(f"{path} is missing the column(s): {', '.join(missing)}")
    rows = []
    for row_number, record in enumerate(records[HEADER_ROWS:], start=HEADER_ROWS + 1):
        if not any(cell.strip() for cell in record):
            continue
        padded = record + [""] * (len(header) - len(record))
        values = tuple((column, padded[header.index(column)]) for column in COLUMNS)
        rows.append(RawRow(row_number=row_number, values=values))
    return tuple(rows)


def build_report(result: CleanResult) -> dict[str, object]:
    return {
        "rows_read": result.rows_read,
        "rows_written": len(result.contacts),
        "rejected": [{"row": item.row_number, "reason": item.reason} for item in result.rejections],
        "invalid_fields": [
            {"row": item.row_number, "field": item.field, "value": item.value, "reason": item.reason}
            for item in result.issues
        ],
        "merged": [
            {"kept_row": item.kept_row, "merged_rows": list(item.merged_rows), "reasons": list(item.reasons)}
            for item in result.merges
        ],
    }


def write_outputs(result: CleanResult, output: Path, report: Path) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for contact in result.contacts:
        writer.writerow(contact.as_output_row())
    report_text = json.dumps(build_report(result), indent=REPORT_INDENT) + "\n"
    _write_text(output, buffer.getvalue())
    _write_text(report, report_text)


def _write_text(path: Path, text: str) -> None:
    # Boundary (declared in .shockharness.toml): one file write.
    try:
        path.write_text(text, encoding="utf-8", newline="")
    except OSError as exc:
        raise OutputError(f"cannot write {path}: {exc}") from exc
