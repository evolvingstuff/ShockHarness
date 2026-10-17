"""Reading the input CSV: the file boundary of the program."""

import csv
import io
from pathlib import Path


class InputUnreadable(Exception):
    """The input file cannot be read, decoded or parsed as CSV with a name column."""


REQUIRED_COLUMN = "name"


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise InputUnreadable(f"cannot read {path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise InputUnreadable(f"cannot decode {path} as UTF-8: {exc}") from exc


def parse_records(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text), restval="")
    try:
        records = list(reader)
    except csv.Error as exc:
        raise InputUnreadable(f"malformed CSV: {exc}") from exc
    if reader.fieldnames is None:
        raise InputUnreadable("input has no header row")
    header = [column.strip().lower() for column in reader.fieldnames]
    if REQUIRED_COLUMN not in header:
        raise InputUnreadable(f"input has no {REQUIRED_COLUMN!r} column")
    return [
        {key.strip().lower(): value for key, value in record.items() if key is not None}
        for record in records
    ]


def read_records(path: Path) -> list[dict[str, str]]:
    return parse_records(read_text(path))
