"""Field normalizers. Each returns a normalized value or raises InvalidValue."""

from __future__ import annotations

import datetime as _dt
import re


class InvalidValue(ValueError):
    """The value is present but cannot be used; the message is the reason."""


def clean_text(value: str | None) -> str:
    return (value or "").strip()


# --- email -----------------------------------------------------------------

_LOCAL_RE = re.compile(r"^[a-z0-9!#$%&'*+/=?^_`{|}~-]+(\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*$")
_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if email.count("@") != 1:
        raise InvalidValue("email must contain exactly one '@'")
    local, domain = email.split("@")
    if not local or len(local) > 64 or not _LOCAL_RE.match(local):
        raise InvalidValue("email has an invalid local part")
    labels = domain.split(".")
    if len(labels) < 2 or not all(_LABEL_RE.match(label) for label in labels):
        raise InvalidValue("email has an invalid domain")
    if not labels[-1].isalpha() or len(labels[-1]) < 2:
        raise InvalidValue("email has an invalid top-level domain")
    return email


# --- country ---------------------------------------------------------------

def normalize_country(value: str) -> str:
    country = value.strip()
    if len(country) == 2 and country.isalpha():
        return country.upper()
    return country


# --- phone -----------------------------------------------------------------

def _valid_us(nsn: str) -> bool:
    # NANP: NPA-NXX-XXXX, area code and exchange cannot start with 0 or 1.
    return len(nsn) == 10 and nsn[0] in "23456789" and nsn[3] in "23456789"


def _valid_gb(nsn: str) -> bool:
    return len(nsn) in (9, 10) and nsn[0] != "0"


def _valid_de(nsn: str) -> bool:
    return 6 <= len(nsn) <= 13 and nsn[0] != "0"


def _valid_fr(nsn: str) -> bool:
    return len(nsn) == 9 and nsn[0] != "0"


# country -> (calling code, trunk prefix, validator of the national significant number)
PHONE_RULES = {
    "US": ("1", "1", _valid_us),
    "GB": ("44", "0", _valid_gb),
    "DE": ("49", "0", _valid_de),
    "FR": ("33", "0", _valid_fr),
}
_BY_CALLING_CODE = {code: country for country, (code, _, _) in PHONE_RULES.items()}

_PHONE_CHARS_RE = re.compile(r"^\+?[0-9 ().\-/]+$")


def normalize_phone(value: str, country: str) -> tuple[str, bool]:
    """Return (phone, verified).

    Verified phones are in E.164. Unverified phones are the digits as given
    (keeping a leading '+'), used when the number's country is not supported.
    """
    raw = value.strip()
    if not _PHONE_CHARS_RE.match(raw):
        raise InvalidValue("phone contains characters other than digits and separators")
    digits = re.sub(r"\D", "", raw)
    international = raw.startswith("+")
    if not international and digits.startswith("00"):
        international, digits = True, digits[2:]
    if not 5 <= len(digits) <= 15:
        raise InvalidValue("phone has too few or too many digits")

    if international:
        for code, cc_country in _BY_CALLING_CODE.items():
            if digits.startswith(code):
                _, _, valid = PHONE_RULES[cc_country]
                nsn = digits[len(code):]
                if not valid(nsn):
                    raise InvalidValue(f"phone is not a valid {cc_country} number")
                return f"+{code}{nsn}", True
        return f"+{digits}", False

    rules = PHONE_RULES.get(country)
    if rules is None:
        return digits, False
    code, trunk, valid = rules
    candidates = []
    if digits.startswith(trunk):
        candidates.append(digits[len(trunk):])
    candidates.append(digits)
    if digits.startswith(code):  # calling code written without '+'
        candidates.append(digits[len(code):])
    for nsn in candidates:
        if valid(nsn):
            return f"+{code}{nsn}", True
    raise InvalidValue(f"phone is not a valid {country} number")


# --- birthday --------------------------------------------------------------

_ISO_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_SLASH_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def _make_date(year: int, month: int, day: int) -> _dt.date:
    try:
        return _dt.date(year, month, day)
    except ValueError:
        raise InvalidValue("birthday is not a real date") from None


def normalize_birthday(value: str, today: _dt.date | None = None) -> str:
    text = value.strip()
    today = today or _dt.date.today()
    if m := _ISO_RE.match(text):
        date = _make_date(int(m[1]), int(m[2]), int(m[3]))
    elif m := _SLASH_RE.match(text):
        a, b, year = int(m[1]), int(m[2]), int(m[3])
        if a > 12 and b > 12:
            raise InvalidValue("birthday is not a real date")
        if a <= 12 and b <= 12 and a != b:
            raise InvalidValue("birthday is ambiguous (could be DD/MM/YYYY or MM/DD/YYYY)")
        if a > 12:  # DD/MM/YYYY
            date = _make_date(year, b, a)
        else:  # MM/DD/YYYY, or both readings agree
            date = _make_date(year, a, b)
    else:
        raise InvalidValue("birthday is not in YYYY-MM-DD, DD/MM/YYYY or MM/DD/YYYY format")
    if date > today:
        raise InvalidValue("birthday is in the future")
    return date.isoformat()
