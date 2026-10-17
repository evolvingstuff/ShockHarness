"""Read the contacts CSV and write the cleaned CSV and the JSON report.

Boundary (declared in .shockharness.toml): reading the input file, decoding it
and parsing it as CSV. Each failure becomes InputUnreadable.
"""

import csv
import io
import json
from pathlib import Path

from contactclean.errors import InputUnreadable
from contactclean.model import Contact, RawRow

REQUIRED_COLUMN = "name"
INPUT_COLUMNS = ("name", "email", "phone", "birthday", "country")
OUTPUT_COLUMNS = ("name", "email", "phone", "phone_status", "birthday", "country")
INPUT_ENCODING = "utf-8-sig"  # accepts a byte order mark, as spreadsheet exports write one
HEADER_ROW_NUMBER = 1


def _read_bytes(path: Path) -> bytes:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise InputUnreadable(f"cannot read {path}: {exc.strerror}") from exc
    return data


def _decode(path: Path, data: bytes) -> str:
    try:
        text = data.decode(INPUT_ENCODING)
    except UnicodeDecodeError as exc:
        raise InputUnreadable(f"{path} is not UTF-8 text: {exc.reason}") from exc
    return text


def _parse(path: Path, text: str) -> list[list[str]]:
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        records = list(reader)
    except csv.Error as exc:
        raise InputUnreadable(f"{path} is not valid CSV: {exc}") from exc
    return records


def _row_fields(header: list[str], record: list[str]) -> dict[str, str]:
    fields = {column: "" for column in INPUT_COLUMNS}
    for column, value in zip(header, record):
        if column in fields:
            fields[column] = value
    return fields


def read_rows(path: Path) -> tuple[RawRow, ...]:
    """Data rows with their row number in the file (the header is row 1); blank lines are skipped."""
    records = _parse(path, _decode(path, _read_bytes(path)))
    if not records:
        raise InputUnreadable(f"{path} is empty: it has no header row")
    header = [column.strip().lower() for column in records[0]]
    if REQUIRED_COLUMN not in header:
        raise InputUnreadable(f"{path} has no {REQUIRED_COLUMN!r} column")
    rows = []
    for number, record in enumerate(records, start=HEADER_ROW_NUMBER):
        if number == HEADER_ROW_NUMBER or not record:
            continue
        rows.append(RawRow(row=number, fields=_row_fields(header, record)))
    return tuple(rows)


def write_contacts(path: Path, contacts: tuple[Contact, ...]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(OUTPUT_COLUMNS)
        for contact in contacts:
            writer.writerow(
                (
                    contact.name,
                    contact.email,
                    contact.phone,
                    contact.phone_status.value,
                    contact.birthday,
                    contact.country,
                )
            )


def write_report(path: Path, report: dict[str, object]) -> None:
    path.write_text(json.dumps(report, indent="  ", ensure_ascii=False) + "\n", encoding="utf-8")
