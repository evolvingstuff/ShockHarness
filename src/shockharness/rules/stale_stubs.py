"""VERIFY005: a test's stub that the code the test calls no longer reaches.

Each patch of project code (``ir/python_stubs.py``) is resolved to the functions it
replaces: through the test file's imports for ``monkeypatch.setattr(module, "name")`` and
``patch.object(Class, "name")``, and through the project's module names for the dotted
form (``patch("pkg.mod.name")``). The tests that run the patch are the test it is in,
the tests that reach the helper it is in, and the tests that take the fixture it is in as
a parameter. When none of them reaches what the patch replaces (by the dead-code rules'
edges: calls, same-name fallbacks, value references, nesting), the stub is stale: the
code under test calls something else, so the test runs real code it meant to stub out,
or stubs nothing. A tripwire (a stub there to be not called) is never reported.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

from shockharness.complexity.callgraph import CallGraph
from shockharness.complexity.metrics import UnitMetrics
from shockharness.findings import CONFIDENCE_APPROXIMATE, STATUS_VIOLATION, Finding
from shockharness.ir.model import MODULE_SCOPE, ImportFact, StubFacts, StubPatch
from shockharness.rules.dead_code import DeadFile, Project, reach_from, reachability
from shockharness.rules.defaults import module_names
from shockharness.rules.registry import VERIFY005
from shockharness.rules.severity import section_severity

LISTED = 3  # tests named in a message; the rest are counted
PYTHON_SUFFIX = ".py"
PACKAGE_INIT = "/__init__.py"


@dataclass(frozen=True)
class StubFile:
    dead: DeadFile  # the file as the reachability sees it
    stubs: StubFacts
    applied: bool  # VERIFY005 applies to the file


K = TypeVar("K")
V = TypeVar("V")


def _append(table: dict[K, list[V]], key: K, value: V) -> None:
    if key not in table:
        table[key] = []
    table[key].append(value)


def _final(dotted: str) -> tuple[str, str]:
    head, _dot, last = dotted.rpartition(".")
    return head, last


class _Resolver:
    """Which project functions a patch replaces."""

    def __init__(
        self, files: Sequence[StubFile], graph: CallGraph, units: Mapping[str, UnitMetrics]
    ) -> None:
        self.module_path = {name: f.dead.path for f in files for name in module_names(f.dead.path)}
        self.by_name: dict[tuple[str, str], list[str]] = {}
        for key, unit in units.items():
            _append(self.by_name, (unit.path, unit.name), key)
        self.import_targets: dict[tuple[str, int, int], list[str]] = {}
        for edge in graph.module_edges:
            if edge.target is not None:
                site = (edge.source, edge.span.line, edge.span.column)
                _append(self.import_targets, site, edge.target)

    def _bindings(self, path: str, imports: Sequence[ImportFact]) -> dict[str, tuple[str, str]]:
        """A local name to (the file it imports from, the name it imports; "" for the
        module itself)."""
        found: dict[str, tuple[str, str]] = {}
        for fact in imports:
            key = (path, fact.span.line, fact.span.column)
            if key not in self.import_targets:
                continue
            for target in self.import_targets[key]:
                for imported, local in fact.names:
                    found[local] = (target, imported)
        return found

    def _is_module(self, path: str, imported: str) -> bool:
        """``from pkg import mod``: the name is the submodule the import resolved to."""
        _head, final = _final(imported)
        endings = ("/" + final + PYTHON_SUFFIX, "/" + final + PACKAGE_INIT)
        return path.endswith(endings)

    def _dotted(self, dotted: str) -> tuple[str, str] | None:
        module, name = _final(dotted)
        if module in self.module_path:
            return (self.module_path[module], name)
        outer, owner = _final(module)
        if outer in self.module_path:
            return (self.module_path[outer], f"{owner}.{name}")
        return None

    def site(self, file: StubFile, patch: StubPatch) -> tuple[str, str] | None:
        """(file, qualified name) of what the patch replaces; None when it is not a name
        in an analyzed module."""
        if patch.target == "":
            return self._dotted(patch.attribute)
        if patch.target in self.module_path:
            return (self.module_path[patch.target], patch.attribute)
        root, _dot, rest = patch.target.partition(".")
        bindings = self._bindings(file.dead.path, file.dead.imports)
        if root not in bindings or rest != "":
            return None
        path, imported = bindings[root]
        if imported == "" or self._is_module(path, imported):
            return (path, patch.attribute)
        return (path, f"{imported}.{patch.attribute}")


class _Runs:
    """Which tests run a patch, and what each test reaches."""

    def __init__(
        self, files: Sequence[StubFile], project_at: Mapping[tuple[str, int, int], str]
    ) -> None:
        self.tests: dict[str, tuple[str, ...]] = {}
        self.fixtures: dict[str, list[str]] = {}
        for f in files:
            for line, column, parameters in f.stubs.tests:
                at = (f.dead.path, line, column)
                if at in project_at:
                    self.tests[project_at[at]] = parameters
            for line, column, name in f.stubs.fixtures:
                at = (f.dead.path, line, column)
                if at in project_at:
                    _append(self.fixtures, name, project_at[at])
        self.reached: dict[str, set[str]] = {}

    def reach(self, out: Mapping[str, set[str]], test: str) -> set[str]:
        if test not in self.reached:
            self.reached[test] = reach_from(out, test)
        return self.reached[test]

    def runners(self, out: Mapping[str, set[str]], holder: str) -> list[str]:
        found = [t for t in self.tests if t == holder or holder in self.reach(out, t)]
        for test, parameters in self.tests.items():
            fixtures = [k for p in parameters if p in self.fixtures for k in self.fixtures[p]]
            if holder in fixtures and test not in found:
                found.append(test)
        return found


def _finding(file: StubFile, patch: StubPatch, message: str, severity: str) -> Finding:
    return Finding(
        rule_id=VERIFY005.rule_id,
        rule_version=VERIFY005.version,
        severity=severity,
        path=file.dead.path,
        span=patch.span,
        message=message,
        evidence=file.dead.source.excerpt(patch.span.line),
        confidence=CONFIDENCE_APPROXIMATE,
        status=STATUS_VIOLATION,
        remediation=VERIFY005.remediation,
        safe_autofix=False,
        scope=MODULE_SCOPE,
        suppression=None,
        fingerprint=None,
        baseline=None,
    )


def _message(target: UnitMetrics, tests: Sequence[UnitMetrics]) -> str:
    names = ", ".join(t.name for t in tests[:LISTED])
    if len(tests) > LISTED:
        names += f" and {len(tests) - LISTED} more"
    return (
        f"the stub replaces {target.name} ({target.path}), which the code {names} calls no "
        "longer reaches: the test runs the code it meant to stub out, or stubs nothing"
    )


@dataclass(frozen=True)
class _Judge:
    project: Project
    out: Mapping[str, set[str]]
    resolver: _Resolver
    runs: _Runs

    def stale(self, file: StubFile, patch: StubPatch) -> str | None:
        """The finding's message when the patch is stale, else None."""
        holder_at = (file.dead.path, patch.holder_line, patch.holder_column)
        if patch.tripwire or holder_at not in self.project.at:
            return None
        site = self.resolver.site(file, patch)
        if site is None or site not in self.resolver.by_name:
            return None  # not a function of the analyzed project
        targets = self.resolver.by_name[site]
        runners = self.runs.runners(self.out, self.project.at[holder_at])
        if len(runners) == 0:
            return None  # no test is seen to run it: nothing to judge
        if any(t in self.runs.reach(self.out, r) for r in runners for t in targets):
            return None
        tests = [self.project.units[r] for r in sorted(runners)]
        return _message(self.project.units[targets[0]], tests)


def run_stale_stubs(
    files: Sequence[StubFile], graph: CallGraph, settings: Mapping[str, Any]
) -> dict[str, list[Finding]]:
    project, out = reachability([f.dead for f in files], graph)
    judge = _Judge(project, out, _Resolver(files, graph, project.units), _Runs(files, project.at))
    severity = section_severity(settings, VERIFY005.default_severity)
    found: dict[str, list[Finding]] = {}
    for f in files:
        if not f.applied:
            continue
        for patch in f.stubs.patches:
            message = judge.stale(f, patch)
            if message is not None:
                _append(found, f.dead.path, _finding(f, patch, message, severity))
    return found
