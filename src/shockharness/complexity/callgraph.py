"""Call graph with confidence-classified edges, and module import edges.

Every call site of every unit is classified exactly once:

* ``resolved``: a direct call of a name that is a function or class defined in
  the same module (or nested in the calling unit), or a name bound by an
  import; the target is the unit when the imported module is among the
  analyzed files and defines that name, otherwise an external symbol.
* ``probable``: an attribute call on a known module alias (``os.path.join``,
  ``ns.helper()``), a method call on ``self``/``this`` that the enclosing
  class body defines, a static call on a module-level class, or a known
  function name passed as an argument (higher-order use).
* ``unresolved``: computed callees (``o[k]()``, ``getattr(o, n)()``,
  ``f()()``), method calls on values of unknown type (parameters, locals,
  results), unbound names, and attribute calls on ``self`` that the class
  body does not define. These are reported as unresolved, never guessed.

Builtins (Python ``builtins``, a fixed list of JavaScript globals) are resolved
to a ``builtin`` target that is excluded from fan-out. Module edges are
``resolved`` (target among the analyzed files), ``external`` (a package that is
not analyzed) or ``unresolved`` (dynamic, ambiguous, or a relative target that
is not among the analyzed files).
"""

import builtins
import posixpath
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from shockharness.complexity.metrics import UnitMetrics
from shockharness.ir.model import (
    BINDING_CLASS,
    BINDING_FUNCTION,
    BINDING_VARIABLE,
    CALL_ARGUMENT,
    CALL_ATTRIBUTE,
    CALL_DYNAMIC,
    CALL_NAME,
    CALL_NEW,
    CONFIDENCE_UNRESOLVED,
    IMPORT_DYNAMIC,
    IMPORT_MODULE,
    IMPORT_NAMES,
    IMPORT_REEXPORT,
    MODULE_SCOPE,
    CallSite,
    ImportFact,
    ModuleBinding,
    Span,
)
from shockharness.rules.registry import JAVASCRIPT, PYTHON

CONFIDENCE_RESOLVED = "resolved"
CONFIDENCE_PROBABLE = "probable"
# CONFIDENCE_UNRESOLVED is shared with the exception identities ("unresolved").
CONFIDENCE_EXTERNAL = "external"

TARGET_UNIT = "unit"
TARGET_EXTERNAL = "external"
TARGET_BUILTIN = "builtin"
TARGET_UNRESOLVED = "unresolved"

EDGE_CALL = "call"
EDGE_ARGUMENT = "argument"
EDGE_NEW = "new"

CONFIDENCE_DESCRIPTIONS: Mapping[str, str] = {
    CONFIDENCE_RESOLVED: (
        "direct call of a function or class defined in the module, nested in the caller, "
        "or bound by an import (target unit when the module is analyzed, external symbol "
        "otherwise)"
    ),
    CONFIDENCE_PROBABLE: (
        "attribute call on a known module alias, method call on self/this that the class "
        "body defines, static call on a module-level class, or a known function passed as "
        "an argument; the binding is not proven"
    ),
    CONFIDENCE_UNRESOLVED: (
        "computed callee, method call on a value of unknown type, unbound name, or an "
        "attribute of self/this the class body does not define; never counted as a target"
    ),
}

PYTHON_BUILTINS: frozenset[str] = frozenset(dir(builtins))
JAVASCRIPT_GLOBALS: frozenset[str] = frozenset(
    {
        "Array",
        "ArrayBuffer",
        "BigInt",
        "Boolean",
        "Buffer",
        "DataView",
        "Date",
        "Error",
        "EvalError",
        "Function",
        "Intl",
        "JSON",
        "Map",
        "Math",
        "Number",
        "Object",
        "Promise",
        "Proxy",
        "RangeError",
        "ReferenceError",
        "Reflect",
        "RegExp",
        "Set",
        "String",
        "Symbol",
        "SyntaxError",
        "TypeError",
        "URIError",
        "URL",
        "URLSearchParams",
        "WeakMap",
        "WeakRef",
        "WeakSet",
        "console",
        "process",
        "globalThis",
        "window",
        "document",
        "navigator",
        "fetch",
        "setTimeout",
        "setInterval",
        "setImmediate",
        "clearTimeout",
        "clearInterval",
        "clearImmediate",
        "queueMicrotask",
        "structuredClone",
        "parseInt",
        "parseFloat",
        "isNaN",
        "isFinite",
        "encodeURIComponent",
        "decodeURIComponent",
        "encodeURI",
        "decodeURI",
        "atob",
        "btoa",
        "require",
        "AbortController",
        "TextEncoder",
        "TextDecoder",
        "Blob",
        "FormData",
        "Headers",
        "Request",
        "Response",
        "Event",
        "EventTarget",
        "crypto",
        "performance",
    }
)
JAVASCRIPT_EXTENSIONS = (".js", ".mjs", ".cjs")
JAVASCRIPT_INDEXES = tuple(f"/index{ext}" for ext in JAVASCRIPT_EXTENSIONS)
PYTHON_INIT = "/__init__.py"
# A JavaScript default import binds the module's default export; attribute calls on it are
# reported against the module (``lodash.map``), not against a member named "default".
DEFAULT_EXPORT = "default"
PYTHON_SUFFIX = ".py"


