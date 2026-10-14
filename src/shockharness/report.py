"""The report: everything one run knows, in a schema-versioned structure.

Sorting is fixed (files by path; findings by path, line, column, rule ID,
message) so two runs over the same inputs produce byte-identical JSON. No
timestamps are included for the same reason.
"""

import platform
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from shockharness.analysis import FileResult
from shockharness.config import EffectiveConfig
from shockharness.constants import REPORT_SCHEMA_VERSION
from shockharness.discovery import DiscoveryResult
from shockharness.findings import Finding
from shockharness.gate import GateResult
from shockharness.rules import registry
from shockharness.version import __version__

STATUS_COMPLETE = "complete"
STATUS_INCOMPLETE = "incomplete"
STATUS_FAILED = "failed"


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

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "tool_version": self.tool_version,
            "analysis_status": self.analysis_status,
            "config_digest": self.config.digest,
            "policy_profile": self.config.values["profile"],
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
        }


def _analysis_status(files: Sequence[FileResult], config: EffectiveConfig) -> str:
    failures = sum(1 for f in files if f.failed)
    if failures == 0:
        return STATUS_COMPLETE
    if config.values["parse_errors"] == "fail":
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
    if discovery is not None:
        discovery_counts = discovery.counts_json()
        explicit_excluded = [
            {"path": s.relative, "reason": s.reason} for s in discovery.explicit_excluded
        ]
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
        "limitations": [
            "Only rules listed in rules_implemented produced findings; every other registered "
            "rule is not analyzed.",
            "Python syntax coverage equals the host interpreter's ast module.",
            "JavaScript regular-expression internals and string contents are not analyzed for "
            "numeric policy.",
        ],
    }


def build_report(
    files: Sequence[FileResult],
    discovery: DiscoveryResult | None,
    config: EffectiveConfig,
    gate: GateResult,
) -> Report:
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
        metrics={},
        gate=gate,
        execution_summary={
            "files": len(ordered_files),
            "findings": len(findings),
            "findings_by_severity": dict(sorted(severity_counts.items())),
            "suppressed": sum(1 for f in findings if f.is_suppressed),
        },
    )
