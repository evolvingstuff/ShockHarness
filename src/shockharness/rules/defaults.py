"""DEF001-DEF006: no implicit defaults, no silent fallbacks.

Each rule consumes one family of :class:`DefaultFact` produced by the parser
adapters (``ir/python_defaults.py``, ``ir/javascript_defaults.py``) and maps the
configured mode to a severity:

* ``forbid`` -> ``error`` (fails the gate), ``review`` -> ``review`` (reported,
  never fails), ``allow`` -> no finding. ``rules.defaults.function_parameters``
  drives DEF001 (``dataclass_fields`` drives its dataclass kinds),
  ``missing_value_fallbacks`` DEF002, ``truthiness_fallbacks`` DEF003,
  ``nullish_fallbacks`` DEF004, ``configuration_fallbacks`` DEF006. DEF005 has no
  mode: a handler that turns a failure into a value is always an error.
* The *implicit* shapes (``m.get(k)`` and ``os.getenv("X")`` with no fallback)
  are ``review`` findings whatever the mode (unless ``allow``): the code may
  yield ``None`` for a missing value, but nothing proves the value was required.

DEF005 and EXC002 describe the same handler from two sides. To count it once,
EXC002 does not report the ``return_fallback`` classification while DEF005 is
active; DEF005 reports it (saying so) and adds the handlers whose returned
constant or helper could be traced statically. When DEF005 is disabled, EXC002
reports ``return_fallback`` as before.

Findings are suggestions: ``safe_autofix`` is always false. Removing a default
changes the function's contract; only the author knows whether the value was
optional.
"""

from collections.abc import Mapping
from typing import Any

from shockharness.findings import Finding
from shockharness.ir.model import (
    BODY_RETURN_FALLBACK,
    CONFIDENCE_EXACT,
    FAMILY_CONFIGURATION,
    FAMILY_EXCEPTION,
    FAMILY_MAPPING,
    FAMILY_NULLISH,
    FAMILY_PARAMETER,
    FAMILY_TRUTHINESS,
    KIND_DATACLASS_FACTORY,
    KIND_DATACLASS_FIELD,
    KIND_DESTRUCTURING,
    KIND_ENV_DESTRUCTURING,
    KIND_ENV_GET_IMPLICIT,
    KIND_GETATTR,
    KIND_MAPPING_GET_IMPLICIT,
    KIND_MEMBER_NULLISH,
    KIND_MEMBERSHIP_TERNARY,
    KIND_PARAMETER,
    KIND_PARAMETER_DESTRUCTURING,
    DefaultFact,
    ModuleFacts,
    Span,
)
from shockharness.rules.exceptions import KIND_LABELS
from shockharness.rules.registry import (
    DEF001,
    DEF002,
    DEF003,
    DEF004,
    DEF005,
    DEF006,
    PYTHON,
    SEVERITY_ERROR,
    SEVERITY_REVIEW,
    RuleSpec,
)
from shockharness.rules.severity import section_severity
from shockharness.source import SourceText

MODE_FORBID = "forbid"
MODE_REVIEW = "review"
MODE_ALLOW = "allow"
# Strictest first; a configured mode later in this order than the default loosens the profile.
MODE_ORDER = (MODE_FORBID, MODE_REVIEW, MODE_ALLOW)

KEY_FUNCTION_PARAMETERS = "function_parameters"
KEY_DATACLASS_FIELDS = "dataclass_fields"
KEY_MISSING_VALUE = "missing_value_fallbacks"
KEY_TRUTHINESS = "truthiness_fallbacks"
KEY_NULLISH = "nullish_fallbacks"
KEY_CONFIGURATION = "configuration_fallbacks"

# The strict profile's value for every mode key (also what defaults.toml ships).
STRICT_MODES: Mapping[str, str] = {
    KEY_FUNCTION_PARAMETERS: MODE_FORBID,
    KEY_DATACLASS_FIELDS: MODE_FORBID,
    KEY_MISSING_VALUE: MODE_FORBID,
    KEY_TRUTHINESS: MODE_REVIEW,
    KEY_NULLISH: MODE_FORBID,
    KEY_CONFIGURATION: MODE_FORBID,
}

DEFAULT_RULES: tuple[RuleSpec, ...] = (DEF001, DEF002, DEF003, DEF004, DEF005, DEF006)
FAMILY_RULES: Mapping[str, RuleSpec] = {
    FAMILY_PARAMETER: DEF001,
    FAMILY_MAPPING: DEF002,
    FAMILY_TRUTHINESS: DEF003,
    FAMILY_NULLISH: DEF004,
    FAMILY_EXCEPTION: DEF005,
    FAMILY_CONFIGURATION: DEF006,
}
DATACLASS_KINDS = frozenset({KIND_DATACLASS_FIELD, KIND_DATACLASS_FACTORY})
IMPLICIT_KINDS = frozenset({KIND_MAPPING_GET_IMPLICIT, KIND_ENV_GET_IMPLICIT})
DECLARATION_KINDS = frozenset(
    {
        KIND_PARAMETER,
        KIND_PARAMETER_DESTRUCTURING,
        KIND_DATACLASS_FIELD,
        KIND_DATACLASS_FACTORY,
        KIND_DESTRUCTURING,
        KIND_ENV_DESTRUCTURING,
    }
)
MISSING_KEY_KINDS = frozenset({KIND_MEMBERSHIP_TERNARY, KIND_GETATTR})


def severity_for_mode(mode: str) -> str | None:
    """``forbid`` -> error, ``review`` -> review, ``allow`` -> None (no finding)."""
    if mode == MODE_FORBID:
        return SEVERITY_ERROR
    if mode == MODE_REVIEW:
        return SEVERITY_REVIEW
    return None


