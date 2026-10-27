"""Revision diff: analyze the full tree at two commits and compare by fingerprint.

Both revisions are resolved with local git only, exported with ``git archive``
into temporary directories, and analyzed completely (not just changed files) so
that cross-file effects are never missed. ``diff_revisions`` does not analyze the
working tree: uncommitted changes are not part of ``HEAD``; ``diff_working_tree`` (the
finish-time hook) compares a base revision with the working tree itself. The
configuration is the working tree's, applied to both sides, so the diff compares code
under one policy.

A diff finding's ``status`` has meant ``new``/``fixed``/``unchanged`` since 0.1.0, so
the finding's own status (H1: ``violation`` or ``unknown``) is ``finding_status`` there.
"""

import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from shockharness import gate as gate_module
from shockharness.analysis import (
    AnalysisOptions,
    AnalysisOutcome,
    analyze_files,
    with_unsupported_sources,
)
from shockharness.api import open_run_cache
from shockharness.cache.store import (
    REASON_REVISION,
    STATUS_BYPASSED,
    FileCache,
    cache_coverage_without_cache,
    cache_directory,
    cache_settings,
)
from shockharness.complexity.regressions import abstraction_displacement, complexity_regressions
from shockharness.config import EffectiveConfig
from shockharness.constants import REPORT_SCHEMA_VERSION
from shockharness.discovery import DiscoveryResult, discover
from shockharness.errors import UsageError
from shockharness.findings import Finding
from shockharness.gate import NO_REGRESSIONS, GateResult
from shockharness.gating.baseline import SOURCE_BASE_REVISION, apply_fingerprints
from shockharness.history.git import (
    RepositoryLocation,
    export_tree,
    locate_repository,
    renamed_files,
)
from shockharness.history.git import resolve_commit as git_resolve_commit
from shockharness.report import (
    VERIFICATION_COVERAGE,
    Report,
    build_report,
    build_summary,
    config_block,
    execution_summary,
    rebuild_with_findings,
)
from shockharness.roles import FILE_ROLES_KEY, role_classifier
from shockharness.rules.policy_integrity import (
    PolicySnapshot,
    compare_policy,
    fingerprinted,
    policy_attempt_findings,
    strictest_verification,
    take_snapshot,
)
from shockharness.rules.registry import (
    CATEGORY_POLICY,
    SEVERITY_ERROR,
    VERIFICATION_SECTION,
    VERIFY003,
    category_of,
)
from shockharness.rules.verification import (
    FileVerification,
    Renames,
    VerificationResult,
    compare_revisions,
)
from shockharness.version import __version__

COMPLEXITY_SECTION = "complexity"
GRAPH_SECTION = "graph"
STATUS_NEW = "new"
STATUS_FIXED = "fixed"
STATUS_UNCHANGED = "unchanged"


@dataclass(frozen=True)
class Revision:
    ref: str
    commit: str
    report: Report
    # Per-file verification facts (H2) and the committed policy (H2 part 2); compared
    # between base and head, never serialized.
    verification: Mapping[str, FileVerification]
    policy: PolicySnapshot

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "commit": self.commit,
            "analysis_status": self.report.analysis_status,
            "files_analyzed": self.report.coverage["files_analyzed"],
            "files_failed": self.report.coverage["files_failed"],
            "files": [f.to_json_dict() for f in self.report.files],
            "findings": len(self.report.findings),
            "suppressed": sum(1 for f in self.report.findings if f.is_suppressed),
        }


@dataclass(frozen=True)
class DiffFinding:
    status: str
    finding: Finding  # from head for new/unchanged, from base for fixed

    def sort_key(self) -> tuple[str, int, int, str, str, str]:
        return (*self.finding.sort_key(), self.status)

    def to_json_dict(self) -> dict[str, Any]:
        data = self.finding.to_json_dict()
        data["finding_status"] = self.finding.status
        data["status"] = self.status
        return data


