"""Phone normalization to E.164 for the countries in phone_plans.json."""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from types import MappingProxyType

from contactclean.results import Invalid, Phone, PhoneResult

_ALLOWED = re.compile(r"\+?[\d\s().\-/]+")
_NON_DIGIT = re.compile(r"\D")
_COUNTRY_CODE = re.compile(r"[A-Z]{2}")
PLUS = "+"
INTERNATIONAL_PREFIX = "00"


@dataclass(frozen=True)
class CountryPlan:
    calling_code: str
    trunk_prefix: str
    national_pattern: re.Pattern[str]


@dataclass(frozen=True)
class PhonePlans:
    countries: Mapping[str, CountryPlan]
    unverified_pattern: re.Pattern[str]


def _required_str(table: Mapping[str, object], key: str, where: str) -> str:
    value = table[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{where}: {key!r} must be a non-empty string")
    return value


def parse_phone_plans(raw: object) -> PhonePlans:
    """Validate the phone plan data; any missing or malformed entry raises."""
    if not isinstance(raw, Mapping):
        raise ValueError("phone plans must be a table")
    countries_raw = raw["countries"]
    if not isinstance(countries_raw, Mapping) or not countries_raw:
        raise ValueError("phone plans: 'countries' must be a non-empty table")
    countries = {}
    for code, table in countries_raw.items():
        if not isinstance(code, str) or _COUNTRY_CODE.fullmatch(code) is None:
            raise ValueError(f"phone plans: {code!r} is not an ISO 3166 alpha-2 code")
        if not isinstance(table, Mapping):
            raise ValueError(f"phone plans: {code} must be a table")
        calling_code = _required_str(table, "calling_code", code)
        if not calling_code.isdigit():
            raise ValueError(f"phone plans: {code} calling_code must be digits")
        countries[code] = CountryPlan(
            calling_code=calling_code,
            trunk_prefix=_required_str(table, "trunk_prefix", code),
            national_pattern=re.compile(_required_str(table, "national_pattern", code)),
        )
    unverified = re.compile(_required_str(raw, "unverified_pattern", "phone plans"))
    return PhonePlans(countries=MappingProxyType(countries), unverified_pattern=unverified)


def load_phone_plans() -> PhonePlans:
    """Read the plans shipped with the package."""
    text = resources.files("contactclean").joinpath("phone_plans.json").read_text(encoding="utf-8")
    return parse_phone_plans(json.loads(text))


def _national_candidates(digits: str, plan: CountryPlan) -> tuple[str, ...]:
    candidates = [digits]
    if digits.startswith(plan.trunk_prefix):
        candidates.append(digits[len(plan.trunk_prefix):])
    if digits.startswith(plan.calling_code):
        candidates.append(digits[len(plan.calling_code):])
    return tuple(candidates)


def _international(digits: str, plans: PhonePlans, text: str) -> PhoneResult:
    for code, plan in plans.countries.items():
        if digits.startswith(plan.calling_code):
            national = digits[len(plan.calling_code):]
            if plan.national_pattern.fullmatch(national) is None:
                return Invalid(f"not a valid {code} phone number: {text!r}")
            return Phone(PLUS + digits, verified=True)
    return _unverified(PLUS + digits, plans, text)


def _unverified(value: str, plans: PhonePlans, text: str) -> PhoneResult:
    if plans.unverified_pattern.fullmatch(value) is None:
        return Invalid(f"not a valid phone number: {text!r}")
    return Phone(value, verified=False)


def normalize_phone(raw: str, country: str, plans: PhonePlans) -> PhoneResult:
    """Return a Phone when usable (empty value for an empty field), Invalid otherwise.

    With a supported country (or an international prefix of a supported calling
    code) the number is checked against that plan and written in E.164; other
    numbers keep their digits as given and are unverified.
    """
    text = raw.strip()
    if not text:
        return Phone("", verified=False)
    if _ALLOWED.fullmatch(text) is None:
        return Invalid(f"phone contains characters other than digits and separators: {text!r}")
    digits = _NON_DIGIT.sub("", text)
    if not digits:
        return Invalid(f"phone contains no digits: {text!r}")
    if text.startswith(PLUS):
        return _international(digits, plans, text)
    if digits.startswith(INTERNATIONAL_PREFIX):
        return _international(digits[len(INTERNATIONAL_PREFIX):], plans, text)
    if country not in plans.countries:
        return _unverified(digits, plans, text)
    plan = plans.countries[country]
    for national in _national_candidates(digits, plan):
        if plan.national_pattern.fullmatch(national) is not None:
            return Phone(PLUS + plan.calling_code + national, verified=True)
    return Invalid(f"not a valid {country} phone number: {text!r}")