def mode_key_for(fact: DefaultFact) -> str | None:
    """The ``rules.defaults`` key whose mode decides this fact's severity (None for DEF005)."""
    if fact.family == FAMILY_PARAMETER:
        return KEY_DATACLASS_FIELDS if fact.kind in DATACLASS_KINDS else KEY_FUNCTION_PARAMETERS
    if fact.family == FAMILY_MAPPING:
        return KEY_MISSING_VALUE
    if fact.family == FAMILY_TRUTHINESS:
        return KEY_TRUTHINESS
    if fact.family == FAMILY_NULLISH:
        return KEY_NULLISH
    if fact.family == FAMILY_CONFIGURATION:
        return KEY_CONFIGURATION
    return None


def _severity(fact: DefaultFact, settings: Mapping[str, Any]) -> str | None:
    key = mode_key_for(fact)
    if key is None:
        return section_severity(settings, SEVERITY_ERROR)
    mode = str(settings[key])
    if mode == MODE_ALLOW:
        return None
    if fact.kind in IMPLICIT_KINDS:
        return SEVERITY_REVIEW
    by_mode = severity_for_mode(mode)
    if by_mode is None:
        return None
    return section_severity(settings, by_mode)


def _message(fact: DefaultFact, language: str) -> str:
    if fact.kind in IMPLICIT_KINDS:
        return fact.detail
    if fact.kind in DECLARATION_KINDS:
        return f"{fact.detail}: {fact.fallback}"
    if fact.family == FAMILY_CONFIGURATION:
        return f"environment variable {fact.subject} falls back to {fact.fallback}; {fact.detail}"
    if fact.family == FAMILY_EXCEPTION:
        return f"exception handler converts the failure into a default: {fact.detail}"
    if fact.family == FAMILY_TRUTHINESS:
        return f"{fact.subject} falls back to {fact.fallback} when falsy; {fact.detail}"
    if fact.family == FAMILY_NULLISH:
        missing = "None" if language == PYTHON else "null or undefined"
        return f"{fact.subject} falls back to {fact.fallback} when {missing}; {fact.detail}"
    if fact.kind == KIND_MEMBER_NULLISH:
        return f"{fact.subject} falls back to {fact.fallback}; {fact.detail}"
    what = "attribute" if fact.kind == KIND_GETATTR else "key"
    if fact.kind in MISSING_KEY_KINDS or fact.family == FAMILY_MAPPING:
        return (
            f"{fact.subject} falls back to {fact.fallback} when the {what} is missing; "
            f"{fact.detail}"
        )
    return fact.detail


def _finding(
    rule: RuleSpec,
    severity: str,
    path: str,
    span: Span,
    message: str,
    source: SourceText,
    confidence: str,
    scope: str,
) -> Finding:
    return Finding(
        rule_id=rule.rule_id,
        rule_version=rule.version,
        severity=severity,
        path=path,
        span=span,
        message=message,
        evidence=source.excerpt(span.line),
        confidence=confidence,
        remediation=rule.remediation,
        safe_autofix=False,
        scope=scope,
        suppression=None,
        fingerprint=None,
        baseline=None,
    )


def run_default_rules(
    facts: ModuleFacts,
    source: SourceText,
    settings: Mapping[str, Any],
    path: str,
    language: str,
    active_rule_ids: frozenset[str],
) -> list[Finding]:
    """Run DEF001-DEF006 over the module's default facts; only ``active_rule_ids`` report."""
    findings: list[Finding] = []
    for fact in facts.defaults:
        rule = FAMILY_RULES[fact.family]
        if rule.rule_id not in active_rule_ids:
            continue
        severity = _severity(fact, settings)
        if severity is None:
            continue
        findings.append(
            _finding(
                rule,
                severity,
                path,
                fact.span,
                _message(fact, language),
                source,
                fact.confidence,
                fact.scope,
            )
        )
    if DEF005.rule_id in active_rule_ids:
        for catch in facts.catches:
            if catch.body.classification != BODY_RETURN_FALLBACK:
                continue
            findings.append(
                _finding(
                    DEF005,
                    section_severity(settings, SEVERITY_ERROR),
                    path,
                    catch.span,
                    f"{KIND_LABELS[catch.kind]} converts the exception into a fallback value: "
                    f"{catch.body.detail} (EXC002 classification return_fallback; the handler is "
                    "reported once, here)",
                    source,
                    CONFIDENCE_EXACT,
                    catch.scope,
                )
            )
    return findings


def loosened_modes(settings: Mapping[str, Any]) -> list[str]:
    """Human-readable deviations for every mode key looser than the strict profile."""
    found: list[str] = []
    for key in STRICT_MODES:
        strict = STRICT_MODES[key]
        actual = str(settings[key])
        if MODE_ORDER.index(actual) > MODE_ORDER.index(strict):
            found.append(
                f"rules.defaults.{key} is {actual!r} (strict profile: {strict!r}); "
                f"{_rule_for_key(key).rule_id} findings of that kind "
                + ("are reported as review" if actual == MODE_REVIEW else "are not reported")
            )
    return found


def _rule_for_key(key: str) -> RuleSpec:
    if key in (KEY_FUNCTION_PARAMETERS, KEY_DATACLASS_FIELDS):
        return DEF001
    if key == KEY_MISSING_VALUE:
        return DEF002
    if key == KEY_TRUTHINESS:
        return DEF003
    if key == KEY_NULLISH:
        return DEF004
    return DEF006
