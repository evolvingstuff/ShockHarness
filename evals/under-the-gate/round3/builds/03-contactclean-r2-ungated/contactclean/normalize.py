"""Field normalizers.

Each normalizer takes a raw (already trimmed, non-empty) value and returns the
normalized value, or raises InvalidValue with a human-readable reason.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date


class InvalidValue(ValueError):
    """The value is present but cannot be used."""


# --- email -------------------------------------------------------------------

_EMAIL_RE = re.compile(
    r"^[a-z0-9!#$%&'*+/=?^_`{|}~-]+(\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$"
)


def normalize_email(value: str) -> str:
    email = value.lower()
    if not _EMAIL_RE.match(email):
        raise InvalidValue(f"invalid email address: {value!r}")
    return email


# --- phone -------------------------------------------------------------------


@dataclass(frozen=True)
class CountryRule:
    calling_code: str
    # Allowed lengths of the national significant number (no trunk prefix).
    nsn_lengths: range
    # Whether a leading national trunk digit is used domestically.
    trunk_prefix: str
    nsn_pattern: re.Pattern[str]


COUNTRIES: dict[str, CountryRule] = {
    # NANP: NXX-NXX-XXXX, trunk prefix 1.
    "US": CountryRule("1", range(10, 11), "1", re.compile(r"^[2-9]\d{2}[2-9]\d{6}$")),
    "GB": CountryRule("44", range(9, 11), "0", re.compile(r"^[1-9]\d+$")),
    "DE": CountryRule("49", range(6, 14), "0", re.compile(r"^[1-9]\d+$")),
    "FR": CountryRule("33", range(9, 10), "0", re.compile(r"^[1-9]\d+$")),
}

_PHONE_FORMATTING = re.compile(r"[\s\-.()/]")


@dataclass(frozen=True)
class Phone:
    value: str
    verified: bool


def _check_nsn(nsn: str, country: str) -> str:
    rule = COUNTRIES[country]
    if len(nsn) not in rule.nsn_lengths or not rule.nsn_pattern.match(nsn):
        raise InvalidValue(f"not a valid {country} phone number")
    return f"+{rule.calling_code}{nsn}"


def normalize_phone(value: str, country: str) -> Phone:
    """Normalize a phone number.

    With a supported ``country`` the result is E.164 and verified. Otherwise the
    digits (and a leading '+', if given) are kept as-is and marked unverified.
    """
    compact = _PHONE_FORMATTING.sub("", value)
    international = False
    if compact.startswith("+"):
        international, compact = True, compact[1:]
    elif compact.startswith("00"):
        international, compact = True, compact[2:]
    if not compact.isdigit() or not compact.isascii():
        raise InvalidValue(f"phone number contains invalid characters: {value!r}")
    if not 6 <= len(compact) <= 15:
        raise InvalidValue(f"phone number has an invalid length: {value!r}")

    if international:
        # The number carries its own country code: verify it if we know it.
        for code, rule in COUNTRIES.items():
            if compact.startswith(rule.calling_code):
                return Phone(_check_nsn(compact[len(rule.calling_code):], code), True)
        return Phone("+" + compact, False)

    if country not in COUNTRIES:
        return Phone(compact, False)

    rule = COUNTRIES[country]
    nsn = compact
    if nsn.startswith(rule.trunk_prefix) and len(nsn) - 1 in rule.nsn_lengths:
        nsn = nsn[1:]
    return Phone(_check_nsn(nsn, country), True)


# --- birthday ----------------------------------------------------------------

_ISO_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_SLASH_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def _make_date(year: int, month: int, day: int, value: str) -> date:
    try:
        return date(year, month, day)
    except ValueError:
        raise InvalidValue(f"not a real date: {value!r}") from None


def normalize_birthday(value: str, today: date | None = None) -> str:
    today = today or date.today()
    if m := _ISO_RE.match(value):
        result = _make_date(int(m[1]), int(m[2]), int(m[3]), value)
    elif m := _SLASH_RE.match(value):
        a, b, year = int(m[1]), int(m[2]), int(m[3])
        candidates = set()
        for day, month in ((a, b), (b, a)):  # DD/MM/YYYY, then MM/DD/YYYY
            try:
                candidates.add(date(year, month, day))
            except ValueError:
                pass
        if not candidates:
            raise InvalidValue(f"not a real date: {value!r}")
        if len(candidates) > 1:
            raise InvalidValue(
                f"ambiguous date (could be DD/MM/YYYY or MM/DD/YYYY): {value!r}"
            )
        result = candidates.pop()
    else:
        raise InvalidValue(f"unrecognized date format: {value!r}")
    if result > today:
        raise InvalidValue(f"birthday is in the future: {value!r}")
    return result.isoformat()
