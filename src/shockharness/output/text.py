"""Human-readable rendering of a report."""

import textwrap
from collections.abc import Mapping, Sequence
from typing import Any

from shockharness.cache.store import STATUS_ENABLED as CACHE_ENABLED
from shockharness.config import SUPPORTED_EXTENSIONS, EffectiveConfig
from shockharness.constants import (
    COMMIT_SHORT_HEX,
    CONFIG_DIGEST_SHORT_HEX,
    HOTSPOTS_SHOWN,
    SCORE_DECIMALS,
    TEXT_WRAP_WIDTH,
)
from shockharness.findings import Finding
from shockharness.gate import GateResult, advisory_line
from shockharness.gating.diff import STATUS_UNCHANGED, DiffReport
from shockharness.report import Report
from shockharness.rules.complexity import is_cycle_finding
from shockharness.rules.registry import CATEGORY_POLICY, PYTHON, RuleSpec, category_of
from shockharness.rules.verification import COVERAGE_DISABLED as VERIFICATION_DISABLED
from shockharness.rules.verification import COVERAGE_NOT_APPLICABLE as VERIFICATION_NOT_APPLICABLE
from shockharness.rules.verification import RENAMES_AVAILABLE as VERIFICATION_RENAMES_AVAILABLE


def _finding_line(finding: Finding) -> str:
    location = f"{finding.path}:{finding.span.line}:{finding.span.column}"
    severity = finding.severity
    if finding.is_unknown:
        severity += f" ({finding.status})"
    line = f"{location}: {finding.rule_id} {severity}: {finding.message}"
    if finding.evidence != "":
        line += f"  [{finding.evidence}]"
    if finding.suppression is not None:
        line += f"  (suppressed: {finding.suppression.reason})"
    if finding.baseline is not None:
        line += f"  (baseline: {finding.baseline})"
    return line


def _unknown_line(gate: GateResult) -> str:
    """How many findings the rules could not establish, and which families gate on them."""
    families = ", ".join(gate.unknown_gating_families)
    if families == "":
        families = "none"
    return (
        f"  unknown: {gate.unknown} finding(s) the rules could not establish; "
        f"fail_on_unknown families: {families}"
    )


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
    lines = [
        f"  history: {history['commits_considered']} commit(s) in {horizon['days']} day(s) "
        f"before {horizon['until']} (file granularity); {len(history['cochange'])} "
        f"co-change pair(s) with support >= {history['cochange_min_support']}"
    ]
    hotspots = history["hotspots"]
    if hotspots is None:
        lines.append(f"  hotspots: {history['hotspots_reason']}")
        return lines
    top = [h for h in hotspots if h["score"] > 0][:HOTSPOTS_SHOWN]
    if len(top) == 0:
        lines.append("  hotspots: none (no analyzed file has both churn and cognitive complexity)")
        return lines
    listed = ", ".join(f"{h['path']} ({h['score']:.{SCORE_DECIMALS}f})" for h in top)
    lines.append(f"  hotspots (log1p(churn) * normalized cognitive, file granularity): {listed}")
    return lines


def _complexity_lines(metrics: dict[str, Any]) -> list[str]:
    if "complexity" not in metrics:
        return []
    complexity = metrics["complexity"]
    if complexity["status"] != "available":
        return [f"  complexity: {complexity['status']} ({complexity['reason']})"]
    functions = complexity["functions"]
    saturated = sum(1 for f in functions if f["npath"]["saturated"])
    conventions = complexity["conventions"]
    lines = [
        f"  complexity: {len(functions)} unit(s) in {len(complexity['files'])} file(s); "
        f"conventions {conventions['cyclomatic']}, {conventions['cognitive']}, "
        f"{conventions['nesting']}, {conventions['npath']}; {saturated} NPath saturated; "
        "advisory (CPLX001-CPLX004 and CPLX006 are warnings)"
    ]
    if "regressions" in complexity:
        lines.append(
            f"  complexity regressions against base: {len(complexity['regressions'])} "
            f'(gates.complexity_regressions = "{complexity["regression_policy"]}")'
        )
    graph = metrics["graph"]
    if graph["status"] == "available":
        edges = graph["summary"]["call_edges"]
        modules = graph["summary"]["module_edges"]
        lines.append(
            f"  graph: call edges {edges['resolved']} resolved, {edges['probable']} probable, "
            f"{edges['unresolved']} unresolved; module edges {modules['resolved']} resolved, "
            f"{modules['external']} external, {modules['unresolved']} unresolved; "
            f"{graph['summary']['cycles']} cycle(s); "
            f"{graph['summary']['shared_mutable_state']} shared mutable binding(s)"
        )
        displacement = graph["abstraction_displacement"]
        if displacement["status"] == "available":
            lines.append(
                f"  abstraction displacement (experimental, approximate): "
                f"{len(displacement['findings'])} unit(s)"
            )
    return lines