def hard_violation(finding: Finding, gating_sections: frozenset[str]) -> bool:
    """Whether the gate counts ``finding`` as a hard violation: an error, not suppressed,
    and (when unknown) in a family whose ``fail_on_unknown`` is on."""
    return (
        finding.severity == SEVERITY_ERROR
        and not finding.is_suppressed
        and gate_module.gates_by_severity(finding, gating_sections)
    )


@dataclass(frozen=True)
class DiffReport:
    schema_version: str
    tool_version: str
    config: EffectiveConfig
    base: Revision
    head: Revision
    findings: tuple[DiffFinding, ...]
    metrics: dict[str, Any]
    gate: GateResult

    def summary(self) -> dict[str, Any]:
        counts = {STATUS_NEW: 0, STATUS_FIXED: 0, STATUS_UNCHANGED: 0}
        hard = {STATUS_NEW: 0, STATUS_FIXED: 0, STATUS_UNCHANGED: 0}
        gating = gate_module.unknown_gating_sections(self.config)
        for entry in self.findings:
            counts[entry.status] += 1
            if hard_violation(entry.finding, gating):
                hard[entry.status] += 1
        return {
            "new": counts[STATUS_NEW],
            "fixed": counts[STATUS_FIXED],
            "unchanged": counts[STATUS_UNCHANGED],
            "new_hard_violations": hard[STATUS_NEW],
            "fixed_hard_violations": hard[STATUS_FIXED],
            "unchanged_hard_violations": hard[STATUS_UNCHANGED],
            "complexity_regressions": self.gate.complexity_regressions,
            "new_policy_integrity": sum(
                1
                for entry in self.findings
                if entry.status == STATUS_NEW
                and category_of(entry.finding.rule_id) == CATEGORY_POLICY
            ),
        }

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "tool_version": self.tool_version,
            "report_kind": "diff",
            "analysis_status": self.head.report.analysis_status,
            "config_digest": self.config.digest,
            "effective_profile": self.config.values["profile"],
            "config": config_block(self.config),
            "coverage": dict(self.head.report.coverage),
            "base": self.base.to_json_dict(),
            "head": self.head.to_json_dict(),
            "findings": [entry.to_json_dict() for entry in self.findings],
            "summary": self.summary(),
            "metrics": dict(self.metrics),
            "gate": self.gate.to_json_dict(),
        }


def _require_repository(root: Path) -> RepositoryLocation:
    location, error = locate_repository(root)
    if location is None:
        raise UsageError(f"revision diff needs a git repository: {error}", str(root))
    return location


def resolve_commit(root: Path, ref: str) -> str:
    commit, error = git_resolve_commit(root, ref)
    if commit is None:
        raise UsageError(f"cannot resolve revision {ref!r}: {error}", ref)
    return commit


def analyze_revision(
    root: Path,
    location: RepositoryLocation,
    ref: str,
    config: EffectiveConfig,
    options: AnalysisOptions,
    base_config: EffectiveConfig | None,
    *,
    is_head: bool,
    cache: FileCache | None,
) -> Revision:
    """Export the tree at ``ref`` and analyze the part that corresponds to ``root``.

    While the tree exists, the revision's committed policy is read (VERIFY003); for the
    head revision, ``base_config`` (the base revision's committed configuration) is used
    to list the files the base configuration would analyze in the head tree. ``cache``
    is None for ``diff`` (an export is analyzed afresh); the finish-time hook passes the
    base revision's own cache."""
    commit = resolve_commit(root, ref)
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="shockharness-") as exported:
        error = export_tree(location.toplevel, commit, Path(exported))
        if error is not None:
            raise UsageError(f"cannot export revision {ref!r}: {error}", ref)
        export_root = Path(exported) / location.prefix
        if not export_root.is_dir():
            where = "." if location.prefix == "" else location.prefix
            raise UsageError(f"the analysis root ({where}) does not exist at {ref}", ref)
        discovery = discover(export_root, [export_root], config)
        outcome = analyze_files(discovery.files, config, options, cache)
        policy = take_snapshot(export_root, Path(exported), location.prefix, base_config, is_head)
    coverage = cache_coverage_without_cache(
        STATUS_BYPASSED, str(cache_settings(config)["directory"]), REASON_REVISION
    )
    if cache is not None:
        coverage = cache.coverage()
    report = _tree_report(discovery, outcome, config, started, coverage)
    return Revision(
        ref=ref, commit=commit, report=report, verification=outcome.verification, policy=policy
    )


