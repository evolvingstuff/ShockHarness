"""Revision diff: analyze the full tree at two commits and compare by fingerprint.

Both revisions are resolved with local git only, exported with ``git archive``
into temporary directories, and analyzed completely (not just changed files) so
that cross-file effects are never missed. The working tree is not analyzed:
uncommitted changes are not part of ``HEAD``. The configuration is the working
tree's, applied to both sides, so the diff compares code under one policy.
"""

import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shockharness import gate as gate_module
from shockharness.analysis import AnalysisOptions, analyze_files
from shockharness.complexity.regressions import abstraction_displacement, complexity_regressions
from shockharness.config import EffectiveConfig
from shockharness.constants import REPORT_SCHEMA_VERSION
from shockharness.discovery import discover
from shockharness.errors import UsageError
from shockharness.findings import Finding
from shockharness.gate import NO_REGRESSIONS, GateResult
from shockharness.gating.baseline import SOURCE_BASE_REVISION, apply_fingerprints
from shockharness.history.git import RepositoryLocation, export_tree, locate_repository
from shockharness.history.git import resolve_commit as git_resolve_commit
from shockharness.report import Report, build_report, rebuild_with_findings
from shockharness.rules.registry import SEVERITY_ERROR
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
        data["status"] = self.status
        return data


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
        for entry in self.findings:
            counts[entry.status] += 1
            finding = entry.finding
            if finding.severity == SEVERITY_ERROR and not finding.is_suppressed:
                hard[entry.status] += 1
        return {
            "new": counts[STATUS_NEW],
            "fixed": counts[STATUS_FIXED],
            "unchanged": counts[STATUS_UNCHANGED],
            "new_hard_violations": hard[STATUS_NEW],
            "fixed_hard_violations": hard[STATUS_FIXED],
            "unchanged_hard_violations": hard[STATUS_UNCHANGED],
            "complexity_regressions": self.gate.complexity_regressions,
        }

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "tool_version": self.tool_version,
            "report_kind": "diff",
            "analysis_status": self.head.report.analysis_status,
            "config_digest": self.config.digest,
            "effective_profile": self.config.values["profile"],
            "config": {
                "source": {"tier": self.config.source.tier, "path": self.config.source.path},
                "notes": list(self.config.notes),
                "deviations": list(self.config.deviations),
            },
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
) -> Revision:
    """Export the tree at ``ref`` and analyze the part that corresponds to ``root``."""
    commit = resolve_commit(root, ref)
    with tempfile.TemporaryDirectory(prefix="shockharness-") as exported:
        error = export_tree(location.toplevel, commit, Path(exported))
        if error is not None:
            raise UsageError(f"cannot export revision {ref!r}: {error}", ref)
        export_root = Path(exported) / location.prefix
        if not export_root.is_dir():
            where = "." if location.prefix == "" else location.prefix
            raise UsageError(f"the analysis root ({where}) does not exist at {ref}", ref)
        discovery = discover(export_root, [export_root], config)
        outcome = analyze_files(discovery.files, config, options)
    findings = [f for result in outcome.files for f in result.findings]
    verdict = gate_module.evaluate(findings, outcome.files, config, None, NO_REGRESSIONS)
    report = build_report(outcome.files, discovery, config, verdict, outcome.metrics)
    return Revision(ref=ref, commit=commit, report=report)


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
    base = analyze_revision(root, location, base_ref, config, options)
    head = analyze_revision(root, location, head_ref, config, options)
    base_by_fp = {f.fingerprint: f for f in base.report.findings if f.fingerprint is not None}
    head_by_fp = {f.fingerprint: f for f in head.report.findings if f.fingerprint is not None}
    assert len(base_by_fp) == len(base.report.findings), "fingerprints must be unique"
    assert len(head_by_fp) == len(head.report.findings), "fingerprints must be unique"

    entries: list[DiffFinding] = []
    for fingerprint, finding in head_by_fp.items():
        status = STATUS_UNCHANGED if fingerprint in base_by_fp else STATUS_NEW
        entries.append(DiffFinding(status, finding))
    for fingerprint, finding in base_by_fp.items():
        if fingerprint not in head_by_fp:
            entries.append(DiffFinding(STATUS_FIXED, finding))
    entries.sort(key=lambda e: e.sort_key())

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
    complexity_settings = config.section(COMPLEXITY_SECTION)
    regressions = complexity_regressions(
        base.report.metrics[COMPLEXITY_SECTION],
        head.report.metrics[COMPLEXITY_SECTION],
        complexity_settings,
    )
    verdict = gate_module.evaluate(marked, head.report.files, config, application, len(regressions))
    head_marked = Revision(
        head.ref, head.commit, rebuild_with_findings(head.report, marked, verdict)
    )
    by_fp = {f.fingerprint: f for f in marked}
    relabelled: list[DiffFinding] = []
    for entry in entries:
        if entry.status == STATUS_FIXED:
            relabelled.append(entry)
            continue
        assert entry.finding.fingerprint in by_fp
        relabelled.append(DiffFinding(entry.status, by_fp[entry.finding.fingerprint]))
    metrics = dict(head_marked.report.metrics)
    complexity = dict(metrics[COMPLEXITY_SECTION])
    complexity["regressions"] = regressions
    complexity["regression_policy"] = config.values["gates"]["complexity_regressions"]
    metrics[COMPLEXITY_SECTION] = complexity
    graph = dict(metrics[GRAPH_SECTION])
    graph["abstraction_displacement"] = abstraction_displacement(
        base.report.metrics, head.report.metrics, complexity_settings
    )
    metrics[GRAPH_SECTION] = graph
    return DiffReport(
        schema_version=REPORT_SCHEMA_VERSION,
        tool_version=__version__,
        config=config,
        base=base,
        head=head_marked,
        findings=tuple(relabelled),
        metrics=metrics,
        gate=verdict,
    )


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
