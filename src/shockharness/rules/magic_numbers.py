"""MAGIC001: every numeric literal in executable code must be exactly 0 or 1; MAGIC004: a
named constant whose name only spells a number (``TWO = 2``).

Value-based: any encoding of 0 or 1 passes. A folded unary-minus literal is a
violation unless it is exactly -1 and ``allow_unary_negative_one`` is set; this
makes ``-0`` and ``-0.0`` violations, as decided in the specification.

``named_constant_definitions`` (0.2.0): a literal that is the whole value of a
module-level named constant definition (``MAX_PAGES = 8``) is reported under
``"report"`` (strict: a named constant is not automatically justified) and
skipped under ``"allow"`` (recommended, minimal: the name is the remedy the rule
asks for). Since 0.3.0 the value may also be arithmetic over literals
(``CHUNK_BYTES = 64 * 1024``): every literal of such a definition carries the
mark. The adapters mark the literals; the rule only reads the mark. Since 0.9.0
(spec 21.1 decision 36) ``"allow"`` is the default of every profile.

MAGIC004 (decision 36) reads the adapters' constant definitions: a name whose words are
all number words or digits (``TWO``, ``ONE_HUNDRED``, ``VALUE_100``) restates the value,
which is what allowing named constants could invite. Filler words (``NUMBER``,
``VALUE``) do not count as meaning; a name with any other word (``TIMEOUT_30``) is not
reported.

MAGIC005 reads the adapters' disguises: a number written as something else so that
MAGIC001 does not see it (``len("  ")``, ``int("30")``, ``Number("3000")``, numbers in an
inline string that is parsed, spaces given as an indent). It applies where MAGIC001
applies, and reports what MAGIC001 would: a value outside ``allowed_values``.
"""

from collections.abc import Mapping
from typing import Any

from shockharness.constants import NEGATIVE_ONE
from shockharness.findings import CONFIDENCE_EXACT, STATUS_VIOLATION, Finding
from shockharness.ir.model import (
    DISGUISE_CONVERSION,
    DISGUISE_INDENT,
    DISGUISE_LENGTH,
    DISGUISE_PARSED,
    MODULE_SCOPE,
    ConstantDefinition,
    Disguise,
    ModuleFacts,
    NumericLiteral,
)
from shockharness.rules.registry import MAGIC001, MAGIC004, MAGIC005
from shockharness.rules.severity import section_severity
from shockharness.schema import NAMED_CONSTANT_MODES
from shockharness.source import SourceText

SETTING_NAMED_CONSTANTS = "named_constant_definitions"
NAMED_CONSTANTS_REPORT = NAMED_CONSTANT_MODES[0]
SETTING_MAGIC004_SEVERITY = "magic004_severity"
SETTING_MAGIC005_SEVERITY = "magic005_severity"
DISGUISE_WORDS = {
    DISGUISE_LENGTH: "the length of a literal",
    DISGUISE_CONVERSION: "a string converted to a number",
    DISGUISE_PARSED: "numbers inside an inline string that is parsed",
    DISGUISE_INDENT: "spaces given where an indent count is meant",
}
NAME_SEPARATOR = "_"
NUMBER_WORDS = frozenset(
    {
        "ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE",
        "TEN", "ELEVEN", "TWELVE", "THIRTEEN", "FOURTEEN", "FIFTEEN", "SIXTEEN",
        "SEVENTEEN", "EIGHTEEN", "NINETEEN", "TWENTY", "THIRTY", "FORTY", "FIFTY",
        "SIXTY", "SEVENTY", "EIGHTY", "NINETY", "HUNDRED", "THOUSAND", "MILLION",
        "BILLION", "DOZEN",
    }
)  # fmt: skip
# Words that say nothing about what a number is for.
FILLER_WORDS = frozenset({"NUMBER", "NUM", "VALUE", "CONST", "CONSTANT", "INT", "AND"})


def spells_a_number(name: str) -> bool:
    """Every word of the name is a number word or digits, filler aside (TWO, ONE_HUNDRED,
    VALUE_100); a name of filler alone, or with any other word, is not."""
    words = [w for w in name.upper().split(NAME_SEPARATOR) if w != ""]
    meaningful = [w for w in words if w not in FILLER_WORDS]
    return len(meaningful) > 0 and all(w in NUMBER_WORDS or w.isdigit() for w in meaningful)


