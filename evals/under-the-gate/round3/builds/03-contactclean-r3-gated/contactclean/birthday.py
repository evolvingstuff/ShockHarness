"""Birthday normalization to ISO 8601 (YYYY-MM-DD)."""

import calendar
import datetime
import re

from contactclean.results import FieldResult, Invalid, Valid

_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_SLASHED = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
# calendar.month_name holds an empty entry at index 0, then one name per month.
_MONTHS = range(1, len(calendar.month_name))


def _is_date(year: int, month: int, day: int) -> bool:
    if year < datetime.MINYEAR or month not in _MONTHS:
        return False
    _, days_in_month = calendar.monthrange(year, month)
    return 1 <= day <= days_in_month


def _iso(year: int, month: int, day: int) -> str:
    return datetime.date(year, month, day).isoformat()


def _from_slashed(first: int, second: int, year: int, raw: str) -> FieldResult:
    as_day_month = _is_date(year, second, first)
    as_month_day = _is_date(year, first, second)
    if as_day_month and as_month_day and first != second:
        return Invalid(f"ambiguous date, could be DD/MM/YYYY or MM/DD/YYYY: {raw!r}")
    if as_day_month:
        return Valid(_iso(year, second, first))
    if as_month_day:
        return Valid(_iso(year, first, second))
    return Invalid(f"not a valid date: {raw!r}")


def normalize_birthday(raw: str) -> FieldResult:
    """Accept YYYY-MM-DD, DD/MM/YYYY and MM/DD/YYYY; a slashed date must be unambiguous."""
    text = raw.strip()
    if not text:
        return Valid("")
    iso = _ISO.fullmatch(text)
    if iso is not None:
        year, month, day = (int(part) for part in iso.groups())
        if not _is_date(year, month, day):
            return Invalid(f"not a valid date: {text!r}")
        return Valid(_iso(year, month, day))
    slashed = _SLASHED.fullmatch(text)
    if slashed is not None:
        first, second, year = (int(part) for part in slashed.groups())
        return _from_slashed(first, second, year, text)
    return Invalid(f"unsupported date format (use YYYY-MM-DD, DD/MM/YYYY or MM/DD/YYYY): {text!r}")
