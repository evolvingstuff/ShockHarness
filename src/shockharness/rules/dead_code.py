"""DEAD001 and DEAD002: functions nothing in production reaches, reported by cluster.

Reachability from roots over the call graph and the references it does not record:

* Roots: module and class bodies, functions something registers without a call (a
  decorator, ``__all__``, a dunder, a JavaScript ``constructor``, an entry point in
  ``rules.dead_code.entry_points``), and every method of a class derived from a class
  the project does not define (a framework calls those: ``HTMLParser.handle_*``,
  ``NodeVisitor.visit_*``, ``HTMLElement.connectedCallback``).
* Edges: every call-graph edge to a unit (resolved or probable, calls and arguments); an
  unresolved call reaches every function or method of its final name; a member reference
  (``obj.name``) reaches every function or method of that name; a bare reference reaches
  the file's functions of that name and the function an import of it names; a function
  or lambda reaches the units nested in it.
* Overrides: a method is alive while any method it overrides, or any that overrides it,
  is alive (dispatch decides which runs).

Tests (the ``test`` and ``config`` roles) are roots of their own: a function only they
reach is reported by DEAD002, the rest by DEAD001. One finding per head, a dead function
no other dead function reaches, listing what is reachable only through it.
"""

import fnmatch
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from shockharness.complexity.callgraph import TARGET_UNIT, TARGET_UNRESOLVED, CallGraph
from shockharness.complexity.metrics import UnitMetrics
from shockharness.findings import CONFIDENCE_APPROXIMATE, STATUS_VIOLATION, Finding
from shockharness.ir.model import (
    UNIT_CLASS,
    UNIT_MODULE,
    ImportFact,
    ReceiverClass,
    UsageFacts,
)
from shockharness.rules.registry import DEAD001, DEAD002, RuleSpec
from shockharness.source import SourceText

SETTING_ENTRY_POINTS = "entry_points"
SETTING_SEVERITY = "severity"
SETTING_DEAD002_SEVERITY = "dead002_severity"
CONTAINERS = frozenset({UNIT_MODULE, UNIT_CLASS})
# Bases that carry no framework callbacks: a class derived only from these is the
# project's own, and its methods are judged like any other.
NEUTRAL_BASES = frozenset(
    {
        "object",
        "ABC",
        "Protocol",
        "Generic",
        "NamedTuple",
        "TypedDict",
        "Enum",
        "IntEnum",
        "StrEnum",
        "Flag",
        "IntFlag",
        "BaseException",
        "Exception",
        "Error",
        "ValueError",
        "TypeError",
        "RuntimeError",
        "KeyError",
        "LookupError",
        "OSError",
        "Object",
    }
)
DUNDER = re.compile(r"^__\w+__$")
JS_CONSTRUCTOR = "constructor"
DUPLICATE_SUFFIX = re.compile(r"#\d+$")
LISTED = 6  # members named in a message; the rest are counted


@dataclass(frozen=True)
class DeadFile:
    path: str
    tested: bool  # a test or config file: its units are the tests' roots
    applied: frozenset[str]  # which of DEAD001/DEAD002 apply to the file
    source: SourceText
    units: tuple[UnitMetrics, ...]
    usage: UsageFacts
    imports: tuple[ImportFact, ...]
    classes: tuple[ReceiverClass, ...]


def final_name(dotted: str) -> str:
    _head, _dot, last = dotted.rpartition(".")
    return last


def short_name(unit: UnitMetrics) -> str:
    return final_name(unit.name)


def _add(table: dict[str, list[str]], key: str, value: str) -> None:
    if key not in table:
        table[key] = []
    table[key].append(value)


class _Project:
    """The units, their names and the files they are in. ``by_name`` holds every unit of
    a final name; ``in_file`` the same per "path::name"."""

    def __init__(self, files: Sequence[DeadFile]) -> None:
        self.files = {f.path: f for f in files}
        self.units: dict[str, UnitMetrics] = {}
        self.path_of: dict[str, str] = {}
        self.at: dict[tuple[str, int, int], str] = {}
        self.by_name: dict[str, list[str]] = {}
        self.in_file: dict[str, list[str]] = {}
        for f in files:
            for unit in f.units:
                self.units[unit.key] = unit
                self.path_of[unit.key] = f.path
                self.at[(f.path, unit.fact.span.line, unit.fact.span.column)] = unit.key
                if unit.kind not in CONTAINERS:
                    _add(self.by_name, short_name(unit), unit.key)
                    _add(self.in_file, f"{f.path}::{short_name(unit)}", unit.key)


# -- edges ----------------------------------------------------------------------------------


