"""Cleaning of a whole contacts table: validation, normalization, merging."""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

from .fields import (
    VERIFIED,
    InvalidField,
    normalize_birthday,
    normalize_country,
    normalize_email,
    normalize_phone,
)

INPUT_COLUMNS = ("name", "email", "phone", "birthday", "country")
OUTPUT_COLUMNS = ("name", "email", "phone", "phone_status", "birthday", "country")
# Fields counted when deciding which of several duplicates is most complete.
_COMPLETENESS_FIELDS = ("email", "phone", "birthday", "country")


@dataclass
class Contact:
    row: int
    name: str
    email: str = ""
    phone: str = ""
    phone_status: str = ""
    birthday: str = ""
    country: str = ""

    def completeness(self) -> int:
        score = sum(1 for f in _COMPLETENESS_FIELDS if getattr(self, f))
        # A verified phone is worth slightly more than an unverified one.
        return score * 2 + (self.phone_status == VERIFIED)

    def as_row(self) -> dict[str, str]:
        return {col: getattr(self, col) for col in OUTPUT_COLUMNS}


@dataclass
class Report:
    rows_read: int = 0
    rows_written: int = 0
    rejected: list[dict] = field(default_factory=list)
    invalid_fields: list[dict] = field(default_factory=list)
    merged: list[dict] = field(default_factory=list)

    @property
    def has_issues(self) -> bool:
        """True when some row was rejected or had a field dropped."""
        return bool(self.rejected or self.invalid_fields)

    def to_dict(self) -> dict:
        return {
            "rows_read": self.rows_read,
            "rows_written": self.rows_written,
            "rejected": self.rejected,
            "invalid_fields": self.invalid_fields,
            "merged": self.merged,
        }


def clean_record(row: int, record: dict[str, str], report: Report,
                 today: _dt.date | None = None) -> Contact | None:
    """Normalize one input record; return None if the row is rejected."""
    name = (record.get("name") or "").strip()
    if not name:
        report.rejected.append({"row": row, "reason": "missing name"})
        return None

    contact = Contact(row=row, name=name, country=normalize_country(record.get("country") or ""))

    def attempt(field_name: str, func):
        raw = record.get(field_name) or ""
        try:
            return func(raw)
        except InvalidField as exc:
            report.invalid_fields.append(
                {"row": row, "field": field_name, "value": raw, "reason": str(exc)}
            )
            return None

    if (email := attempt("email", normalize_email)) is not None:
        contact.email = email
    if (phone := attempt("phone", lambda raw: normalize_phone(raw, contact.country))) is not None:
        contact.phone, contact.phone_status = phone
    if (birthday := attempt("birthday", lambda raw: normalize_birthday(raw, today))) is not None:
        contact.birthday = birthday
    return contact


def merge_duplicates(contacts: list[Contact], report: Report) -> list[Contact]:
    """Merge contacts sharing an email or a verified phone (transitively).

    The most complete record of each group is kept unchanged (ties go to the
    earliest row); output order follows each group's earliest row.
    """
    parent = list(range(len(contacts)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)

    seen: dict[tuple[str, str], int] = {}
    for i, c in enumerate(contacts):
        keys = []
        if c.email:
            keys.append(("email", c.email))
        if c.phone and c.phone_status == VERIFIED:
            keys.append(("phone", c.phone))
        for key in keys:
            if key in seen:
                union(seen[key], i)
            else:
                seen[key] = i

    groups: dict[int, list[int]] = {}
    for i in range(len(contacts)):
        groups.setdefault(find(i), []).append(i)

    result = []
    for root in sorted(groups):
        members = [contacts[i] for i in groups[root]]
        kept = max(members, key=lambda c: (c.completeness(), -c.row))
        if len(members) > 1:
            report.merged.append({
                "kept_row": kept.row,
                "merged_rows": [c.row for c in members if c is not kept],
            })
        result.append(kept)
    return result


def clean(records: list[tuple[int, dict[str, str]]],
          today: _dt.date | None = None) -> tuple[list[Contact], Report]:
    """Clean ``(row_number, record)`` pairs; return kept contacts and report."""
    report = Report(rows_read=len(records))
    contacts = [c for row, rec in records if (c := clean_record(row, rec, report, today))]
    kept = merge_duplicates(contacts, report)
    report.rows_written = len(kept)
    return kept, report
