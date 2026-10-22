"""VERIFY001, VERIFY002, VERIFY004, VERIFY006: what a change did to its own verification
(H2).

The facts are extracted per file like every other fact (``ir/*_verification.py``) and
cached with them; this module compares a head revision's facts with the base
revision's and reports what was *added*: skip and focus markers (VERIFY001),
suppression directives (VERIFY002), and assertions made unable to fail (VERIFY004); and
what was *removed*: a test file deleted while the project code it imported remains
(VERIFY006).
Whatever already existed at the base is debt, never a finding here.

A head file is compared with its base version: the same path, or the path git reports
it was renamed from. A file with no base version is new, and everything in it counts
as added. When the base version could not be analyzed, or rename detection failed and
the file has no base version under its own path, the findings are ``unknown``: the rule
cannot tell what this change added.

Findings are policy_integrity, carry ``rules.verification.severity``, and are never
suppressible inline (spec 21.1 decision 5).
"""

from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

from shockharness.complexity.callgraph import resolved_imports
from shockharness.constants import COMMIT_SHORT_HEX, FIRST_COLUMN, FIRST_LINE
from shockharness.findings import (
    CONFIDENCE_EXACT,
    CONFIDENCE_UNRESOLVED,
    STATUS_UNKNOWN,
    STATUS_VIOLATION,
    Finding,
)
from shockharness.gating.baseline import assign_fingerprints
from shockharness.ir.model import (
    DIRECTIVE_SCOPE_FILE,
    DIRECTIVE_SCOPE_LINE,
    DIRECTIVE_SCOPE_NEXT_LINE,
    DIRECTIVE_SCOPE_REGION,
    MARKER_FOCUS,
    MARKER_SKIP,
    MARKER_XFAIL,
    NO_VERIFICATION,
    CaseFact,
    ImportFact,
    SkipMarker,
    Span,
    SuppressionDirective,
    VerificationFacts,
)
from shockharness.roles import ROLE_GENERATED, ROLE_TEST, ROLE_VENDOR, ROLES
from shockharness.rules.registry import VERIFY001, VERIFY002, VERIFY004, VERIFY006, RuleSpec

COVERAGE_ANALYZED = "analyzed"
COVERAGE_DISABLED = "disabled"
COVERAGE_NOT_APPLICABLE = "not_applicable"
NOT_APPLICABLE_REASON = (
    "VERIFY rules compare two revisions; run `shockharness diff` or `shockharness gate` "
    "with --base and --head"
)
RENAMES_AVAILABLE = "available"
RENAMES_UNAVAILABLE = "unavailable"

VERIFICATION_RULES = (VERIFY001, VERIFY002, VERIFY004, VERIFY006)
LISTED_MODULES = 3  # the remaining modules a VERIFY006 message names; the rest are counted
ROLE_SCOPES: Mapping[str, frozenset[str]] = {
    VERIFY001.rule_id: frozenset({ROLE_TEST}),
    VERIFY002.rule_id: frozenset(ROLES) - {ROLE_GENERATED, ROLE_VENDOR},
    VERIFY004.rule_id: frozenset({ROLE_TEST}),
    VERIFY006.rule_id: frozenset({ROLE_TEST}),
}
MARKER_EFFECTS = {
    MARKER_SKIP: "the test no longer runs",
    MARKER_XFAIL: "its failure no longer fails the run",
    MARKER_FOCUS: "every other test in the run is skipped",
}
MARKER_NAMES = {
    MARKER_SKIP: "skip marker",
    MARKER_XFAIL: "expected-failure marker",
    MARKER_FOCUS: "focus marker",
}
SCOPE_PHRASES = {
    DIRECTIVE_SCOPE_LINE: "on its line",
    DIRECTIVE_SCOPE_NEXT_LINE: "on the next line",
    DIRECTIVE_SCOPE_REGION: "until it is re-enabled",
    DIRECTIVE_SCOPE_FILE: "in the whole file",
}

Item = TypeVar("Item")


