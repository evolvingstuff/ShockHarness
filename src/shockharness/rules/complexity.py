"""CPLX001-CPLX005: advisory complexity and coupling warnings.

CPLX001-CPLX004 compare each unit's numbers with the ``complexity`` thresholds;
CPLX005 reads the cross-file graph (module cycles, fan-out). Every finding
names the measured value, the threshold and the convention version. None of
them fails a plain ``check``; in a revision diff ``gates.complexity_regressions``
decides what a per-unit regression means.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from shockharness.complexity import cognitive as cognitive_module
from shockharness.complexity import cyclomatic as cyclomatic_module
from shockharness.complexity import nesting as nesting_module
from shockharness.complexity import npath as npath_module
from shockharness.complexity.coupling import GraphMetrics
from shockharness.complexity.metrics import UnitMetrics
from shockharness.findings import CONFIDENCE_EXACT, Finding
from shockharness.ir.model import MODULE_SCOPE, Span
from shockharness.rules.registry import CPLX001, CPLX002, CPLX003, CPLX004, CPLX005, RuleSpec
from shockharness.source import SourceText

SETTING_CYCLOMATIC_WARN = "cyclomatic_warn"
SETTING_COGNITIVE_WARN = "cognitive_warn"
SETTING_NESTING_WARN = "max_nesting_warn"
SETTING_NPATH_WARN = "npath_warn"
SETTING_FAN_OUT_WARN = "fan_out_warn"

# The metric each rule measures, as it appears in metrics.complexity.functions.
METRIC_OF_RULE: Mapping[str, str] = {
    CPLX001.rule_id: "cyclomatic",
    CPLX002.rule_id: "cognitive",
    CPLX003.rule_id: "nesting",
    CPLX004.rule_id: "npath",
}
THRESHOLD_OF_RULE: Mapping[str, str] = {
    CPLX001.rule_id: SETTING_CYCLOMATIC_WARN,
    CPLX002.rule_id: SETTING_COGNITIVE_WARN,
    CPLX003.rule_id: SETTING_NESTING_WARN,
    CPLX004.rule_id: SETTING_NPATH_WARN,
}


def header_span(span: Span, source: SourceText) -> Span:
    """The first line of a unit: where a finding on the unit is anchored."""
    end_column = len(source.line_text(span.line)) + 1
    if span.end_line == span.line:
        end_column = span.end_column
    return Span(span.line, span.column, span.line, end_column)


def _finding(
    rule: RuleSpec, path: str, span: Span, message: str, source: SourceText, scope: str
) -> Finding:
    return Finding(
        rule_id=rule.rule_id,
        rule_version=rule.version,
        severity=rule.default_severity,
        path=path,
        span=span,
        message=message,
        evidence=source.excerpt(span.line),
        confidence=CONFIDENCE_EXACT,
        remediation=rule.remediation,
        safe_autofix=False,
        scope=scope,
        suppression=None,
        fingerprint=None,
        baseline=None,
    )


def unit_value(unit: UnitMetrics, rule_id: str) -> int:
    metric = METRIC_OF_RULE[rule_id]
    if metric == "cyclomatic":
        return unit.cyclomatic
    if metric == "cognitive":
        return unit.cognitive
    if metric == "nesting":
        return unit.nesting
    return unit.npath


def exceeds(unit: UnitMetrics, rule_id: str, settings: Mapping[str, Any]) -> bool:
    threshold = int(settings[THRESHOLD_OF_RULE[rule_id]])
    if rule_id == CPLX004.rule_id:
        return unit.npath_saturated or unit.npath >= threshold
    return unit_value(unit, rule_id) > threshold


def run_unit_rules(
    units: Sequence[UnitMetrics],
    source: SourceText,
    settings: Mapping[str, Any],
    path: str,
    active: frozenset[str],
) -> list[Finding]:
    findings: list[Finding] = []
    for unit in units:
        span = header_span(unit.fact.span, source)
        what = f"{unit.kind} {unit.name}"
        if CPLX001.rule_id in active and exceeds(unit, CPLX001.rule_id, settings):
            findings.append(
                _finding(
                    CPLX001,
                    path,
                    span,
                    f"cyclomatic complexity of {what} is {unit.cyclomatic}, above "
                    f"cyclomatic_warn = {settings[SETTING_CYCLOMATIC_WARN]} "
                    f"(convention {cyclomatic_module.CONVENTION})",
                    source,
                    unit.name,
                )
            )
        if CPLX002.rule_id in active and exceeds(unit, CPLX002.rule_id, settings):
            findings.append(
                _finding(
                    CPLX002,
                    path,
                    span,
                    f"cognitive complexity of {what} is {unit.cognitive}, above "
                    f"cognitive_warn = {settings[SETTING_COGNITIVE_WARN]} "
                    f"(convention {cognitive_module.CONVENTION}; not a Sonar score)",
                    source,
                    unit.name,
                )
            )
        if CPLX003.rule_id in active and exceeds(unit, CPLX003.rule_id, settings):
            findings.append(
                _finding(
                    CPLX003,
                    path,
                    span,
                    f"decision nesting depth of {what} is {unit.nesting}, above "
                    f"max_nesting_warn = {settings[SETTING_NESTING_WARN]} "
                    f"(convention {nesting_module.CONVENTION})",
                    source,
                    unit.name,
                )
            )
        if CPLX004.rule_id in active and exceeds(unit, CPLX004.rule_id, settings):
            if unit.npath_saturated:
                measured = f"saturated at the cap ({unit.npath_text()})"
            else:
                measured = f"{unit.npath}, at or above npath_warn = {settings[SETTING_NPATH_WARN]}"
            findings.append(
                _finding(
                    CPLX004,
                    path,
                    span,
                    f"NPath estimate of {what} is {measured} (convention "
                    f"{npath_module.CONVENTION}; a bounded estimate, not an exact count)",
                    source,
                    unit.name,
                )
            )
    return findings


def run_graph_rules(
    metrics: GraphMetrics,
    sources: Mapping[str, SourceText],
    settings: Mapping[str, Any],
    active_paths: frozenset[str],
) -> dict[str, list[Finding]]:
    """CPLX005 findings per path, for the paths where the rule is active."""
    by_path: dict[str, list[Finding]] = {}
    fan_out_warn = int(settings[SETTING_FAN_OUT_WARN])
    for unit in metrics.units:
        if unit.path not in active_paths or unit.fan_out_total <= fan_out_warn:
            continue
        source = sources[unit.path]
        span = header_span(unit.span, source)
        finding = _finding(
            CPLX005,
            unit.path,
            span,
            f"fan-out of {unit.name} is {unit.fan_out_total} distinct call target(s) "
            f"({unit.fan_out} analyzed, {unit.fan_out_external} external; resolved and probable "
            f"edges only, {unit.unresolved_calls} unresolved call(s) not counted), above "
            f"fan_out_warn = {fan_out_warn}",
            source,
            unit.name,
        )
        if unit.path not in by_path:
            by_path[unit.path] = []
        by_path[unit.path].append(finding)
    for cycle in metrics.cycles:
        members = " -> ".join([*cycle.modules, cycle.modules[0]])
        for edge in cycle.edges:
            if edge.source not in active_paths:
                continue
            source = sources[edge.source]
            finding = _finding(
                CPLX005,
                edge.source,
                edge.span,
                f"module import cycle of {len(cycle.modules)} module(s): {members} "
                f"(this import of {edge.target} closes it; resolved edges only)",
                source,
                MODULE_SCOPE,
            )
            if edge.source not in by_path:
                by_path[edge.source] = []
            by_path[edge.source].append(finding)
    return by_path
