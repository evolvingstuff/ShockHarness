"""Gate evaluation: turns findings and file statuses into a pass/fail/error verdict.

Hard violations are counted, never averaged. Suppressed findings do not count.
Analysis failures (parse, read, decode) are a separate dimension controlled by
``parse_errors``; with ``fail`` they produce the internal-error exit code so a
broken file can never look like a passing one.

Legacy findings (fingerprint in a baseline file, or present at the base revision
of a diff) carry a ``baseline`` marker set before the gate runs. ``matched`` ones
are counted in the totals but never fail the gate; ``ignored`` ones are not
counted at all. Both stay in the report.

Complexity never fails a plain ``check``. A revision diff passes the number of
per-unit complexity regressions it found; ``gates.complexity_regressions``
decides whether they fail the gate (``fail``), are listed (``warn``), or are
not mentioned (``ignore``).

Finding status (H1) is orthogonal to severity. A ``violation`` gates by its
severity. An ``unknown`` finding (the rule could not establish the property) is
always counted in ``unknown``; it gates by its severity exactly like a violation
when its family's ``fail_on_unknown`` is true, and otherwise is reported only: it
adds to no other count and never fails the gate.

An *advisory* run (``--exit-zero``) leaves the verdict, its exit code and every
count untouched and only changes what the process returns: a ``fail`` verdict
exits 0. ``error`` (exit 3) is never masked, and configuration or usage errors
never reach the gate at all. The report says ``advisory = true`` so nobody can
mistake the 0 for a pass.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from shockharness.analysis import STATUS_UNSUPPORTED, FileResult
from shockharness.config import (
    FAIL_ON_UNKNOWN_KEY,
    FAIL_ON_UNKNOWN_SECTIONS,
    PARSE_ERRORS_FAIL,
    PARSE_ERRORS_KEY,
    EffectiveConfig,
)
from shockharness.constants import COMMIT_SHORT_HEX, EXIT_INTERNAL_ERROR, EXIT_OK, EXIT_VIOLATIONS
from shockharness.findings import Finding
from shockharness.gating.baseline import (
    LEGACY_IGNORE,
    MARKER_IGNORED,
    SOURCE_FILE,
    BaselineApplication,
)
from shockharness.rules.registry import (
    SEVERITY_ERROR,
    SEVERITY_REVIEW,
    SEVERITY_WARNING,
    get_rule,
)

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
    baselined: int
    new_hard_violations: int
    complexity_regressions: int
    unknown: int
    unknown_gating_families: tuple[str, ...]
    baseline: BaselineApplication | None
    reasons: tuple[str, ...]
    advisory: bool

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "exit_code": self.exit_code,
            "hard_violations": self.hard_violations,
            "suppressed": self.suppressed,
            "warnings": self.warnings,
            "review": self.review,
            "analysis_failures": self.analysis_failures,
            "baselined": self.baselined,
            "new_hard_violations": self.new_hard_violations,
            "complexity_regressions": self.complexity_regressions,
            "unknown": self.unknown,
            "unknown_gating_families": list(self.unknown_gating_families),
            "baseline": None if self.baseline is None else self.baseline.to_json_dict(),
            "reasons": list(self.reasons),
            "advisory": self.advisory,
        }


NO_REGRESSIONS = 0


def family_name(section: str) -> str:
    """``rules.exceptions`` -> ``exceptions``; ``complexity`` -> ``complexity``."""
    parts = section.split(".")
    return parts[len(parts) - 1]


def unknown_gating_sections(config: EffectiveConfig) -> frozenset[str]:
    """The sections (``rules.exceptions`` ...) whose ``fail_on_unknown`` is true."""
    return frozenset(
        section
        for section in FAIL_ON_UNKNOWN_SECTIONS
        if config.section(section)[FAIL_ON_UNKNOWN_KEY] is True
    )


def unknown_gating_families(config: EffectiveConfig) -> tuple[str, ...]:
    """Family names that gate on unknown findings, in ``FAIL_ON_UNKNOWN_SECTIONS`` order."""
    gating = unknown_gating_sections(config)
    return tuple(family_name(s) for s in FAIL_ON_UNKNOWN_SECTIONS if s in gating)


def gates_by_severity(finding: Finding, gating_sections: frozenset[str]) -> bool:
    """True when ``finding`` counts by its severity: a violation always, an unknown
    finding only when its family's ``fail_on_unknown`` is true."""
    if not finding.is_unknown:
        return True
    section = get_rule(finding.rule_id).config_section
    assert section is not None, f"{finding.rule_id} has no family and cannot be unknown"
    return section in gating_sections


REGRESSIONS_FAIL = "fail"
REGRESSIONS_WARN = "warn"
REGRESSIONS_IGNORE = "ignore"


