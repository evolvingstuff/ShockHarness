"""The report: everything one run knows, in a schema-versioned structure.

Sorting is fixed (files by path; findings by path, line, column, rule ID,
message) so two runs over the same inputs produce byte-identical JSON. No
timestamps are included for the same reason; the one run-dependent field is
``summary.elapsed_seconds`` (0.2.0), which consumers comparing reports ignore.

``summary`` (0.2.0) is the first-contact overview behind ``check --summary``:
findings by rule and top-level directory and by severity, the files with the
most policy findings, complexity counts, parse failures and the elapsed time.
Its totals equal ``execution_summary``.
"""

import platform
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from shockharness.analysis import STATUS_UNSUPPORTED, FileResult
from shockharness.complexity.coupling import STATUS_AVAILABLE
from shockharness.complexity.regressions import exceeds_threshold
from shockharness.config import UNSUPPORTED_IGNORE, UNSUPPORTED_SOURCES_KEY, EffectiveConfig
from shockharness.constants import ELAPSED_DECIMALS, REPORT_SCHEMA_VERSION, SUMMARY_TOP_FILES
from shockharness.discovery import DiscoveryResult
from shockharness.findings import Finding
from shockharness.gate import GateResult
from shockharness.history.hotspots import HOTSPOTS_FORMULA
from shockharness.rules import registry
from shockharness.rules.complexity import SETTING_FAN_OUT_WARN, THRESHOLD_OF_RULE
from shockharness.version import __version__

STATUS_COMPLETE = "complete"
HISTORY_NOT_COLLECTED = {
    "status": "not_collected",
    "reason": (
        "git history is collected by the CLI (or shockharness.api.with_history); "
        "analyze_paths alone never runs git"
    ),
    "granularity": "file",
    "files": {},
    "cochange": [],
    "hotspots": None,
    "hotspots_reason": "not computed: history was not collected",
    "hotspots_formula": HOTSPOTS_FORMULA,
}
STATUS_INCOMPLETE = "incomplete"
STATUS_FAILED = "failed"
# Rule families whose findings are policy (gating or review) rather than advisory metrics.
POLICY_FAMILIES = ("MAGIC", "EXC", "DEF", "SUPP")
ROOT_DIRECTORY = "."


@dataclass(frozen=True)
class Report:
    schema_version: str
    tool_version: str
    analysis_status: str
    config: EffectiveConfig
    coverage: Mapping[str, Any]
    files: tuple[FileResult, ...]
    findings: tuple[Finding, ...]
    metrics: Mapping[str, Any]
    gate: GateResult
    execution_summary: Mapping[str, Any]
    summary: Mapping[str, Any]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "tool_version": self.tool_version,
            "analysis_status": self.analysis_status,
            "config_digest": self.config.digest,
            "effective_profile": self.config.values["profile"],
            "config": {
                "source": {"tier": self.config.source.tier, "path": self.config.source.path},
                "notes": list(self.config.notes),
                "deviations": list(self.config.deviations),
            },
            "coverage": dict(self.coverage),
            "files": [f.to_json_dict() for f in self.files],
            "findings": [f.to_json_dict() for f in self.findings],
            "metrics": dict(self.metrics),
            "gate": self.gate.to_json_dict(),
            "execution_summary": dict(self.execution_summary),
            "summary": dict(self.summary),
        }


def _analysis_status(files: Sequence[FileResult], config: EffectiveConfig) -> str:
    failures = sum(1 for f in files if f.failed)
    if failures == 0:
        return STATUS_COMPLETE
    unsupported = any(f.status == STATUS_UNSUPPORTED for f in files)
    if config.values["parse_errors"] == "fail" or unsupported:
        return STATUS_FAILED
    return STATUS_INCOMPLETE