def _is_allowed(
    literal: NumericLiteral, allowed_values: list[Any], allow_negative_one: bool
) -> bool:
    if literal.negated:
        return allow_negative_one and literal.value == NEGATIVE_ONE
    return any(literal.value == allowed for allowed in allowed_values)


def run_magic001(
    facts: ModuleFacts,
    source: SourceText,
    settings: Mapping[str, Any],
    path: str,
) -> list[Finding]:
    allowed_values = list(settings["allowed_values"])
    allow_negative_one = bool(settings["allow_unary_negative_one"])
    report_constants = str(settings[SETTING_NAMED_CONSTANTS]) == NAMED_CONSTANTS_REPORT
    severity = section_severity(settings, MAGIC001.default_severity)
    findings: list[Finding] = []
    for literal in facts.numeric_literals:
        if _is_allowed(literal, allowed_values, allow_negative_one):
            continue
        if literal.constant_definition and not report_constants:
            continue
        where = " in a type annotation" if literal.in_annotation else " in executable code"
        findings.append(
            Finding(
                rule_id=MAGIC001.rule_id,
                rule_version=MAGIC001.version,
                severity=severity,
                path=path,
                span=literal.span,
                message=f"Numeric literal {literal.raw} has no permitted justification{where}",
                evidence=source.excerpt(literal.span.line),
                confidence=CONFIDENCE_EXACT,
                status=STATUS_VIOLATION,
                remediation=MAGIC001.remediation,
                safe_autofix=False,
                scope=literal.scope,
                suppression=None,
                fingerprint=None,
                baseline=None,
            )
        )
    return findings


def _magic004_finding(
    constant: ConstantDefinition, source: SourceText, path: str, severity: str
) -> Finding:
    return Finding(
        rule_id=MAGIC004.rule_id,
        rule_version=MAGIC004.version,
        severity=severity,
        path=path,
        span=constant.span,
        message=(
            f"the constant name {constant.name} only spells a number: it restates the value "
            "instead of saying what the number is for"
        ),
        evidence=source.excerpt(constant.span.line),
        confidence=CONFIDENCE_EXACT,
        status=STATUS_VIOLATION,
        remediation=MAGIC004.remediation,
        safe_autofix=False,
        scope=MODULE_SCOPE,
        suppression=None,
        fingerprint=None,
        baseline=None,
    )


def run_magic004(
    facts: ModuleFacts,
    source: SourceText,
    settings: Mapping[str, Any],
    path: str,
) -> list[Finding]:
    severity = str(settings[SETTING_MAGIC004_SEVERITY])
    return [
        _magic004_finding(constant, source, path, severity)
        for constant in facts.constants
        if spells_a_number(constant.name)
    ]


def _value_allowed(value: int | float, allowed_values: list[Any], allow_negative_one: bool) -> bool:
    if value < 0:
        return allow_negative_one and value == NEGATIVE_ONE
    return any(value == allowed for allowed in allowed_values)


def _magic005_finding(
    disguise: Disguise, hidden: list[int | float], source: SourceText, path: str, severity: str
) -> Finding:
    numbers = ", ".join(str(value) for value in hidden)
    return Finding(
        rule_id=MAGIC005.rule_id,
        rule_version=MAGIC005.version,
        severity=severity,
        path=path,
        span=disguise.span,
        message=(
            f"{disguise.text} is {numbers} written as {DISGUISE_WORDS[disguise.kind]}: "
            "MAGIC001 would report the literal"
        ),
        evidence=source.excerpt(disguise.span.line),
        confidence=CONFIDENCE_EXACT,
        status=STATUS_VIOLATION,
        remediation=MAGIC005.remediation,
        safe_autofix=False,
        scope=disguise.scope,
        suppression=None,
        fingerprint=None,
        baseline=None,
    )


def run_magic005(
    facts: ModuleFacts,
    source: SourceText,
    settings: Mapping[str, Any],
    path: str,
) -> list[Finding]:
    allowed_values = list(settings["allowed_values"])
    allow_negative_one = bool(settings["allow_unary_negative_one"])
    severity = str(settings[SETTING_MAGIC005_SEVERITY])
    findings: list[Finding] = []
    for disguise in facts.disguises:
        hidden = [
            value
            for value in disguise.values
            if not _value_allowed(value, allowed_values, allow_negative_one)
        ]
        if len(hidden) > 0:
            findings.append(_magic005_finding(disguise, hidden, source, path, severity))
    return findings
