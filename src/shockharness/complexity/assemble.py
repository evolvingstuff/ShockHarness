"""Assemble ``metrics.complexity`` and ``metrics.graph`` for one analysis run."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from shockharness.complexity.callgraph import ModuleInput, build_call_graph
from shockharness.complexity.coupling import (
    STATUS_AVAILABLE,
    STATUS_DISABLED,
    GraphMetrics,
    disabled_graph,
    module_cycles,
    shared_mutable_state,
    unit_coupling,
)
from shockharness.complexity.metrics import (
    UnitMetrics,
    conventions_json,
    file_aggregate,
)
from shockharness.config import EffectiveConfig
from shockharness.findings import Finding
from shockharness.rules.complexity import (
    SETTING_COGNITIVE_WARN,
    SETTING_CYCLOMATIC_WARN,
    SETTING_FAN_OUT_WARN,
    SETTING_MAX_LINES_WARN,
    SETTING_NESTING_WARN,
    SETTING_NPATH_WARN,
    run_graph_rules,
)
from shockharness.source import SourceText

COMPLEXITY_SECTION = "complexity"
DISABLED_REASON = "complexity.enabled = false"
DISPLACEMENT_NOT_APPLICABLE = "needs a base revision: computed only by diff and gate --base/--head"
DISPLACEMENT_DISABLED = "complexity.abstraction_displacement = false"
SETTING_DISPLACEMENT = "abstraction_displacement"


@dataclass(frozen=True)
class ComplexityOutcome:
    complexity: dict[str, Any]
    graph: dict[str, Any]
    graph_findings: Mapping[str, Sequence[Finding]]


def thresholds_json(settings: Mapping[str, Any]) -> dict[str, int]:
    return {
        SETTING_CYCLOMATIC_WARN: int(settings[SETTING_CYCLOMATIC_WARN]),
        SETTING_COGNITIVE_WARN: int(settings[SETTING_COGNITIVE_WARN]),
        SETTING_NESTING_WARN: int(settings[SETTING_NESTING_WARN]),
        SETTING_NPATH_WARN: int(settings[SETTING_NPATH_WARN]),
        SETTING_FAN_OUT_WARN: int(settings[SETTING_FAN_OUT_WARN]),
        SETTING_MAX_LINES_WARN: int(settings[SETTING_MAX_LINES_WARN]),
    }


def displacement_placeholder(settings: Mapping[str, Any]) -> dict[str, Any]:
    enabled = bool(settings[SETTING_DISPLACEMENT])
    return {
        "enabled": enabled,
        "experimental": True,
        "status": "not_applicable",
        "reason": DISPLACEMENT_NOT_APPLICABLE if enabled else DISPLACEMENT_DISABLED,
        "findings": [],
    }


def disabled_outcome(config: EffectiveConfig) -> ComplexityOutcome:
    settings = config.section(COMPLEXITY_SECTION)
    graph = disabled_graph(DISABLED_REASON)
    graph["abstraction_displacement"] = displacement_placeholder(settings)
    return ComplexityOutcome(
        complexity={
            "status": STATUS_DISABLED,
            "reason": DISABLED_REASON,
            "conventions": conventions_json(settings),
            "thresholds": thresholds_json(settings),
            "functions": [],
            "files": {},
        },
        graph=graph,
        graph_findings={},
    )


def assemble(
    modules: Sequence[ModuleInput],
    sources: Mapping[str, SourceText],
    config: EffectiveConfig,
    cplx005_paths: frozenset[str],
) -> ComplexityOutcome:
    """Metrics and CPLX005 findings for every parsed module of a run."""
    settings = config.section(COMPLEXITY_SECTION)
    if settings["enabled"] is False:
        return disabled_outcome(config)
    ordered = sorted(modules, key=lambda m: m.path)
    graph = build_call_graph(ordered)
    all_units: list[UnitMetrics] = [u for m in ordered for u in m.units]
    metrics = GraphMetrics(
        graph=graph,
        units=unit_coupling(graph, all_units),
        cycles=module_cycles(graph),
        shared=shared_mutable_state(ordered),
    )
    graph_json = metrics.to_json_dict()
    graph_json["abstraction_displacement"] = displacement_placeholder(settings)
    return ComplexityOutcome(
        complexity={
            "status": STATUS_AVAILABLE,
            "reason": None,
            "conventions": conventions_json(settings),
            "thresholds": thresholds_json(settings),
            "functions": [u.to_json_dict() for u in all_units],
            "files": {m.path: file_aggregate(m.units) for m in ordered},
        },
        graph=graph_json,
        graph_findings=run_graph_rules(
            metrics, sources, {m.path: m.language for m in ordered}, settings, cplx005_paths
        ),
    )