def _module_targets(graph: CallGraph) -> dict[tuple[str, int, int], list[str]]:
    """The files each import statement resolves to, by (path, line, column)."""
    targets: dict[tuple[str, int, int], list[str]] = {}
    for edge in graph.module_edges:
        if edge.target is not None:
            key = (edge.source, edge.span.line, edge.span.column)
            if key not in targets:
                targets[key] = []
            targets[key].append(edge.target)
    return targets


def _imported_targets(project: _Project, graph: CallGraph) -> dict[str, list[tuple[str, str]]]:
    """For each "path::local" a bare name may be, the (file, name) its import names."""
    targets = _module_targets(graph)
    found: dict[str, list[tuple[str, str]]] = {}
    for f in project.files.values():
        for fact in f.imports:
            key = (f.path, fact.span.line, fact.span.column)
            if key in targets:
                _bind_names(found, f.path, fact, targets[key])
    return found


def _bind_names(
    found: dict[str, list[tuple[str, str]]], path: str, fact: ImportFact, targets: list[str]
) -> None:
    """Each name the import binds, to the (file, name) it imports; whole-module imports
    bind no function."""
    for imported, local in fact.names:
        if imported == "":
            continue
        local_key = f"{path}::{local}"
        if local_key not in found:
            found[local_key] = []
        found[local_key].extend((target, imported) for target in targets)


class _Edges:
    def __init__(self, project: _Project) -> None:
        self.project = project
        self.out: dict[str, set[str]] = {key: set() for key in project.units}

    def add(self, source: str, targets: Iterable[str]) -> None:
        self.out[source].update(t for t in targets if t != source)

    def _add_named(self, source: str, name: str) -> None:
        """Every function or method of this final name; a name no unit has adds nothing."""
        if name in self.project.by_name:
            self.add(source, self.project.by_name[name])

    def calls(self, graph: CallGraph) -> None:
        for edge in graph.edges:
            if edge.source not in self.out:
                continue
            if edge.target.kind == TARGET_UNIT:
                self.add(edge.source, [edge.target.identifier])
            elif edge.target.kind == TARGET_UNRESOLVED:
                self._add_named(edge.source, final_name(edge.target.identifier))

    def references(self, imported: Mapping[str, list[tuple[str, str]]]) -> None:
        project = self.project
        for f in project.files.values():
            for reference in f.usage.references:
                at = (f.path, reference.line, reference.column)
                if at not in project.at:
                    continue
                source = project.at[at]
                if reference.member:
                    self._add_named(source, reference.name)
                    continue
                local = f"{f.path}::{reference.name}"
                if local in project.in_file:
                    self.add(source, project.in_file[local])
                if local in imported:
                    self._add_imported(source, imported[local])

    def _add_imported(self, source: str, pairs: Sequence[tuple[str, str]]) -> None:
        """The functions an imported name is: in the target file, or, for a package that
        re-exports it, every function of that name."""
        for target, name in pairs:
            here = f"{target}::{name}"
            if here in self.project.in_file:
                self.add(source, self.project.in_file[here])
            else:
                self._add_named(source, name)

    def nesting(self, declared: frozenset[str]) -> None:
        """A function reaches what is nested in it. A module or class body reaches its
        anonymous functions and classes, not the functions it declares."""
        for f in self.project.files.values():
            open_units: list[UnitMetrics] = []
            for unit in sorted(f.units, key=lambda u: (u.fact.span, -u.fact.span.end_line)):
                while len(open_units) > 0 and not _contains(open_units[len(open_units) - 1], unit):
                    open_units.pop()
                if len(open_units) > 0:
                    parent = open_units[len(open_units) - 1]
                    if parent.kind not in CONTAINERS or unit.key not in declared:
                        self.add(parent.key, [unit.key])
                open_units.append(unit)


def _contains(outer: UnitMetrics, inner: UnitMetrics) -> bool:
    a, b = outer.fact.span, inner.fact.span
    return (a.line, a.column) <= (b.line, b.column) and (b.end_line, b.end_column) <= (
        a.end_line,
        a.end_column,
    )


# -- classes --------------------------------------------------------------------------------


