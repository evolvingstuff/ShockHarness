"""Turn raw rows into cleaned contacts, field problems, rejections and merges."""

from dataclasses import dataclass
from datetime import date

from contactclean.model import (
    Contact,
    FieldProblem,
    Invalid,
    Merge,
    PhoneRules,
    PhoneStatus,
    RawRow,
    Rejection,
)
from contactclean.normalize import (
    EMPTY_PHONE,
    normalize_birthday,
    normalize_country,
    normalize_email,
    normalize_phone,
    normalize_text,
)


@dataclass(frozen=True)
class CleanResult:
    contacts: tuple[Contact, ...]
    problems: tuple[FieldProblem, ...]
    rejections: tuple[Rejection, ...]
    merges: tuple[Merge, ...]
    rows_read: int

    def every_row_usable(self) -> bool:
        return not self.problems and not self.rejections


def _field[T](row: RawRow, field: str, normalized: T | Invalid, empty: T, problems: list[FieldProblem]) -> T:
    """The normalized value, or `empty` with a problem recorded when the value is invalid."""
    if isinstance(normalized, Invalid):
        problems.append(FieldProblem(row=row.row, field=field, value=row.fields[field].strip(), reason=normalized.reason))
        return empty
    return normalized


def clean_row(row: RawRow, rules: PhoneRules, today: date) -> tuple[Contact | None, list[FieldProblem]]:
    """The cleaned contact (None when the row has no name) and the problems of its fields."""
    name = normalize_text(row.fields["name"])
    if name == "":
        return None, []
    fields = row.fields
    problems: list[FieldProblem] = []
    email = _field(row, "email", normalize_email(fields["email"]), "", problems)
    country = _field(row, "country", normalize_country(fields["country"]), "", problems)
    phone = _field(row, "phone", normalize_phone(fields["phone"], country, rules), EMPTY_PHONE, problems)
    birthday = _field(row, "birthday", normalize_birthday(fields["birthday"], today), "", problems)
    contact = Contact(
        row=row.row,
        name=name,
        email=email,
        phone=phone.value,
        phone_status=phone.status,
        birthday=birthday,
        country=country,
    )
    return contact, problems


def _merge_keys(contact: Contact) -> list[str]:
    keys = []
    if contact.email != "":
        keys.append(f"email {contact.email}")
    if contact.phone_status is PhoneStatus.VERIFIED:
        keys.append(f"phone {contact.phone}")
    return keys


def _groups(contacts: list[Contact]) -> list[list[int]]:
    """Indices of contacts that share an email or a verified phone, transitively, in row order."""
    parent = list(range(len(contacts)))

    def root(index: int) -> int:
        while parent[index] != index:
            index = parent[index]
        return index

    first_with_key: dict[str, int] = {}
    for index, contact in enumerate(contacts):
        for key in _merge_keys(contact):
            if key in first_with_key:
                parent[root(index)] = root(first_with_key[key])
            else:
                first_with_key[key] = index
    groups: dict[int, list[int]] = {}
    for index in range(len(contacts)):
        groups.setdefault(root(index), []).append(index)
    return sorted(groups.values(), key=lambda group: group[0])


def merge_duplicates(contacts: list[Contact]) -> tuple[tuple[Contact, ...], tuple[Merge, ...]]:
    """Keep the most complete contact of each duplicate group (the earliest row on a tie)."""
    kept: list[Contact] = []
    merges: list[Merge] = []
    for group in _groups(contacts):
        members = [contacts[index] for index in group]
        best = max(members, key=lambda contact: (contact.completeness(), -contact.row))
        kept.append(best)
        if len(members) > 1:
            shared = sorted({key for member in members for key in _merge_keys(member)} & _shared_keys(members))
            merges.append(
                Merge(
                    kept_row=best.row,
                    merged_rows=tuple(member.row for member in members if member is not best),
                    reason="same " + ", ".join(shared),
                )
            )
    kept.sort(key=lambda contact: contact.row)
    return tuple(kept), tuple(merges)


def _shared_keys(members: list[Contact]) -> set[str]:
    seen: set[str] = set()
    shared: set[str] = set()
    for member in members:
        keys = set(_merge_keys(member))
        shared |= keys & seen
        seen |= keys
    return shared


def clean(rows: tuple[RawRow, ...], rules: PhoneRules, today: date) -> CleanResult:
    contacts: list[Contact] = []
    problems: list[FieldProblem] = []
    rejections: list[Rejection] = []
    for row in rows:
        contact, row_problems = clean_row(row, rules, today)
        if contact is None:
            rejections.append(Rejection(row=row.row, reason="row has no name"))
            continue
        contacts.append(contact)
        problems.extend(row_problems)
    kept, merges = merge_duplicates(contacts)
    return CleanResult(
        contacts=kept,
        problems=tuple(problems),
        rejections=tuple(rejections),
        merges=merges,
        rows_read=len(rows),
    )


def report(result: CleanResult) -> dict[str, object]:
    return {
        "rows_read": result.rows_read,
        "rows_written": len(result.contacts),
        "rejected": [{"row": item.row, "reason": item.reason} for item in result.rejections],
        "invalid_fields": [
            {"row": item.row, "field": item.field, "value": item.value, "reason": item.reason}
            for item in result.problems
        ],
        "merged": [
            {"kept_row": item.kept_row, "merged_rows": list(item.merged_rows), "reason": item.reason}
            for item in result.merges
        ],
        "unverified_phones": [
            {"row": contact.row, "phone": contact.phone}
            for contact in result.contacts
            if contact.phone_status is PhoneStatus.UNVERIFIED
        ],
    }
