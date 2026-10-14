"""Human-readable rendering of a report."""

import textwrap
from typing import Any

from shockharness.constants import COMMIT_SHORT_HEX, CONFIG_DIGEST_SHORT_HEX, TEXT_WRAP_WIDTH
from shockharness.findings import Finding
from shockharness.gate import GateResult, advisory_line
from shockharness.gating.diff import STATUS_UNCHANGED, DiffReport
from shockharness.report import Report
from shockharness.rules.registry import RuleSpec


def _finding_line(finding: Finding) -> str:
    location = f"{finding.path}:{finding.span.line}:{finding.span.column}"
    line = f"{location}: {finding.rule_id} {finding.severity}: {finding.message}"
    if finding.evidence != "":
        line += f"  [{finding.evidence}]"
    if finding.suppression is not None:
        line += f"  (suppressed: {finding.suppression.reason})"
    if finding.baseline is not None:
        line += f"  (baseline: {finding.baseline})"
    return line


def _gate_lines(gate: GateResult) -> list[str]:
    lines = [f"gate: {gate.status.upper()} (exit {gate.exit_code})"]
    for reason in gate.reasons:
        lines.append(f"  {reason}")
    if gate.advisory:
        lines.append(advisory_line(gate))
    return lines


def _history_lines(metrics: dict[str, Any]) -> list[str]:
    if "history" not in metrics:
        return []
    history = metrics["history"]
    if history["status"] != "available":
        return [f"  history: {history['status']} ({history['reason']})"]
    horizon = history["horizon"]
    return [
        f"  history: {history['commits_considered']} commit(s) in {horizon['days']} day(s) "
        f"before {horizon['until']} (file granularity); {len(history['cochange'])} "
        f"co-change pair(s) with support >= {history['cochange_min_support']}; "
        f"hotspots: {history['hotspots_reason']}"
    ]


def render(report: Report) -> str:
    lines: list[str] = []
    for finding in report.findings:
        lines.append(_finding_line(finding))

    for file in report.files:
        if not file.failed:
            continue
        where = file.path
        if file.parse_failure is not None and file.parse_failure.span is not None:
            where = f"{file.path}:{file.parse_failure.span.line}:{file.parse_failure.span.column}"
        lines.append(f"{where}: {file.status}: {file.error}")

    if len(lines) > 0:
        lines.append("")

    summary = report.execution_summary
    coverage = report.coverage
    lines.append(
        f"shockharness {report.tool_version}: {summary['files']} file(s), "
        f"{coverage['files_analyzed']} analyzed, {coverage['files_failed']} failed; "
        f"{summary['findings']} finding(s), {summary['suppressed']} suppressed"
    )
    by_severity = summary["findings_by_severity"]
    if len(by_severity) > 0:
        lines.append("  by severity: " + ", ".join(f"{k}={v}" for k, v in by_severity.items()))
    lines.append("  rules applied: " + ", ".join(coverage["rules_implemented"]))
    lines.append(
        "  rules not implemented (not analyzed): " + ", ".join(coverage["rules_not_implemented"])
    )
    if len(coverage["rules_disabled_globally"]) > 0:
        lines.append(
            "  rules disabled by config: " + ", ".join(coverage["rules_disabled_globally"])
        )
    for note in report.config.notes:
        lines.append(f"  config note: {note}")
    for deviation in report.config.deviations:
        lines.append(f"  policy deviation: {deviation}")
    lines.append(
        f"  config: {report.config.source.tier} {report.config.source.path} "
        f"(profile {report.config.values['profile']}, "
        f"digest {report.config.digest[:CONFIG_DIGEST_SHORT_HEX]})"
    )
    lines.extend(_history_lines(dict(report.metrics)))
    lines.append(f"  analysis status: {report.analysis_status}")
    lines.extend(_gate_lines(report.gate))
    return "\n".join(lines) + "\n"


