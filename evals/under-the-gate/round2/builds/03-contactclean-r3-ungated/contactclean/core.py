"""Normalization, validation and merging of contact rows.

Row numbers in the report are line numbers of the CSV record as a spreadsheet
would show them: the header is row 1, the first contact is row 2.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field

FIELDS = ("name", "email", "phone", "birthday", "country")
OUTPUT_FIELDS = ("name", "email", "phone", "phone_status", "birthday", "country")

VERIFIED = "verified"
UNVERIFIED = "unverified"


class InvalidValue(ValueError):
    """A non-empty field value that cannot be normalized."""


# --- email -------------------------------------------------------------------

_EMAIL_RE = re.compile(
    r"^[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$"
)


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if not email:
        return ""
    if not _EMAIL_RE.match(email):
        raise InvalidValue("not a valid email address")
    return email


# --- phone -------------------------------------------------------------------

# country -> (calling code, trunk prefix, allowed national-number lengths)
_PHONE_PLANS = {
    "US": ("1", "", (10,)),
    "CA": ("1", "", (10,)),
    "GB": ("44", "0", (9, 10)),
    "DE": ("49", "0", tuple(range(6, 12))),
    "FR": ("33", "0", (9,)),
}

_PHONE_CHARS_RE = re.compile(r"^\+?[\d\s().\-/]+$")


def normalize_phone(value: str, country: str) -> tuple[str, str]:
    """Return ``(phone, status)``; status is "verified", "unverified" or ""."""
    raw = value.strip()
    if not raw:
        return "", ""
    if not _PHONE_CHARS_RE.match(raw):
        raise InvalidValue("phone contains characters other than digits")
    international = raw.startswith("+")
    digits = re.sub(r"\D", "", raw)
    if international and digits.startswith("00"):
        raise InvalidValue("phone has both '+' and '00' prefixes")
    if not international and digits.startswith("00"):
        international, digits = True, digits[2:]

    plan = _PHONE_PLANS.get(country)
    if plan is None:
        if not 4 <= len(digits) <= 15:
            raise InvalidValue("phone has an implausible number of digits")
        return ("+" if international else "") + digits, UNVERIFIED

    code, trunk, lengths = plan
    if international:
        if not digits.startswith(code):
            raise InvalidValue(f"phone calling code does not match country {country}")
        national = digits[len(code):]
    else:
        national = digits
        if code == "1" and len(national) == 11 and national.startswith("1"):
            national = national[1:]
        elif trunk and national.startswith(trunk):
            national = national[len(trunk):]
    if trunk and national.startswith(trunk):
        raise InvalidValue(f"not a valid {country} phone number")
    if len(national) not in lengths:
        raise InvalidValue(f"not a valid {country} phone number")
    if code == "1" and national[0] in "01":
        raise InvalidValue(f"not a valid {country} phone number")
    return f"+{code}{national}", VERIFIED


# --- birthday ----------------------------------------------------------------

_ISO_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_SLASH_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def _make_date(year: int, month: int, day: int, today: _dt.date) -> _dt.date:
    try:
        date = _dt.date(year, month, day)
    except ValueError:
        raise InvalidValue("not a real calendar date") from None
    if date > today:
        raise InvalidValue("birthday is in the future")
    return date


def normalize_birthday(value: str, today: _dt.date | None = None) -> str:
    raw = value.strip()
    if not raw:
        return ""
    today = today or _dt.date.today()
    m = _ISO_RE.match(raw)
    if m:
        y, mo, d = map(int, m.groups())
        return _make_date(y, mo, d, today).isoformat()
    m = _SLASH_RE.match(raw)
    if not m:
        raise InvalidValue("birthday is not in YYYY-MM-DD, DD/MM/YYYY or MM/DD/YYYY format")
    a, b, y = map(int, m.groups())
    candidates = set()
    for day, month in ((a, b), (b, a)):  # DD/MM/YYYY, then MM/DD/YYYY
        try:
            candidates.add(_dt.date(y, month, day))
        except ValueError:
            pass
    if not candidates:
        raise InvalidValue("not a real calendar date")
    if len(candidates) > 1:
        raise InvalidValue("birthday is ambiguous between DD/MM/YYYY and MM/DD/YYYY")
    date = candidates.pop()
    return _make_date(date.year, date.month, date.day, today).isoformat()


# --- cleaning ----------------------------------------------------------------


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
        score = sum(bool(v) for v in (self.name, self.email, self.phone,
                                      self.birthday, self.country))
        return score + (self.phone_status == VERIFIED)

    def as_row(self) -> dict[str, str]:
        return {f: getattr(self, f) for f in OUTPUT_FIELDS}


@dataclass
class Result:
    contacts: list[Contact] = field(default_factory=list)
    rows_read: int = 0
    rejected: list[dict] = field(default_factory=list)
    invalid_fields: list[dict] = field(default_factory=list)
    merged: list[dict] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        """True when every row was used without rejection or invalid fields."""
        return not self.rejected and not self.invalid_fields

    def report(self) -> dict:
        return {
            "rows_read": self.rows_read,
            "rows_written": len(self.contacts),
            "rejected": self.rejected,
            "invalid_fields": self.invalid_fields,
            "merged": self.merged,
        }


def _clean_row(row_num: int, record: dict[str, str], result: Result,
               today: _dt.date | None) -> Contact | None:
    values = {f: (record.get(f) or "").strip() for f in FIELDS}
    if not values["name"]:
        result.rejected.append({"row": row_num, "reason": "missing name"})
        return None
    contact = Contact(row=row_num, name=values["name"],
                      country=values["country"].upper())

    def invalid(fld: str, exc: InvalidValue) -> None:
        result.invalid_fields.append(
            {"row": row_num, "field": fld, "value": values[fld], "reason": str(exc)})

    try:
        contact.email = normalize_email(values["email"])
    except InvalidValue as exc:
        invalid("email", exc)
    try:
        contact.phone, contact.phone_status = normalize_phone(values["phone"], contact.country)
    except InvalidValue as exc:
        invalid("phone", exc)
    try:
        contact.birthday = normalize_birthday(values["birthday"], today)
    except InvalidValue as exc:
        invalid("birthday", exc)
    return contact


def _merge(contacts: list[Contact], result: Result) -> list[Contact]:
    parent = list(range(len(contacts)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    seen: dict[tuple[str, str], int] = {}
    for i, c in enumerate(contacts):
        keys = []
        if c.email:
            keys.append(("email", c.email))
        if c.phone and c.phone_status == VERIFIED:
            keys.append(("phone", c.phone))
        for key in keys:
            if key in seen:
                a, b = find(seen[key]), find(i)
                if a != b:
                    parent[max(a, b)] = min(a, b)
            else:
                seen[key] = i

    groups: dict[int, list[Contact]] = {}
    for i, c in enumerate(contacts):
        groups.setdefault(find(i), []).append(c)

    kept = []
    for members in groups.values():
        # Most complete wins; on a tie the earliest row wins.
        best = max(members, key=lambda c: (c.completeness(), -c.row))
        kept.append(best)
        if len(members) > 1:
            result.merged.append({
                "kept_row": best.row,
                "merged_rows": sorted(c.row for c in members if c is not best),
            })
    kept.sort(key=lambda c: c.row)
    result.merged.sort(key=lambda m: m["kept_row"])
    return kept


def clean(records, today: _dt.date | None = None) -> Result:
    """Clean an iterable of dicts (as from csv.DictReader) into a Result."""
    result = Result()
    contacts = []
    for index, record in enumerate(records):
        result.rows_read += 1
        contact = _clean_row(index + 2, record, result, today)
        if contact is not None:
            contacts.append(contact)
    result.contacts = _merge(contacts, result)
    return result