@dataclass(frozen=True)
class FileVerification:
    """One analyzed file's verification facts with what the comparison needs."""

    path: str
    role: str
    failure: str | None  # why the file could not be analyzed, None when it was
    disabled: frozenset[str]
    facts: VerificationFacts
    language: str
    imports: tuple[ImportFact, ...]  # what VERIFY006 resolves at the base revision


@dataclass(frozen=True)
class Renames:
    """``head_to_base``: root-relative head path -> base path, for files git renamed."""

    available: bool
    error: str | None
    head_to_base: Mapping[str, str]


@dataclass(frozen=True)
class VerificationResult:
    findings: tuple[Finding, ...]
    applied: Mapping[str, tuple[str, ...]]  # head path -> VERIFY rules applied to it
    coverage: dict[str, Any]


def not_applicable_coverage(settings: Mapping[str, Any]) -> dict[str, Any]:
    """``coverage.verification`` for a run without a base revision (a plain check)."""
    status = COVERAGE_NOT_APPLICABLE if settings["enabled"] is True else COVERAGE_DISABLED
    return {
        "status": status,
        "rules": [rule.rule_id for rule in VERIFICATION_RULES],
        "reason": NOT_APPLICABLE_REASON,
    }


def _added(
    head: Sequence[Item], base: Sequence[Item], key: Callable[[Item], Hashable]
) -> list[Item]:
    """The head items left after matching each base item once (a multiset difference)."""
    remaining: dict[Hashable, int] = {}
    for item in base:
        identity = key(item)
        if identity not in remaining:
            remaining[identity] = 0
        remaining[identity] += 1
    added: list[Item] = []
    for item in head:
        identity = key(item)
        if identity in remaining and remaining[identity] > 0:
            remaining[identity] -= 1
            continue
        added.append(item)
    return added


@dataclass(frozen=True)
class _Context:
    path: str
    base_label: str  # "at base 1a2b3c4d5e6f" or "in a new file"
    unknown: str | None  # why the base is unknown, None when it is known
    severity: str


def _finding(
    rule: RuleSpec,
    context: _Context,
    span: Span,
    message: str,
    evidence: str,
    scope: str | None,
) -> Finding:
    status = STATUS_VIOLATION
    confidence = CONFIDENCE_EXACT
    if context.unknown is not None:
        status = STATUS_UNKNOWN
        confidence = CONFIDENCE_UNRESOLVED
        message = f"{message}; unknown: {context.unknown}"
    return Finding(
        rule_id=rule.rule_id,
        rule_version=rule.version,
        severity=context.severity,
        path=context.path,
        span=span,
        message=message,
        evidence=evidence,
        confidence=confidence,
        status=status,
        remediation=rule.remediation,
        safe_autofix=False,
        scope=scope,
        suppression=None,
        fingerprint=None,
        baseline=None,
    )


def _marker_key(marker: SkipMarker) -> Hashable:
    return (marker.test, marker.kind, marker.text)


def _verify001(
    context: _Context, head: VerificationFacts, base: VerificationFacts, allowed: frozenset[str]
) -> list[Finding]:
    findings: list[Finding] = []
    for marker in _added(head.markers, base.markers, _marker_key):
        if marker.reason is not None and marker.reason in allowed:
            continue
        message = (
            f"{MARKER_NAMES[marker.kind]} {marker.text} added to {marker.test}: "
            f"{MARKER_EFFECTS[marker.kind]} (not present {context.base_label})"
        )
        findings.append(
            _finding(VERIFY001, context, marker.span, message, marker.text, marker.test)
        )
    return findings


def _directive_key(directive: SuppressionDirective) -> Hashable:
    return (directive.tool, directive.text)


def _verify002(
    context: _Context, head: VerificationFacts, base: VerificationFacts, report_narrow: bool
) -> list[Finding]:
    findings: list[Finding] = []
    for directive in _added(head.suppressions, base.suppressions, _directive_key):
        where = SCOPE_PHRASES[directive.scope]
        if directive.narrow:
            if not report_narrow:
                continue
            message = (
                f"suppression {directive.text} added for {', '.join(directive.codes)} {where} "
                f"(not present {context.base_label}; reported because "
                "rules.verification.report_narrow_suppressions = true)"
            )
        else:
            message = (
                f"blanket suppression {directive.text} added: it names no specific rule "
                f"codes, so it silences every check of that tool {where} "
                f"(not present {context.base_label})"
            )
        findings.append(_finding(VERIFY002, context, directive.span, message, directive.text, None))
    return findings


