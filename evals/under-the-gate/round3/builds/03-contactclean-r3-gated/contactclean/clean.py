"""Turning CSV records into clean, merged contacts and a report of what could not be used."""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from contactclean import fields
from contactclean.birthday import normalize_birthday
from contactclean.emails import normalize_email
from contactclean.phone import PhonePlans, normalize_phone
from contactclean.reader import InputError
from contactclean.results import Invalid, Phone, Valid

# Row numbers follow a spreadsheet: the header is row 1, the first contact row 2.
HEADER_ROW = 1
FIRST_DATA_ROW = HEADER_ROW + 1


@dataclass(frozen=True)
class Contact:
    row: int
    name: str
    email: str
    phone: str
    phone_verified: bool
    birthday: str
    country: str

    def completeness(self) -> int:
        """Number of filled optional fields."""
        return sum(1 for value in (self.email, self.phone, self.birthday, self.country) if value)

    def as_output(self) -> dict[str, str]:
        status = ""
        if self.phone:
            status = fields.VERIFIED if self.phone_verified else fields.UNVERIFIED
        return {
            fields.NAME: self.name,
            fields.EMAIL: self.email,
            fields.PHONE: self.phone,
            fields.PHONE_STATUS: status,
            fields.BIRTHDAY: self.birthday,
            fields.COUNTRY: self.country,
        }


@dataclass(frozen=True)
class Rejected:
    row: int
    reason: str


@dataclass(frozen=True)
class InvalidField:
    row: int
    field: str
    reason: str


@dataclass(frozen=True)
class Merge:
    kept_row: int
    merged_rows: tuple[int, ...]
    reason: str


@dataclass(frozen=True)
class CleanResult:
    rows_read: int
    contacts: tuple[Contact, ...]
    rejected: tuple[Rejected, ...]
    invalid_fields: tuple[InvalidField, ...]
    merges: tuple[Merge, ...]

    def all_rows_usable(self) -> bool:
        return not self.rejected and not self.invalid_fields

    def report(self) -> dict[str, object]:
        return {
            "rows_read": self.rows_read,
            "rows_written": len(self.contacts),
            "rejected": [{"row": item.row, "reason": item.reason} for item in self.rejected],
            "invalid_fields": [
                {"row": item.row, "field": item.field, "reason": item.reason}
                for item in self.invalid_fields
            ],
            "merged": [
                {"kept_row": item.kept_row, "merged_rows": list(item.merged_rows), "reason": item.reason}
                for item in self.merges
            ],
        }


def column_positions(header: Sequence[str]) -> Mapping[str, int]:
    """Map each known column to its position; the name column is required."""
    positions: dict[str, int] = {}
    for position, column in enumerate(header):
        key = column.strip().lower()
        if key in positions:
            raise InputError(f"column {key!r} appears more than once in the header")
        if key in fields.INPUT_COLUMNS:
            positions[key] = position
    missing = fields.REQUIRED_COLUMNS - positions.keys()
    if missing:
        raise InputError(f"missing required column(s): {', '.join(sorted(missing))}")
    return positions


def _cell(record: Sequence[str], positions: Mapping[str, int], column: str) -> str:
    if column not in positions:
        return ""
    return record[positions[column]].strip()


def _parse_row(
    row: int,
    record: Sequence[str],
    positions: Mapping[str, int],
    plans: PhonePlans,
) -> tuple[Contact | Rejected, tuple[InvalidField, ...]]:
    name = _cell(record, positions, fields.NAME)
    if not name:
        return Rejected(row, "missing name"), ()
    country = _cell(record, positions, fields.COUNTRY).upper()
    problems: list[InvalidField] = []
    email = normalize_email(_cell(record, positions, fields.EMAIL))
    birthday = normalize_birthday(_cell(record, positions, fields.BIRTHDAY))
    phone = normalize_phone(_cell(record, positions, fields.PHONE), country, plans)
    for column, result in ((fields.EMAIL, email), (fields.BIRTHDAY, birthday), (fields.PHONE, phone)):
        if isinstance(result, Invalid):
            problems.append(InvalidField(row, column, result.reason))
    usable_phone = phone if isinstance(phone, Phone) else Phone("", verified=False)
    contact = Contact(
        row=row,
        name=name,
        email=email.value if isinstance(email, Valid) else "",
        phone=usable_phone.value,
        phone_verified=usable_phone.verified,
        birthday=birthday.value if isinstance(birthday, Valid) else "",
        country=country,
    )
    return contact, tuple(problems)


def _merge_keys(contact: Contact) -> tuple[str, ...]:
    keys = []
    if contact.email:
        keys.append(f"email {contact.email}")
    if contact.phone and contact.phone_verified:
        keys.append(f"phone {contact.phone}")
    return tuple(keys)


def _groups(contacts: Sequence[Contact]) -> list[list[int]]:
    """Indices of contacts sharing an email or a verified phone, directly or through others."""
    parent = list(range(len(contacts)))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    owner: dict[str, int] = {}
    for index, contact in enumerate(contacts):
        for key in _merge_keys(contact):
            if key in owner:
                parent[root(index)] = root(owner[key])
            else:
                owner[key] = index
    groups: dict[int, list[int]] = {}
    for index in range(len(contacts)):
        groups.setdefault(root(index), []).append(index)
    return sorted(groups.values(), key=lambda group: group[0])


def _shared_keys(group: Sequence[Contact]) -> list[str]:
    counts = Counter(key for contact in group for key in _merge_keys(contact))
    return [key for key, count in counts.items() if count > 1]


def merge_contacts(contacts: Sequence[Contact]) -> tuple[tuple[Contact, ...], tuple[Merge, ...]]:
    """Keep the most complete contact of each group (the earliest row on a tie)."""
    kept: list[Contact] = []
    merges: list[Merge] = []
    for indices in _groups(contacts):
        group = [contacts[index] for index in indices]
        best = max(group, key=lambda contact: (contact.completeness(), -contact.row))
        kept.append(best)
        if len(group) > 1:
            reason = "same " + ", ".join(_shared_keys(group))
            others = tuple(contact.row for contact in group if contact is not best)
            merges.append(Merge(kept_row=best.row, merged_rows=others, reason=reason))
    kept.sort(key=lambda contact: contact.row)
    return tuple(kept), tuple(merges)


def clean(records: Sequence[Sequence[str]], plans: PhonePlans) -> CleanResult:
    """Clean every record after the header; the header must name the columns."""
    if not records:
        raise InputError("the file is empty: expected a header row")
    header, *rows = records
    positions = column_positions(header)
    contacts: list[Contact] = []
    rejected: list[Rejected] = []
    invalid: list[InvalidField] = []
    for row, record in enumerate(rows, start=FIRST_DATA_ROW):
        if len(record) != len(header):
            rejected.append(Rejected(row, f"row has {len(record)} fields, the header has {len(header)}"))
            continue
        parsed, problems = _parse_row(row, record, positions, plans)
        invalid.extend(problems)
        if isinstance(parsed, Rejected):
            rejected.append(parsed)
        else:
            contacts.append(parsed)
    kept, merges = merge_contacts(contacts)
    return CleanResult(
        rows_read=len(rows),
        contacts=kept,
        rejected=tuple(rejected),
        invalid_fields=tuple(invalid),
        merges=merges,
    )
