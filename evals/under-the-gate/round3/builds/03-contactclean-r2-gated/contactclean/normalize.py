"""Normalization of single contact fields: email, phone, birthday, country."""

import calendar
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources

PHONE_VERIFIED = "verified"
PHONE_UNVERIFIED = "unverified"
NO_PHONE_STATUS = ""

MONTHS_PER_YEAR = len(calendar.month_name) - 1
FIRST_MONTH = 1
FIRST_DAY = 1
DAYS_IN_MONTH_INDEX = 1  # calendar.monthrange returns (first weekday, number of days)

EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s.]+")
PHONE_CHARACTERS = re.compile(r"\+?[\d\s().\-/]+")
NON_DIGITS = re.compile(r"\D")
ISO_DATE = re.compile(r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})")
SLASH_DATE = re.compile(r"(?P<first>\d{1,2})/(?P<second>\d{1,2})/(?P<year>\d{4})")


@dataclass(frozen=True)
class PhoneRule:
    calling_code: str
    trunk_prefix: str
    international_prefix: str
    national_pattern: re.Pattern[str]


@dataclass(frozen=True)
class Field:
    """A normalized field value, or the reason the raw value was invalid."""

    value: str
    problem: str | None


@dataclass(frozen=True)
class Phone:
    value: str
    status: str
    problem: str | None


EMPTY_FIELD = Field(value="", problem=None)
EMPTY_PHONE = Phone(value="", status=NO_PHONE_STATUS, problem=None)


def load_phone_rules() -> Mapping[str, PhoneRule]:
    """Read the per-country phone numbering rules shipped with the package."""
    text = resources.files("contactclean").joinpath("phone_rules.json").read_text(encoding="utf-8")
    raw = json.loads(text)
    return {
        country: PhoneRule(
            calling_code=entry["calling_code"],
            trunk_prefix=entry["trunk_prefix"],
            international_prefix=entry["international_prefix"],
            national_pattern=re.compile(entry["national_pattern"]),
        )
        for country, entry in raw.items()
    }


def invalid(reason: str) -> Field:
    return Field(value="", problem=reason)


def normalize_email(raw: str) -> Field:
    email = raw.strip().lower()
    if not email:
        return EMPTY_FIELD
    if not EMAIL_PATTERN.fullmatch(email):
        return invalid(f"not a valid email address: {raw.strip()!r}")
    return Field(value=email, problem=None)


def normalize_country(raw: str) -> str:
    return raw.strip().upper()


def normalize_phone(raw: str, country: str, rules: Mapping[str, PhoneRule]) -> Phone:
    """Return the phone in E.164 when the country is known, else its digits, unverified."""
    phone = raw.strip()
    if not phone:
        return EMPTY_PHONE
    if not PHONE_CHARACTERS.fullmatch(phone):
        return Phone(value="", status=NO_PHONE_STATUS, problem=f"phone contains characters other than digits: {phone!r}")
    digits = NON_DIGITS.sub("", phone)
    international = phone.startswith("+")
    if country not in rules:
        prefix = "+" if international else ""
        return Phone(value=prefix + digits, status=PHONE_UNVERIFIED, problem=None)
    return to_e164(phone, digits, rules[country], country)


def to_e164(phone: str, digits: str, rule: PhoneRule, country: str) -> Phone:
    international_marker = rule.international_prefix + rule.calling_code
    if phone.startswith("+"):
        if not digits.startswith(rule.calling_code):
            return Phone(value="", status=NO_PHONE_STATUS, problem=f"phone {phone!r} is not a {country} number")
        national = digits[len(rule.calling_code):]
    elif digits.startswith(international_marker):
        national = digits[len(international_marker):]
    else:
        national = digits
    if not rule.national_pattern.fullmatch(national) and national.startswith(rule.trunk_prefix):
        national = national[len(rule.trunk_prefix):]
    if not rule.national_pattern.fullmatch(national):
        return Phone(value="", status=NO_PHONE_STATUS, problem=f"phone {phone!r} is not a valid {country} number")
    return Phone(value="+" + rule.calling_code + national, status=PHONE_VERIFIED, problem=None)


def normalize_birthday(raw: str) -> Field:
    """Accept YYYY-MM-DD, DD/MM/YYYY or MM/DD/YYYY (the latter two only when unambiguous)."""
    text = raw.strip()
    if not text:
        return EMPTY_FIELD
    iso = ISO_DATE.fullmatch(text)
    if iso:
        return checked_date(text, int(iso["year"]), int(iso["month"]), int(iso["day"]))
    slashed = SLASH_DATE.fullmatch(text)
    if not slashed:
        return invalid(f"birthday {text!r} is not in YYYY-MM-DD, DD/MM/YYYY or MM/DD/YYYY form")
    first, second, year = int(slashed["first"]), int(slashed["second"]), int(slashed["year"])
    first_is_month = first <= MONTHS_PER_YEAR
    second_is_month = second <= MONTHS_PER_YEAR
    if first_is_month and second_is_month and first != second:
        return invalid(f"birthday {text!r} is ambiguous between DD/MM/YYYY and MM/DD/YYYY")
    if second_is_month:
        return checked_date(text, year, second, first)
    return checked_date(text, year, first, second)


def checked_date(text: str, year: int, month: int, day: int) -> Field:
    if not FIRST_MONTH <= month <= MONTHS_PER_YEAR:
        return invalid(f"birthday {text!r} has no valid month")
    if not FIRST_DAY <= day <= calendar.monthrange(year, month)[DAYS_IN_MONTH_INDEX]:
        return invalid(f"birthday {text!r} is not a calendar date")
    return Field(value=f"{year:04d}-{month:02d}-{day:02d}", problem=None)