def _tautology_key(item: tuple[str, str, Span]) -> Hashable:
    case_name, text, _ = item
    return (case_name, text)


def _verify004(
    context: _Context, head: VerificationFacts, base: VerificationFacts
) -> list[Finding]:
    findings: list[Finding] = []
    head_tautologies = [(c.name, t.text, t.span) for c in head.cases for t in c.tautologies]
    base_tautologies = [(c.name, t.text, t.span) for c in base.cases for t in c.tautologies]
    for case_name, text, span in _added(head_tautologies, base_tautologies, _tautology_key):
        message = (
            f"assertion {text} added to {case_name} can never fail "
            f"(not present {context.base_label})"
        )
        findings.append(_finding(VERIFY004, context, span, message, text, case_name))
    base_cases: dict[str, CaseFact] = {}
    for case in base.cases:
        if case.name not in base_cases:
            base_cases[case.name] = case
    for case in head.cases:
        if case.name not in base_cases:
            continue
        before = base_cases[case.name]
        if before.assertions == 0 or case.assertions > 0:
            continue
        if case.body_empty and not before.body_empty:
            message = (
                f"the body of {case.name} is now empty (pass, ..., a docstring or an empty "
                f"block); it had {before.assertions} assertion(s) {context.base_label}"
            )
        else:
            message = (
                f"{case.name} had {before.assertions} assertion(s) {context.base_label} and "
                "has none now; the test can no longer fail"
            )
        evidence = f"{case.name}: {before.assertions} -> {case.assertions} assertion(s)"
        findings.append(_finding(VERIFY004, context, case.span, message, evidence, case.name))
    return findings


def _deleted_tests(
    base: Mapping[str, FileVerification], head: Mapping[str, FileVerification], renames: Renames
) -> list[FileVerification]:
    """Test files of the base that the head neither has nor renamed."""
    renamed_from = frozenset(renames.head_to_base.values())
    return [
        file
        for path, file in sorted(base.items())
        if path not in head
        and path not in renamed_from
        and file.failure is None
        and VERIFY006.rule_id not in file.disabled
        and file.role in ROLE_SCOPES[VERIFY006.rule_id]
    ]


def _verify006(
    base: Mapping[str, FileVerification],
    head: Mapping[str, FileVerification],
    renames: Renames,
    short: str,
    severity: str,
) -> list[Finding]:
    """A test file deleted while every project module it imported remains: the change
    removes verification of code that is still there. A file that imported no project
    module (a helper, a conftest) is not judged."""
    deleted = _deleted_tests(base, head, renames)
    if len(deleted) == 0:
        return []
    targets = resolved_imports([(f.path, f.language, f.imports) for f in base.values()])
    present = frozenset(head) | frozenset(renames.head_to_base.values())
    unknown: str | None = None
    if not renames.available:
        unknown = f"rename detection failed ({renames.error}), so the file may have moved"
    found: list[Finding] = []
    for file in deleted:
        imported = sorted(t for t in targets[file.path] if t != file.path)
        if len(imported) == 0 or any(t not in present for t in imported):
            continue
        listed = ", ".join(imported[:LISTED_MODULES])
        if len(imported) > LISTED_MODULES:
            listed += f" and {len(imported) - LISTED_MODULES} more"
        message = (
            f"{file.path} is deleted since base {short}, while the project code it imported "
            f"remains ({listed}): its tests are gone and nothing in this change replaces them"
        )
        context = _Context(file.path, f"at base {short}", unknown, severity)
        span = Span(FIRST_LINE, FIRST_COLUMN, FIRST_LINE, FIRST_COLUMN)
        found.extend(assign_fingerprints([_finding(VERIFY006, context, span, message, "", None)]))
    return found


def _applied_rules(file: FileVerification) -> tuple[str, ...]:
    return tuple(
        rule.rule_id
        for rule in VERIFICATION_RULES
        if rule.rule_id not in file.disabled and file.role in ROLE_SCOPES[rule.rule_id]
    )


