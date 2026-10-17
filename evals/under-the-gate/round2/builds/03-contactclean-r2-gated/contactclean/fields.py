"""Normalization of the email and birthday fields."""

import calendar
import datetime
import re

from contactclean.errors import Rejected

ISO_DATE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})", re.ASCII)
SLASH_DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})", re.ASCII)
# calendar.month_name holds an empty entry followed by one name per month.
MONTHS_PER_YEAR = len(calendar.month_name) - 1
EMAIL_AT = "@"
DOMAIN_SEPARATOR = "."


def normalize_email(text: str) -> str | Rejected:
    """Lowercase a non-empty email after checking its basic shape."""
    email = text.lower()
    if any(char.isspace() for char in email):
        return Rejected("email contains whitespace")
    if email.count(EMAIL_AT) != 1:
        return Rejected("email must contain exactly one '@'")
    local, domain = email.split(EMAIL_AT)
    if not local:
        return Rejected("email has nothing before '@'")
    labels = domain.split(DOMAIN_SEPARATOR)
    if len(labels) == 1 or not all(labels):
        return Rejected(f"email domain {domain!r} is not a valid domain")
    return email


def _iso_date(year: int, month: int, day: int) -> str | Rejected:
    if year < datetime.MINYEAR:
        return Rejected(f"birthday year {year} is not a valid year")
    if not 1 <= month <= MONTHS_PER_YEAR:
        return Rejected(f"birthday month {month} is not a valid month")
    _, days_in_month = calendar.monthrange(year, month)
    if not 1 <= day <= days_in_month:
        return Rejected(f"birthday day {day} does not exist in {year:04d}-{month:02d}")
    return datetime.date(year, month, day).isoformat()


def _day_and_month(first: int, second: int) -> tuple[int, int] | Rejected:
    """Resolve DD/MM against MM/DD; only an unambiguous reading is accepted."""
    first_is_day = first > MONTHS_PER_YEAR
    second_is_day = second > MONTHS_PER_YEAR
    if first_is_day and second_is_day:
        return Rejected("birthday has no valid month")
    if first_is_day:
        return first, second
    if second_is_day or first == second:
        return second, first
    return Rejected("birthday is ambiguous between DD/MM/YYYY and MM/DD/YYYY")


def normalize_birthday(text: str) -> str | Rejected:
    """Convert a non-empty birthday in YYYY-MM-DD, DD/MM/YYYY or MM/DD/YYYY to ISO 8601."""
    iso = ISO_DATE.fullmatch(text)
    if iso is not None:
        year, month, day = (int(part) for part in iso.groups())
        return _iso_date(year, month, day)
    slash = SLASH_DATE.fullmatch(text)
    if slash is None:
        return Rejected("birthday is not in YYYY-MM-DD, DD/MM/YYYY or MM/DD/YYYY format")
    first, second, year = (int(part) for part in slash.groups())
    day_and_month = _day_and_month(first, second)
    if isinstance(day_and_month, Rejected):
        return day_and_month
    day, month = day_and_month
    return _iso_date(year, month, day)