def _tree_report(
    discovery: DiscoveryResult,
    outcome: AnalysisOutcome,
    config: EffectiveConfig,
    started: float,
    cache_coverage: dict[str, Any],
) -> Report:
    """One analyzed tree's report, gated on its own (the diff gates it again)."""
    files = with_unsupported_sources(outcome.files, discovery, config)
    findings = [f for result in files for f in result.findings]
    verdict = gate_module.evaluate(findings, files, config, None, NO_REGRESSIONS)
    elapsed = time.perf_counter() - started
    return build_report(
        files, discovery, config, verdict, outcome.metrics, elapsed, cache_coverage, (), {}
    )


WORKING_TREE = "working tree"  # the head's ref when the diff's head is the working tree
# The base revision's cache entries, in a directory of their own under the cache
# directory: entries are kept per path, so sharing the working tree's would overwrite
# the entry of every file the change touched, on both sides, at every run.
BASE_CACHE_DIRECTORY = "base"


@dataclass(frozen=True)
class TreeCaches:
    """The caches of a working-tree diff: both None when the cache is off or bypassed,
    and ``coverage`` is then the working tree's ``coverage.cache`` block."""

    head: FileCache | None
    base: FileCache | None
    coverage: dict[str, Any]


def open_tree_caches(root: Path, config: EffectiveConfig, options: AnalysisOptions) -> TreeCaches:
    head, coverage = open_run_cache(root, config, options)
    if head is None:
        return TreeCaches(None, None, coverage)
    configured = f"{cache_settings(config)['directory']}/{BASE_CACHE_DIRECTORY}"
    base = FileCache(
        cache_directory(root, config) / BASE_CACHE_DIRECTORY, configured, config.digest
    )
    base.open()
    return TreeCaches(head, base, coverage)


def analyze_working_tree(
    root: Path,
    location: RepositoryLocation,
    config: EffectiveConfig,
    options: AnalysisOptions,
    base_config: EffectiveConfig | None,
    caches: TreeCaches,
) -> Revision:
    """The working tree under ``root`` as a head revision: analyzed in place, with the
    project's cache, and its policy read from the files on disk. Its commit is
    ``HEAD``'s, which the working tree may differ from."""
    commit = resolve_commit(root, "HEAD")
    started = time.perf_counter()
    discovery = discover(root, [root], config)
    outcome = analyze_files(discovery.files, config, options, caches.head)
    policy = take_snapshot(root, location.toplevel, location.prefix, base_config, is_head=True)
    coverage = caches.coverage
    if caches.head is not None:
        coverage = caches.head.coverage()
    report = _tree_report(discovery, outcome, config, started, coverage)
    return Revision(
        ref=WORKING_TREE,
        commit=commit,
        report=report,
        verification=outcome.verification,
        policy=policy,
    )


def _renames(location: RepositoryLocation, revisions: Sequence[str]) -> Renames:
    found, error = renamed_files(location, revisions)
    if found is None:
        return Renames(available=False, error=error, head_to_base={})
    return Renames(available=True, error=None, head_to_base=found)