def _cycle_order(finding: Finding) -> tuple[int, str, int, int]:
    """Python cycles before JavaScript cycles (an import cycle fails at import time in
    Python and is usually resolved at call time in an ES module), then report order."""
    suffix = "." + finding.path.rsplit(".", 1)[len(finding.path.rsplit(".", 1)) - 1]
    first = 0 if suffix in SUPPORTED_EXTENSIONS and SUPPORTED_EXTENSIONS[suffix] == PYTHON else 1
    return (first, finding.path, finding.span.line, finding.span.column)


def finding_lines(findings: Sequence[Finding]) -> list[str]:
    """One line per finding in report order, except that import-cycle findings (one per
    cycle, cross-file by nature) are listed together after the per-file findings, Python
    cycles first."""
    lines: list[str] = []
    cycles: list[Finding] = []
    for finding in findings:
        if is_cycle_finding(finding):
            cycles.append(finding)
            continue
        lines.append(_finding_line(finding))
    for finding in sorted(cycles, key=_cycle_order):
        lines.append(_finding_line(finding))
    return lines


def _cache_lines(cache: Mapping[str, Any]) -> list[str]:
    if cache["status"] != CACHE_ENABLED:
        return [f"  cache: {cache['status']} ({cache['reason']})"]
    lines = [
        f"  cache: {cache['directory']}: {cache['hits']} hit(s), {cache['misses']} miss(es), "
        f"{cache['invalidated']} invalidated, {cache['errors']} error(s)"
    ]
    lines.extend(f"  warning: cache: {problem}" for problem in cache["problems"])
    return lines


def _verification_line(verification: Mapping[str, Any], rules: Sequence[str]) -> str:
    """The VERIFY rules' state for this run (H2): they need a base revision."""
    listed = ", ".join(rules)
    if verification["status"] == VERIFICATION_DISABLED:
        return (
            "  verification rules disabled by config (rules.verification.enabled = false): "
            + listed
        )
    if verification["status"] == VERIFICATION_NOT_APPLICABLE:
        return (
            f"  rules needing a base revision (not analyzed in this run; use diff or gate "
            f"--base/--head): {listed}"
        )
    renames = f"{verification['renamed']} renamed"
    if verification["rename_detection"] != VERIFICATION_RENAMES_AVAILABLE:
        renames = f"rename detection unavailable ({verification['rename_detection_error']})"
    base = str(verification["base_commit"])[:COMMIT_SHORT_HEX]
    line = (
        f"  verification: {', '.join(verification['rules'])} against base {base}: "
        f"{verification['files_compared']} source file(s) compared "
        f"({verification['files_new']} new, {renames}, {verification['base_unanalyzable']} "
        f"with an unanalyzable base)"
    )
    if "policy" in verification:
        policy = verification["policy"]
        line += (
            f"; {len(policy['files_compared'])} policy file(s) and "
            f"{len(policy['baselines'])} baseline(s) checked"
        )
        if policy["workflows_checked"] is not True:
            line += " (workflows not checked: the analysis root is not the repository top level)"
    return line + f"; severity {verification['severity']}"


