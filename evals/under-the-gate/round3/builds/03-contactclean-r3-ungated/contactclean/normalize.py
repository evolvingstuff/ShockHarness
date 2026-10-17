"""Field normalizers.

Each normalizer takes an already-trimmed, non-empty string and either returns
the normalized value or raises ``InvalidValue`` with a human-readable reason.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date


class InvalidValue(ValueError):
    """Raised when a non-empty field value cannot be normalized."""


# --- email -----------------------------------------------------------------

_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+"
    r"@"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+"
    r"[A-Za-z]{2,}$"
)


def normalize_email(value: str) -> str:
    email = value.lower()
    if not _EMAIL_RE.match(email):
        raise InvalidValue("not a valid email address")
    local = email.split("@", 1)[0]
    if local.startswith(".") or local.endswith(".") or ".." in local:
        raise InvalidValue("not a valid email address")
    return email


# --- phone -----------------------------------------------------------------

@dataclass(frozen=True)
class _CountryPlan:
    calling_code: str
    trunk_prefix: str | None
    min_len: int  # national significant number length bounds
    max_len: int
    first_digit: str  # allowed first digits of the national number


_COUNTRIES = {
    "US": _CountryPlan("1", None, 10, 10, "23456789"),
    "GB": _CountryPlan("44", "0", 9, 10, "123456789"),
    "DE": _CountryPlan("49", "0", 6, 13, "123456789"),
    "FR": _CountryPlan("33", "0", 9, 9, "123456789"),
}

SUPPORTED_COUNTRIES = frozenset(_COUNTRIES)

_PHONE_PUNCT_RE = re.compile(r"[\s().\-/]")


@dataclass(frozen=True)
class Phone:
    value: str
    verified: bool


def _valid_national(nsn: str, plan: _CountryPlan) -> bool:
    if not (plan.min_len <= len(nsn) <= plan.max_len):
        return False
    if nsn[0] not in plan.first_digit:
        return False
    if plan.calling_code == "1" and nsn[3] not in "23456789":
        return False  # NANP exchange code cannot start with 0 or 1
    return True


def normalize_phone(value: str, country: str) -> Phone:
    """Normalize a phone number.

    With a supported ``country`` the result is E.164 and verified. Otherwise
    the value is kept as given and marked unverified. A number that has a
    leading ``+``/``00`` with a calling code other than the country's is also
    kept unverified, since it cannot be checked against the country's plan.
    """
    compact = _PHONE_PUNCT_RE.sub("", value)
    international = False
    if compact.startswith("+"):
        international = True
        compact = compact[1:]
    elif compact.startswith("00"):
        international = True
        compact = compact[2:]
    if not compact.isdigit() or not compact.isascii():
        raise InvalidValue("phone number contains invalid characters")
    if not 4 <= len(compact) <= 15:
        raise InvalidValue("phone number has an invalid length")

    plan = _COUNTRIES.get(country)
    if plan is None:
        return Phone(value, verified=False)

    candidates: list[str] = []
    if international:
        if not compact.startswith(plan.calling_code):
            return Phone(value, verified=False)
        rest = compact[len(plan.calling_code):]
        candidates.append(rest)
        # Tolerate the common "+44 (0)20..." style.
        if plan.trunk_prefix and rest.startswith(plan.trunk_prefix):
            candidates.append(rest[len(plan.trunk_prefix):])
    else:
        if plan.trunk_prefix and compact.startswith(plan.trunk_prefix):
            candidates.append(compact[len(plan.trunk_prefix):])
        else:
            candidates.append(compact)
            if compact.startswith(plan.calling_code):
                candidates.append(compact[len(plan.calling_code):])

    for nsn in candidates:
        if nsn and _valid_national(nsn, plan):
            return Phone(f"+{plan.calling_code}{nsn}", verified=True)
    raise InvalidValue(f"not a valid {country} phone number")


# --- birthday --------------------------------------------------------------

_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_SLASH_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def _make_date(year: int, month: int, day: int) -> date:
    try:
        return date(year, month, day)
    except ValueError:
        raise InvalidValue("not a real calendar date") from None


def normalize_birthday(value: str, today: date | None = None) -> str:
    today = today or date.today()
    if m := _ISO_RE.match(value):
        d = _make_date(int(m[1]), int(m[2]), int(m[3]))
    elif m := _SLASH_RE.match(value):
        a, b, year = int(m[1]), int(m[2]), int(m[3])
        options = set()
        for day, month in ((a, b), (b, a)):  # DD/MM, then MM/DD
            try:
                options.add(date(year, month, day))
            except ValueError:
                pass
        if not options:
            raise InvalidValue("not a real calendar date")
        if len(options) > 1:
            raise InvalidValue(
                "ambiguous date: could be DD/MM/YYYY or MM/DD/YYYY"
            )
        d = options.pop()
    else:
        raise InvalidValue(
            "unrecognized date format (expected YYYY-MM-DD, DD/MM/YYYY or MM/DD/YYYY)"
        )
    if d > today:
        raise InvalidValue("birthday is in the future")
    return d.isoformat()
