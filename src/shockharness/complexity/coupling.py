"""Fan-in/fan-out, module cycles, shared mutable state, and the ``metrics.graph`` shape."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from shockharness.complexity.callgraph import (
    CONFIDENCE_DESCRIPTIONS,
    CONFIDENCE_EXTERNAL,
    CONFIDENCE_PROBABLE,
    CONFIDENCE_RESOLVED,
    CONFIDENCE_UNRESOLVED,
    TARGET_EXTERNAL,
    TARGET_UNIT,
    CallGraph,
    ModuleEdge,
    ModuleInput,
)
from shockharness.complexity.metrics import UnitMetrics
from shockharness.ir.model import (
    BINDING_VARIABLE,
    CONFIDENCE_APPROXIMATE,
    MODULE_SCOPE,
    Span,
)

STATUS_AVAILABLE = "available"
STATUS_DISABLED = "disabled"
COUNTED_CONFIDENCES = frozenset({CONFIDENCE_RESOLVED, CONFIDENCE_PROBABLE})


@dataclass(frozen=True)
class UnitCoupling:
    key: str
    path: str
    name: str
    span: Span
    fan_in: int
    fan_out: int  # distinct analyzed-unit targets
    fan_out_external: int  # distinct external symbols
    resolved_calls: int
    probable_calls: int
    unresolved_calls: int

    @property
    def fan_out_total(self) -> int:
        return self.fan_out + self.fan_out_external

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "path": self.path,
            "name": self.name,
            "fan_in": self.fan_in,
            "fan_out": self.fan_out,
            "fan_out_external": self.fan_out_external,
            "fan_out_total": self.fan_out_total,
            "calls": {
                CONFIDENCE_RESOLVED: self.resolved_calls,
                CONFIDENCE_PROBABLE: self.probable_calls,
                CONFIDENCE_UNRESOLVED: self.unresolved_calls,
            },
        }


@dataclass(frozen=True)
class Cycle:
    modules: tuple[str, ...]
    edges: tuple[ModuleEdge, ...]  # one edge per member, pointing into the cycle

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "modules": list(self.modules),
            "confidence": CONFIDENCE_RESOLVED,
            "edges": [
                {"from": e.source, "to": e.target, "span": e.span.to_json_dict()}
                for e in self.edges
            ],
        }


@dataclass(frozen=True)
class SharedState:
    path: str
    name: str
    span: Span
    writers: tuple[str, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "name": self.name,
            "span": self.span.to_json_dict(),
            "writers": list(self.writers),
            "confidence": CONFIDENCE_APPROXIMATE,
            "note": (
                "module-level mutable binding written from more than one unit; shadowing, "
                "aliasing and writes through other modules are not tracked"
            ),
        }


def unit_coupling(graph: CallGraph, units: Sequence[UnitMetrics]) -> tuple[UnitCoupling, ...]:
    targets: dict[str, set[str]] = {key: set() for key in graph.unit_keys}
    external: dict[str, set[str]] = {key: set() for key in graph.unit_keys}
    callers: dict[str, set[str]] = {key: set() for key in graph.unit_keys}
    counts: dict[str, dict[str, int]] = {
        key: {CONFIDENCE_RESOLVED: 0, CONFIDENCE_PROBABLE: 0, CONFIDENCE_UNRESOLVED: 0}
        for key in graph.unit_keys
    }
    for edge in graph.edges:
        counts[edge.source][edge.confidence] += edge.calls
        if edge.confidence not in COUNTED_CONFIDENCES:
            continue
        if edge.target.kind == TARGET_UNIT:
            targets[edge.source].add(edge.target.identifier)
            if edge.target.identifier in callers:
                callers[edge.target.identifier].add(edge.source)
        elif edge.target.kind == TARGET_EXTERNAL:
            external[edge.source].add(edge.target.identifier)
    result: list[UnitCoupling] = []
    for unit in units:
        result.append(
            UnitCoupling(
                key=unit.key,
                path=unit.path,
                name=unit.name,
                span=unit.fact.span,
                fan_in=len(callers[unit.key]),
                fan_out=len(targets[unit.key]),
                fan_out_external=len(external[unit.key]),
                resolved_calls=counts[unit.key][CONFIDENCE_RESOLVED],
                probable_calls=counts[unit.key][CONFIDENCE_PROBABLE],
                unresolved_calls=counts[unit.key][CONFIDENCE_UNRESOLVED],
            )
        )
    return tuple(result)


def strongly_connected_components(
    nodes: Sequence[str], successors: Mapping[str, Sequence[str]]
) -> list[list[str]]:
    """Tarjan's algorithm, iterative. Components are returned sorted, members sorted."""
    index_of: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    components: list[list[str]] = []
    counter = 0
    for root in nodes:
        if root in index_of:
            continue
        work: list[tuple[str, int]] = [(root, 0)]
        index_of[root] = counter
        low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while len(work) > 0:
            node, position = work.pop()
            succ = successors[node]
            if position < len(succ):
                work.append((node, position + 1))
                child = succ[position]
                if child not in index_of:
                    index_of[child] = counter
                    low[child] = counter
                    counter += 1
                    stack.append(child)
                    on_stack.add(child)
                    work.append((child, 0))
                elif child in on_stack:
                    low[node] = min(low[node], index_of[child])
                continue
            if len(work) > 0:
                parent = work[len(work) - 1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index_of[node]:
                component: list[str] = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                components.append(sorted(component))
    components.sort()
    return components


def module_cycles(graph: CallGraph) -> tuple[Cycle, ...]:
    successors: dict[str, list[str]] = {path: [] for path in graph.paths}
    by_pair: dict[tuple[str, str], ModuleEdge] = {}
    for edge in graph.module_edges:
        if edge.confidence != CONFIDENCE_RESOLVED or edge.target is None:
            continue
        if edge.target == edge.source or edge.target not in successors:
            continue
        if edge.target not in successors[edge.source]:
            successors[edge.source].append(edge.target)
        pair = (edge.source, edge.target)
        if pair not in by_pair:
            by_pair[pair] = edge
    cycles: list[Cycle] = []
    for component in strongly_connected_components(list(graph.paths), successors):
        if len(component) < 1 + 1:
            continue
        members = set(component)
        edges: list[ModuleEdge] = []
        for member in component:
            for target in successors[member]:
                if target in members:
                    edges.append(by_pair[(member, target)])
                    break
        cycles.append(Cycle(tuple(component), tuple(edges)))
    return tuple(cycles)


def _mutable_bindings(module: ModuleInput) -> dict[str, Span]:
    """Module-level variables bound to a mutable value, or named by a ``global`` statement."""
    declared_global: set[str] = set()
    for unit in module.units:
        declared_global.update(unit.fact.globals_declared)
    mutable: dict[str, Span] = {}
    for binding in module.bindings:
        if binding.kind != BINDING_VARIABLE:
            continue
        if binding.mutable or binding.name in declared_global:
            mutable[binding.name] = binding.span
    return mutable


def _writers(module: ModuleInput, names: Mapping[str, Span]) -> dict[str, set[str]]:
    writers: dict[str, set[str]] = {name: set() for name in names}
    for unit in module.units:
        if unit.name == MODULE_SCOPE:
            continue
        for name, _kind in unit.fact.writes:
            if name in writers:
                writers[name].add(unit.name)
    return writers


def shared_mutable_state(modules: Sequence[ModuleInput]) -> tuple[SharedState, ...]:
    found: list[SharedState] = []
    for module in sorted(modules, key=lambda m: m.path):
        mutable = _mutable_bindings(module)
        writers = _writers(module, mutable)
        for name in sorted(mutable):
            if len(writers[name]) > 1:
                found.append(
                    SharedState(module.path, name, mutable[name], tuple(sorted(writers[name])))
                )
    return tuple(found)


@dataclass(frozen=True)
class GraphMetrics:
    graph: CallGraph
    units: tuple[UnitCoupling, ...]
    cycles: tuple[Cycle, ...]
    shared: tuple[SharedState, ...]

    def to_json_dict(self) -> dict[str, Any]:
        module_counts = {
            CONFIDENCE_RESOLVED: 0,
            CONFIDENCE_EXTERNAL: 0,
            CONFIDENCE_UNRESOLVED: 0,
        }
        for edge in self.graph.module_edges:
            module_counts[edge.confidence] += 1
        edge_counts = {CONFIDENCE_RESOLVED: 0, CONFIDENCE_PROBABLE: 0, CONFIDENCE_UNRESOLVED: 0}
        site_counts = {CONFIDENCE_RESOLVED: 0, CONFIDENCE_PROBABLE: 0, CONFIDENCE_UNRESOLVED: 0}
        for edge in self.graph.edges:
            edge_counts[edge.confidence] += 1
            site_counts[edge.confidence] += edge.calls
        importers: dict[str, set[str]] = {path: set() for path in self.graph.paths}
        imported: dict[str, set[str]] = {path: set() for path in self.graph.paths}
        for edge in self.graph.module_edges:
            if edge.target is not None and edge.target in importers:
                importers[edge.target].add(edge.source)
                imported[edge.source].add(edge.target)
        cycle_of: dict[str, int | None] = {path: None for path in self.graph.paths}
        for position, cycle in enumerate(self.cycles):
            for member in cycle.modules:
                cycle_of[member] = position
        modules = [
            {
                "path": path,
                "fan_in": len(importers[path]),
                "fan_out": len(imported[path]),
                "cycle": cycle_of[path],
            }
            for path in self.graph.paths
        ]
        return {
            "status": STATUS_AVAILABLE,
            "reason": None,
            "confidence": dict(CONFIDENCE_DESCRIPTIONS),
            "summary": {
                "modules": len(self.graph.paths),
                "units": len(self.graph.unit_keys),
                "call_edges": edge_counts,
                "call_sites": site_counts,
                "module_edges": module_counts,
                "cycles": len(self.cycles),
                "shared_mutable_state": len(self.shared),
            },
            "modules": modules,
            "module_edges": [e.to_json_dict() for e in self.graph.module_edges],
            "units": [u.to_json_dict() for u in self.units],
            "edges": [e.to_json_dict() for e in self.graph.edges],
            "cycles": [c.to_json_dict() for c in self.cycles],
            "shared_mutable_state": [s.to_json_dict() for s in self.shared],
        }


def disabled_graph(reason: str) -> dict[str, Any]:
    return {
        "status": STATUS_DISABLED,
        "reason": reason,
        "confidence": dict(CONFIDENCE_DESCRIPTIONS),
        "summary": {
            "modules": 0,
            "units": 0,
            "call_edges": {
                CONFIDENCE_RESOLVED: 0,
                CONFIDENCE_PROBABLE: 0,
                CONFIDENCE_UNRESOLVED: 0,
            },
            "call_sites": {
                CONFIDENCE_RESOLVED: 0,
                CONFIDENCE_PROBABLE: 0,
                CONFIDENCE_UNRESOLVED: 0,
            },
            "module_edges": {
                CONFIDENCE_RESOLVED: 0,
                CONFIDENCE_EXTERNAL: 0,
                CONFIDENCE_UNRESOLVED: 0,
            },
            "cycles": 0,
            "shared_mutable_state": 0,
        },
        "modules": [],
        "module_edges": [],
        "units": [],
        "edges": [],
        "cycles": [],
        "shared_mutable_state": [],
    }