@dataclass(frozen=True)
class Target:
    kind: str  # unit / external / builtin / unresolved
    identifier: str  # unit key, symbol, or callee text

    def to_json_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "id": self.identifier}


@dataclass(frozen=True)
class CallEdge:
    source: str  # unit key
    target: Target
    confidence: str
    kind: str  # call / argument / new
    calls: int
    span: Span  # first call site
    reason: str

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "from": self.source,
            "to": self.target.to_json_dict(),
            "confidence": self.confidence,
            "kind": self.kind,
            "calls": self.calls,
            "span": self.span.to_json_dict(),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ModuleEdge:
    source: str  # path
    specifier: str
    level: int  # Python relative-import level (0 for absolute imports and JavaScript)
    kind: str
    imported: str  # the imported name when it is itself a submodule, else ""
    target: str | None  # resolved path
    confidence: str  # resolved / external / unresolved
    span: Span
    reason: str

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "from": self.source,
            "specifier": self.specifier,
            "level": self.level,
            "kind": self.kind,
            "imported": self.imported,
            "to": self.target,
            "confidence": self.confidence,
            "span": self.span.to_json_dict(),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ModuleInput:
    path: str
    language: str
    units: tuple[UnitMetrics, ...]
    imports: tuple[ImportFact, ...]
    bindings: tuple[ModuleBinding, ...]


@dataclass(frozen=True)
class _ImportBinding:
    specifier: str
    level: int
    imported: str  # "" for a whole-module binding
    kind: str


class _ModuleIndex:
    """Where each analyzed module lives, for import resolution in both languages.

    A Python module's absolute name starts at the first directory on its path that is a
    package (its ``__init__.py`` is among the analyzed files): ``src/pkg/mod.py`` with
    ``src/pkg/__init__.py`` is ``pkg.mod``; a file in no package is just its basename.
    Names are never matched by suffix, so ``import json`` is external even when an
    analyzed file is called ``json.py``.
    """

    def __init__(self, modules: Sequence[ModuleInput]) -> None:
        self.paths: frozenset[str] = frozenset(m.path for m in modules)
        packages: set[str] = set()
        for path in self.paths:
            if path.endswith(PYTHON_INIT) or path == "__init__.py":
                packages.add(path[: len(path) - len("__init__.py")].rstrip("/"))
        self.by_dotted: dict[str, str] = {}
        for module in modules:
            if module.language != PYTHON:
                continue
            for name in _python_module_names(module.path, packages):
                if name not in self.by_dotted:
                    self.by_dotted[name] = module.path

    def python_absolute(self, dotted: str) -> tuple[str | None, str, str]:
        """(path, confidence, reason) for an absolute Python module name."""
        if dotted in self.by_dotted:
            return (
                self.by_dotted[dotted],
                CONFIDENCE_RESOLVED,
                "module name matches an analyzed file",
            )
        return None, CONFIDENCE_EXTERNAL, "not among the analyzed files"

    def python_relative(
        self, importer: str, level: int, module: str
    ) -> tuple[str | None, str, str]:
        parts = importer.split("/")
        base_parts = parts[: len(parts) - 1]
        up = level - 1
        if up > len(base_parts):
            return None, CONFIDENCE_UNRESOLVED, "relative import climbs above the analysis root"
        if up > 0:
            base_parts = base_parts[: len(base_parts) - up]
        target_parts = list(base_parts)
        if module != "":
            target_parts.extend(module.split("."))
        target = "/".join(target_parts)
        for candidate in (target + PYTHON_SUFFIX, target + PYTHON_INIT):
            if candidate in self.paths:
                return (
                    candidate,
                    CONFIDENCE_RESOLVED,
                    "relative import resolved to an analyzed file",
                )
        if target == "" and "__init__.py" in self.paths:
            return "__init__.py", CONFIDENCE_RESOLVED, "relative import of the package itself"
        return None, CONFIDENCE_UNRESOLVED, "relative import target is not among the analyzed files"

    def javascript(self, importer: str, specifier: str) -> tuple[str | None, str, str]:
        if not (specifier.startswith(".") or specifier.startswith("/")):
            return None, CONFIDENCE_EXTERNAL, "bare specifier: a package, not an analyzed file"
        base = posixpath.dirname(importer)
        joined = posixpath.normpath(posixpath.join(base, specifier))
        if joined.startswith("/"):
            joined = joined.lstrip("/")
        candidates = [joined, *[joined + ext for ext in JAVASCRIPT_EXTENSIONS]]
        candidates.extend(joined + index for index in JAVASCRIPT_INDEXES)
        for candidate in candidates:
            if candidate in self.paths:
                return (
                    candidate,
                    CONFIDENCE_RESOLVED,
                    "relative specifier resolved to an analyzed file",
                )
        return (
            None,
            CONFIDENCE_UNRESOLVED,
            "relative specifier is not among the analyzed files (another extension, or excluded)",
        )


