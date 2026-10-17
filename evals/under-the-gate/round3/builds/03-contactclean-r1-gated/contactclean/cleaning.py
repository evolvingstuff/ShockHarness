"""Turn parsed CSV records into cleaned contacts, report entries and merges."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from contactclean.normalize import (
    FieldError,
    PhonePlan,
    PhoneStatus,
    normalize_birthday,
    normalize_country,
    normalize_email,
    normalize_phone,
    normalize_text,
)

INPUT_COLUMNS = ("name", "email", "phone", "birthday", "country")
OUTPUT_COLUMNS = ("name", "email", "phone", "phone_status", "birthday", "country")
# Row numbers count the header as row 1, as a spreadsheet shows them.
HEADER_ROW = 1
FIRST_DATA_ROW = HEADER_ROW + 1
EMPTY = ""


@dataclass(frozen=True)
class Contact:
    row: int
    name: str
    email: str
    phone: str
    phone_status: str
    birthday: str
    country: str

    def filled_fields(self) -> int:
        return sum(1 for column in OUTPUT_COLUMNS if getattr(self, column) != EMPTY)

    def as_output_row(self) -> dict[str, str]:
        return {column: getattr(self, column) for column in OUTPUT_COLUMNS}


@dataclass(frozen=True)
class Rejection:
    row: int
    reason: str


@dataclass(frozen=True)
class FieldProblem:
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
    rejected: tuple[Rejection, ...]
    invalid_fields: tuple[FieldProblem, ...]
    merges: tuple[Merge, ...]
    rows_read: int

    @property
    def every_row_usable(self) -> bool:
        return not self.rejected and not self.invalid_fields


def _header_names(header: Sequence[str]) -> list[str]:
    return [normalize_text(column).lower() for column in header]


def missing_columns(header: Sequence[str]) -> tuple[str, ...]:
    """The input columns the header does not provide; empty when the header is usable."""
    names = _header_names(header)
    return tuple(column for column in INPUT_COLUMNS if column not in names)


def column_positions(header: Sequence[str]) -> Mapping[str, int]:
    """Index of every input column in a header that missing_columns accepted."""
    names = _header_names(header)
    return {column: names.index(column) for column in INPUT_COLUMNS}


def clean_records(
    header: Sequence[str], data: Sequence[Sequence[str]], plans: Mapping[str, PhonePlan]
) -> CleanResult:
    """Clean every data record; raises ValueError when the header lacks an input column."""
    missing = missing_columns(header)
    if missing:
        raise ValueError(f"header lacks column(s): {', '.join(missing)}")
    positions = column_positions(header)
    contacts: list[Contact] = []
    rejected: list[Rejection] = []
    problems: list[FieldProblem] = []
    rows_read = 0
    for row, record in enumerate(data, start=FIRST_DATA_ROW):
        if not record:
            continue
        rows_read += 1
        if len(record) != len(header):
            rejected.append(Rejection(row, f"expected {len(header)} fields, found {len(record)}"))
            continue
        values = {column: record[index] for column, index in positions.items()}
        name = normalize_text(values["name"])
        if name == EMPTY:
            rejected.append(Rejection(row, "name is missing"))
            continue
        contacts.append(_clean_contact(row, name, values, plans, problems))
    merged, merges = merge_duplicates(contacts)
    return CleanResult(
        contacts=merged,
        rejected=tuple(rejected),
        invalid_fields=tuple(problems),
        merges=merges,
        rows_read=rows_read,
    )


def _clean_contact(
    row: int,
    name: str,
    values: Mapping[str, str],
    plans: Mapping[str, PhonePlan],
    problems: list[FieldProblem],
) -> Contact:
    """Build the contact for one row; appends each invalid field to problems (the caller's list)."""
    country = normalize_country(values["country"])
    raw_email = normalize_text(values["email"])
    raw_phone = normalize_text(values["phone"])
    raw_birthday = normalize_text(values["birthday"])
    email = EMPTY
    if raw_email != EMPTY:
        email = _accept_text(normalize_email(raw_email), row, "email", raw_email, problems)
    phone = EMPTY
    phone_status = EMPTY
    if raw_phone != EMPTY:
        parsed = normalize_phone(raw_phone, country, plans)
        if isinstance(parsed, FieldError):
            problems.append(FieldProblem(row, "phone", raw_phone, parsed.reason))
        else:
            phone = parsed.number
            phone_status = parsed.status.value
    birthday = EMPTY
    if raw_birthday != EMPTY:
        birthday = _accept_text(normalize_birthday(raw_birthday), row, "birthday", raw_birthday, problems)
    return Contact(
        row=row,
        name=name,
        email=email,
        phone=phone,
        phone_status=phone_status,
        birthday=birthday,
        country=country,
    )


def _accept_text(
    result: str | FieldError, row: int, field: str, raw: str, problems: list[FieldProblem]
) -> str:
    """The normalized value, or EMPTY after recording the problem: an invalid field is dropped from the row."""
    if isinstance(result, FieldError):
        problems.append(FieldProblem(row, field, raw, result.reason))
        return EMPTY
    return result


def merge_duplicates(contacts: Sequence[Contact]) -> tuple[tuple[Contact, ...], tuple[Merge, ...]]:
    """Merge contacts sharing an email or a verified phone, keeping the most complete record of each group."""
    parent = {contact.row: contact.row for contact in contacts}

    def root(row: int) -> int:
        while parent[row] != row:
            row = parent[row]
        return row

    owners: dict[str, int] = {}
    for contact in contacts:
        for key in _merge_keys(contact):
            if key not in owners:
                owners[key] = contact.row
                continue
            first, second = root(owners[key]), root(contact.row)
            parent[max(first, second)] = min(first, second)
    groups: dict[int, list[Contact]] = {}
    for contact in contacts:
        group_root = root(contact.row)
        if group_root not in groups:
            groups[group_root] = []
        groups[group_root].append(contact)
    kept: list[Contact] = []
    merges: list[Merge] = []
    for members in groups.values():
        best = max(members, key=lambda contact: (contact.filled_fields(), -contact.row))
        kept.append(best)
        if len(members) > 1:
            merges.append(
                Merge(
                    kept_row=best.row,
                    merged_rows=tuple(sorted(contact.row for contact in members)),
                    reason=", ".join(_shared_keys(members)),
                )
            )
    kept.sort(key=lambda contact: contact.row)
    if len(kept) + sum(len(merge.merged_rows) - 1 for merge in merges) != len(contacts):
        raise AssertionError("merging lost or duplicated contacts")
    return tuple(kept), tuple(merges)


def _shared_keys(members: Sequence[Contact]) -> tuple[str, ...]:
    """The merge keys held by more than one member of a group, sorted."""
    seen: set[str] = set()
    shared: set[str] = set()
    for contact in members:
        for key in _merge_keys(contact):
            if key in seen:
                shared.add(key)
            seen.add(key)
    if not shared:
        raise AssertionError("a merged group always shares at least one key")
    return tuple(sorted(shared))


def _merge_keys(contact: Contact) -> tuple[str, ...]:
    keys = []
    if contact.email != EMPTY:
        keys.append(f"same email {contact.email}")
    if contact.phone_status == PhoneStatus.VERIFIED.value:
        keys.append(f"same phone {contact.phone}")
    return tuple(keys)