def _policy_lines(config: EffectiveConfig) -> list[str]:
    """The ``--policy`` file and every repository key that tried to loosen it."""
    if config.policy is None:
        return []
    lines = [
        f"  policy: {config.policy.path} sets {len(config.policy.keys)} key(s) "
        f"(digest {config.policy.digest[:CONFIG_DIGEST_SHORT_HEX]}); "
        f"{len(config.policy_attempts)} repository key(s) tried to loosen them (VERIFY003)"
    ]
    return lines


def _unanalyzed_rule_lines(coverage: Mapping[str, Any]) -> list[str]:
    """The rules not implemented and the rules the configuration disables, when any."""
    lines: list[str] = []
    if len(coverage["rules_not_implemented"]) > 0:
        lines.append(
            "  rules not implemented (not analyzed): "
            + ", ".join(coverage["rules_not_implemented"])
        )
    if len(coverage["rules_disabled_globally"]) > 0:
        lines.append(
            "  rules disabled by config: " + ", ".join(coverage["rules_disabled_globally"])
        )
    return lines


def _trailer_lines(report: Report) -> list[str]:
    """Everything after the findings: totals, rules, config, metrics, status, gate."""
    lines: list[str] = []
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
    needing_base = coverage["rules_needing_base_revision"]
    applied = [rule for rule in coverage["rules_implemented"] if rule not in needing_base]
    lines.append("  rules applied: " + ", ".join(applied))
    lines.append(_verification_line(coverage["verification"], needing_base))
    lines.extend(_unanalyzed_rule_lines(coverage))
    unsupported = coverage["unsupported_sources"]
    if len(unsupported) > 0 and coverage["unsupported_sources_policy"] == "warn":
        listed = ", ".join(entry["path"] for entry in unsupported)
        lines.append(
            f"  warning: {len(unsupported)} included file(s) have an "
            f'extension no adapter parses and were not analyzed (unsupported_sources = "warn"): '
            f"{listed}"
        )
    lines.extend(_cache_lines(coverage["cache"]))
    for note in report.config.notes:
        lines.append(f"  config note: {note}")
    lines.extend(_policy_lines(report.config))
    for deviation in report.config.deviations:
        lines.append(f"  policy deviation: {deviation}")
    lines.append(
        f"  config: {report.config.source.tier} {report.config.source.path} "
        f"(profile {report.config.values['profile']}, "
        f"digest {report.config.digest[:CONFIG_DIGEST_SHORT_HEX]})"
    )
    lines.extend(_complexity_lines(dict(report.metrics)))
    lines.extend(_history_lines(dict(report.metrics)))
    lines.append(f"  analysis status: {report.analysis_status}")
    lines.append(_unknown_line(report.gate))
    lines.extend(_gate_lines(report.gate))
    return lines


def _failure_lines(report: Report) -> list[str]:
    lines: list[str] = []
    for file in report.files:
        if not file.failed:
            continue
        where = file.path
        if file.parse_failure is not None and file.parse_failure.span is not None:
            where = f"{file.path}:{file.parse_failure.span.line}:{file.parse_failure.span.column}"
        lines.append(f"{where}: {file.status}: {file.error}")
    return lines


def render(report: Report) -> str:
    lines = finding_lines(report.findings)
    lines.extend(_failure_lines(report))
    if len(lines) > 0:
        lines.append("")
    lines.extend(_trailer_lines(report))
    return "\n".join(lines) + "\n"


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    widths = [len(cell) for cell in header]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    rendered: list[str] = []
    for row in [header, *rows]:
        cells = [row[0].ljust(widths[0])]
        cells.extend(cell.rjust(widths[index]) for index, cell in enumerate(row) if index > 0)
        rendered.append("    " + "  ".join(cells).rstrip())
    return rendered


