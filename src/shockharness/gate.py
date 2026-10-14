"""Gate evaluation: turns findings and file statuses into a pass/fail/error verdict.

Hard violations are counted, never averaged. Suppressed findings do not count.
Analysis failures (parse, read, decode) are a separate dimension controlled by
``parse_errors``; with ``fail`` they produce the internal-error exit code so a
broken file can never look like a passing one.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from shockharness.analysis import FileResult
from shockharness.config import EffectiveConfig
from shockharness.constants import EXIT_INTERNAL_ERROR, EXIT_OK, EXIT_VIOLATIONS
from shockharness.findings import Finding
from shockharness.rules.registry import SEVERITY_ERROR, SEVERITY_REVIEW, SEVERITY_WARNING

GATE_PASS = "pass"
GATE_FAIL = "fail"
GATE_ERROR = "error"


@dataclass(frozen=True)
class GateResult:
    status: str
    exit_code: int
    hard_violations: int
    suppressed: int
    warnings: int
    review: int
    analysis_failures: int
    reasons: tuple[str, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "exit_code": self.exit_code,
            "hard_violations": self.hard_violations,
            "suppressed": self.suppressed,
            "warnings": self.warnings,
            "review": self.review,
            "analysis_failures": self.analysis_failures,
            "reasons": list(self.reasons),
        }


def evaluate(
    findings: Sequence[Finding], files: Sequence[FileResult], config: EffectiveConfig
) -> GateResult:
    hard = 0
    suppressed = 0
    warnings = 0
    review = 0
    for finding in findings:
        if finding.is_suppressed:
            suppressed += 1
            continue
        if finding.severity == SEVERITY_ERROR:
            hard += 1
        elif finding.severity == SEVERITY_WARNING:
            warnings += 1
        elif finding.severity == SEVERITY_REVIEW:
            review += 1
    failures = sum(1 for f in files if f.failed)

    reasons: list[str] = []
    parse_policy = config.values["parse_errors"]
    hard_policy = config.values["gates"]["new_hard_violations"]

    if failures > 0 and parse_policy == "fail":
        reasons.append(f'{failures} file(s) could not be analyzed and parse_errors = "fail"')
        status = GATE_ERROR
        exit_code = EXIT_INTERNAL_ERROR
    elif hard > 0 and hard_policy == "fail":
        reasons.append(f'{hard} hard violation(s) and gates.new_hard_violations = "fail"')
        status = GATE_FAIL
        exit_code = EXIT_VIOLATIONS
    else:
        status = GATE_PASS
        exit_code = EXIT_OK
        if failures > 0:
            reasons.append(
                f'{failures} file(s) could not be analyzed; parse_errors = "warn" '
                "so the gate passes"
            )
        if hard > 0:
            reasons.append(
                f"{hard} hard violation(s) reported as warnings because "
                'gates.new_hard_violations = "warn"'
            )

    return GateResult(
        status=status,
        exit_code=exit_code,
        hard_violations=hard,
        suppressed=suppressed,
        warnings=warnings,
        review=review,
        analysis_failures=failures,
        reasons=tuple(reasons),
    )