def _coverage(
    files: Sequence[FileResult], discovery: DiscoveryResult | None, config: EffectiveConfig
) -> dict[str, Any]:
    by_language: dict[str, dict[str, Any]] = {}
    for file in files:
        if file.language not in by_language:
            by_language[file.language] = {"files": 0, "failed": 0, "parser": file.parser}
        entry = by_language[file.language]
        entry["files"] += 1
        if file.failed:
            entry["failed"] += 1
        if entry["parser"] is None and file.parser is not None:
            entry["parser"] = file.parser
    # analyze_source has no discovery step; the report says so with empty sections.
    discovery_counts: dict[str, Any] = {}
    explicit_excluded: list[dict[str, str]] = []
    unsupported: list[dict[str, str]] = []
    policy = str(config.values[UNSUPPORTED_SOURCES_KEY])
    if discovery is not None:
        discovery_counts = discovery.counts_json()
        explicit_excluded = [
            {"path": s.relative, "reason": s.reason} for s in discovery.explicit_excluded
        ]
        if policy != UNSUPPORTED_IGNORE:
            unsupported = [{"path": s.relative, "reason": s.reason} for s in discovery.unsupported]
    disabled_globally: list[str] = []
    for rule in registry.implemented_rules():
        if (
            rule.config_section is not None
            and config.section(rule.config_section)["enabled"] is False
        ):
            disabled_globally.append(rule.rule_id)
    return {
        "host_python": platform.python_version(),
        "host_implementation": platform.python_implementation(),
        "languages": dict(sorted(by_language.items())),
        "rules_implemented": [r.rule_id for r in registry.implemented_rules()],
        "rules_not_implemented": [r.rule_id for r in registry.RULES if not r.implemented],
        "rules_disabled_globally": disabled_globally,
        "files_analyzed": sum(1 for f in files if not f.failed),
        "files_failed": sum(1 for f in files if f.failed),
        "discovery": discovery_counts,
        "explicit_targets_excluded": explicit_excluded,
        "unsupported_sources_policy": policy,
        "unsupported_sources": unsupported,
        "limitations": [
            "Only rules listed in rules_implemented produced findings; every other registered "
            "rule is not analyzed.",
            "Complexity metrics (CPLX001-CPLX006) are advisory and never fail a plain check; "
            "call-graph edges carry a confidence and unresolved calls are never counted as "
            "resolved.",
            "Python syntax coverage equals the host interpreter's ast module.",
            "JavaScript regular-expression internals and string contents are not analyzed for "
            "numeric policy.",
        ],
    }


def top_level_directory(path: str) -> str:
    """``src/pkg/a.py`` -> ``src/``; a file at the root -> ``.``."""
    if "/" not in path:
        return ROOT_DIRECTORY
    return path.split("/", 1)[0] + "/"


def is_policy_rule(rule_id: str) -> bool:
    return any(rule_id.startswith(family) for family in POLICY_FAMILIES)


def _complexity_summary(metrics: Mapping[str, Any]) -> dict[str, Any]:
    complexity = metrics["complexity"]
    graph = metrics["graph"]
    thresholds: Mapping[str, Any] = complexity["thresholds"]
    units_over = {THRESHOLD_OF_RULE[rule_id]: 0 for rule_id in THRESHOLD_OF_RULE}
    saturated = 0
    for entry in complexity["functions"]:
        if entry["npath"]["saturated"]:
            saturated += 1
        for rule_id, key in THRESHOLD_OF_RULE.items():
            if exceeds_threshold(entry, rule_id, thresholds):
                units_over[key] += 1
    fan_out_warn = int(thresholds[SETTING_FAN_OUT_WARN])
    over_fan_out = 0
    if graph["status"] == STATUS_AVAILABLE:
        over_fan_out = sum(1 for u in graph["units"] if u["fan_out_total"] > fan_out_warn)
    return {
        "status": complexity["status"],
        "units": len(complexity["functions"]),
        "units_over": units_over,
        "npath_saturated_units": saturated,
        "cycles": graph["summary"]["cycles"],
        "units_over_fan_out_warn": over_fan_out,
        "thresholds": dict(thresholds),
    }


