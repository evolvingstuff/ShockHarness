"""Normalization of individual contact fields.

Each ``normalize_*`` function takes the raw (untrimmed) cell value and returns
the normalized value, ``""`` for an empty cell, or raises ``InvalidField`` with
a human-readable reason.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass


class InvalidField(ValueError):
    """Raised when a non-empty field value cannot be normalized."""


# --- email -----------------------------------------------------------------

_EMAIL_LOCAL = re.compile(r"^[a-z0-9!#$%&'*+/=?^_`{|}~-]+(\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*$")
_DOMAIN_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


def normalize_email(raw: str) -> str:
    value = raw.strip().lower()
    if not value:
        return ""
    if value.count("@") != 1:
        raise InvalidField("email must contain exactly one '@'")
    local, domain = value.split("@")
    if not local or len(local) > 64 or not _EMAIL_LOCAL.match(local):
        raise InvalidField("email has an invalid local part")
    labels = domain.split(".")
    if len(labels) < 2 or not all(_DOMAIN_LABEL.match(label) for label in labels):
        raise InvalidField("email has an invalid domain")
    if not labels[-1].isalpha() or len(labels[-1]) < 2:
        raise InvalidField("email has an invalid top-level domain")
    return value


# --- phone -----------------------------------------------------------------

VERIFIED = "verified"
UNVERIFIED = "unverified"


@dataclass(frozen=True)
class _PhoneRule:
    calling_code: str
    # Pattern for the national significant number (no trunk prefix).
    nsn: re.Pattern[str]
    trunk_prefix: str


PHONE_RULES: dict[str, _PhoneRule] = {
    # NANP: area code and exchange code both start with 2-9.
    "US": _PhoneRule("1", re.compile(r"^[2-9]\d{2}[2-9]\d{6}$"), "1"),
    "GB": _PhoneRule("44", re.compile(r"^[1-9]\d{8,9}$"), "0"),
    "DE": _PhoneRule("49", re.compile(r"^[1-9]\d{5,12}$"), "0"),
    "FR": _PhoneRule("33", re.compile(r"^[1-9]\d{8}$"), "0"),
}

_CALLING_CODES = {rule.calling_code: country for country, rule in PHONE_RULES.items()}
_PHONE_CHARS = re.compile(r"^\+?[\d\s().\-/]+$")


def normalize_phone(raw: str, country: str) -> tuple[str, str]:
    """Return ``(phone, status)`` where status is ``verified``/``unverified``.

    ``country`` is the already-normalized (upper-case) ISO alpha-2 code, or "".
    Numbers written in international form (``+`` or ``00`` prefix) are checked
    against the rules of their calling code, regardless of ``country``.
    """
    value = raw.strip()
    if not value:
        return "", ""
    if not _PHONE_CHARS.match(value):
        raise InvalidField("phone contains characters other than digits and separators")
    digits = re.sub(r"\D", "", value)
    if not digits:
        raise InvalidField("phone contains no digits")

    international = value.startswith("+")
    if not international and digits.startswith("00"):
        international = True
        digits = digits[2:]

    if international:
        for code, code_country in _CALLING_CODES.items():
            if digits.startswith(code):
                rule = PHONE_RULES[code_country]
                nsn = digits[len(code):]
                # Tolerate the "+44 (0)20 ..." convention.
                if rule.trunk_prefix == "0" and nsn.startswith("0"):
                    nsn = nsn[1:]
                if not rule.nsn.match(nsn):
                    raise InvalidField(f"phone is not a valid {code_country} number")
                return f"+{code}{nsn}", VERIFIED
        if not 8 <= len(digits) <= 15:
            raise InvalidField("phone has an invalid number of digits")
        return f"+{digits}", UNVERIFIED

    rule = PHONE_RULES.get(country)
    if rule is None:
        if not 4 <= len(digits) <= 15:
            raise InvalidField("phone has an invalid number of digits")
        return digits, UNVERIFIED

    nsn = digits
    if rule.nsn.match(nsn):
        return f"+{rule.calling_code}{nsn}", VERIFIED
    if nsn.startswith(rule.trunk_prefix):
        nsn = nsn[len(rule.trunk_prefix):]
        if rule.nsn.match(nsn):
            return f"+{rule.calling_code}{nsn}", VERIFIED
    raise InvalidField(f"phone is not a valid {country} number")


# --- birthday --------------------------------------------------------------

_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_SLASH_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def _make_date(year: int, month: int, day: int) -> _dt.date:
    try:
        return _dt.date(year, month, day)
    except ValueError:
        raise InvalidField("birthday is not a real calendar date") from None


def normalize_birthday(raw: str, today: _dt.date | None = None) -> str:
    value = raw.strip()
    if not value:
        return ""
    today = today or _dt.date.today()

    if m := _ISO_DATE.match(value):
        date = _make_date(int(m[1]), int(m[2]), int(m[3]))
    elif m := _SLASH_DATE.match(value):
        first, second, year = int(m[1]), int(m[2]), int(m[3])
        if first > 12 and second > 12:
            raise InvalidField("birthday is not a real calendar date")
        if first > 12:  # DD/MM/YYYY
            date = _make_date(year, second, first)
        elif second > 12 or first == second:  # MM/DD/YYYY, or both readings agree
            date = _make_date(year, first, second)
        else:
            raise InvalidField("birthday is ambiguous (could be DD/MM/YYYY or MM/DD/YYYY)")
    else:
        raise InvalidField("birthday is not in YYYY-MM-DD, DD/MM/YYYY or MM/DD/YYYY format")

    if date > today:
        raise InvalidField("birthday is in the future")
    return date.isoformat()


# --- country ---------------------------------------------------------------

def normalize_country(raw: str) -> str:
    return raw.strip().upper()