def compare_revisions(
    base: Mapping[str, FileVerification],
    head: Mapping[str, FileVerification],
    renames: Renames,
    settings: Mapping[str, Any],
    base_commit: str,
) -> VerificationResult:
    """Every VERIFY finding for the head revision, fingerprinted, with coverage."""
    short = base_commit[:COMMIT_SHORT_HEX]
    severity = str(settings["severity"])
    allowed = frozenset(str(reason) for reason in settings["allowed_skip_reasons"])
    report_narrow = bool(settings["report_narrow_suppressions"])
    enabled = settings["enabled"] is True
    by_path: dict[str, list[Finding]] = {}
    applied: dict[str, tuple[str, ...]] = {}
    rules_seen: set[str] = set()
    counts = {"files_compared": 0, "files_new": 0, "renamed": 0, "base_unanalyzable": 0}
    for path in sorted(head):
        file = head[path]
        if file.failure is not None or not enabled:
            continue
        rules = _applied_rules(file)
        if len(rules) == 0:
            continue
        applied[path] = rules
        rules_seen.update(rules)
        counts["files_compared"] += 1
        base_path = path
        if path in renames.head_to_base:
            base_path = renames.head_to_base[path]
            counts["renamed"] += 1
        base_facts = NO_VERIFICATION
        unknown: str | None = None
        base_label = f"at base {short}"
        if base_path not in base:
            base_label = f"in a file that does not exist at base {short}"
            counts["files_new"] += 1
            if not renames.available:
                unknown = (
                    f"rename detection failed ({renames.error}), so whether {path} is new "
                    "or renamed cannot be established"
                )
        elif base[base_path].failure is not None:
            counts["base_unanalyzable"] += 1
            unknown = (
                f"the base version of {base_path} could not be analyzed "
                f"({base[base_path].failure}), so what this change added cannot be established"
            )
        else:
            base_facts = base[base_path].facts
        context = _Context(path, base_label, unknown, severity)
        found: list[Finding] = []
        if VERIFY001.rule_id in rules:
            found.extend(_verify001(context, file.facts, base_facts, allowed))
        if VERIFY002.rule_id in rules:
            found.extend(_verify002(context, file.facts, base_facts, report_narrow))
        if VERIFY004.rule_id in rules:
            found.extend(_verify004(context, file.facts, base_facts))
        if len(found) > 0:
            found.sort(key=lambda f: f.sort_key())
            by_path[path] = assign_fingerprints(found)
    by_path.update(_deletions(base, head, renames, short, severity, enabled=enabled))
    findings = tuple(f for path in sorted(by_path) for f in by_path[path])
    coverage = _coverage(settings, rules_seen, base_commit, counts, renames)
    return VerificationResult(findings=findings, applied=applied, coverage=coverage)


def _deletions(
    base: Mapping[str, FileVerification],
    head: Mapping[str, FileVerification],
    renames: Renames,
    short: str,
    severity: str,
    *,
    enabled: bool,
) -> dict[str, list[Finding]]:
    """VERIFY006's findings by deleted path (none while the family is off)."""
    if not enabled:
        return {}
    return {f.path: [f] for f in _verify006(base, head, renames, short, severity)}


def _coverage(
    settings: Mapping[str, Any],
    rules_seen: set[str],
    base_commit: str,
    counts: Mapping[str, int],
    renames: Renames,
) -> dict[str, Any]:
    enabled = settings["enabled"] is True
    return {
        "status": COVERAGE_ANALYZED if enabled else COVERAGE_DISABLED,
        "rules": sorted(rules_seen),
        "base_commit": base_commit,
        **counts,
        "rename_detection": RENAMES_AVAILABLE if renames.available else RENAMES_UNAVAILABLE,
        "rename_detection_error": renames.error,
        "severity": str(settings["severity"]),
        "allowed_skip_reasons": sorted(str(reason) for reason in settings["allowed_skip_reasons"]),
        "report_narrow_suppressions": bool(settings["report_narrow_suppressions"]),
    }
