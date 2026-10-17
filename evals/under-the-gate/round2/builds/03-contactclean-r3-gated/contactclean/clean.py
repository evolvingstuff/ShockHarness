"""Turn raw rows into contacts, field issues, rejections and merges."""

from dataclasses import dataclass

from contactclean.merge import merge_contacts
from contactclean.model import (
    EMPTY,
    NO_PHONE_STATUS,
    PHONE_UNVERIFIED,
    PHONE_VERIFIED,
    Contact,
    FieldIssue,
    Merge,
    RawRow,
    Rejection,
)
from contactclean.normalize import (
    PhoneRule,
    normalize_birthday,
    normalize_country,
    normalize_email,
    normalize_phone,
)


@dataclass(frozen=True)
class CleanResult:
    rows_read: int
    contacts: tuple[Contact, ...]
    issues: tuple[FieldIssue, ...]
    rejections: tuple[Rejection, ...]
    merges: tuple[Merge, ...]

    @property
    def every_row_usable(self) -> bool:
        return not self.issues and not self.rejections


@dataclass(frozen=True)
class _RowResult:
    contact: Contact | None
    issues: tuple[FieldIssue, ...]


def clean_rows(rows: tuple[RawRow, ...], rules: dict[str, PhoneRule]) -> CleanResult:
    contacts = []
    issues = []
    rejections = []
    for row in rows:
        name = row.field("name").strip()
        if name == EMPTY:
            rejections.append(Rejection(row_number=row.row_number, reason="row has no name"))
            continue
        result = _clean_row(row, name, rules)
        assert result.contact is not None, "a row with a name always yields a contact"
        contacts.append(result.contact)
        issues.extend(result.issues)
    merged = merge_contacts(tuple(contacts))
    return CleanResult(
        rows_read=len(rows),
        contacts=merged.contacts,
        issues=tuple(issues),
        rejections=tuple(rejections),
        merges=merged.merges,
    )


def _clean_row(row: RawRow, name: str, rules: dict[str, PhoneRule]) -> _RowResult:
    issues = []
    email = EMPTY
    raw_email = row.field("email")
    if raw_email.strip() != EMPTY:
        normalized = normalize_email(raw_email)
        if normalized.invalid_reason is not None:
            issues.append(_issue(row, "email", normalized.invalid_reason))
        email = normalized.value

    birthday = EMPTY
    raw_birthday = row.field("birthday")
    if raw_birthday.strip() != EMPTY:
        normalized = normalize_birthday(raw_birthday)
        if normalized.invalid_reason is not None:
            issues.append(_issue(row, "birthday", normalized.invalid_reason))
        birthday = normalized.value

    country = normalize_country(row.field("country"))
    phone = EMPTY
    phone_status = NO_PHONE_STATUS
    raw_phone = row.field("phone")
    if raw_phone.strip() != EMPTY:
        normalized_phone = normalize_phone(raw_phone, country, rules)
        if normalized_phone.invalid_reason is not None:
            issues.append(_issue(row, "phone", normalized_phone.invalid_reason))
        else:
            phone = normalized_phone.value
            phone_status = PHONE_VERIFIED if normalized_phone.verified else PHONE_UNVERIFIED

    contact = Contact(
        row_number=row.row_number,
        name=name,
        email=email,
        phone=phone,
        phone_status=phone_status,
        birthday=birthday,
        country=country,
    )
    return _RowResult(contact=contact, issues=tuple(issues))


def _issue(row: RawRow, field: str, reason: str) -> FieldIssue:
    return FieldIssue(row_number=row.row_number, field=field, value=row.field(field), reason=reason)