def render_diff(diff: DiffReport) -> str:
    """New and fixed findings line by line; unchanged ones are counted, not listed."""
    lines: list[str] = []
    for entry in diff.findings:
        if entry.status == STATUS_UNCHANGED:
            continue
        lines.append(f"{entry.status}: {_finding_line(entry.finding)}")
    for file in diff.head.report.files:
        if not file.failed:
            continue
        lines.append(f"head {file.path}: {file.status}: {file.error}")
    if len(lines) > 0:
        lines.append("")
    summary = diff.summary()
    base = diff.base
    head = diff.head
    lines.append(
        f"shockharness {diff.tool_version} diff: base {base.ref} "
        f"({base.commit[:COMMIT_SHORT_HEX]}) -> head {head.ref} "
        f"({head.commit[:COMMIT_SHORT_HEX]}); {summary['new']} new, {summary['fixed']} fixed, "
        f"{summary['unchanged']} unchanged finding(s)"
    )
    lines.append(
        f"  hard violations: {summary['new_hard_violations']} new, "
        f"{summary['fixed_hard_violations']} fixed, "
        f"{summary['unchanged_hard_violations']} unchanged"
    )
    lines.append(
        f"  base: {base.report.coverage['files_analyzed']} analyzed, "
        f"{base.report.coverage['files_failed']} failed, status {base.report.analysis_status}; "
        f"head: {head.report.coverage['files_analyzed']} analyzed, "
        f"{head.report.coverage['files_failed']} failed, status {head.report.analysis_status}"
    )
    lines.append("  uncommitted changes are not part of HEAD; only committed trees are compared")
    for note in diff.config.notes:
        lines.append(f"  config note: {note}")
    for deviation in diff.config.deviations:
        lines.append(f"  policy deviation: {deviation}")
    lines.append(
        f"  config: {diff.config.source.tier} {diff.config.source.path} "
        f"(profile {diff.config.values['profile']}, "
        f"digest {diff.config.digest[:CONFIG_DIGEST_SHORT_HEX]})"
    )
    lines.extend(_history_lines(diff.metrics))
    lines.append(f"  analysis status: {head.report.analysis_status}")
    lines.extend(_gate_lines(diff.gate))
    return "\n".join(lines) + "\n"


def render_rule_table(rules: tuple[RuleSpec, ...]) -> str:
    lines = []
    for rule in rules:
        status = "implemented" if rule.implemented else "planned"
        lines.append(f"{rule.rule_id:<9} {rule.default_severity:<8} {status:<12} {rule.summary}")
    return "\n".join(lines) + "\n"


def render_rule_explanation(rule: RuleSpec) -> str:
    def block(title: str, body: str) -> str:
        if body == "":
            return f"{title}:\n  (none)\n"
        wrapped = textwrap.fill(
            body, width=TEXT_WRAP_WIDTH, initial_indent="  ", subsequent_indent="  "
        )
        return f"{title}:\n{wrapped}\n"

    def code(title: str, body: str) -> str:
        if body == "":
            return f"{title}:\n  (none)\n"
        indented = "\n".join("  " + line for line in body.split("\n"))
        return f"{title}:\n{indented}\n"

    status = (
        "implemented" if rule.implemented else "planned (not implemented; produces no findings)"
    )
    header = (
        f"{rule.rule_id} v{rule.version}: {rule.name}\n"
        f"family: {rule.family}  severity: {rule.default_severity}  status: {status}\n"
        f"languages: {', '.join(rule.languages)}  config: {rule.config_section}\n"
    )
    return "\n".join(
        [
            header,
            block("Summary", rule.summary),
            block("Rationale", rule.rationale),
            block("Detection guarantees", rule.guarantees),
            block("Limitations", rule.limitations),
            block("Remediation", rule.remediation),
            code("Non-compliant", rule.noncompliant_example),
            code("Compliant", rule.compliant_example),
        ]
    )