def _edge(
    module: ModuleInput,
    fact: ImportFact,
    specifier: str,
    imported: str,
    resolved: tuple[str | None, str, str],
) -> ModuleEdge:
    target, confidence, reason = resolved
    return ModuleEdge(
        module.path,
        specifier,
        fact.level,
        fact.kind,
        imported,
        target,
        confidence,
        fact.span,
        reason,
    )


def _python_module_names(path: str, packages: set[str]) -> list[str]:
    """The absolute names an analyzed Python file answers to (canonical name first)."""
    parts = path.split("/")
    basename = parts[len(parts) - 1]
    directories = parts[: len(parts) - 1]
    if basename.endswith(PYTHON_SUFFIX):
        basename = basename[: len(basename) - len(PYTHON_SUFFIX)]
    module_parts = [] if basename == "__init__" else [basename]
    start = len(directories)
    for depth in range(len(directories)):
        if "/".join(directories[: depth + 1]) in packages:
            start = depth
            break
    canonical = ".".join([*directories[start:], *module_parts])
    names = [canonical] if canonical != "" else []
    full = ".".join([*directories, *module_parts])
    if full != "" and full != canonical:
        names.append(full)
    return names


def resolve_module_edges(
    index: _ModuleIndex, module: ModuleInput, fact: ImportFact
) -> list[ModuleEdge]:
    """One edge per import fact, plus one per imported name that is itself a submodule
    (``from pkg import mod`` / ``from . import mod``) among the analyzed files."""
    if fact.kind == IMPORT_DYNAMIC:
        return [
            ModuleEdge(
                module.path,
                fact.module,
                fact.level,
                fact.kind,
                "",
                None,
                CONFIDENCE_UNRESOLVED,
                fact.span,
                "computed import target",
            )
        ]
    if module.language == JAVASCRIPT:
        return [_edge(module, fact, fact.module, "", index.javascript(module.path, fact.module))]
    specifier = "." * fact.level + fact.module
    if fact.level > 0:
        resolved = index.python_relative(module.path, fact.level, fact.module)
    else:
        resolved = index.python_absolute(fact.module)
    package_edge = _edge(module, fact, specifier, "", resolved)
    if fact.kind != IMPORT_NAMES:
        return [package_edge]
    submodules: list[ModuleEdge] = []
    for imported, _local in fact.names:
        if imported == "*":
            continue
        child = f"{fact.module}.{imported}" if fact.module != "" else imported
        if fact.level > 0:
            candidate = index.python_relative(module.path, fact.level, child)
        else:
            candidate = index.python_absolute(child)
        if candidate[0] is not None:
            submodules.append(_edge(module, fact, specifier, imported, candidate))
    if len(submodules) > 0 and len(submodules) == len([n for n, _l in fact.names if n != "*"]):
        # ``from pkg import mod``: a dependency on the submodule, not on the package facade
        return submodules
    return [package_edge, *submodules]


@dataclass(frozen=True)
class _Scope:
    """Per-module lookup tables built once."""

    units_by_name: Mapping[str, str]  # qualified unit name -> key
    functions: frozenset[str]  # module-level function / class names
    imports: Mapping[str, _ImportBinding]  # local name -> import
    variables: frozenset[str]  # module-level variable names
    module_edges: Mapping[tuple[str, int, str], ModuleEdge]  # (specifier, level, imported)


