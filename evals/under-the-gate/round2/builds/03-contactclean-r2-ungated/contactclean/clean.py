"""Clean a list of contact rows: normalize, reject, report and merge."""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

from .normalize import (
    InvalidValue,
    clean_text,
    normalize_birthday,
    normalize_country,
    normalize_email,
    normalize_phone,
)

INPUT_FIELDS = ["name", "email", "phone", "birthday", "country"]
OUTPUT_FIELDS = ["name", "email", "phone", "phone_status", "birthday", "country"]

# The CSV header is spreadsheet row 1, so the first contact is row 2.
FIRST_DATA_ROW = 2


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
        return sum(bool(v) for v in (self.name, self.email, self.phone, self.birthday, self.country))

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
class Result:
    total_rows: int = 0
    contacts: list[Contact] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)
    merged: list[dict] = field(default_factory=list)

    @property
    def all_usable(self) -> bool:
        return not self.rejected and not self.issues

    def report(self) -> dict:
        return {
            "summary": {
                "rows": self.total_rows,
                "written": len(self.contacts),
                "rejected": len(self.rejected),
                "invalid_fields": len(self.issues),
                "merged_groups": len(self.merged),
            },
            "rejected": self.rejected,
            "invalid_fields": self.issues,
            "merged": self.merged,
        }


def _parse_row(row_number: int, raw: dict, result: Result, today: _dt.date) -> Contact | None:
    values = {name: clean_text(raw.get(name)) for name in INPUT_FIELDS}
    if not values["name"]:
        result.rejected.append({"row": row_number, "reason": "missing name"})
        return None

    contact = Contact(row=row_number, name=values["name"], country=normalize_country(values["country"]))

    def attempt(field_name: str, fn) -> None:
        value = values[field_name]
        if not value:
            return
        try:
            fn(value)
        except InvalidValue as exc:
            result.issues.append(
                {"row": row_number, "field": field_name, "value": value, "reason": str(exc)}
            )

    def set_email(v):
        contact.email = normalize_email(v)

    def set_phone(v):
        contact.phone, contact.phone_verified = normalize_phone(v, contact.country)

    def set_birthday(v):
        contact.birthday = normalize_birthday(v, today)

    attempt("email", set_email)
    attempt("phone", set_phone)
    attempt("birthday", set_birthday)
    return contact


def _merge(contacts: list[Contact], result: Result) -> list[Contact]:
    """Group contacts sharing an email or a verified phone (transitively)."""
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
    for members in groups.values():
        group = [contacts[i] for i in members]
        # Most complete wins; ties go to a verified phone, then the earliest row.
        best = max(group, key=lambda c: (c.completeness(), c.phone_verified, -c.row))
        kept.append(best)
        if len(group) > 1:
            shared = set()
            emails = [c.email for c in group if c.email]
            phones = [c.phone for c in group if c.phone and c.phone_verified]
            if len(emails) != len(set(emails)):
                shared.add("email")
            if len(phones) != len(set(phones)):
                shared.add("phone")
            result.merged.append(
                {
                    "kept_row": best.row,
                    "merged_rows": sorted(c.row for c in group if c is not best),
                    "rows": sorted(c.row for c in group),
                    "matched_on": sorted(shared),
                }
            )
    kept.sort(key=lambda c: c.row)
    result.merged.sort(key=lambda m: m["rows"][0])
    return kept


def clean_rows(rows, today: _dt.date | None = None) -> Result:
    """Clean an iterable of dicts (as from csv.DictReader)."""
    today = today or _dt.date.today()
    result = Result()
    parsed = []
    for offset, raw in enumerate(rows):
        result.total_rows += 1
        contact = _parse_row(FIRST_DATA_ROW + offset, raw, result, today)
        if contact is not None:
            parsed.append(contact)
    result.contacts = _merge(parsed, result)
    return result
