"""CPLX001-CPLX006: advisory complexity and coupling warnings.

CPLX001-CPLX004 and CPLX006 compare each unit's numbers with the ``complexity``
thresholds; CPLX005 reads the cross-file graph (module cycles, fan-out). Every finding
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
from shockharness.complexity import size as size_module
from shockharness.complexity.callgraph import ModuleEdge
from shockharness.complexity.coupling import Cycle, GraphMetrics
from shockharness.complexity.metrics import UnitMetrics
from shockharness.constants import CYCLE_MEMBERS_LISTED
from shockharness.findings import CONFIDENCE_EXACT, STATUS_VIOLATION, Finding
from shockharness.ir.model import MODULE_SCOPE, UNIT_MODULE, Span
from shockharness.rules.registry import (
    CPLX001,
    CPLX002,
    CPLX003,
    CPLX004,
    CPLX005,
    CPLX006,
    CSHARP,
    JAVASCRIPT,
    PYTHON,
    TYPESCRIPT,
    RuleSpec,
)
from shockharness.source import SourceText

SETTING_CYCLOMATIC_WARN = "cyclomatic_warn"
SETTING_COGNITIVE_WARN = "cognitive_warn"
SETTING_NESTING_WARN = "max_nesting_warn"
SETTING_NPATH_WARN = "npath_warn"
SETTING_FAN_OUT_WARN = "fan_out_warn"
SETTING_FAN_OUT_SEVERITY = "fan_out_severity"
SETTING_MAX_LINES_WARN = "max_lines_warn"
SETTING_NPATH_ONLY_WITHOUT_COGNITIVE = "npath_only_without_cognitive"

# The metric each rule measures, as it appears in metrics.complexity.functions
# ("size" is functions[].size.logical_lines).
METRIC_SIZE = "size"
METRIC_OF_RULE: Mapping[str, str] = {
    CPLX001.rule_id: "cyclomatic",
    CPLX002.rule_id: "cognitive",
    CPLX003.rule_id: "nesting",
    CPLX004.rule_id: "npath",
    CPLX006.rule_id: METRIC_SIZE,
}
THRESHOLD_OF_RULE: Mapping[str, str] = {
    CPLX001.rule_id: SETTING_CYCLOMATIC_WARN,
    CPLX002.rule_id: SETTING_COGNITIVE_WARN,
    CPLX003.rule_id: SETTING_NESTING_WARN,
    CPLX004.rule_id: SETTING_NPATH_WARN,
    CPLX006.rule_id: SETTING_MAX_LINES_WARN,
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
    return _finding_at(rule, rule.default_severity, path, span, message, source, scope)


def _finding_at(
    rule: RuleSpec,
    severity: str,
    path: str,
    span: Span,
    message: str,
    source: SourceText,
    scope: str,
) -> Finding:
    return Finding(
        rule_id=rule.rule_id,
        rule_version=rule.version,
        severity=severity,
        path=path,
        span=span,
        message=message,
        evidence=source.excerpt(span.line),
        confidence=CONFIDENCE_EXACT,
        status=STATUS_VIOLATION,
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
    if metric == METRIC_SIZE:
        return unit.fact.logical_lines
    return unit.npath


def exceeds(unit: UnitMetrics, rule_id: str, settings: Mapping[str, Any]) -> bool:
    threshold = int(settings[THRESHOLD_OF_RULE[rule_id]])
    if rule_id == CPLX004.rule_id:
        return unit.npath_saturated or unit.npath >= threshold
    if rule_id == CPLX006.rule_id and unit.kind == UNIT_MODULE:
        return False  # a module body is a container; its length is the sum of its units
    return unit_value(unit, rule_id) > threshold


def _npath_measured(unit: UnitMetrics, settings: Mapping[str, Any]) -> str:
    if unit.npath_saturated:
        return f"saturated at the cap ({unit.npath_text()})"
    return f"{unit.npath}, at or above npath_warn = {settings[SETTING_NPATH_WARN]}"


def run_unit_rules(
    units: Sequence[UnitMetrics],
    source: SourceText,
    settings: Mapping[str, Any],
    path: str,
    active: frozenset[str],
) -> list[Finding]:
    """CPLX001-CPLX004 and CPLX006 for every unit of one file.

    With ``complexity.npath_only_without_cognitive`` (the default) a unit above both
    ``cognitive_warn`` and ``npath_warn`` is reported once, as CPLX002 with the NPath
    number in the same message, instead of as two findings on the same line.
    """
    npath_only_without_cognitive = bool(settings[SETTING_NPATH_ONLY_WITHOUT_COGNITIVE])
    findings: list[Finding] = []
    for unit in units:
        span = header_span(unit.fact.span, source)
        what = f"{unit.kind} {unit.name}"
        cognitive_fires = CPLX002.rule_id in active and exceeds(unit, CPLX002.rule_id, settings)
        npath_fires = CPLX004.rule_id in active and exceeds(unit, CPLX004.rule_id, settings)
        folded = npath_only_without_cognitive and cognitive_fires and npath_fires
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
        if cognitive_fires:
            message = (
                f"cognitive complexity of {what} is {unit.cognitive}, above "
                f"cognitive_warn = {settings[SETTING_COGNITIVE_WARN]} "
                f"(convention {cognitive_module.CONVENTION}; not a Sonar score)"
            )
            if folded:
                message += (
                    f"; its NPath estimate is {_npath_measured(unit, settings)} (convention "
                    f"{npath_module.CONVENTION}), reported here instead of as CPLX004 "
                    f"({SETTING_NPATH_ONLY_WITHOUT_COGNITIVE} = true)"
                )
            findings.append(_finding(CPLX002, path, span, message, source, unit.name))
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
        if npath_fires and not folded:
            findings.append(
                _finding(
                    CPLX004,
                    path,
                    span,
                    f"NPath estimate of {what} is {_npath_measured(unit, settings)} (convention "
                    f"{npath_module.CONVENTION}; a bounded estimate, not an exact count)",
                    source,
                    unit.name,
                )
            )
        if CPLX006.rule_id in active and exceeds(unit, CPLX006.rule_id, settings):
            findings.append(
                _finding(
                    CPLX006,
                    path,
                    span,
                    f"size of {what} is {unit.fact.logical_lines} logical line(s), above "
                    f"max_lines_warn = {settings[SETTING_MAX_LINES_WARN]} "
                    f"(convention {size_module.CONVENTION}; module bodies are exempt)",
                    source,
                    unit.name,
                )
            )
    return findings


CYCLE_MESSAGE_PREFIX = "module import cycle of "
CYCLE_NOTES: Mapping[str, str] = {
    PYTHON: "a Python import cycle fails at import time",
    JAVASCRIPT: (
        "an ES-module cycle is usually resolved at call time, so it ranks after Python cycles"
    ),
    TYPESCRIPT: (
        "an ES-module cycle is usually resolved at call time, so it ranks after Python cycles"
    ),
    CSHARP: (
        "C# files that call into each other's classes (a class's partial files are one); "
        "nothing fails at load time, so it ranks after Python cycles"
    ),
}
LANGUAGE_LABELS: Mapping[str, str] = {
    PYTHON: "Python",
    JAVASCRIPT: "JavaScript",
    TYPESCRIPT: "TypeScript",
    CSHARP: "C#",
}
# How an edge of each language enters a cycle: an import, or (C#) a call into a class.
CYCLE_EDGES: Mapping[str, str] = {
    PYTHON: "import of",
    JAVASCRIPT: "import of",
    TYPESCRIPT: "import of",
    CSHARP: "call into",
}


def _cycle_message(cycle: Cycle, edge: ModuleEdge, language: str) -> str:
    return (
        f"{CYCLE_MESSAGE_PREFIX}{len(cycle.modules)} {LANGUAGE_LABELS[language]} "
        f"module(s): {cycle_members_text(cycle.modules)} (one finding per cycle, anchored "
        f"on {edge.source}, whose {CYCLE_EDGES[language]} {edge.target} enters it; "
        f"{CYCLE_NOTES[language]}; resolved edges only; every member is listed in "
        "metrics.graph.cycles)"
    )


def is_cycle_finding(finding: Finding) -> bool:
    """A CPLX005 finding that reports an import cycle (as opposed to fan-out)."""
    return finding.rule_id == CPLX005.rule_id and finding.message.startswith(CYCLE_MESSAGE_PREFIX)


def cycle_members_text(modules: Sequence[str]) -> str:
    """``a -> b -> a`` for short cycles; the first ``CYCLE_MEMBERS_LISTED`` members
    followed by ``and N more`` for long ones."""
    if len(modules) <= CYCLE_MEMBERS_LISTED:
        return " -> ".join([*modules, modules[0]])
    listed = " -> ".join(modules[:CYCLE_MEMBERS_LISTED])
    return f"{listed} -> ... and {len(modules) - CYCLE_MEMBERS_LISTED} more"


def _cycle_anchor(cycle: Cycle, active_paths: frozenset[str]) -> ModuleEdge | None:
    """The edge that anchors the cycle's one finding: the lexically first member's import
    into the cycle. A member where CPLX005 is disabled cannot carry the finding, so the
    first active member is used instead; a cycle with no active member has no finding."""
    for edge in sorted(cycle.edges, key=lambda e: e.source):
        if edge.source in active_paths:
            return edge
    return None


def run_graph_rules(
    metrics: GraphMetrics,
    sources: Mapping[str, SourceText],
    languages: Mapping[str, str],
    settings: Mapping[str, Any],
    active_paths: frozenset[str],
) -> dict[str, list[Finding]]:
    """CPLX005 findings per path, for the paths where the rule is active.

    Fan-out: one finding per unit above ``fan_out_warn``. Cycles: one finding per
    cycle (not per member), anchored on the lexically first member so that its
    fingerprint does not move when unrelated modules are added; the message names
    the language, the size and up to :data:`CYCLE_MEMBERS_LISTED` members.
    """
    by_path: dict[str, list[Finding]] = {}
    fan_out_warn = int(settings[SETTING_FAN_OUT_WARN])
    fan_out_severity = str(settings[SETTING_FAN_OUT_SEVERITY])
    for unit in metrics.units:
        if unit.path not in active_paths or unit.fan_out_total <= fan_out_warn:
            continue
        source = sources[unit.path]
        span = header_span(unit.span, source)
        finding = _finding_at(
            CPLX005,
            fan_out_severity,
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
        edge = _cycle_anchor(cycle, active_paths)
        if edge is None:
            continue
        language = languages[edge.source]
        source = sources[edge.source]
        finding = _finding(
            CPLX005,
            edge.source,
            edge.span,
            _cycle_message(cycle, edge, language),
            source,
            MODULE_SCOPE,
        )
        if edge.source not in by_path:
            by_path[edge.source] = []
        by_path[edge.source].append(finding)
    return by_path
