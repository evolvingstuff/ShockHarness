"""Field-level normalization and validation.

Each normalizer takes the raw (untrimmed) cell value and returns either a
normalized value or raises ``InvalidValue`` with a human-readable reason.
An empty input always normalizes to an empty output: empty is not invalid.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass


class InvalidValue(ValueError):
    """Raised when a non-empty field cannot be normalized."""


# --- email -----------------------------------------------------------------

_EMAIL_RE = re.compile(
    r"^[a-z0-9!#$%&'*+/=?^_`{|}~.-]+"  # local part
    r"@"
    r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$"  # domain with a TLD
)


def normalize_email(raw: str) -> str:
    value = raw.strip().lower()
    if not value:
        return ""
    if not _EMAIL_RE.match(value):
        raise InvalidValue("not a valid email address")
    local = value.split("@", 1)[0]
    if local.startswith(".") or local.endswith(".") or ".." in local:
        raise InvalidValue("not a valid email address")
    return value


# --- phone -----------------------------------------------------------------

PHONE_VERIFIED = "verified"
PHONE_UNVERIFIED = "unverified"


@dataclass(frozen=True)
class _CountryRule:
    calling_code: str
    # Allowed lengths of the national significant number (no trunk prefix).
    lengths: tuple[int, ...]
    pattern: re.Pattern[str]
    trunk_prefix: str = "0"


COUNTRY_RULES: dict[str, _CountryRule] = {
    # NANP: area code and exchange both start with 2-9.
    "US": _CountryRule("1", (10,), re.compile(r"^[2-9]\d{2}[2-9]\d{6}$"), trunk_prefix="1"),
    "GB": _CountryRule("44", (9, 10), re.compile(r"^[1-9]\d+$")),
    "DE": _CountryRule("49", tuple(range(6, 14)), re.compile(r"^[1-9]\d+$")),
    "FR": _CountryRule("33", (9,), re.compile(r"^[1-9]\d{8}$")),
}

_PHONE_ALLOWED_RE = re.compile(r"^\+?[\d\s().\-/]+$")


@dataclass(frozen=True)
class Phone:
    value: str
    status: str  # PHONE_VERIFIED or PHONE_UNVERIFIED

    @property
    def verified(self) -> bool:
        return self.status == PHONE_VERIFIED


def _validate_national(nsn: str, rule: _CountryRule, country: str) -> str:
    if len(nsn) not in rule.lengths or not rule.pattern.match(nsn):
        raise InvalidValue(f"not a valid {country} phone number")
    return f"+{rule.calling_code}{nsn}"


def normalize_phone(raw: str, country: str) -> Phone | None:
    """Return the normalized phone, or ``None`` when the field is empty.

    ``country`` must already be normalized (trimmed, upper-case).
    """
    value = raw.strip()
    if not value:
        return None
    if not _PHONE_ALLOWED_RE.match(value):
        raise InvalidValue("phone number contains invalid characters")
    digits = re.sub(r"\D", "", value)
    has_plus = value.startswith("+")
    if not digits:
        raise InvalidValue("phone number contains no digits")

    international = None
    if has_plus:
        international = digits
    elif digits.startswith("00") and country in COUNTRY_RULES:
        # International dialling prefix used in GB/DE/FR (and accepted for US).
        international = digits[2:]

    if international is not None:
        for code, rule in COUNTRY_RULES.items():
            if international.startswith(rule.calling_code):
                nsn = international[len(rule.calling_code):]
                return Phone(_validate_national(nsn, rule, code), PHONE_VERIFIED)
        if len(international) > 15:
            raise InvalidValue("phone number has too many digits")
        if len(international) < 4:
            raise InvalidValue("phone number has too few digits")
        return Phone("+" + international, PHONE_UNVERIFIED)

    rule = COUNTRY_RULES.get(country)
    if rule is None:
        if len(digits) > 15:
            raise InvalidValue("phone number has too many digits")
        if len(digits) < 4:
            raise InvalidValue("phone number has too few digits")
        return Phone(digits, PHONE_UNVERIFIED)

    nsn = digits
    if rule.trunk_prefix and nsn.startswith(rule.trunk_prefix) and (
        len(nsn) - len(rule.trunk_prefix) in rule.lengths or len(nsn) not in rule.lengths
    ):
        nsn = nsn[len(rule.trunk_prefix):]
    return Phone(_validate_national(nsn, rule, country), PHONE_VERIFIED)


# --- birthday --------------------------------------------------------------

_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_SLASH_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def _make_date(year: int, month: int, day: int) -> _dt.date:
    try:
        return _dt.date(year, month, day)
    except ValueError:
        raise InvalidValue("not a real calendar date") from None


def normalize_birthday(raw: str, today: _dt.date | None = None) -> str:
    value = raw.strip()
    if not value:
        return ""
    today = today or _dt.date.today()

    if m := _ISO_RE.match(value):
        date = _make_date(int(m[1]), int(m[2]), int(m[3]))
    elif m := _SLASH_RE.match(value):
        first, second, year = int(m[1]), int(m[2]), int(m[3])
        if first > 12 and second > 12:
            raise InvalidValue("not a real calendar date")
        if first > 12:  # DD/MM/YYYY
            date = _make_date(year, second, first)
        elif second > 12:  # MM/DD/YYYY
            date = _make_date(year, first, second)
        elif first == second:  # same either way
            date = _make_date(year, first, second)
        else:
            raise InvalidValue("ambiguous date: could be DD/MM/YYYY or MM/DD/YYYY")
    else:
        raise InvalidValue("unrecognized date format (expected YYYY-MM-DD, DD/MM/YYYY or MM/DD/YYYY)")

    if date > today:
        raise InvalidValue("birthday is in the future")
    return date.isoformat()


# --- simple fields ---------------------------------------------------------

def normalize_country(raw: str) -> str:
    return raw.strip().upper()


def normalize_name(raw: str) -> str:
    return raw.strip()
