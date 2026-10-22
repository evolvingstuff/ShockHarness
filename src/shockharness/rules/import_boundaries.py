"""IMPORT002: an import across a boundary the project declared (spec 21.1 decision 44).

Each ``[[rules.import_boundaries.forbidden]]`` entry names the files it binds (the
``importers`` globs, less the ``allowed_importers`` globs), what they may not import
(project files by path, the ``imported`` globs; other modules by name, ``modules``) and
the names they may still take from it (``allowed_names``). Every import fact of a bound
file is judged through the module graph's edge for it. An edge that resolves to an
analyzed file is matched by path, so a relative import, ``from pkg import mod`` and a
JavaScript path all reach the file they name. An external edge (a package or the standard
library) is matched by name: the named module or any submodule (``cryptography.hazmat``
covers ``cryptography.hazmat.primitives``, and ``from cryptography import hazmat``), a
JavaScript package and its paths (``fs`` covers ``fs/promises``; ``node:`` is ignored). An
import of the whole module (``import m``, ``import * as m``, a bare ``require``, a star or
side-effect import, a submodule imported by name) takes every name, so it is reported
whenever the entry allows only some.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from shockharness.complexity.callgraph import CONFIDENCE_EXTERNAL, ModuleEdge
from shockharness.findings import CONFIDENCE_EXACT, STATUS_VIOLATION, Finding
from shockharness.globs import GlobSet, compile_globset
from shockharness.ir.model import IMPORT_NAMES, MODULE_SCOPE, ImportFact, Span
from shockharness.rules.registry import IMPORT002, JAVASCRIPT_FAMILY
from shockharness.schema import forbidden_import_entry
from shockharness.source import SourceText

# An imported name that stands for the whole module: "" (import m, import * as m,
# const m = require(...)) and "*" (a star import or export * from).
WHOLE_MODULE = frozenset({"", "*"})
# Node's built-in modules answer to both spellings: "fs" and "node:fs".
NODE_PREFIX = "node:"
PYTHON_SEPARATOR = "."
JAVASCRIPT_SEPARATOR = "/"


@dataclass(frozen=True)
class BoundaryFile:
    path: str
    imports: tuple[ImportFact, ...]
    source: SourceText
    applies: bool  # IMPORT002 applies to the file
    language: str


@dataclass(frozen=True)
class Boundary:
    importers: GlobSet
    exempt: GlobSet
    exempt_patterns: tuple[str, ...]  # allowed_importers as written, for the message
    imported: GlobSet
    modules: tuple[str, ...]  # without the node: prefix
    allowed: tuple[str, ...]
    reason: str


def _boundary(raw: Mapping[str, Any]) -> Boundary:
    entry = forbidden_import_entry(raw)
    exempt = [str(p) for p in entry["allowed_importers"]]
    return Boundary(
        importers=compile_globset([str(p) for p in entry["importers"]]),
        exempt=compile_globset(exempt),
        exempt_patterns=tuple(exempt),
        imported=compile_globset([str(p) for p in entry["imported"]]),
        modules=tuple(str(name).removeprefix(NODE_PREFIX) for name in entry["modules"]),
        allowed=tuple(str(name) for name in entry["allowed_names"]),
        reason=str(entry["reason"]),
    )


def _boundaries(settings: Mapping[str, Any]) -> tuple[Boundary, ...]:
    return tuple(_boundary(entry) for entry in settings["forbidden"])


def _taken(fact: ImportFact, edge: ModuleEdge) -> tuple[str, ...] | None:
    """The names the import takes from the module the edge reaches; None for all of it."""
    if edge.imported != "":
        return None  # from pkg import mod: the submodule itself
    names = tuple(name for name, _local in fact.names)
    if len(names) == 0 or any(name in WHOLE_MODULE for name in names):
        return None
    return names


def _names(modules: Sequence[str], module: str, separator: str) -> bool:
    """Whether ``module`` is one of ``modules`` or below one of them."""
    return any(module == name or module.startswith(name + separator) for name in modules)


def _named_module(
    boundary: Boundary, edge: ModuleEdge, fact: ImportFact, language: str
) -> tuple[str, tuple[str, ...] | None] | None:
    """(the module, the names taken from it or None for all) when an external import
    reaches a module the entry names."""
    if language in JAVASCRIPT_FAMILY:
        package = edge.specifier.removeprefix(NODE_PREFIX)
        if _names(boundary.modules, package, JAVASCRIPT_SEPARATOR):
            return package, _taken(fact, edge)
        return None
    if _names(boundary.modules, edge.specifier, PYTHON_SEPARATOR):
        return edge.specifier, _taken(fact, edge)
    if fact.kind != IMPORT_NAMES:
        return None
    for name, _local in fact.names:
        submodule = f"{edge.specifier}{PYTHON_SEPARATOR}{name}"
        if _names(boundary.modules, submodule, PYTHON_SEPARATOR):
            return submodule, None  # from pkg import mod: the submodule itself
    return None


def _reached(
    boundary: Boundary, edge: ModuleEdge, fact: ImportFact, language: str
) -> tuple[str, tuple[str, ...] | None] | None:
    """(what the import reaches, the names taken from it or None for all) when the entry
    forbids it: an analyzed file by path, an external module by name."""
    if edge.target is not None:
        if boundary.imported.matches(edge.target):
            return edge.target, _taken(fact, edge)
        return None
    if edge.confidence != CONFIDENCE_EXTERNAL:
        return None
    return _named_module(boundary, edge, fact, language)


def _message(boundary: Boundary, edge: ModuleEdge, fact: ImportFact, language: str) -> str | None:
    """The finding's message when the import crosses the boundary, else None."""
    reached = _reached(boundary, edge, fact, language)
    if reached is None:
        return None
    target, taken = reached
    if len(boundary.allowed) == 0 and len(boundary.exempt_patterns) > 0:
        only = ", ".join(boundary.exempt_patterns)
        return f"imports {target}, which only {only} may import: {boundary.reason}"
    if len(boundary.allowed) == 0:
        return f"imports {target}, which this file may not import: {boundary.reason}"
    allowed = ", ".join(boundary.allowed)
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
    boundaries: Sequence[Boundary], file: BoundaryFile, edge: ModuleEdge, fact: ImportFact
) -> str | None:
    """The message of the first boundary binding the file that the import crosses."""
    for boundary in boundaries:
        if not boundary.importers.matches(file.path) or boundary.exempt.matches(file.path):
            continue
        message = _message(boundary, edge, fact, file.language)
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
        message = _crossing(boundaries, file, edge, facts[site])
        if message is None:
            continue
        if file.path not in found:
            found[file.path] = []
        found[file.path].append(_finding(file, edge.span, message, severity))
    return found