def with_verification(report: Report, result: VerificationResult) -> Report:
    """``report`` (a head revision) with the VERIFY findings added to its files, the
    rules they applied recorded per file, and ``coverage.verification`` filled in."""
    by_path: dict[str, list[Finding]] = {}
    for finding in result.findings:
        if finding.path not in by_path:
            by_path[finding.path] = []
        by_path[finding.path].append(finding)
    files = []
    for file in report.files:
        added: list[Finding] = []
        if file.path in by_path:
            added = by_path[file.path]
        applied = file.rules_applied
        if file.path in result.applied:
            applied = tuple(sorted({*file.rules_applied, *result.applied[file.path]}))
        findings = tuple(sorted([*file.findings, *added], key=lambda f: f.sort_key()))
        files.append(replace(file, rules_applied=applied, findings=findings))
    findings = tuple(sorted([*report.findings, *result.findings], key=lambda f: f.sort_key()))
    coverage = dict(report.coverage)
    coverage[VERIFICATION_COVERAGE] = result.coverage
    analyzed = {file.path for file in report.files}
    classifier = role_classifier(report.config.values[FILE_ROLES_KEY])
    extra_roles = {
        f.path: classifier.classify(f.path).role for f in result.findings if f.path not in analyzed
    }
    return replace(
        report,
        files=tuple(files),
        findings=findings,
        coverage=coverage,
        execution_summary=execution_summary(files, findings),
        summary=build_summary(files, findings, report.metrics, extra_roles),
    )


def _verify(
    root: Path,
    config: EffectiveConfig,
    base: Revision,
    head: Revision,
    renames: Renames,
) -> VerificationResult:
    """VERIFY001-VERIFY004 for the change from ``base`` to ``head``, plus the ``--policy``
    attempts, as one result for the head report."""
    base_settings = None
    if base.policy.config is not None:
        base_settings = base.policy.config.section(VERIFICATION_SECTION)
    # A change cannot switch off or lower the rules that report it doing so.
    settings = strictest_verification(config.section(VERIFICATION_SECTION), base_settings)
    verification = compare_revisions(
        base.verification, head.verification, renames, settings, base.commit
    )
    policy = compare_policy(base.policy, head.policy, renames.head_to_base, settings, base.commit)
    attempts = policy_attempt_findings(config, root, settings)
    policy_findings = fingerprinted([*policy.findings, *attempts])
    rules = set(verification.coverage["rules"])
    if settings["enabled"] is True:
        rules.add(VERIFY003.rule_id)
    return VerificationResult(
        findings=tuple(
            sorted([*verification.findings, *policy_findings], key=lambda f: f.sort_key())
        ),
        applied=verification.applied,
        coverage={
            **verification.coverage,
            "rules": sorted(rules),
            "policy": policy.coverage,
            "policy_attempts": len(attempts),
        },
    )


def _by_fingerprint(findings: Sequence[Finding]) -> dict[str, Finding]:
    by_fp = {f.fingerprint: f for f in findings if f.fingerprint is not None}
    if len(by_fp) != len(findings):
        raise AssertionError("fingerprints must be unique")
    return by_fp


def diff_revisions(
    root: Path,
    base_ref: str,
    head_ref: str,
    config: EffectiveConfig,
    options: AnalysisOptions,
) -> DiffReport:
    """Analyze both revisions and classify every finding as new, fixed, or unchanged.

    The gate is evaluated on the head findings with unchanged ones treated as
    legacy under ``gates.legacy``; head analysis failures follow ``parse_errors``.
    Per-unit complexity regressions against the base revision are listed under
    ``metrics.complexity.regressions`` and follow ``gates.complexity_regressions``;
    the experimental abstraction-displacement heuristic, when enabled, is under
    ``metrics.graph.abstraction_displacement``.
    """
    location = _require_repository(root)
    base = analyze_revision(
        root, location, base_ref, config, options, None, is_head=False, cache=None
    )
    head = analyze_revision(
        root, location, head_ref, config, options, base.policy.config, is_head=True, cache=None
    )
    return _compared(root, config, base, head, _renames(location, (base.commit, head.commit)))


def diff_working_tree(
    root: Path, base_ref: str, config: EffectiveConfig, options: AnalysisOptions
) -> DiffReport:
    """``diff_revisions`` with the working tree as the head: what a commit of the tree as
    it is would add. The base export is analyzed with a cache of its own, so the files the
    change did not touch are hits; untracked files are part of the working tree."""
    location = _require_repository(root)
    caches = open_tree_caches(root, config, options)
    base = analyze_revision(
        root, location, base_ref, config, options, None, is_head=False, cache=caches.base
    )
    head = analyze_working_tree(root, location, config, options, base.policy.config, caches)
    return _compared(root, config, base, head, _renames(location, (base.commit,)))


