"""Normalize, validate and merge contact rows."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from contactclean.errors import Rejected
from contactclean.fields import normalize_birthday, normalize_email
from contactclean.phone import Phone, PhoneRules, normalize_phone

COLUMNS = ("name", "email", "phone", "birthday", "country")
HEADER_ROW = 1
FIRST_DATA_ROW = HEADER_ROW + 1
PHONE_VERIFIED = "verified"
PHONE_UNVERIFIED = "unverified"
NO_PHONE_STATUS = ""


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
        """Number of optional fields that hold a value."""
        return sum(1 for value in (self.email, self.phone, self.birthday, self.country) if value)


@dataclass(frozen=True)
class RejectedRow:
    row: int
    reason: str


@dataclass(frozen=True)
class InvalidField:
    row: int
    field: str
    value: str
    reason: str


@dataclass(frozen=True)
class Merge:
    kept_row: int
    rows: tuple[int, ...]


@dataclass(frozen=True)
class CleanResult:
    rows_read: int
    contacts: tuple[Contact, ...]
    rejected: tuple[RejectedRow, ...]
    invalid_fields: tuple[InvalidField, ...]
    merges: tuple[Merge, ...]

    @property
    def all_rows_usable(self) -> bool:
        return not self.rejected and not self.invalid_fields


def _cell(record: Mapping[str, str | None], column: str) -> str:
    """A trimmed cell; a cell missing from a short row is empty."""
    value = record[column]
    if value is None:
        return ""
    return value.strip()


def _phone_fields(phone: Phone) -> tuple[str, str]:
    if phone.verified:
        return phone.value, PHONE_VERIFIED
    return phone.value, PHONE_UNVERIFIED


def _normalize_row(
    row: int, record: Mapping[str, str | None], rules: PhoneRules, invalid: list[InvalidField]
) -> Contact:
    """Build a contact from a named row; invalid optional fields are appended to `invalid` and left empty."""
    raw = {column: _cell(record, column) for column in COLUMNS}
    country = raw["country"].upper()
    email = ""
    if raw["email"]:
        normalized_email = normalize_email(raw["email"])
        if isinstance(normalized_email, Rejected):
            invalid.append(InvalidField(row, "email", raw["email"], normalized_email.reason))
        else:
            email = normalized_email
    phone, phone_status = "", NO_PHONE_STATUS
    if raw["phone"]:
        normalized_phone = normalize_phone(raw["phone"], country, rules)
        if isinstance(normalized_phone, Rejected):
            invalid.append(InvalidField(row, "phone", raw["phone"], normalized_phone.reason))
        else:
            phone, phone_status = _phone_fields(normalized_phone)
    birthday = ""
    if raw["birthday"]:
        normalized_birthday = normalize_birthday(raw["birthday"])
        if isinstance(normalized_birthday, Rejected):
            invalid.append(InvalidField(row, "birthday", raw["birthday"], normalized_birthday.reason))
        else:
            birthday = normalized_birthday
    return Contact(row, raw["name"], email, phone, phone_status, birthday, country)


def _merge_keys(contact: Contact) -> tuple[str, ...]:
    keys = []
    if contact.email:
        keys.append("email:" + contact.email)
    if contact.phone_status == PHONE_VERIFIED:
        keys.append("phone:" + contact.phone)
    return tuple(keys)


def _groups(contacts: Sequence[Contact]) -> list[list[Contact]]:
    """Group contacts that share an email or a verified phone, directly or through others."""
    parent = list(range(len(contacts)))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    owner_of_key: dict[str, int] = {}
    for index, contact in enumerate(contacts):
        for key in _merge_keys(contact):
            if key in owner_of_key:
                parent[root(index)] = root(owner_of_key[key])
            else:
                owner_of_key[key] = index
    groups: dict[int, list[Contact]] = {}
    for index, contact in enumerate(contacts):
        groups.setdefault(root(index), []).append(contact)
    return sorted(groups.values(), key=lambda group: group[0].row)


def _most_complete(group: Sequence[Contact]) -> Contact:
    """The contact with the most filled fields; the earliest row wins a tie."""
    return min(group, key=lambda contact: (-contact.completeness(), contact.row))


def clean(records: Sequence[Mapping[str, str | None]], rules: PhoneRules) -> CleanResult:
    """Clean rows read from the CSV, in file order."""
    rejected: list[RejectedRow] = []
    invalid: list[InvalidField] = []
    contacts: list[Contact] = []
    for row, record in enumerate(records, start=FIRST_DATA_ROW):
        if not _cell(record, "name"):
            rejected.append(RejectedRow(row, "name is missing"))
            continue
        contacts.append(_normalize_row(row, record, rules, invalid))
    kept: list[Contact] = []
    merges: list[Merge] = []
    for group in _groups(contacts):
        winner = _most_complete(group)
        kept.append(winner)
        if len(group) > 1:
            merges.append(Merge(kept_row=winner.row, rows=tuple(contact.row for contact in group)))
    if len(kept) + sum(len(merge.rows) - 1 for merge in merges) != len(contacts):
        raise AssertionError("merging lost or duplicated contacts")
    return CleanResult(len(records), tuple(kept), tuple(rejected), tuple(invalid), tuple(merges))
