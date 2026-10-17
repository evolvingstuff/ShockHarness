"""Reading the input CSV and writing the cleaned CSV and the JSON report."""

import csv
import io
import json

from pathlib import Path

from contactclean.clean import CleanResult

OUTPUT_COLUMNS = ("name", "email", "phone", "phone_status", "birthday", "country")


class UnreadableInputError(Exception):
    """The input file could not be read or parsed as CSV."""


def read_records(path: Path) -> list[list[str]]:
    """Read every CSV record of the file, header included."""
    # Boundary (declared in .shockharness.toml): one file read.
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise UnreadableInputError(f"cannot read {path}: {exc}") from exc
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    # Boundary (declared in .shockharness.toml): one CSV parse of external text.
    try:
        records = list(reader)
    except csv.Error as exc:
        raise UnreadableInputError(f"{path} is not valid CSV: {exc}") from exc
    return records


def write_contacts(path: Path, result: CleanResult) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(OUTPUT_COLUMNS)
        for contact in result.contacts:
            writer.writerow(
                (contact.name, contact.email, contact.phone, contact.phone_status, contact.birthday, contact.country)
            )


def report_document(result: CleanResult) -> dict[str, object]:
    return {
        "rows_read": result.rows_read,
        "rows_written": len(result.contacts),
        "row_numbering": "the header is row 1, the first contact row is row 2",
        "rejected": [{"row": item.row, "reason": item.reason} for item in result.rejections],
        "invalid_fields": [
            {"row": item.row, "field": item.field, "value": item.value, "reason": item.reason}
            for item in result.field_issues
        ],
        "merged": [
            {"kept_row": item.kept_row, "merged_rows": list(item.merged_rows), "reason": item.reason}
            for item in result.merges
        ],
    }


def write_report(path: Path, result: CleanResult) -> None:
    path.write_text(json.dumps(report_document(result), indent="  ") + "\n", encoding="utf-8")



