"""Row cleaning and duplicate merging."""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Iterable, Mapping

from .normalize import (
    InvalidValue,
    normalize_birthday,
    normalize_country,
    normalize_email,
    normalize_name,
    normalize_phone,
)

INPUT_COLUMNS = ("name", "email", "phone", "birthday", "country")
OUTPUT_COLUMNS = ("name", "email", "phone", "phone_status", "birthday", "country")
# Fields that count towards how "complete" a record is.
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

    @property
    def completeness(self) -> int:
        return sum(1 for f in _COMPLETENESS_FIELDS if getattr(self, f))

    def as_output(self) -> dict[str, str]:
        return {col: getattr(self, col) for col in OUTPUT_COLUMNS}


@dataclass
class Result:
    contacts: list[Contact] = field(default_factory=list)
    rows_read: int = 0
    rejected: list[dict] = field(default_factory=list)
    invalid_fields: list[dict] = field(default_factory=list)
    merged: list[dict] = field(default_factory=list)

    @property
    def all_rows_usable(self) -> bool:
        return not self.rejected and not self.invalid_fields

    def report(self) -> dict:
        return {
            "rows_read": self.rows_read,
            "rows_written": len(self.contacts),
            "rejected": self.rejected,
            "invalid_fields": self.invalid_fields,
            "merged": self.merged,
        }


def clean_row(
    row_number: int,
    raw: Mapping[str, str | None],
    result: Result,
    today: _dt.date | None = None,
) -> Contact | None:
    """Normalize one input row; record problems in ``result``."""

    def get(col: str) -> str:
        return raw.get(col) or ""

    name = normalize_name(get("name"))
    if not name:
        result.rejected.append({"row": row_number, "reason": "missing name"})
        return None

    contact = Contact(row=row_number, name=name, country=normalize_country(get("country")))

    def invalid(field_name: str, exc: InvalidValue) -> None:
        result.invalid_fields.append(
            {"row": row_number, "field": field_name, "value": get(field_name).strip(), "reason": str(exc)}
        )

    try:
        contact.email = normalize_email(get("email"))
    except InvalidValue as exc:
        invalid("email", exc)
    try:
        phone = normalize_phone(get("phone"), contact.country)
        if phone is not None:
            contact.phone, contact.phone_status = phone.value, phone.status
    except InvalidValue as exc:
        invalid("phone", exc)
    try:
        contact.birthday = normalize_birthday(get("birthday"), today)
    except InvalidValue as exc:
        invalid("birthday", exc)
    return contact


def merge_duplicates(contacts: list[Contact], result: Result) -> list[Contact]:
    """Merge contacts sharing an email or a verified phone (transitively).

    The most complete record of each group is kept (ties go to the earliest
    row); output order follows the kept record's row number.
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
        if c.phone and c.phone_status == "verified":
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
    for members in groups.values():
        group = [contacts[i] for i in members]
        best = max(group, key=lambda c: (c.completeness, -c.row))
        kept.append(best)
        if len(group) > 1:
            shared = _shared_keys(group)
            result.merged.append(
                {
                    "kept_row": best.row,
                    "merged_rows": sorted(c.row for c in group if c is not best),
                    "matched_on": shared,
                }
            )
    kept.sort(key=lambda c: c.row)
    result.merged.sort(key=lambda m: m["kept_row"])
    return kept


def _shared_keys(group: list[Contact]) -> list[str]:
    out = []
    emails = [c.email for c in group if c.email]
    if len(emails) != len(set(emails)):
        out.append("email")
    phones = [c.phone for c in group if c.phone and c.phone_status == "verified"]
    if len(phones) != len(set(phones)):
        out.append("phone")
    return out


def clean(
    rows: Iterable[tuple[int, Mapping[str, str | None]]],
    today: _dt.date | None = None,
) -> Result:
    """Clean ``(row_number, row_dict)`` pairs and merge duplicates."""
    result = Result()
    contacts = []
    for row_number, raw in rows:
        result.rows_read += 1
        contact = clean_row(row_number, raw, result, today)
        if contact is not None:
            contacts.append(contact)
    result.contacts = merge_duplicates(contacts, result)
    return result
