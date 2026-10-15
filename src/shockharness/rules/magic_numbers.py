"""MAGIC001: every numeric literal in executable code must be exactly 0 or 1.

Value-based: any encoding of 0 or 1 passes. A folded unary-minus literal is a
violation unless it is exactly -1 and ``allow_unary_negative_one`` is set; this
makes ``-0`` and ``-0.0`` violations, as decided in the specification.

``named_constant_definitions`` (0.2.0): a literal that is the whole value of a
module-level named constant definition (``MAX_PAGES = 8``) is reported under
``"report"`` (strict: a named constant is not automatically justified) and
skipped under ``"allow"`` (recommended, minimal: the name is the remedy the rule
asks for). The adapters mark such literals; the rule only reads the mark.
"""

from collections.abc import Mapping
from typing import Any

from shockharness.constants import NEGATIVE_ONE
from shockharness.findings import CONFIDENCE_EXACT, Finding
from shockharness.ir.model import ModuleFacts, NumericLiteral
from shockharness.rules.registry import MAGIC001
from shockharness.rules.severity import section_severity
from shockharness.schema import NAMED_CONSTANT_MODES
from shockharness.source import SourceText

SETTING_NAMED_CONSTANTS = "named_constant_definitions"
NAMED_CONSTANTS_REPORT = NAMED_CONSTANT_MODES[0]


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
                remediation=MAGIC001.remediation,
                safe_autofix=False,
                scope=literal.scope,
                suppression=None,
                fingerprint=None,
                baseline=None,
            )
        )
    return findings
