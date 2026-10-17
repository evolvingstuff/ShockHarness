"""Reading the input CSV: the only place where file and decoding errors are caught."""

import csv
import io
from pathlib import Path


class InputError(Exception):
    """The input file cannot be read as a CSV."""


def read_records(path: Path) -> tuple[tuple[str, ...], ...]:
    """Return every CSV record of the file, header included, skipping blank lines."""
    # Boundary (declared in .shockharness.toml): one file read.
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise InputError(f"cannot read {path}: {exc.strerror}") from exc
    except UnicodeDecodeError as exc:
        raise InputError(f"{path} is not UTF-8 text: {exc.reason}") from exc
    rows = csv.reader(io.StringIO(text, newline=""), strict=True)
    # Boundary (declared in .shockharness.toml): one CSV parse.
    try:
        records = list(rows)
    except csv.Error as exc:
        raise InputError(f"{path} is not a valid CSV file: {exc}") from exc
    return tuple(tuple(record) for record in records if record)
