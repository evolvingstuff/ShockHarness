"""Load the numbering-plan data shipped with the package (phone_plans.json)."""

import json
from importlib import resources
from types import MappingProxyType

from contactclean.model import PhonePlan, PhoneRules

PLAN_FILE = "phone_plans.json"


def _positive_int(value: object, what: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{PLAN_FILE}: {what} must be a positive integer, got {value!r}")
    return value


def _digit_string(value: object, what: str) -> str:
    if not isinstance(value, str) or not value.isdigit():
        raise ValueError(f"{PLAN_FILE}: {what} must be a string of digits, got {value!r}")
    return value


def _plan(country: str, raw: dict[str, object]) -> PhonePlan:
    plan = PhonePlan(
        calling_code=_digit_string(raw["calling_code"], f"{country}.calling_code"),
        trunk_prefix=_digit_string(raw["trunk_prefix"], f"{country}.trunk_prefix"),
        min_digits=_positive_int(raw["min_digits"], f"{country}.min_digits"),
        max_digits=_positive_int(raw["max_digits"], f"{country}.max_digits"),
    )
    if plan.min_digits > plan.max_digits:
        raise ValueError(f"{PLAN_FILE}: {country} has min_digits above max_digits")
    return plan


def load_phone_rules() -> PhoneRules:
    """Read the bundled plans; a malformed file raises KeyError or ValueError."""
    raw = json.loads(resources.files(__package__).joinpath(PLAN_FILE).read_text(encoding="utf-8"))
    plans = {country: _plan(country, entry) for country, entry in raw["countries"].items()}
    if not plans:
        raise ValueError(f"{PLAN_FILE}: no countries defined")
    return PhoneRules(
        plans=MappingProxyType(plans),
        e164_max_digits=_positive_int(raw["e164_max_digits"], "e164_max_digits"),
    )
