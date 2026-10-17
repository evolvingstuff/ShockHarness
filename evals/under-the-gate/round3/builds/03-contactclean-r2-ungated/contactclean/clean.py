"""Row cleaning and duplicate merging."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Mapping

from contactclean.normalize import (
    InvalidValue,
    normalize_birthday,
    normalize_email,
    normalize_phone,
)

INPUT_FIELDS = ("name", "email", "phone", "birthday", "country")
OUTPUT_FIELDS = ("name", "email", "phone", "phone_status", "birthday", "country")


@dataclass
class Contact:
    row: int
    name: str
    email: str = ""
    phone: str = ""
    phone_verified: bool = False
    birthday: str = ""
    country: str = ""

    def completeness(self) -> int:
        return sum(bool(v) for v in (self.email, self.phone, self.birthday, self.country))

    def as_output(self) -> dict[str, str]:
        status = ""
        if self.phone:
            status = "verified" if self.phone_verified else "unverified"
        return {
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "phone_status": status,
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
    def all_usable(self) -> bool:
        return not self.rejected and not self.invalid_fields

    def report(self) -> dict:
        return {
            "rows_read": self.rows_read,
            "rows_written": len(self.contacts),
            "rejected": self.rejected,
            "invalid_fields": self.invalid_fields,
            "merged": self.merged,
        }


def _clean_row(row_num: int, raw: Mapping[str, str | None], result: CleanResult,
               today: date | None) -> Contact | None:
    values = {k: (raw.get(k) or "").strip() for k in INPUT_FIELDS}
    if not values["name"]:
        result.rejected.append({"row": row_num, "reason": "missing name"})
        return None

    contact = Contact(row=row_num, name=values["name"], country=values["country"].upper())

    def report(field_name: str, err: InvalidValue) -> None:
        result.invalid_fields.append({
            "row": row_num,
            "field": field_name,
            "value": values[field_name],
            "reason": str(err),
        })

    if values["email"]:
        try:
            contact.email = normalize_email(values["email"])
        except InvalidValue as err:
            report("email", err)
    if values["phone"]:
        try:
            phone = normalize_phone(values["phone"], contact.country)
            contact.phone, contact.phone_verified = phone.value, phone.verified
        except InvalidValue as err:
            report("phone", err)
    if values["birthday"]:
        try:
            contact.birthday = normalize_birthday(values["birthday"], today)
        except InvalidValue as err:
            report("birthday", err)
    return contact


def _merge(contacts: list[Contact], result: CleanResult) -> list[Contact]:
    """Group contacts sharing an email or verified phone (transitively)."""
    parent = list(range(len(contacts)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    first_seen: dict[tuple[str, str], int] = {}
    for i, c in enumerate(contacts):
        keys = []
        if c.email:
            keys.append(("email", c.email))
        if c.phone and c.phone_verified:
            keys.append(("phone", c.phone))
        for key in keys:
            if key in first_seen:
                parent[find(i)] = find(first_seen[key])
            else:
                first_seen[key] = i

    groups: dict[int, list[Contact]] = {}
    for i, c in enumerate(contacts):
        groups.setdefault(find(i), []).append(c)

    kept = []
    for group in groups.values():
        # Most complete wins; ties go to the earliest row.
        best = max(group, key=lambda c: (c.completeness(), -c.row))
        kept.append(best)
        if len(group) > 1:
            emails = {c.email for c in group if c.email}
            phones = {c.phone for c in group if c.phone and c.phone_verified}
            shared = []
            if len(emails) < sum(1 for c in group if c.email):
                shared.append("email")
            if len(phones) < sum(1 for c in group if c.phone and c.phone_verified):
                shared.append("phone")
            result.merged.append({
                "kept_row": best.row,
                "merged_rows": sorted(c.row for c in group if c is not best),
                "reason": "same " + " and ".join(shared),
            })
    kept.sort(key=lambda c: c.row)
    return kept


def clean_rows(rows: Iterable[Mapping[str, str | None]], first_row: int = 2,
               today: date | None = None) -> CleanResult:
    """Clean rows of a contacts CSV.

    Row numbers start at ``first_row`` (2 by default: the first data row after
    the header, as a spreadsheet would show it).
    """
    result = CleanResult()
    contacts = []
    for row_num, raw in enumerate(rows, start=first_row):
        result.rows_read += 1
        contact = _clean_row(row_num, raw, result, today)
        if contact is not None:
            contacts.append(contact)
    result.contacts = _merge(contacts, result)
    return result