class _Classes:
    """Inheritance among the project's module-level classes: method families, and the
    classes derived from a class the project does not define."""

    def __init__(self, project: _Project) -> None:
        self.project = project
        self.parent: dict[tuple[str, str], tuple[str, str]] = {}
        self.defined: dict[str, list[tuple[str, str]]] = {}
        self.external: dict[tuple[str, str], str] = {}
        for f in project.files.values():
            for cls in f.classes:
                node = (f.path, cls.name)
                self.parent[node] = node
                if cls.name not in self.defined:
                    self.defined[cls.name] = []
                self.defined[cls.name].append(node)
        for f in project.files.values():
            for cls in f.classes:
                self._link(f.path, cls)

    def _find(self, node: tuple[str, str]) -> tuple[str, str]:
        while self.parent[node] != node:
            self.parent[node] = self.parent[self.parent[node]]
            node = self.parent[node]
        return node

    def _link(self, path: str, cls: ReceiverClass) -> None:
        for base in cls.bases:
            final = final_name(base)
            if final == "" or final in NEUTRAL_BASES:
                continue
            if final not in self.defined:
                self.external[(path, cls.name)] = base
                continue
            for other in self.defined[final]:
                self.parent[self._find(other)] = self._find((path, cls.name))

    def families(self) -> dict[str, list[str]]:
        """Each method's family: the methods of its name in related classes."""
        groups: dict[tuple[tuple[str, str], str], list[str]] = {}
        for unit in self.project.units.values():
            owner = unit.fact.class_name
            if owner is None or (self.project.path_of[unit.key], owner) not in self.parent:
                continue
            group = (self._find((self.project.path_of[unit.key], owner)), short_name(unit))
            if group not in groups:
                groups[group] = []
            groups[group].append(unit.key)
        return {key: members for members in groups.values() for key in members}

    def framework_method(self, unit: UnitMetrics) -> bool:
        """A method a framework may call: its class derives from a class the project does
        not define, or is nested in a function, where its bases are not known."""
        if unit.fact.class_name is None:
            return False
        node = (self.project.path_of[unit.key], unit.fact.class_name)
        return node in self.external or node not in self.parent


# -- reachability ---------------------------------------------------------------------------


def _reach(out: Mapping[str, set[str]], starts: Iterable[str], seen: set[str]) -> set[str]:
    stack = [s for s in starts if s not in seen]
    seen.update(stack)
    while len(stack) > 0:
        for target in out[stack.pop()]:
            if target not in seen:
                seen.add(target)
                stack.append(target)
    return seen


def _alive(
    out: Mapping[str, set[str]], roots: Iterable[str], families: Mapping[str, list[str]]
) -> set[str]:
    """What the roots reach, with every method of a live method's family alive too."""
    live = _reach(out, roots, set())
    while True:
        extra = {m for key in live if key in families for m in families[key] if m not in live}
        if len(extra) == 0:
            return live
        live = _reach(out, extra, live)


def _matches(key: str, patterns: Sequence[str]) -> bool:
    plain = DUPLICATE_SUFFIX.sub("", key)
    return any(fnmatch.fnmatchcase(plain, p) for p in patterns)


def _registered(
    project: _Project, classes: _Classes, declared: Mapping[str, str], patterns: Sequence[str]
) -> set[str]:
    found: set[str] = set()
    for key, reason in declared.items():
        unit = project.units[key]
        name = short_name(unit)
        if (
            reason != ""
            or DUNDER.match(name) is not None
            or name == JS_CONSTRUCTOR
            or classes.framework_method(unit)
            or _matches(key, patterns)
        ):
            found.add(key)
    return found


def _declared(project: _Project) -> dict[str, str]:
    """Each judged function's unit key and what registers it ("" for nothing)."""
    found: dict[str, str] = {}
    for f in project.files.values():
        for function in f.usage.declared:
            at = (f.path, function.line, function.column)
            if at in project.at:
                found[project.at[at]] = function.registered
    return found


# -- clusters and findings ------------------------------------------------------------------


@dataclass(frozen=True)
class _Cluster:
    head: str
    members: tuple[str, ...]  # reachable only through the head, head excluded
    tested: bool  # the tests reach the head
    tested_members: tuple[str, ...]


def _heads(inner: Mapping[str, set[str]], dead: set[str]) -> list[str]:
    """Dead functions no other dead function reaches; then, for dead cycles that have
    none, the first function of each such cycle."""
    reached = {t for key in dead for t in inner[key]}
    heads = sorted(dead - reached)
    covered = _reach(inner, heads, set())
    for key in sorted(dead):
        if key not in covered:
            heads.append(key)
            _reach(inner, [key], covered)
    return heads


def _within(out: Mapping[str, set[str]], keep: set[str]) -> dict[str, set[str]]:
    return {key: {t for t in targets if t in keep} for key, targets in out.items()}


def _clusters(
    out: Mapping[str, set[str]],
    dead: set[str],
    reach: tuple[set[str], set[str]],
    families: Mapping[str, list[str]],
) -> list[_Cluster]:
    """``reach``: what the tests reach, and what a test calls or names itself. A dead
    method and its dead overrides are one cluster."""
    tested, called = reach
    inner = _within(out, dead)
    for key in dead:
        if key in families:
            inner[key].update(m for m in families[key] if m in dead and m != key)
    clusters: list[_Cluster] = []
    for head in _heads(inner, dead):
        members = sorted(_reach(inner, [head], set()) - {head})
        clusters.append(
            _Cluster(
                head,
                tuple(members),
                head in tested,
                tuple(m for m in members if m in called),
            )
        )
    return clusters