def _scope_for(module: ModuleInput, edges: Sequence[ModuleEdge]) -> _Scope:
    units_by_name = {u.name: u.key for u in module.units}
    functions: set[str] = set()
    variables: set[str] = set()
    for binding in module.bindings:
        if binding.kind in (BINDING_FUNCTION, BINDING_CLASS):
            functions.add(binding.name)
        elif binding.kind == BINDING_VARIABLE:
            variables.add(binding.name)
    imports: dict[str, _ImportBinding] = {}
    for fact in module.imports:
        if fact.kind in (IMPORT_REEXPORT, IMPORT_DYNAMIC):
            continue
        for imported, local in fact.names:
            if local == "" or local == "*":
                continue
            if fact.kind == IMPORT_MODULE:
                imports[local] = _ImportBinding(fact.module, fact.level, "", fact.kind)
            else:
                imports[local] = _ImportBinding(fact.module, fact.level, imported, fact.kind)
    edge_map: dict[tuple[str, int, str], ModuleEdge] = {}
    for edge in edges:
        key = (edge.specifier, edge.level, edge.imported)
        if key not in edge_map:
            edge_map[key] = edge
    return _Scope(units_by_name, frozenset(functions), imports, frozenset(variables), edge_map)


@dataclass(frozen=True)
class _Resolution:
    target: Target
    confidence: str
    reason: str


def _builtins_for(language: str) -> frozenset[str]:
    if language == PYTHON:
        return PYTHON_BUILTINS
    return JAVASCRIPT_GLOBALS


