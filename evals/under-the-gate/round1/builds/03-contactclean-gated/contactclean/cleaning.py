"""Row cleaning and merging."""

from dataclasses import dataclass, replace
from typing import Mapping, Sequence

from contactclean.fields import (
    STATUS_NONE,
    STATUS_VERIFIED,
    normalize_birthday,
    normalize_country,
    normalize_email,
    normalize_phone,
)

OPTIONAL_COLUMNS = ("email", "phone", "birthday", "country")
ACTION_REJECTED = "row_rejected"
ACTION_FIELD_DROPPED = "field_dropped"


@dataclass(frozen=True)
class Contact:
    row: int
    name: str
    email: str
    phone: str
    phone_status: str
    birthday: str
    country: str


@dataclass(frozen=True)
class Issue:
    row: int
    field: str
    action: str
    reason: str


@dataclass(frozen=True)
class Merge:
    kept_row: int
    rows: tuple[int, ...]


@dataclass(frozen=True)
class CleanResult:
    contacts: tuple[Contact, ...]
    issues: tuple[Issue, ...]
    merges: tuple[Merge, ...]


def cell(record: Mapping[str, str], column: str) -> str:
    if column not in record:
        return ""
    return record[column].strip()


def clean_record(row: int, record: Mapping[str, str]) -> tuple[Contact | None, list[Issue]]:
    name = cell(record, "name")
    if not name:
        return None, [Issue(row, "name", ACTION_REJECTED, "name is missing")]
    country = normalize_country(cell(record, "country"))
    outcomes = {
        "email": normalize_email(cell(record, "email")),
        "phone": normalize_phone(cell(record, "phone"), country),
        "birthday": normalize_birthday(cell(record, "birthday")),
    }
    issues = [
        Issue(row, field, ACTION_FIELD_DROPPED, outcome.problem)
        for field, outcome in outcomes.items()
        if outcome.problem is not None
    ]
    contact = Contact(
        row=row,
        name=name,
        email=outcomes["email"].value,
        phone=outcomes["phone"].value,
        phone_status=outcomes["phone"].status,
        birthday=outcomes["birthday"].value,
        country=country,
    )
    return contact, issues


def completeness(contact: Contact) -> int:
    values = (contact.email, contact.phone, contact.birthday, contact.country)
    return sum(1 for value in values if value)


def merge_keys(contact: Contact) -> list[tuple[str, str]]:
    keys = []
    if contact.email:
        keys.append(("email", contact.email))
    if contact.phone and contact.phone_status == STATUS_VERIFIED:
        keys.append(("phone", contact.phone))
    return keys


def group_contacts(contacts: Sequence[Contact]) -> list[list[Contact]]:
    """Group contacts sharing an email or a verified phone, transitively, in first-row order."""
    parent = list(range(len(contacts)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    owner: dict[tuple[str, str], int] = {}
    for index, contact in enumerate(contacts):
        for key in merge_keys(contact):
            if key in owner:
                parent[find(index)] = find(owner[key])
            else:
                owner[key] = index
    groups: dict[int, list[Contact]] = {}
    for index, contact in enumerate(contacts):
        groups.setdefault(find(index), []).append(contact)
    return sorted(groups.values(), key=lambda members: members[0].row)


def merge_group(members: Sequence[Contact]) -> Contact:
    merged = max(members, key=completeness)
    for other in members:
        if not merged.email:
            merged = replace(merged, email=other.email)
        if not merged.phone:
            merged = replace(merged, phone=other.phone, phone_status=other.phone_status)
        if not merged.birthday:
            merged = replace(merged, birthday=other.birthday)
        if not merged.country:
            merged = replace(merged, country=other.country)
    return merged


def clean(records: Sequence[Mapping[str, str]]) -> CleanResult:
    usable: list[Contact] = []
    issues: list[Issue] = []
    for row, record in enumerate(records, start=1):
        contact, row_issues = clean_record(row, record)
        issues.extend(row_issues)
        if contact is not None:
            usable.append(contact)
    contacts: list[Contact] = []
    merges: list[Merge] = []
    for members in group_contacts(usable):
        merged = merge_group(members)
        contacts.append(merged)
        if len(members) > 1:
            merges.append(Merge(merged.row, tuple(member.row for member in members)))
    return CleanResult(tuple(contacts), tuple(issues), tuple(merges))