def _label(project: _Project, key: str, head_path: str) -> str:
    unit = project.units[key]
    path = project.path_of[key]
    if path == head_path:
        return unit.name
    return f"{unit.name} ({path})"


def _listing(project: _Project, keys: Sequence[str], head_path: str) -> str:
    """The head's file first, then the others by path."""
    ordered = sorted(keys, key=lambda k: (project.path_of[k] != head_path, k))
    shown = ", ".join(_label(project, k, head_path) for k in ordered[:LISTED])
    rest = len(keys) - LISTED
    if rest > 0:
        return f"{shown} and {rest} more"
    return shown


def _message(project: _Project, cluster: _Cluster) -> str:
    head = project.units[cluster.head]
    path = project.path_of[cluster.head]
    if cluster.tested:
        opening = f"{head.name} is called only by tests: no production code calls or names it"
    else:
        opening = f"{head.name}: no production code calls or names it"
    message = f"{opening}, and nothing registers it (decorator, __all__, entry point)"
    if len(cluster.members) > 0:
        lines = sum(project.units[k].fact.logical_lines for k in (cluster.head, *cluster.members))
        message += (
            f"; {len(cluster.members)} more functions are reachable only through it: "
            f"{_listing(project, cluster.members, path)} ({lines} lines in all)"
        )
    if len(cluster.tested_members) > 0:
        message += (
            "; tests still call "
            f"{_listing(project, cluster.tested_members, path)}, so they pass while "
            "production never runs it"
        )
    return message


def _finding(
    rule: RuleSpec, severity: str, unit: UnitMetrics, path: str, message: str, source: SourceText
) -> Finding:
    span = unit.fact.span
    return Finding(
        rule_id=rule.rule_id,
        rule_version=rule.version,
        severity=severity,
        path=path,
        span=span,
        message=message,
        evidence=source.excerpt(span.line),
        confidence=CONFIDENCE_APPROXIMATE,
        status=STATUS_VIOLATION,
        remediation=rule.remediation,
        safe_autofix=False,
        scope=unit.name,
        suppression=None,
        fingerprint=None,
        baseline=None,
    )


def _graph(project: _Project, graph: CallGraph, declared: Mapping[str, str]) -> _Edges:
    edges = _Edges(project)
    edges.calls(graph)
    edges.references(_imported_targets(project, graph))
    edges.nesting(frozenset(declared))
    return edges


def _judge(project: _Project, graph: CallGraph, patterns: Sequence[str]) -> list[_Cluster]:
    """The dead clusters: what production roots do not reach, by head."""
    declared = _declared(project)
    classes = _Classes(project)
    out = _graph(project, graph, declared).out
    registered = _registered(project, classes, declared, patterns)
    tests = [k for k in project.units if project.files[project.path_of[k]].tested]
    production = set(project.units) - set(tests)
    roots = [k for k in production if project.units[k].kind in CONTAINERS or k in registered]
    families = classes.families()
    live = _alive(out, roots, families)
    tested = _alive(out, tests, families)
    called = {target for key in tests for target in out[key]}
    dead = {k for k in declared if k not in live and k in production}
    return _clusters(out, dead, (tested, called), families)


def run_dead_code(
    files: Sequence[DeadFile],
    graph: CallGraph,
    settings: Mapping[str, Any],
    libraries: Sequence[str],
) -> dict[str, list[Finding]]:
    """``libraries``: the files installed as libraries (the property-contracts runtime),
    whose functions are there to be called, not judged."""
    project = _Project(files)
    entry_points = [str(p) for p in settings[SETTING_ENTRY_POINTS]]
    patterns = [*entry_points, *(f"{p}::*" for p in libraries)]
    found: dict[str, list[Finding]] = {}
    for cluster in _judge(project, graph, patterns):
        rule, severity_key = DEAD001, SETTING_SEVERITY
        if cluster.tested:
            rule, severity_key = DEAD002, SETTING_DEAD002_SEVERITY
        path = project.path_of[cluster.head]
        f = project.files[path]
        if rule.rule_id not in f.applied:
            continue
        unit = project.units[cluster.head]
        message = _message(project, cluster)
        severity = str(settings[severity_key])
        _add_finding(found, _finding(rule, severity, unit, path, message, f.source))
    return found


def _add_finding(found: dict[str, list[Finding]], finding: Finding) -> None:
    if finding.path not in found:
        found[finding.path] = []
    found[finding.path].append(finding)