def _summary_lines(report: Report) -> list[str]:
    summary = report.summary
    lines = [
        f"shockharness {report.tool_version} summary: {summary['files']} file(s), "
        f"{summary['files_analyzed']} analyzed, {summary['parse_failures']} parse failure(s); "
        f"{summary['findings']} finding(s), {summary['suppressed']} suppressed; "
        f"{report.elapsed_seconds} s"
    ]
    by_severity = summary["by_severity"]
    if len(by_severity) > 0:
        lines.append("  by severity: " + ", ".join(f"{k}={v}" for k, v in by_severity.items()))
    directories = list(summary["by_directory"])
    if len(summary["by_rule"]) > 0:
        lines.append("  findings by rule and top-level directory:")
        rows: list[list[str]] = []
        for rule_id, row in summary["by_rule_and_directory"].items():
            cells = [rule_id]
            for directory in directories:
                cells.append(str(row[directory]) if directory in row else "")
            cells.append(str(summary["by_rule"][rule_id]))
            rows.append(cells)
        totals = ["total", *[str(summary["by_directory"][d]) for d in directories]]
        totals.append(str(summary["findings"]))
        rows.append(totals)
        lines.extend(_table(["rule", *directories, "total"], rows))
    families = "/".join(summary["policy_families"])
    if len(summary["top_files"]) > 0:
        lines.append(
            f"  files with the most policy findings ({families}; not CPLX; "
            f"top {summary['top_files_limit']}):"
        )
        for entry in summary["top_files"]:
            lines.append(f"    {entry['policy_findings']:>6}  {entry['path']}")
    else:
        lines.append(f"  files with the most policy findings ({families}; not CPLX): none")
    complexity = summary["complexity"]
    if complexity["status"] == "available":
        over = ", ".join(
            f"{key} = {complexity['thresholds'][key]}: {count}"
            for key, count in complexity["units_over"].items()
        )
        fan_out_warn = complexity["thresholds"]["fan_out_warn"]
        lines.append(
            f"  complexity: {complexity['units']} unit(s) analyzed; over {over}; "
            f"{complexity['npath_saturated_units']} NPath saturated; "
            f"{complexity['cycles']} import cycle(s); "
            f"{complexity['units_over_fan_out_warn']} unit(s) over fan_out_warn = {fan_out_warn}"
        )
    else:
        lines.append(f"  complexity: {complexity['status']}")
    lines.append(f"  parse failures: {summary['parse_failures']}")
    return lines


def render_summary(report: Report) -> str:
    """``check --summary``: the overview, then the same trailer and gate line as ``render``."""
    lines = _summary_lines(report)
    lines.extend(_failure_lines(report))
    lines.append("")
    lines.extend(_trailer_lines(report))
    return "\n".join(lines) + "\n"


def render_diff(diff: DiffReport) -> str:
    """New and fixed findings line by line; unchanged ones are counted, not listed."""
    lines: list[str] = []
    listed = [entry for entry in diff.findings if entry.status != STATUS_UNCHANGED]
    policy = [e for e in listed if category_of(e.finding.rule_id) == CATEGORY_POLICY]
    others = [e for e in listed if category_of(e.finding.rule_id) != CATEGORY_POLICY]
    if len(policy) > 0:
        lines.append("policy integrity (the change weakened its own verification):")
        lines.extend(f"  {entry.status}: {_finding_line(entry.finding)}" for entry in policy)
        if len(others) > 0:
            lines.append("")
    lines.extend(f"{entry.status}: {_finding_line(entry.finding)}" for entry in others)
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
    lines.extend(_policy_lines(diff.config))
    for deviation in diff.config.deviations:
        lines.append(f"  policy deviation: {deviation}")
    lines.append(
        f"  config: {diff.config.source.tier} {diff.config.source.path} "
        f"(profile {diff.config.values['profile']}, "
        f"digest {diff.config.digest[:CONFIG_DIGEST_SHORT_HEX]})"
    )
    lines.append(
        _verification_line(
            head.report.coverage["verification"],
            head.report.coverage["rules_needing_base_revision"],
        )
    )
    lines.extend(_complexity_lines(diff.metrics))
    lines.extend(_history_lines(diff.metrics))
    lines.append(f"  analysis status: {head.report.analysis_status}")
    lines.append(_unknown_line(diff.gate))
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
