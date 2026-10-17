"""Email normalization."""

import re

from contactclean.results import FieldResult, Invalid, Valid

_EMAIL = re.compile(r"[^@\s]+@[^@\s.]+(\.[^@\s.]+)+")


def normalize_email(raw: str) -> FieldResult:
    """Trim and lowercase; an address without a local part and a dotted domain is invalid."""
    email = raw.strip().lower()
    if not email:
        return Valid("")
    if _EMAIL.fullmatch(email) is None:
        return Invalid(f"not a valid email address: {raw.strip()!r}")
    return Valid(email)
