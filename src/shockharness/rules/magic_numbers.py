"""MAGIC001: every numeric literal in executable code must be exactly 0 or 1.

Value-based: any encoding of 0 or 1 passes. A folded unary-minus literal is a
violation unless it is exactly -1 and ``allow_unary_negative_one`` is set; this
makes ``-0`` and ``-0.0`` violations, as decided in the specification.
"""

from collections.abc import Mapping
from typing import Any

from shockharness.constants import NEGATIVE_ONE
from shockharness.findings import CONFIDENCE_EXACT, Finding
from shockharness.ir.model import ModuleFacts, NumericLiteral
from shockharness.rules.registry import MAGIC001
from shockharness.source import SourceText


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
    findings: list[Finding] = []
    for literal in facts.numeric_literals:
        if _is_allowed(literal, allowed_values, allow_negative_one):
            continue
        where = " in a type annotation" if literal.in_annotation else " in executable code"
        findings.append(
            Finding(
                rule_id=MAGIC001.rule_id,
                rule_version=MAGIC001.version,
                severity=MAGIC001.default_severity,
                path=path,
                span=literal.span,
                message=f"Numeric literal {literal.raw} has no permitted justification{where}",
                evidence=source.excerpt(literal.span.line),
                confidence=CONFIDENCE_EXACT,
                remediation=MAGIC001.remediation,
                safe_autofix=False,
                scope=literal.scope,
                suppression=None,
            )
        )
    return findings