class _Resolver:
    def __init__(self, modules: Sequence[ModuleInput], scopes: Mapping[str, _Scope]) -> None:
        self.scopes = scopes
        self.units_by_path: dict[str, Mapping[str, str]] = {
            path: scope.units_by_name for path, scope in scopes.items()
        }
        self.languages = {m.path: m.language for m in modules}

    def _imported(
        self, binding: _ImportBinding, scope: _Scope, attribute: str | None
    ) -> _Resolution:
        """A call through an import binding; ``attribute`` is the member called on a module."""
        qualified_module = "." * binding.level + binding.specifier
        edge: ModuleEdge | None = None
        submodule_key = (qualified_module, binding.level, binding.imported)
        module_key = (qualified_module, binding.level, "")
        if binding.imported != "" and submodule_key in scope.module_edges:
            # ``from pkg import mod`` then ``mod.f()``: the binding is the submodule itself
            edge = scope.module_edges[submodule_key]
            if attribute is None:
                return _Resolution(
                    Target(TARGET_UNRESOLVED, qualified_module + "." + binding.imported),
                    CONFIDENCE_UNRESOLVED,
                    "a module binding is not callable",
                )
            units = self.units_by_path[str(edge.target)]
            if attribute in units:
                return _Resolution(
                    Target(TARGET_UNIT, units[attribute]),
                    CONFIDENCE_PROBABLE,
                    "attribute call on an imported submodule",
                )
            return _Resolution(
                Target(TARGET_EXTERNAL, f"{edge.target}::{attribute}"),
                CONFIDENCE_PROBABLE,
                "attribute call on an imported submodule that does not define this name",
            )
        if module_key in scope.module_edges:
            edge = scope.module_edges[module_key]
        # The name looked up in the target module: the imported name, the attribute called
        # on a whole-module alias, or ``Imported.attribute`` for a call through an import.
        lookup = binding.imported
        if attribute is not None:
            lookup = attribute
            if binding.imported not in ("", DEFAULT_EXPORT):
                lookup = f"{binding.imported}.{attribute}"
        symbol = qualified_module
        if lookup != "":
            symbol = f"{qualified_module}.{lookup}"
        confidence = CONFIDENCE_PROBABLE
        if attribute is None:
            confidence = CONFIDENCE_RESOLVED
        if edge is not None and edge.target is not None:
            units = self.units_by_path[edge.target]
            if lookup in units:
                return _Resolution(
                    Target(TARGET_UNIT, units[lookup]),
                    confidence,
                    "imported from an analyzed module",
                )
            return _Resolution(
                Target(TARGET_EXTERNAL, f"{edge.target}::{lookup}"),
                CONFIDENCE_PROBABLE,
                "imported module is analyzed but does not define this name (re-export or value)",
            )
        if edge is not None and edge.confidence == CONFIDENCE_UNRESOLVED:
            return _Resolution(
                Target(TARGET_UNRESOLVED, symbol), CONFIDENCE_UNRESOLVED, edge.reason
            )
        return _Resolution(
            Target(TARGET_EXTERNAL, symbol), confidence, "imported from an external module"
        )

    def resolve_name(self, path: str, unit: UnitMetrics, name: str) -> _Resolution | None:
        """A bare name that is called or passed. ``None`` for a plain local/variable argument."""
        scope = self.scopes[path]
        nested = f"{unit.name}.{name}" if unit.name != MODULE_SCOPE else name
        if nested in scope.units_by_name and nested != unit.name:
            return _Resolution(
                Target(TARGET_UNIT, scope.units_by_name[nested]),
                CONFIDENCE_RESOLVED,
                "defined in the calling unit",
            )
        fact = unit.fact
        if name in fact.locals and name not in fact.globals_declared:
            return _Resolution(
                Target(TARGET_UNRESOLVED, name),
                CONFIDENCE_UNRESOLVED,
                "a parameter or local binding; its value is not known statically",
            )
        if name in scope.functions and name in scope.units_by_name:
            return _Resolution(
                Target(TARGET_UNIT, scope.units_by_name[name]),
                CONFIDENCE_RESOLVED,
                "defined at module level",
            )
        if name in scope.imports:
            binding = scope.imports[name]
            if binding.imported == "":
                return _Resolution(
                    Target(TARGET_UNRESOLVED, name),
                    CONFIDENCE_UNRESOLVED,
                    "a whole-module import is not callable",
                )
            return self._imported(binding, scope, None)
        if name in scope.variables:
            return _Resolution(
                Target(TARGET_UNRESOLVED, name),
                CONFIDENCE_UNRESOLVED,
                "a module-level variable, not a definition",
            )
        if name in _builtins_for(self.languages[path]):
            return _Resolution(Target(TARGET_BUILTIN, name), CONFIDENCE_RESOLVED, "builtin")
        return _Resolution(Target(TARGET_UNRESOLVED, name), CONFIDENCE_UNRESOLVED, "unbound name")

    def resolve_attribute(
        self, path: str, unit: UnitMetrics, dotted: str, receiver_self: bool
    ) -> _Resolution:
        scope = self.scopes[path]
        parts = dotted.split(".")
        root = parts[0]
        rest = parts[1:]
        if receiver_self:
            if unit.fact.class_name is None:
                return _Resolution(
                    Target(TARGET_UNRESOLVED, dotted),
                    CONFIDENCE_UNRESOLVED,
                    "receiver call outside a class body",
                )
            method = f"{unit.fact.class_name}.{rest[0]}" if len(rest) == 1 else None
            if method is not None and method in scope.units_by_name:
                return _Resolution(
                    Target(TARGET_UNIT, scope.units_by_name[method]),
                    CONFIDENCE_PROBABLE,
                    "method defined in the enclosing class body; overriding is not ruled out",
                )
            return _Resolution(
                Target(TARGET_UNRESOLVED, dotted),
                CONFIDENCE_UNRESOLVED,
                "attribute of the receiver that the class body does not define "
                "(inherited, assigned, or dynamic)",
            )
        fact = unit.fact
        if root in fact.locals and root not in fact.globals_declared:
            return _Resolution(
                Target(TARGET_UNRESOLVED, dotted),
                CONFIDENCE_UNRESOLVED,
                "method call on a parameter or local value of unknown type",
            )
        if root in scope.imports:
            binding = scope.imports[root]
            return self._imported(binding, scope, ".".join(rest))
        if root in scope.functions:
            static = ".".join([root, *rest])
            if static in scope.units_by_name:
                return _Resolution(
                    Target(TARGET_UNIT, scope.units_by_name[static]),
                    CONFIDENCE_PROBABLE,
                    "static call on a module-level class",
                )
            return _Resolution(
                Target(TARGET_UNRESOLVED, dotted),
                CONFIDENCE_UNRESOLVED,
                "attribute of a module-level definition that is not itself defined",
            )
        if root in scope.variables:
            return _Resolution(
                Target(TARGET_UNRESOLVED, dotted),
                CONFIDENCE_UNRESOLVED,
                "method call on a module-level value of unknown type",
            )
        if root in _builtins_for(self.languages[path]):
            return _Resolution(Target(TARGET_BUILTIN, dotted), CONFIDENCE_RESOLVED, "builtin")
        return _Resolution(
            Target(TARGET_UNRESOLVED, dotted),
            CONFIDENCE_UNRESOLVED,
            "receiver of unknown type",
        )


