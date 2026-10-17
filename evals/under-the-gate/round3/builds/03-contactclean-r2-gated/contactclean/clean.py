"""Turn parsed CSV records into cleaned, merged contacts and a report."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from contactclean.normalize import (
    PHONE_VERIFIED,
    PhoneRule,
    normalize_birthday,
    normalize_country,
    normalize_email,
    normalize_phone,
)

NAME = "name"
EMAIL = "email"
PHONE = "phone"
BIRTHDAY = "birthday"
COUNTRY = "country"
INPUT_COLUMNS = (NAME, EMAIL, PHONE, BIRTHDAY, COUNTRY)
REQUIRED_COLUMNS = frozenset({NAME})
HEADER_ROW_NUMBER = 1  # rows are numbered as in a spreadsheet: the header is row 1


class InputFormatError(Exception):
    """The input is not a contacts CSV this tool can read."""


@dataclass(frozen=True)
class Contact:
    row: int
    name: str
    email: str
    phone: str
    phone_status: str
    birthday: str
    country: str

    def completeness(self) -> int:
        return sum(1 for value in (self.email, self.phone, self.birthday, self.country) if value)


@dataclass(frozen=True)
class Rejection:
    row: int
    reason: str


@dataclass(frozen=True)
class FieldIssue:
    row: int
    field: str
    value: str
    reason: str


@dataclass(frozen=True)
class Merge:
    kept_row: int
    merged_rows: tuple[int, ...]
    reason: str


@dataclass(frozen=True)
class CleanResult:
    contacts: tuple[Contact, ...]
    rejections: tuple[Rejection, ...]
    field_issues: tuple[FieldIssue, ...]
    merges: tuple[Merge, ...]
    rows_read: int

    def all_rows_usable(self) -> bool:
        return not self.rejections and not self.field_issues


def column_positions(header: Sequence[str]) -> Mapping[str, int]:
    """Map each known input column to its index; a missing required column is an error."""
    names = [cell.strip().lower() for cell in header]
    positions = {name: index for index, name in enumerate(names) if name in INPUT_COLUMNS}
    if len(positions) != len([name for name in names if name in INPUT_COLUMNS]):
        raise InputFormatError("the header names a column more than once")
    missing = sorted(REQUIRED_COLUMNS - positions.keys())
    if missing:
        raise InputFormatError(f"the header has no {', '.join(missing)} column")
    return positions


def cell(record: Sequence[str], positions: Mapping[str, int], column: str) -> str:
    """The raw value of a column; an absent column or a short record reads as empty."""
    if column not in positions or positions[column] >= len(record):
        return ""
    return record[positions[column]]


def clean_records(records: Sequence[Sequence[str]], rules: Mapping[str, PhoneRule]) -> CleanResult:
    """Normalize, validate and merge the records; records[0] is the header."""
    if not records:
        raise InputFormatError("the input is empty: it has no header row")
    positions = column_positions(records[0])
    header_width = len(records[0])
    contacts: list[Contact] = []
    rejections: list[Rejection] = []
    issues: list[FieldIssue] = []
    rows_read = 0
    for offset, record in enumerate(records[1:]):
        row = HEADER_ROW_NUMBER + offset + 1
        if not any(value.strip() for value in record):
            continue
        rows_read += 1
        if len(record) > header_width:
            rejections.append(Rejection(row=row, reason=f"row has {len(record)} fields, the header has {header_width}"))
            continue
        name = cell(record, positions, NAME).strip()
        if not name:
            rejections.append(Rejection(row=row, reason="row has no name"))
            continue
        contacts.append(clean_row(row, name, record, positions, rules, issues))
    contacts_kept, merges = merge_duplicates(contacts)
    return CleanResult(
        contacts=tuple(contacts_kept),
        rejections=tuple(rejections),
        field_issues=tuple(issues),
        merges=tuple(merges),
        rows_read=rows_read,
    )


def clean_row(
    row: int,
    name: str,
    record: Sequence[str],
    positions: Mapping[str, int],
    rules: Mapping[str, PhoneRule],
    issues: list[FieldIssue],
) -> Contact:
    """Normalize one named row; each invalid field is appended to issues and left empty."""
    country = normalize_country(cell(record, positions, COUNTRY))
    raw_email = cell(record, positions, EMAIL)
    raw_phone = cell(record, positions, PHONE)
    raw_birthday = cell(record, positions, BIRTHDAY)
    email = normalize_email(raw_email)
    phone = normalize_phone(raw_phone, country, rules)
    birthday = normalize_birthday(raw_birthday)
    for field, raw, problem in (
        (EMAIL, raw_email, email.problem),
        (PHONE, raw_phone, phone.problem),
        (BIRTHDAY, raw_birthday, birthday.problem),
    ):
        if problem is not None:
            issues.append(FieldIssue(row=row, field=field, value=raw.strip(), reason=problem))
    return Contact(
        row=row,
        name=name,
        email=email.value,
        phone=phone.value,
        phone_status=phone.status,
        birthday=birthday.value,
        country=country,
    )


def merge_keys(contact: Contact) -> list[tuple[str, str]]:
    keys = []
    if contact.email:
        keys.append((EMAIL, contact.email))
    if contact.phone and contact.phone_status == PHONE_VERIFIED:
        keys.append((PHONE, contact.phone))
    return keys


class Groups:
    """Union-find over contact indexes."""

    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def root(self, index: int) -> int:
        while self.parent[index] != index:
            self.parent[index] = self.parent[self.parent[index]]
            index = self.parent[index]
        return index

    def join(self, first: int, second: int) -> None:
        self.parent[self.root(second)] = self.root(first)


def merge_duplicates(contacts: Sequence[Contact]) -> tuple[list[Contact], list[Merge]]:
    """Group contacts sharing an email or a verified phone; keep the most complete of each group."""
    groups = Groups(len(contacts))
    first_with_key: dict[tuple[str, str], int] = {}
    links: list[tuple[int, str]] = []
    for index, contact in enumerate(contacts):
        for key in merge_keys(contact):
            if key in first_with_key:
                groups.join(first_with_key[key], index)
                links.append((index, key[0]))
            else:
                first_with_key[key] = index

    members_by_root: dict[int, list[Contact]] = {}
    for index, contact in enumerate(contacts):
        members_by_root.setdefault(groups.root(index), []).append(contact)
    fields_by_root: dict[int, set[str]] = {}
    for index, field in links:
        fields_by_root.setdefault(groups.root(index), set()).add(field)

    kept: list[Contact] = []
    merges: list[Merge] = []
    for group_root, members in members_by_root.items():
        best = max(members, key=lambda member: (member.completeness(), -member.row))
        kept.append(best)
        if group_root in fields_by_root:
            merges.append(
                Merge(
                    kept_row=best.row,
                    merged_rows=tuple(sorted(member.row for member in members if member is not best)),
                    reason="same " + " or ".join(sorted(fields_by_root[group_root])),
                )
            )
    kept.sort(key=lambda contact: contact.row)
    return kept, merges
