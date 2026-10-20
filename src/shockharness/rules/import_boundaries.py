"""IMPORT002: an import across a boundary the project declared (spec 21.1 decision 44).

Each ``[[rules.import_boundaries.forbidden]]`` entry names the files it binds (the
``importers`` globs), the modules they may not import (the ``imported`` globs) and the
names they may still take from them (``allowed_names``). Every import fact of a bound
file is judged through the module graph's resolved edge for it, so a relative import,
``from pkg import mod`` and a JavaScript path all reach the file they name. An import of
the whole module (``import m``, ``import * as m``, a bare ``require``, a star or
side-effect import, a submodule imported by name) takes every name, so it is reported
whenever the entry allows only some.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from shockharness.complexity.callgraph import ModuleEdge
from shockharness.findings import CONFIDENCE_EXACT, STATUS_VIOLATION, Finding
from shockharness.globs import GlobSet, compile_globset
from shockharness.ir.model import MODULE_SCOPE, ImportFact, Span
from shockharness.rules.registry import IMPORT002
from shockharness.source import SourceText

# An imported name that stands for the whole module: "" (import m, import * as m,
# const m = require(...)) and "*" (a star import or export * from).
WHOLE_MODULE = frozenset({"", "*"})


@dataclass(frozen=True)
class BoundaryFile:
    path: str
    imports: tuple[ImportFact, ...]
    source: SourceText
    applies: bool  # IMPORT002 applies to the file


@dataclass(frozen=True)
class Boundary:
    importers: GlobSet
    imported: GlobSet
    allowed: tuple[str, ...]
    reason: str


def _boundaries(settings: Mapping[str, Any]) -> tuple[Boundary, ...]:
    return tuple(
        Boundary(
            importers=compile_globset([str(p) for p in entry["importers"]]),
            imported=compile_globset([str(p) for p in entry["imported"]]),
            allowed=tuple(str(name) for name in entry["allowed_names"]),
            reason=str(entry["reason"]),
        )
        for entry in settings["forbidden"]
    )


def _taken(fact: ImportFact, edge: ModuleEdge) -> tuple[str, ...] | None:
    """The names the import takes from the module the edge reaches; None for all of it."""
    if edge.imported != "":
        return None  # from pkg import mod: the submodule itself
    names = tuple(name for name, _local in fact.names)
    if len(names) == 0 or any(name in WHOLE_MODULE for name in names):
        return None
    return names


def _message(boundary: Boundary, edge: ModuleEdge, fact: ImportFact) -> str | None:
    """The finding's message when the import crosses the boundary, else None."""
    target = edge.target
    if target is None or not boundary.imported.matches(target):
        return None
    if len(boundary.allowed) == 0:
        return f"imports {target}, which this file may not import: {boundary.reason}"
    allowed = ", ".join(boundary.allowed)
    taken = _taken(fact, edge)
    if taken is None:
        return (
            f"imports all of {target}; only {allowed} may be imported from it here: "
            f"{boundary.reason}"
        )
    refused = [name for name in taken if name not in boundary.allowed]
    if len(refused) == 0:
        return None
    return (
        f"imports {', '.join(refused)} from {target}; only {allowed} may be imported from it "
        f"here: {boundary.reason}"
    )


def _finding(file: BoundaryFile, span: Span, message: str, severity: str) -> Finding:
    return Finding(
        rule_id=IMPORT002.rule_id,
        rule_version=IMPORT002.version,
        severity=severity,
        path=file.path,
        span=span,
        message=message,
        evidence=file.source.excerpt(span.line),
        confidence=CONFIDENCE_EXACT,
        status=STATUS_VIOLATION,
        remediation=IMPORT002.remediation,
        safe_autofix=False,
        scope=MODULE_SCOPE,
        suppression=None,
        fingerprint=None,
        baseline=None,
    )


def _crossing(
    boundaries: Sequence[Boundary], path: str, edge: ModuleEdge, fact: ImportFact
) -> str | None:
    """The message of the first boundary binding ``path`` that the import crosses."""
    for boundary in boundaries:
        if not boundary.importers.matches(path):
            continue
        message = _message(boundary, edge, fact)
        if message is not None:
            return message
    return None


def run_import002(
    files: Sequence[BoundaryFile], module_edges: Sequence[ModuleEdge], settings: Mapping[str, Any]
) -> dict[str, list[Finding]]:
    boundaries = _boundaries(settings)
    bound = {f.path: f for f in files if f.applies}
    facts = {(f.path, fact.span): fact for f in bound.values() for fact in f.imports}
    severity = str(settings["severity"])
    found: dict[str, list[Finding]] = {}
    for edge in module_edges:
        site = (edge.source, edge.span)
        if site not in facts:
            continue
        file = bound[edge.source]
        message = _crossing(boundaries, file.path, edge, facts[site])
        if message is None:
            continue
        if file.path not in found:
            found[file.path] = []
        found[file.path].append(_finding(file, edge.span, message, severity))
    return found
