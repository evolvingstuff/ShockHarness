"""Finding model: one diagnostic with stable identity, span, and explanation."""

from dataclasses import dataclass, replace
from typing import Any

from shockharness.ir.model import (
    CONFIDENCE_APPROXIMATE,
    CONFIDENCE_EXACT,
    CONFIDENCE_UNRESOLVED,
    Span,
)
from shockharness.rules.registry import category_of

__all__ = [
    "CONFIDENCE_APPROXIMATE",
    "CONFIDENCE_EXACT",
    "CONFIDENCE_UNRESOLVED",
    "FINDING_STATUSES",
    "STATUS_UNKNOWN",
    "STATUS_VIOLATION",
    "Finding",
    "SuppressionRecord",
]

# A finding's status (H1), orthogonal to its severity. ``violation``: the rule established
# the property it checks and it does not hold. ``unknown``: the rule could not establish
# the property (an unresolved exception identity, an opaque handler, a receiver whose type
# is not established) and says so instead of passing; ``fail_on_unknown`` of the rule's
# family decides whether an unknown finding gates (see gate.py).
STATUS_VIOLATION = "violation"
STATUS_UNKNOWN = "unknown"
FINDING_STATUSES = (STATUS_VIOLATION, STATUS_UNKNOWN)


@dataclass(frozen=True)
class SuppressionRecord:
    line: int
    reason: str

    def to_json_dict(self) -> dict[str, Any]:
        return {"line": self.line, "reason": self.reason}


@dataclass(frozen=True)
class Finding:
    """One diagnostic.

    ``fingerprint`` is assigned once every finding of the file is known (it carries an
    occurrence index); ``baseline`` is ``None`` until a baseline or base revision is
    applied, then ``"matched"`` (counted, not gating) or ``"ignored"`` (not counted).
    ``status`` is one of :data:`FINDING_STATUSES`; every rule decides it explicitly.
    """

    rule_id: str
    rule_version: str
    severity: str
    path: str
    span: Span
    message: str
    evidence: str
    confidence: str
    status: str
    remediation: str
    safe_autofix: bool
    scope: str | None
    suppression: SuppressionRecord | None
    fingerprint: str | None
    baseline: str | None

    def __post_init__(self) -> None:
        assert self.status in FINDING_STATUSES, f"unknown finding status {self.status!r}"

    @property
    def is_unknown(self) -> bool:
        return self.status == STATUS_UNKNOWN

    @property
    def is_suppressed(self) -> bool:
        return self.suppression is not None

    def sort_key(self) -> tuple[str, int, int, str, str]:
        return (self.path, self.span.line, self.span.column, self.rule_id, self.message)

    def with_suppression(self, record: SuppressionRecord) -> "Finding":
        return replace(self, suppression=record)

    def with_fingerprint(self, fingerprint: str) -> "Finding":
        return replace(self, fingerprint=fingerprint)

    def with_baseline(self, marker: str | None) -> "Finding":
        return replace(self, baseline=marker)

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
            "status": self.status,
            "category": category_of(self.rule_id),
            "remediation": self.remediation,
            "safe_autofix": self.safe_autofix,
            "scope": self.scope,
            "suppression": None if self.suppression is None else self.suppression.to_json_dict(),
            "fingerprint": self.fingerprint,
            "baseline": self.baseline,
        }