def _compared(
    root: Path, config: EffectiveConfig, base: Revision, head: Revision, renames: Renames
) -> DiffReport:
    combined = _verify(root, config, base, head, renames)
    head = replace(head, report=with_verification(head.report, combined))
    base_by_fp = _by_fingerprint(base.report.findings)
    entries = _classified(base_by_fp, _by_fingerprint(head.report.findings))
    marked, application = apply_fingerprints(
        head.report.findings,
        frozenset(base_by_fp),
        config.values["gates"]["legacy"],
        SOURCE_BASE_REVISION,
        base.commit,
        None,
        None,
        (),
    )
    regressions = complexity_regressions(
        base.report.metrics[COMPLEXITY_SECTION],
        head.report.metrics[COMPLEXITY_SECTION],
        config.section(COMPLEXITY_SECTION),
    )
    verdict = gate_module.evaluate(marked, head.report.files, config, application, len(regressions))
    head_marked = replace(head, report=rebuild_with_findings(head.report, marked, verdict))
    return DiffReport(
        schema_version=REPORT_SCHEMA_VERSION,
        tool_version=__version__,
        config=config,
        base=base,
        head=head_marked,
        findings=_relabelled(entries, marked),
        metrics=_diff_metrics(base, head_marked, regressions, config),
        gate=verdict,
    )


def _classified(
    base_by_fp: Mapping[str, Finding], head_by_fp: Mapping[str, Finding]
) -> list[DiffFinding]:
    entries: list[DiffFinding] = []
    for fingerprint, finding in head_by_fp.items():
        status = STATUS_UNCHANGED if fingerprint in base_by_fp else STATUS_NEW
        entries.append(DiffFinding(status, finding))
    for fingerprint, finding in base_by_fp.items():
        if fingerprint not in head_by_fp:
            entries.append(DiffFinding(STATUS_FIXED, finding))
    entries.sort(key=lambda e: e.sort_key())
    return entries


def _relabelled(
    entries: Sequence[DiffFinding], marked: Sequence[Finding]
) -> tuple[DiffFinding, ...]:
    """The new and unchanged entries with their head finding as the gate marked it."""
    by_fp = {f.fingerprint: f for f in marked}
    relabelled: list[DiffFinding] = []
    for entry in entries:
        if entry.status == STATUS_FIXED:
            relabelled.append(entry)
            continue
        if entry.finding.fingerprint not in by_fp:
            raise AssertionError(f"no head finding for fingerprint {entry.finding.fingerprint}")
        relabelled.append(DiffFinding(entry.status, by_fp[entry.finding.fingerprint]))
    return tuple(relabelled)


def _diff_metrics(
    base: Revision, head: Revision, regressions: list[dict[str, Any]], config: EffectiveConfig
) -> dict[str, Any]:
    metrics = dict(head.report.metrics)
    complexity = dict(metrics[COMPLEXITY_SECTION])
    complexity["regressions"] = regressions
    complexity["regression_policy"] = config.values["gates"]["complexity_regressions"]
    metrics[COMPLEXITY_SECTION] = complexity
    graph = dict(metrics[GRAPH_SECTION])
    graph["abstraction_displacement"] = abstraction_displacement(
        base.report.metrics, head.report.metrics, config.section(COMPLEXITY_SECTION)
    )
    metrics[GRAPH_SECTION] = graph
    return metrics


def with_metrics(diff: DiffReport, metrics: dict[str, Any]) -> DiffReport:
    return DiffReport(
        schema_version=diff.schema_version,
        tool_version=diff.tool_version,
        config=diff.config,
        base=diff.base,
        head=diff.head,
        findings=diff.findings,
        metrics=metrics,
        gate=diff.gate,
    )


def head_paths(diff: DiffReport) -> Sequence[str]:
    return [f.path for f in diff.head.report.files]
