"""Finding model: one diagnostic with stable identity, span, and explanation."""

from dataclasses import dataclass, replace
from typing import Any

from shockharness.ir.model import Span

CONFIDENCE_EXACT = "exact"
CONFIDENCE_APPROXIMATE = "approximate"
CONFIDENCE_UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class SuppressionRecord:
    line: int
    reason: str

    def to_json_dict(self) -> dict[str, Any]:
        return {"line": self.line, "reason": self.reason}


@dataclass(frozen=True)
class Finding:
    rule_id: str
    rule_version: str
    severity: str
    path: str
    span: Span
    message: str
    evidence: str
    confidence: str
    remediation: str
    safe_autofix: bool
    scope: str | None
    suppression: SuppressionRecord | None

    @property
    def is_suppressed(self) -> bool:
        return self.suppression is not None

    def sort_key(self) -> tuple[str, int, int, str, str]:
        return (self.path, self.span.line, self.span.column, self.rule_id, self.message)

    def with_suppression(self, record: SuppressionRecord) -> "Finding":
        return replace(self, suppression=record)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_version": self.rule_version,
            "severity": self.severity,
            "path": self.path,
            "span": self.span.to_json_dict(),
            "message": self.message,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "remediation": self.remediation,
            "safe_autofix": self.safe_autofix,
            "scope": self.scope,
            "suppression": None if self.suppression is None else self.suppression.to_json_dict(),
        }
