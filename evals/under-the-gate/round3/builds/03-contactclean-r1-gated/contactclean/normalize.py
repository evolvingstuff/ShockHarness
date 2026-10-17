"""Normalization and validation of the individual contact fields."""

import calendar
import datetime
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

PHONE_PLANS_FILE = Path(__file__).with_name("phone_plans.json")
INTERNATIONAL_PREFIX = "+"
EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s.]+(\.[^@\s.]+)+")
PHONE_ALLOWED_PATTERN = re.compile(r"\+?[0-9 ().\-/]+")
NON_DIGITS = re.compile(r"[^0-9]")
# calendar.month_name holds an empty string at index 0, then one entry per month.
CALENDAR_MONTHS = range(1, len(calendar.month_name))
FIRST_DAY_OF_MONTH = 1
ISO_DATE_PATTERN = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
SLASH_DATE_PATTERN = re.compile(r"(\d{2})/(\d{2})/(\d{4})")


class PhoneStatus(Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"


@dataclass(frozen=True)
class PhonePlan:
    """The numbering plan of one country: E.164 calling code and national number lengths."""

    calling_code: str
    trunk_prefix: str
    min_length: int
    max_length: int


@dataclass(frozen=True)
class Phone:
    number: str
    status: PhoneStatus


@dataclass(frozen=True)
class FieldError:
    """Why a field value cannot be normalized; the row is kept without that field."""

    reason: str


def load_phone_plans(path: Path) -> Mapping[str, PhonePlan]:
    """Read the phone numbering plans, keyed by ISO 3166 alpha-2 country code."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    plans = {
        country: PhonePlan(
            calling_code=entry["calling_code"],
            trunk_prefix=entry["trunk_prefix"],
            min_length=int(entry["min_length"]),
            max_length=int(entry["max_length"]),
        )
        for country, entry in raw["plans"].items()
    }
    if not plans:
        raise ValueError(f"{path} defines no phone numbering plans")
    return plans


def normalize_text(value: str) -> str:
    return value.strip()


def normalize_country(value: str) -> str:
    return value.strip().upper()


def normalize_email(value: str) -> str | FieldError:
    """Trimmed, lowercased email; a FieldError when it is not an address."""
    email = value.strip().lower()
    if not EMAIL_PATTERN.fullmatch(email):
        return FieldError(f"not a valid email address: {value!r}")
    return email


def normalize_phone(value: str, country: str, plans: Mapping[str, PhonePlan]) -> Phone | FieldError:
    """E.164 when the country's plan is known, otherwise the digits as given, unverified."""
    text = value.strip()
    if not PHONE_ALLOWED_PATTERN.fullmatch(text):
        return FieldError(f"phone number contains characters other than digits and separators: {value!r}")
    digits = NON_DIGITS.sub("", text)
    if not digits:
        return FieldError(f"phone number has no digits: {value!r}")
    international = text.startswith(INTERNATIONAL_PREFIX)
    if country not in plans:
        if international:
            return Phone(number=INTERNATIONAL_PREFIX + digits, status=PhoneStatus.UNVERIFIED)
        return Phone(number=digits, status=PhoneStatus.UNVERIFIED)
    plan = plans[country]
    national = _national_number(digits, plan, international=international, original=value)
    if isinstance(national, FieldError):
        return national
    if not plan.min_length <= len(national) <= plan.max_length:
        return FieldError(
            f"phone number {value!r} has {len(national)} national digits; "
            f"{country} numbers have {plan.min_length} to {plan.max_length}"
        )
    return Phone(number=INTERNATIONAL_PREFIX + plan.calling_code + national, status=PhoneStatus.VERIFIED)


def _national_number(digits: str, plan: PhonePlan, *, international: bool, original: str) -> str | FieldError:
    if international:
        if not digits.startswith(plan.calling_code):
            return FieldError(f"phone number {original!r} does not start with calling code +{plan.calling_code}")
        return digits[len(plan.calling_code) :]
    if len(digits) > plan.max_length and digits.startswith(plan.trunk_prefix):
        return digits[len(plan.trunk_prefix) :]
    if plan.trunk_prefix != plan.calling_code and digits.startswith(plan.trunk_prefix):
        return digits[len(plan.trunk_prefix) :]
    return digits


def normalize_birthday(value: str) -> str | FieldError:
    """ISO 8601 date from YYYY-MM-DD, DD/MM/YYYY or MM/DD/YYYY (the latter two only when unambiguous)."""
    text = value.strip()
    iso = ISO_DATE_PATTERN.fullmatch(text)
    if iso:
        year, month, day = (int(part) for part in iso.groups())
        date = _date_or_none(year, month, day)
        if date is None:
            return FieldError(f"not a calendar date: {value!r}")
        return date.isoformat()
    slash = SLASH_DATE_PATTERN.fullmatch(text)
    if not slash:
        return FieldError(f"birthday is not in YYYY-MM-DD, DD/MM/YYYY or MM/DD/YYYY form: {value!r}")
    first, second, year = (int(part) for part in slash.groups())
    readings = {
        date
        for date in (_date_or_none(year, second, first), _date_or_none(year, first, second))
        if date is not None
    }
    if not readings:
        return FieldError(f"not a calendar date: {value!r}")
    if len(readings) > 1:
        return FieldError(f"ambiguous birthday, could be DD/MM/YYYY or MM/DD/YYYY: {value!r}")
    (date,) = readings
    return date.isoformat()


def _date_or_none(year: int, month: int, day: int) -> datetime.date | None:
    """The date, or None when that year, month and day do not name a calendar day."""
    if year < datetime.MINYEAR or month not in CALENDAR_MONTHS:
        return None
    _, days_in_month = calendar.monthrange(year, month)
    if not FIRST_DAY_OF_MONTH <= day <= days_in_month:
        return None
    return datetime.date(year, month, day)
