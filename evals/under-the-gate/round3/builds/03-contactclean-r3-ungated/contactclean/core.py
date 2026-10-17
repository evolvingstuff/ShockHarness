"""Row cleaning, validation and merging."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, TextIO

from .normalize import (
    InvalidValue,
    normalize_birthday,
    normalize_email,
    normalize_phone,
)

INPUT_COLUMNS = ("name", "email", "phone", "birthday", "country")
OUTPUT_COLUMNS = ("name", "email", "phone", "phone_status", "birthday", "country")
_COMPLETENESS_FIELDS = ("name", "email", "phone", "birthday", "country")


class InputError(Exception):
    """The input cannot be read as a contacts CSV."""


@dataclass
class Contact:
    row: int
    name: str
    email: str = ""
    phone: str = ""
    phone_verified: bool = False
    birthday: str = ""
    country: str = ""

    @property
    def phone_status(self) -> str:
        if not self.phone:
            return ""
        return "verified" if self.phone_verified else "unverified"

    def completeness(self) -> int:
        return sum(1 for f in _COMPLETENESS_FIELDS if getattr(self, f))

    def as_output(self) -> dict[str, str]:
        return {
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "phone_status": self.phone_status,
            "birthday": self.birthday,
            "country": self.country,
        }


@dataclass
class CleanResult:
    contacts: list[Contact] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    invalid_fields: list[dict] = field(default_factory=list)
    merged: list[dict] = field(default_factory=list)
    rows_read: int = 0

    @property
    def all_rows_usable(self) -> bool:
        return not self.rejected and not self.invalid_fields

    def report(self) -> dict:
        return {
            "summary": {
                "rows_read": self.rows_read,
                "contacts_written": len(self.contacts),
                "rows_rejected": len(self.rejected),
                "invalid_fields": len(self.invalid_fields),
                "merge_groups": len(self.merged),
            },
            "rejected": self.rejected,
            "invalid_fields": self.invalid_fields,
            "merged": self.merged,
        }


def _cell(raw: dict, key: str) -> str:
    value = raw.get(key)
    if value is None:
        return ""
    return value.strip()


def read_rows(stream: TextIO) -> Iterable[tuple[int, dict]]:
    """Yield ``(row_number, raw_dict)``; row numbers count the header as row 1."""
    reader = csv.DictReader(stream)
    try:
        fieldnames = reader.fieldnames
    except csv.Error as exc:
        raise InputError(f"malformed CSV: {exc}") from exc
    if fieldnames is None:
        raise InputError("input is empty (no header row)")
    normalized = [(f or "").strip().lower() for f in fieldnames]
    if "name" not in normalized:
        raise InputError("input has no 'name' column")
    reader.fieldnames = normalized
    row_number = 1
    try:
        for raw in reader:
            row_number += 1
            yield row_number, raw
    except csv.Error as exc:
        raise InputError(f"malformed CSV near row {row_number + 1}: {exc}") from exc


def clean(stream: TextIO, today: date | None = None) -> CleanResult:
    result = CleanResult()
    for row_number, raw in read_rows(stream):
        result.rows_read += 1
        values = {key: _cell(raw, key) for key in INPUT_COLUMNS}
        if not values["name"]:
            result.rejected.append({"row": row_number, "reason": "missing name"})
            continue

        contact = Contact(row=row_number, name=values["name"])
        contact.country = values["country"].upper()

        def invalid(field_name: str, exc: InvalidValue) -> None:
            result.invalid_fields.append({
                "row": row_number,
                "field": field_name,
                "value": values[field_name],
                "reason": str(exc),
            })

        if values["email"]:
            try:
                contact.email = normalize_email(values["email"])
            except InvalidValue as exc:
                invalid("email", exc)
        if values["phone"]:
            try:
                phone = normalize_phone(values["phone"], contact.country)
                contact.phone = phone.value
                contact.phone_verified = phone.verified
            except InvalidValue as exc:
                invalid("phone", exc)
        if values["birthday"]:
            try:
                contact.birthday = normalize_birthday(values["birthday"], today)
            except InvalidValue as exc:
                invalid("birthday", exc)

        result.contacts.append(contact)

    result.contacts, result.merged = merge_duplicates(result.contacts)
    return result


def merge_duplicates(contacts: list[Contact]) -> tuple[list[Contact], list[dict]]:
    """Merge contacts sharing an email or a verified phone (transitively).

    The most complete record of each group is kept (ties go to the earliest
    row); output keeps the order of each group's first row.
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
        if c.phone and c.phone_verified:
            keys.append(("phone", c.phone))
        for key in keys:
            if key in seen:
                union(seen[key], i)
            else:
                seen[key] = i

    groups: dict[int, list[int]] = {}
    for i in range(len(contacts)):
        groups.setdefault(find(i), []).append(i)

    kept: list[Contact] = []
    merged: list[dict] = []
    for root in sorted(groups):
        members = [contacts[i] for i in groups[root]]
        best = max(members, key=lambda c: (c.completeness(), -c.row))
        kept.append(best)
        if len(members) > 1:
            merged.append({
                "kept_row": best.row,
                "merged_rows": sorted(c.row for c in members if c is not best),
                "rows": sorted(c.row for c in members),
            })
    return kept, merged


def write_contacts(stream: TextIO, contacts: Iterable[Contact]) -> None:
    writer = csv.DictWriter(stream, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for c in contacts:
        writer.writerow(c.as_output())
