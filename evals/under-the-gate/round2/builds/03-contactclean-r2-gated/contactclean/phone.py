"""Phone number normalization to E.164 for supported countries."""

import json
from dataclasses import dataclass
from importlib import resources

from contactclean.errors import Rejected

SEPARATORS = frozenset(" -.()/")
PLUS = "+"


@dataclass(frozen=True)
class CountryRule:
    calling_code: str
    international_prefix: str
    trunk_prefix: str
    national_lengths: frozenset[int]
    invalid_first_digits: str


@dataclass(frozen=True)
class PhoneRules:
    e164_max_digits: int
    unverified_min_digits: int
    countries: dict[str, CountryRule]


@dataclass(frozen=True)
class Phone:
    value: str
    verified: bool


def load_phone_rules() -> PhoneRules:
    """Load the per-country numbering rules shipped with the package."""
    raw = json.loads(resources.files("contactclean").joinpath("phone_rules.json").read_text(encoding="utf-8"))
    countries = {
        code: CountryRule(
            calling_code=rule["calling_code"],
            international_prefix=rule["international_prefix"],
            trunk_prefix=rule["trunk_prefix"],
            national_lengths=frozenset(rule["national_lengths"]),
            invalid_first_digits=rule["invalid_first_digits"],
        )
        for code, rule in raw["countries"].items()
    }
    return PhoneRules(
        e164_max_digits=int(raw["e164_max_digits"]),
        unverified_min_digits=int(raw["unverified_min_digits"]),
        countries=countries,
    )


def _strip_separators(text: str) -> tuple[bool, str] | Rejected:
    """Return whether the number was written with a leading '+' and its digits."""
    has_plus = text.startswith(PLUS)
    body = text[len(PLUS):] if has_plus else text
    kept = [char for char in body if char not in SEPARATORS]
    for char in kept:
        if not (char.isascii() and char.isdigit()):
            return Rejected(f"phone contains {char!r}, which is not a digit")
    digits = "".join(kept)
    if not digits:
        return Rejected("phone contains no digits")
    return has_plus, digits


def _national_number(digits: str, has_plus: bool, rule: CountryRule) -> str | Rejected:
    """Reduce a number written in any accepted form to its national significant number."""
    if has_plus or digits.startswith(rule.international_prefix):
        international = digits if has_plus else digits[len(rule.international_prefix):]
        if not international.startswith(rule.calling_code):
            return Rejected(f"phone does not start with the calling code +{rule.calling_code} of its country")
        return international[len(rule.calling_code):]
    trunk_stripped = digits[len(rule.trunk_prefix):]
    if digits.startswith(rule.trunk_prefix) and len(trunk_stripped) in rule.national_lengths:
        return trunk_stripped
    return digits


def _unverified(digits: str, has_plus: bool, rules: PhoneRules) -> Phone | Rejected:
    if len(digits) < rules.unverified_min_digits:
        return Rejected(f"phone has only {len(digits)} digits")
    prefix = PLUS if has_plus else ""
    return Phone(value=prefix + digits, verified=False)


def _verified(digits: str, has_plus: bool, country: str, rule: CountryRule) -> Phone | Rejected:
    national = _national_number(digits, has_plus, rule)
    if isinstance(national, Rejected):
        return national
    if len(national) not in rule.national_lengths:
        return Rejected(f"phone has {len(national)} national digits, not a valid length for {country}")
    if national[0] in rule.invalid_first_digits:
        return Rejected(f"phone national number cannot start with {national[0]} in {country}")
    return Phone(value=PLUS + rule.calling_code + national, verified=True)


def normalize_phone(text: str, country: str, rules: PhoneRules) -> Phone | Rejected:
    """Normalize a non-empty phone; E.164 and verified when the country is supported."""
    stripped = _strip_separators(text)
    if isinstance(stripped, Rejected):
        return stripped
    has_plus, digits = stripped
    if len(digits) > rules.e164_max_digits:
        return Rejected(f"phone has {len(digits)} digits, more than E.164 allows ({rules.e164_max_digits})")
    if country not in rules.countries:
        return _unverified(digits, has_plus, rules)
    phone = _verified(digits, has_plus, country, rules.countries[country])
    if isinstance(phone, Phone) and len(phone.value) - len(PLUS) > rules.e164_max_digits:
        return Rejected(f"phone {phone.value} is longer than E.164 allows")
    return phone