def evaluate(
    findings: Sequence[Finding],
    files: Sequence[FileResult],
    config: EffectiveConfig,
    baseline: BaselineApplication | None,
    complexity_regressions: int,
) -> GateResult:
    """``complexity_regressions`` is the number of per-unit regressions a revision diff
    found against its base; a plain analysis passes :data:`NO_REGRESSIONS`."""
    hard = 0
    legacy_hard = 0
    suppressed = 0
    warnings = 0
    review = 0
    baselined = 0
    unknown = 0
    unknown_reported_only = 0
    gating_sections = unknown_gating_sections(config)
    for finding in findings:
        if finding.is_suppressed:
            suppressed += 1
            continue
        if finding.baseline is not None:
            baselined += 1
            if finding.baseline == MARKER_IGNORED:
                continue
        if finding.is_unknown:
            unknown += 1
            if not gates_by_severity(finding, gating_sections):
                unknown_reported_only += 1
                continue
        if finding.severity == SEVERITY_ERROR:
            hard += 1
            if finding.baseline is not None:
                legacy_hard += 1
        elif finding.severity == SEVERITY_WARNING:
            warnings += 1
        elif finding.severity == SEVERITY_REVIEW:
            review += 1
    new_hard = hard - legacy_hard
    failures = sum(1 for f in files if f.failed)
    unsupported = sum(1 for f in files if f.status == STATUS_UNSUPPORTED)
    parse_failures = failures - unsupported

    reasons: list[str] = []
    parse_policy = config.values[PARSE_ERRORS_KEY]
    hard_policy = config.values["gates"]["new_hard_violations"]
    regression_policy = config.values["gates"]["complexity_regressions"]
    regressions_fail = complexity_regressions > 0 and regression_policy == REGRESSIONS_FAIL

    if (parse_failures > 0 and parse_policy == PARSE_ERRORS_FAIL) or unsupported > 0:
        if parse_failures > 0 and parse_policy == PARSE_ERRORS_FAIL:
            reasons.append(
                f'{parse_failures} file(s) could not be analyzed and parse_errors = "fail"'
            )
        if unsupported > 0:
            reasons.append(
                f"{unsupported} included file(s) have an extension no adapter parses and "
                'unsupported_sources = "fail"'
            )
        status = GATE_ERROR
        exit_code = EXIT_INTERNAL_ERROR
    elif new_hard > 0 and hard_policy == "fail":
        reasons.append(f'{new_hard} new hard violation(s) and gates.new_hard_violations = "fail"')
        status = GATE_FAIL
        exit_code = EXIT_VIOLATIONS
    elif regressions_fail:
        reasons.append(
            f"{complexity_regressions} complexity regression(s) against the base revision and "
            'gates.complexity_regressions = "fail"'
        )
        status = GATE_FAIL
        exit_code = EXIT_VIOLATIONS
    else:
        status = GATE_PASS
        exit_code = EXIT_OK
        if parse_failures > 0:
            reasons.append(
                f'{parse_failures} file(s) could not be analyzed; parse_errors = "warn" '
                "so the gate passes"
            )
        if new_hard > 0:
            reasons.append(
                f"{new_hard} new hard violation(s) reported as warnings because "
                'gates.new_hard_violations = "warn"'
            )
    if complexity_regressions > 0 and regression_policy == REGRESSIONS_WARN:
        reasons.append(
            f"{complexity_regressions} complexity regression(s) against the base revision "
            'reported as warnings (gates.complexity_regressions = "warn"); see '
            "metrics.complexity.regressions"
        )
    elif regressions_fail and status == GATE_FAIL and new_hard > 0:
        reasons.append(
            f"{complexity_regressions} complexity regression(s) against the base revision and "
            'gates.complexity_regressions = "fail"'
        )
    if unknown_reported_only > 0:
        reasons.append(
            f"{unknown_reported_only} unknown finding(s) (the rule could not establish the "
            "property) are reported only: their family's fail_on_unknown is false"
        )
    reasons.extend(_baseline_reasons(baseline, baselined, legacy_hard))

    return GateResult(
        status=status,
        exit_code=exit_code,
        hard_violations=hard,
        suppressed=suppressed,
        warnings=warnings,
        review=review,
        analysis_failures=failures,
        baselined=baselined,
        new_hard_violations=new_hard,
        complexity_regressions=complexity_regressions,
        unknown=unknown,
        unknown_gating_families=unknown_gating_families(config),
        baseline=baseline,
        reasons=tuple(reasons),
        advisory=False,
    )


def as_advisory(gate: GateResult) -> GateResult:
    """The same verdict, marked as an advisory run (``--exit-zero``)."""
    return replace(gate, advisory=True)


def process_exit_code(gate: GateResult) -> int:
    """What the process returns: the gate's exit code, except that an advisory run
    turns ``EXIT_VIOLATIONS`` into ``EXIT_OK``. ``EXIT_INTERNAL_ERROR`` is never masked."""
    if gate.advisory and gate.exit_code == EXIT_VIOLATIONS:
        return EXIT_OK
    return gate.exit_code


def advisory_line(gate: GateResult) -> str:
    return (
        f"shockharness: advisory run (--exit-zero): gate verdict {gate.status.upper()} "
        f"reported as exit {process_exit_code(gate)}"
    )


def _baseline_reasons(
    baseline: BaselineApplication | None, baselined: int, legacy_hard: int
) -> list[str]:
    if baseline is None:
        return []
    if baseline.source == SOURCE_FILE:
        what = "baseline"
    else:
        what = f"base revision {baseline.origin[:COMMIT_SHORT_HEX]}"
    reasons: list[str] = []
    if baseline.applied:
        if baseline.mode == LEGACY_IGNORE:
            reasons.append(
                f"{baselined} legacy finding(s) matched the {what} and were not counted "
                f'(gates.legacy = "{baseline.mode}"); they are still listed'
            )
        else:
            reasons.append(
                f"{baselined} legacy finding(s) matched the {what} ({legacy_hard} hard) and do "
                f'not fail the gate (gates.legacy = "{baseline.mode}"); they are still counted'
            )
    if len(baseline.stale) > 0:
        reasons.append(
            f"{len(baseline.stale)} baseline entry(ies) stale (no longer produced); the "
            "baseline is never updated automatically, recreate it with "
            "`shockharness baseline create`"
        )
    reasons.extend(baseline.notes)
    return reasons
