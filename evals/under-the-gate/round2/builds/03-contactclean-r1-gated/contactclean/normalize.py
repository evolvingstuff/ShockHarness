"""Normalize single field values; an unusable value comes back as Invalid with the reason."""

import calendar
import re
from datetime import date

from contactclean.model import Invalid, Phone, PhonePlan, PhoneRules, PhoneStatus

MONTHS_PER_YEAR = len(calendar.month_name) - 1  # month_name[0] is the empty placeholder
FIRST_MONTH = 1
FIRST_DAY = 1
INTERNATIONAL_PREFIX = "+"
# "+44 (0)20 ..." writes the trunk prefix in parentheses next to the country code.
PARENTHESISED_TRUNK = "(0)"
EMPTY_PHONE = Phone(value="", status=PhoneStatus.EMPTY)

EMAIL_PATTERN = re.compile(r"[^@\s.][^@\s]*@[^@\s.]+(\.[^@\s.]+)+")
COUNTRY_PATTERN = re.compile(r"[A-Z]{2}")
PHONE_PATTERN = re.compile(r"\+?[0-9 ()./-]+")
ISO_DATE_PATTERN = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
SLASHED_DATE_PATTERN = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


def normalize_text(value: str) -> str:
    return value.strip()


def normalize_email(value: str) -> str | Invalid:
    email = value.strip().lower()
    if email == "":
        return email
    local_part = email.split("@")[0]
    if not EMAIL_PATTERN.fullmatch(email) or ".." in email or local_part.endswith("."):
        return Invalid(f"not a valid email address: {value.strip()!r}")
    return email


def normalize_country(value: str) -> str | Invalid:
    country = value.strip().upper()
    if country == "":
        return country
    if not COUNTRY_PATTERN.fullmatch(country):
        return Invalid(f"not an ISO 3166 alpha-2 country code: {value.strip()!r}")
    return country


def _phone_digits(text: str, rules: PhoneRules) -> str | Invalid:
    if not PHONE_PATTERN.fullmatch(text):
        return Invalid(f"phone number contains characters other than digits and separators: {text!r}")
    digits = re.sub(r"\D", "", text.replace(PARENTHESISED_TRUNK, ""))
    if digits == "":
        return Invalid(f"phone number has no digits: {text!r}")
    if len(digits) > rules.e164_max_digits:
        return Invalid(f"phone number has more than {rules.e164_max_digits} digits: {text!r}")
    return digits


def _verified_phone(text: str, digits: str, country: str, plan: PhonePlan) -> Phone | Invalid:
    if text.startswith(INTERNATIONAL_PREFIX):
        if not digits.startswith(plan.calling_code):
            return Invalid(f"phone number {text!r} does not have the calling code +{plan.calling_code} of {country}")
        national = digits[len(plan.calling_code) :]
    else:
        national = digits.removeprefix(plan.trunk_prefix)
    if national.startswith(plan.trunk_prefix) or not plan.min_digits <= len(national) <= plan.max_digits:
        return Invalid(f"phone number {text!r} is not a valid {country} number")
    return Phone(value=INTERNATIONAL_PREFIX + plan.calling_code + national, status=PhoneStatus.VERIFIED)


def normalize_phone(value: str, country: str, rules: PhoneRules) -> Phone | Invalid:
    """E.164 when the country's plan is known; otherwise the digits as given, unverified."""
    text = value.strip()
    if text == "":
        return EMPTY_PHONE
    digits = _phone_digits(text, rules)
    if isinstance(digits, Invalid):
        return digits
    if country in rules.plans:
        return _verified_phone(text, digits, country, rules.plans[country])
    prefix = INTERNATIONAL_PREFIX if text.startswith(INTERNATIONAL_PREFIX) else ""
    return Phone(value=prefix + digits, status=PhoneStatus.UNVERIFIED)


def _iso_date(year: int, month: int, day: int, original: str, today: date) -> str | Invalid:
    if not FIRST_MONTH <= month <= MONTHS_PER_YEAR:
        return Invalid(f"birthday {original!r} has no month {month}")
    _, days_in_month = calendar.monthrange(year, month)
    if year < date.min.year or not FIRST_DAY <= day <= days_in_month:
        return Invalid(f"birthday {original!r} is not a calendar date")
    birthday = date(year, month, day)
    if birthday > today:
        return Invalid(f"birthday {original!r} is in the future")
    return birthday.isoformat()


def normalize_birthday(value: str, today: date) -> str | Invalid:
    """YYYY-MM-DD, DD/MM/YYYY or MM/DD/YYYY (only when unambiguous) to ISO 8601."""
    text = value.strip()
    if text == "":
        return text
    iso = ISO_DATE_PATTERN.fullmatch(text)
    if iso:
        year, month, day = (int(part) for part in iso.groups())
        return _iso_date(year, month, day, text, today)
    slashed = SLASHED_DATE_PATTERN.fullmatch(text)
    if not slashed:
        return Invalid(f"birthday {text!r} is not in YYYY-MM-DD, DD/MM/YYYY or MM/DD/YYYY form")
    first, second, year = (int(part) for part in slashed.groups())
    if first == second or second > MONTHS_PER_YEAR:
        return _iso_date(year, first, second, text, today)  # MM/DD/YYYY, or both readings agree
    if first > MONTHS_PER_YEAR:
        return _iso_date(year, second, first, text, today)  # DD/MM/YYYY
    return Invalid(f"birthday {text!r} is ambiguous: it reads as DD/MM/YYYY and as MM/DD/YYYY")
