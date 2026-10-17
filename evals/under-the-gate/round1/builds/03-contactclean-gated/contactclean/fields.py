"""Field normalizers. Each returns an Outcome; an invalid value carries a problem, never raises."""

import calendar
import re
from dataclasses import dataclass
from types import MappingProxyType

STATUS_NONE = ""
STATUS_VERIFIED = "verified"
STATUS_UNVERIFIED = "unverified"

EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
PHONE_CHARS_RE = re.compile(r"\+?[0-9()\-.\s]+")
NON_DIGIT_RE = re.compile(r"\D")
ISO_DATE_RE = re.compile(r"(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})")
SLASH_DATE_RE = re.compile(r"(?P<a>\d{1,2})/(?P<b>\d{1,2})/(?P<y>\d{4})")
INTERNATIONAL_PREFIX = "00"


@dataclass(frozen=True)
class Outcome:
    value: str
    status: str
    problem: str | None


@dataclass(frozen=True)
class CountryRule:
    calling_code: str
    trunk_prefix: str
    national_number: re.Pattern[str]


# Numbering plans: ITU-T E.164 country calling codes with national trunk prefixes.
COUNTRY_RULES = MappingProxyType(
    {
        "US": CountryRule("1", "1", re.compile(r"[2-9]\d{2}[2-9]\d{6}")),
        "GB": CountryRule("44", "0", re.compile(r"\d{9,10}")),
        "DE": CountryRule("49", "0", re.compile(r"\d{6,13}")),
        "FR": CountryRule("33", "0", re.compile(r"\d{9}")),
    }
)

EMPTY = Outcome("", STATUS_NONE, None)


def invalid(raw: str, reason: str) -> Outcome:
    return Outcome("", STATUS_NONE, f"{reason}: {raw!r}")


def normalize_email(raw: str) -> Outcome:
    if not raw:
        return EMPTY
    if not EMAIL_RE.fullmatch(raw):
        return invalid(raw, "invalid email")
    return Outcome(raw.lower(), STATUS_NONE, None)


def normalize_country(raw: str) -> str:
    return raw.upper()


def normalize_phone(raw: str, country: str) -> Outcome:
    if not raw:
        return EMPTY
    if not PHONE_CHARS_RE.fullmatch(raw):
        return invalid(raw, "invalid phone: unexpected characters")
    digits = NON_DIGIT_RE.sub("", raw)
    if not digits:
        return invalid(raw, "invalid phone: no digits")
    if country not in COUNTRY_RULES:
        return Outcome(digits, STATUS_UNVERIFIED, None)
    rule = COUNTRY_RULES[country]
    international = raw.startswith("+")
    if not international and digits.startswith(INTERNATIONAL_PREFIX):
        international = True
        digits = digits[len(INTERNATIONAL_PREFIX) :]
    national = digits
    if international:
        if not digits.startswith(rule.calling_code):
            return invalid(raw, f"invalid phone: calling code does not match {country}")
        national = digits[len(rule.calling_code) :]
    if national.startswith(rule.trunk_prefix):
        national = national[len(rule.trunk_prefix) :]
    if not rule.national_number.fullmatch(national):
        return invalid(raw, f"invalid phone: not a valid {country} number")
    return Outcome("+" + rule.calling_code + national, STATUS_VERIFIED, None)


def is_month(number: int) -> bool:
    return number in range(1, len(calendar.month_name))


def build_date(year: int, month: int, day: int, raw: str) -> Outcome:
    if year < 1 or not is_month(month):
        return invalid(raw, "invalid birthday")
    if not 1 <= day <= calendar.monthrange(year, month)[1]:
        return invalid(raw, "invalid birthday: no such day")
    return Outcome(f"{year:04d}-{month:02d}-{day:02d}", STATUS_NONE, None)


def normalize_birthday(raw: str) -> Outcome:
    if not raw:
        return EMPTY
    iso = ISO_DATE_RE.fullmatch(raw)
    if iso:
        return build_date(int(iso["y"]), int(iso["m"]), int(iso["d"]), raw)
    slash = SLASH_DATE_RE.fullmatch(raw)
    if not slash:
        return invalid(raw, "invalid birthday: unrecognized format")
    first, second, year = int(slash["a"]), int(slash["b"]), int(slash["y"])
    if is_month(first) and is_month(second) and first != second:
        return invalid(raw, "invalid birthday: ambiguous DD/MM/YYYY or MM/DD/YYYY")
    if is_month(second):
        return build_date(year, second, first, raw)
    return build_date(year, first, second, raw)
