"""SARIF 2.1.0 rendering for GitHub code scanning and other SARIF consumers.

One run per document. Rules come from the registry with their full text; each
result carries the finding's baseline fingerprint under ``partialFingerprints``
so consumers can track findings across line moves, an in-source suppression
when the finding was suppressed, and a ``baselineState`` when a baseline file
or base revision was applied. Levels: error -> error, warning -> warning,
review and note -> note. URIs are root-relative with forward slashes.
"""

import json
from typing import Any

from shockharness.constants import JSON_INDENT, SARIF_SCHEMA_URI, SARIF_VERSION
from shockharness.findings import Finding
from shockharness.gate import GateResult, process_exit_code
from shockharness.gating.baseline import FINGERPRINT_KEY
from shockharness.gating.diff import STATUS_FIXED, STATUS_NEW, DiffReport
from shockharness.report import STATUS_FAILED, Report
from shockharness.rules import registry
from shockharness.rules.registry import SEVERITY_ERROR, SEVERITY_WARNING, RuleSpec
from shockharness.version import __version__

TOOL_NAME = "ShockHarness"
INFORMATION_URI = "https://github.com/evolvingstuff/ShockHarness"
RULES_HELP_URI = "https://github.com/evolvingstuff/ShockHarness/blob/main/docs/rules.md"
URI_BASE_ID = "%SRCROOT%"

LEVEL_ERROR = "error"
LEVEL_WARNING = "warning"
LEVEL_NOTE = "note"

BASELINE_NEW = "new"
BASELINE_UNCHANGED = "unchanged"
BASELINE_ABSENT = "absent"


def level_for(severity: str) -> str:
    if severity == SEVERITY_ERROR:
        return LEVEL_ERROR
    if severity == SEVERITY_WARNING:
        return LEVEL_WARNING
    return LEVEL_NOTE


def _rule(rule: RuleSpec) -> dict[str, Any]:
    return {
        "id": rule.rule_id,
        "name": rule.name,
        "shortDescription": {"text": rule.summary},
        "fullDescription": {"text": rule.rationale},
        "help": {"text": rule.remediation},
        "helpUri": RULES_HELP_URI,
        "defaultConfiguration": {"level": level_for(rule.default_severity)},
        "properties": {
            "family": rule.family,
            "implemented": rule.implemented,
            "languages": list(rule.languages),
            "rule_version": rule.version,
            "default_severity": rule.default_severity,
        },
    }


def _rules() -> tuple[list[dict[str, Any]], dict[str, int]]:
    rules = [_rule(rule) for rule in registry.RULES]
    index = {rule.rule_id: position for position, rule in enumerate(registry.RULES)}
    return rules, index


def _location(finding: Finding) -> dict[str, Any]:
    location: dict[str, Any] = {
        "physicalLocation": {
            "artifactLocation": {"uri": finding.path, "uriBaseId": URI_BASE_ID},
            "region": {
                "startLine": finding.span.line,
                "startColumn": finding.span.column,
                "endLine": finding.span.end_line,
                "endColumn": finding.span.end_column,
            },
        }
    }
    if finding.scope is not None:
        location["logicalLocations"] = [{"name": finding.scope}]
    return location


def _result(
    finding: Finding, rule_index: dict[str, int], baseline_state: str | None
) -> dict[str, Any]:
    suppressions: list[dict[str, str]] = []
    if finding.suppression is not None:
        suppressions.append({"kind": "inSource", "justification": finding.suppression.reason})
    fingerprints: dict[str, str] = {}
    if finding.fingerprint is not None:
        fingerprints[FINGERPRINT_KEY] = finding.fingerprint
    result: dict[str, Any] = {
        "ruleId": finding.rule_id,
        "ruleIndex": rule_index[finding.rule_id],
        "level": level_for(finding.severity),
        "message": {"text": finding.message},
        "locations": [_location(finding)],
        "partialFingerprints": fingerprints,
        "suppressions": suppressions,
        "properties": {
            "severity": finding.severity,
            "confidence": finding.confidence,
            "status": finding.status,
            "evidence": finding.evidence,
            "remediation": finding.remediation,
            "safe_autofix": finding.safe_autofix,
            "baseline": finding.baseline,
        },
    }
    if baseline_state is not None:
        result["baselineState"] = baseline_state
    return result


def _invocation(analysis_status: str, gate: GateResult) -> dict[str, Any]:
    return {
        "executionSuccessful": analysis_status != STATUS_FAILED,
        # The process exit code: under --exit-zero a failing verdict still exits 0, and
        # properties.gate.exit_code keeps the verdict's own code next to advisory = true.
        "exitCode": process_exit_code(gate),
        "properties": {"analysis_status": analysis_status, "gate": gate.to_json_dict()},
    }


def _document(run: dict[str, Any]) -> str:
    document = {"$schema": SARIF_SCHEMA_URI, "version": SARIF_VERSION, "runs": [run]}
    return json.dumps(document, indent=JSON_INDENT, sort_keys=True) + "\n"


def _driver(rules: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "name": TOOL_NAME,
        "version": __version__,
        "semanticVersion": __version__,
        "informationUri": INFORMATION_URI,
        "rules": rules,
    }


def render(report: Report) -> str:
    """SARIF for a scan report. ``baselineState`` appears only when a baseline was applied."""
    rules, index = _rules()
    applied = report.gate.baseline is not None and report.gate.baseline.applied
    results: list[dict[str, Any]] = []
    for finding in report.findings:
        state: str | None = None
        if applied:
            state = BASELINE_NEW if finding.baseline is None else BASELINE_UNCHANGED
        results.append(_result(finding, index, state))
    run = {
        "tool": {"driver": _driver(rules)},
        "columnKind": "unicodeCodePoints",
        "invocations": [_invocation(report.analysis_status, report.gate)],
        "results": results,
        "properties": {
            "schema_version": report.schema_version,
            "config_digest": report.config.digest,
            "effective_profile": report.config.values["profile"],
            "config_deviations": list(report.config.deviations),
            "advisory": report.gate.advisory,
            "analysis_status": report.analysis_status,
            "coverage": dict(report.coverage),
            "files_failed": [f.to_json_dict() for f in report.files if f.failed],
        },
    }
    return _document(run)


def render_diff(diff: DiffReport) -> str:
    """SARIF for a revision diff: head results as new/unchanged, base-only results as absent."""
    rules, index = _rules()
    results: list[dict[str, Any]] = []
    for entry in diff.findings:
        if entry.status == STATUS_FIXED:
            state = BASELINE_ABSENT
        elif entry.status == STATUS_NEW:
            state = BASELINE_NEW
        else:
            state = BASELINE_UNCHANGED
        results.append(_result(entry.finding, index, state))
    run = {
        "tool": {"driver": _driver(rules)},
        "columnKind": "unicodeCodePoints",
        "invocations": [_invocation(diff.head.report.analysis_status, diff.gate)],
        "results": results,
        "properties": {
            "schema_version": diff.schema_version,
            "report_kind": "diff",
            "config_digest": diff.config.digest,
            "effective_profile": diff.config.values["profile"],
            "config_deviations": list(diff.config.deviations),
            "advisory": diff.gate.advisory,
            "base": {"ref": diff.base.ref, "commit": diff.base.commit},
            "head": {"ref": diff.head.ref, "commit": diff.head.commit},
            "summary": diff.summary(),
            "coverage": dict(diff.head.report.coverage),
        },
    }
    return _document(run)
