"""Normalization of single field values.

Each normalizer returns either a normalized value or an invalid-value reason;
an empty input is never passed to them (empty optional fields stay empty).
"""

import calendar
import datetime
import json
import re
from dataclasses import dataclass
from importlib import resources

EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s.]+(\.[^@\s.]+)+")
ISO_DATE_PATTERN = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
SLASH_DATE_PATTERN = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
PHONE_ALLOWED_PATTERN = re.compile(r"\+?[\d\s().\-/]+")
PLUS = "+"
# calendar.month_name holds an empty entry followed by one name per month.
MONTHS_IN_YEAR = len(calendar.month_name) - 1
FIRST_MONTH = 1
FIRST_DAY = 1


@dataclass(frozen=True)
class Normalized:
    """A normalized value, or the reason the input value is invalid."""

    value: str
    invalid_reason: str | None


@dataclass(frozen=True)
class Phone:
    value: str
    verified: bool
    invalid_reason: str | None


@dataclass(frozen=True)
class PhoneRule:
    calling_code: str
    international_prefix: str
    trunk_prefix: str
    national_lengths: frozenset[int]
    national_first_digits: str


def _valid(value: str) -> Normalized:
    return Normalized(value=value, invalid_reason=None)


def _invalid(reason: str) -> Normalized:
    return Normalized(value="", invalid_reason=reason)


def load_phone_rules() -> dict[str, PhoneRule]:
    """Read the per-country phone rules shipped with the package."""
    text = resources.files("contactclean").joinpath("phone_rules.json").read_text(encoding="utf-8")
    raw = json.loads(text)
    rules = {}
    for country, entry in raw.items():
        rules[country] = PhoneRule(
            calling_code=entry["calling_code"],
            international_prefix=entry["international_prefix"],
            trunk_prefix=entry["trunk_prefix"],
            national_lengths=frozenset(entry["national_lengths"]),
            national_first_digits=entry["national_first_digits"],
        )
    return rules


def normalize_email(raw: str) -> Normalized:
    email = raw.strip().lower()
    if not EMAIL_PATTERN.fullmatch(email):
        return _invalid("not a valid email address")
    return _valid(email)


def normalize_country(raw: str) -> str:
    return raw.strip().upper()


def normalize_birthday(raw: str) -> Normalized:
    text = raw.strip()
    iso = ISO_DATE_PATTERN.fullmatch(text)
    if iso:
        year, month, day = (int(part) for part in iso.groups())
        return _calendar_date(year, month, day)
    slash = SLASH_DATE_PATTERN.fullmatch(text)
    if not slash:
        return _invalid("birthday is not in YYYY-MM-DD, DD/MM/YYYY or MM/DD/YYYY format")
    first, second, year = (int(part) for part in slash.groups())
    if first > MONTHS_IN_YEAR and second > MONTHS_IN_YEAR:
        return _invalid("birthday has no valid month")
    if first > MONTHS_IN_YEAR:
        return _calendar_date(year, second, first)
    if second > MONTHS_IN_YEAR or first == second:
        return _calendar_date(year, first, second)
    return _invalid("birthday is ambiguous: it reads as both DD/MM/YYYY and MM/DD/YYYY")


def _calendar_date(year: int, month: int, day: int) -> Normalized:
    if year < datetime.MINYEAR or not FIRST_MONTH <= month <= MONTHS_IN_YEAR:
        return _invalid("birthday is not a calendar date")
    _, days_in_month = calendar.monthrange(year, month)
    if not FIRST_DAY <= day <= days_in_month:
        return _invalid("birthday is not a calendar date")
    return _valid(datetime.date(year, month, day).isoformat())


def normalize_phone(raw: str, country: str, rules: dict[str, PhoneRule]) -> Phone:
    """Return the phone in E.164 for a supported country, otherwise its digits as given, unverified."""
    text = raw.strip()
    if not PHONE_ALLOWED_PATTERN.fullmatch(text):
        return Phone(value="", verified=False, invalid_reason="phone contains characters other than digits and separators")
    digits = "".join(character for character in text if character.isdigit())
    if not digits:
        return Phone(value="", verified=False, invalid_reason="phone has no digits")
    international = text.startswith(PLUS)
    if country not in rules:
        prefix = PLUS if international else ""
        return Phone(value=prefix + digits, verified=False, invalid_reason=None)
    national = _national_number(digits, rules[country], international=international)
    if national.invalid_reason is not None:
        return Phone(value="", verified=False, invalid_reason=national.invalid_reason)
    return Phone(value=PLUS + rules[country].calling_code + national.value, verified=True, invalid_reason=None)


def _national_number(digits: str, rule: PhoneRule, *, international: bool) -> Normalized:
    if international:
        if not digits.startswith(rule.calling_code):
            return _invalid(f"phone does not start with the calling code +{rule.calling_code} of its country")
        national = digits[len(rule.calling_code):]
    elif digits.startswith(rule.international_prefix + rule.calling_code):
        national = digits[len(rule.international_prefix + rule.calling_code):]
    else:
        national = digits
    if national.startswith(rule.trunk_prefix) and len(national) - len(rule.trunk_prefix) in rule.national_lengths:
        national = national[len(rule.trunk_prefix):]
    if len(national) not in rule.national_lengths:
        return _invalid("phone has the wrong number of digits for its country")
    if national[0] not in rule.national_first_digits:
        return _invalid("phone is not a valid number for its country")
    return _valid(national)