def build_summary(
    files: Sequence[FileResult],
    findings: Sequence[Finding],
    metrics: Mapping[str, Any],
    elapsed_seconds: float,
) -> dict[str, Any]:
    """The first-contact overview: every count derives from the same findings and files
    as ``execution_summary``, so the totals agree by construction."""
    by_severity: dict[str, int] = {}
    by_rule: dict[str, int] = {}
    by_directory: dict[str, int] = {}
    by_rule_and_directory: dict[str, dict[str, int]] = {}
    policy_per_file: dict[str, int] = {}
    for finding in findings:
        directory = top_level_directory(finding.path)
        if finding.severity not in by_severity:
            by_severity[finding.severity] = 0
        by_severity[finding.severity] += 1
        if finding.rule_id not in by_rule:
            by_rule[finding.rule_id] = 0
            by_rule_and_directory[finding.rule_id] = {}
        by_rule[finding.rule_id] += 1
        if directory not in by_directory:
            by_directory[directory] = 0
        by_directory[directory] += 1
        row = by_rule_and_directory[finding.rule_id]
        if directory not in row:
            row[directory] = 0
        row[directory] += 1
        if is_policy_rule(finding.rule_id):
            if finding.path not in policy_per_file:
                policy_per_file[finding.path] = 0
            policy_per_file[finding.path] += 1
    ranked = sorted(policy_per_file.items(), key=lambda item: (-item[1], item[0]))
    return {
        "files": len(files),
        "files_analyzed": sum(1 for f in files if not f.failed),
        "parse_failures": sum(1 for f in files if f.failed),
        "findings": len(findings),
        "suppressed": sum(1 for f in findings if f.is_suppressed),
        "by_severity": dict(sorted(by_severity.items())),
        "by_rule": dict(sorted(by_rule.items())),
        "by_directory": dict(sorted(by_directory.items())),
        "by_rule_and_directory": {
            rule_id: dict(sorted(row.items()))
            for rule_id, row in sorted(by_rule_and_directory.items())
        },
        "policy_families": list(POLICY_FAMILIES),
        "top_files_limit": SUMMARY_TOP_FILES,
        "top_files": [
            {"path": path, "policy_findings": count} for path, count in ranked[:SUMMARY_TOP_FILES]
        ],
        "complexity": _complexity_summary(metrics),
        "elapsed_seconds": round(elapsed_seconds, ELAPSED_DECIMALS),
    }


def build_report(
    files: Sequence[FileResult],
    discovery: DiscoveryResult | None,
    config: EffectiveConfig,
    gate: GateResult,
    metrics: Mapping[str, Any],
    elapsed_seconds: float,
) -> Report:
    """``metrics`` carries the ``complexity`` and ``graph`` sections from the analysis;
    ``history`` is added here as ``not_collected`` until the CLI or ``with_history`` runs git.
    ``elapsed_seconds`` is the wall-clock time of discovery, analysis and the gate."""
    ordered_files = tuple(sorted(files, key=lambda f: f.path))
    findings = tuple(
        sorted((f for file in ordered_files for f in file.findings), key=lambda f: f.sort_key())
    )
    severity_counts: dict[str, int] = {}
    for finding in findings:
        if finding.severity not in severity_counts:
            severity_counts[finding.severity] = 0
        severity_counts[finding.severity] += 1
    return Report(
        schema_version=REPORT_SCHEMA_VERSION,
        tool_version=__version__,
        analysis_status=_analysis_status(ordered_files, config),
        config=config,
        coverage=_coverage(ordered_files, discovery, config),
        files=ordered_files,
        findings=findings,
        metrics={**dict(metrics), "history": dict(HISTORY_NOT_COLLECTED)},
        gate=gate,
        execution_summary={
            "files": len(ordered_files),
            "findings": len(findings),
            "findings_by_severity": dict(sorted(severity_counts.items())),
            "suppressed": sum(1 for f in findings if f.is_suppressed),
            "baselined": 0,
        },
        summary=build_summary(ordered_files, findings, metrics, elapsed_seconds),
    )


def rebuild_with_findings(report: Report, findings: Sequence[Finding], gate: GateResult) -> Report:
    """The same report with its findings replaced (same identities, new markers) and a new gate."""
    by_path: dict[str, list[Finding]] = {}
    for finding in findings:
        if finding.path not in by_path:
            by_path[finding.path] = []
        by_path[finding.path].append(finding)
    files = tuple(
        replace(file, findings=tuple(by_path[file.path]) if file.path in by_path else ())
        for file in report.files
    )
    ordered = tuple(sorted(findings, key=lambda f: f.sort_key()))
    summary = dict(report.execution_summary)
    summary["baselined"] = sum(1 for f in ordered if f.baseline is not None)
    return replace(report, files=files, findings=ordered, gate=gate, execution_summary=summary)
