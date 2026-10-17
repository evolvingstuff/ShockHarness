"""Records passed between the stages of the cleaner."""

from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class PhoneStatus(Enum):
    EMPTY = ""
    VERIFIED = "verified"
    UNVERIFIED = "unverified"


@dataclass(frozen=True)
class PhonePlan:
    calling_code: str
    trunk_prefix: str
    min_digits: int
    max_digits: int


@dataclass(frozen=True)
class Phone:
    value: str
    status: PhoneStatus


@dataclass(frozen=True)
class Contact:
    """A cleaned row; an empty string means the field is empty or was dropped."""

    row: int
    name: str
    email: str
    phone: str
    phone_status: PhoneStatus
    birthday: str
    country: str

    def completeness(self) -> int:
        return sum(field != "" for field in (self.email, self.phone, self.birthday, self.country))


@dataclass(frozen=True)
class FieldProblem:
    row: int
    field: str
    value: str
    reason: str


@dataclass(frozen=True)
class Rejection:
    row: int
    reason: str


@dataclass(frozen=True)
class Merge:
    kept_row: int
    merged_rows: tuple[int, ...]
    reason: str


@dataclass(frozen=True)
class RawRow:
    row: int
    fields: dict[str, str]


@dataclass(frozen=True)
class PhoneRules:
    plans: Mapping[str, PhonePlan]
    e164_max_digits: int


@dataclass(frozen=True)
class Invalid:
    """A field value that cannot be normalized, and why."""

    reason: str