def _classify(
    resolver: _Resolver, path: str, unit: UnitMetrics, call: CallSite
) -> tuple[_Resolution, str] | None:
    """(resolution, edge kind) for one call site; ``None`` when the site is not an edge."""
    if call.shape == CALL_DYNAMIC:
        return (
            _Resolution(
                Target(TARGET_UNRESOLVED, call.callee), CONFIDENCE_UNRESOLVED, "computed callee"
            ),
            EDGE_CALL,
        )
    if call.shape == CALL_NAME:
        resolution = resolver.resolve_name(path, unit, call.callee)
        assert resolution is not None
        return resolution, EDGE_CALL
    if call.shape == CALL_ATTRIBUTE:
        return resolver.resolve_attribute(path, unit, call.callee, call.receiver_self), EDGE_CALL
    if call.shape == CALL_NEW:
        if "." in call.callee:
            return resolver.resolve_attribute(path, unit, call.callee, False), EDGE_NEW
        resolution = resolver.resolve_name(path, unit, call.callee)
        assert resolution is not None
        return resolution, EDGE_NEW
    assert call.shape == CALL_ARGUMENT
    resolution = resolver.resolve_name(path, unit, call.callee)
    if resolution is None or resolution.target.kind in (TARGET_UNRESOLVED, TARGET_BUILTIN):
        return None
    return (
        _Resolution(
            resolution.target,
            CONFIDENCE_PROBABLE,
            "function passed as an argument (higher-order use); whether it is called is not known",
        ),
        EDGE_ARGUMENT,
    )


@dataclass(frozen=True)
class CallGraph:
    edges: tuple[CallEdge, ...]
    module_edges: tuple[ModuleEdge, ...]
    unit_keys: tuple[str, ...]
    paths: tuple[str, ...]


def build_call_graph(modules: Sequence[ModuleInput]) -> CallGraph:
    ordered = sorted(modules, key=lambda m: m.path)
    index = _ModuleIndex(ordered)
    module_edges: list[ModuleEdge] = []
    per_module_edges: dict[str, list[ModuleEdge]] = {}
    for module in ordered:
        edges = [e for fact in module.imports for e in resolve_module_edges(index, module, fact)]
        per_module_edges[module.path] = edges
        module_edges.extend(edges)
    scopes = {m.path: _scope_for(m, per_module_edges[m.path]) for m in ordered}
    resolver = _Resolver(ordered, scopes)
    aggregated: dict[tuple[str, str, str, str, str], tuple[int, Span, str]] = {}
    unit_keys: list[str] = []
    for module in ordered:
        for unit in module.units:
            unit_keys.append(unit.key)
            for call in unit.fact.calls:
                classified = _classify(resolver, module.path, unit, call)
                if classified is None:
                    continue
                resolution, edge_kind = classified
                key = (
                    unit.key,
                    resolution.target.kind,
                    resolution.target.identifier,
                    resolution.confidence,
                    edge_kind,
                )
                if key in aggregated:
                    count, first, reason = aggregated[key]
                    aggregated[key] = (count + 1, min(first, call.span), reason)
                else:
                    aggregated[key] = (1, call.span, resolution.reason)
    edges: list[CallEdge] = []
    for (source, kind, identifier, confidence, edge_kind), (
        count,
        span,
        reason,
    ) in aggregated.items():
        edges.append(
            CallEdge(source, Target(kind, identifier), confidence, edge_kind, count, span, reason)
        )
    edges.sort(key=lambda e: (e.source, e.span, e.target.kind, e.target.identifier, e.kind))
    return CallGraph(
        edges=tuple(edges),
        module_edges=tuple(module_edges),
        unit_keys=tuple(unit_keys),
        paths=tuple(m.path for m in ordered),
    )


__all__ = [
    "CONFIDENCE_DESCRIPTIONS",
    "CONFIDENCE_EXTERNAL",
    "CONFIDENCE_PROBABLE",
    "CONFIDENCE_RESOLVED",
    "CONFIDENCE_UNRESOLVED",
    "CallEdge",
    "CallGraph",
    "ModuleEdge",
    "ModuleInput",
    "Target",
    "build_call_graph",
]
