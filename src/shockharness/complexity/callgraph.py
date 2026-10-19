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
    ReceiverClass,
    ReceiverFacts,
    ReceiverObject,
    Span,
)
from shockharness.rules.registry import CSHARP, JAVASCRIPT_FAMILY, PYTHON

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
        "otherwise); also a method through an exact receiver: self/cls/this when no "
        "analyzed subclass overrides it, a module-level singleton or JavaScript object "
        "literal, a constructed local, an import or a module-level class that names it"
    ),
    CONFIDENCE_PROBABLE: (
        "attribute call on an external module alias or a JavaScript default import, a "
        "self/this method an analyzed subclass overrides, this in a JavaScript object "
        "literal's method, a call through an import the module rebinds, or a known "
        "function passed as an argument; the binding is not proven"
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
JAVASCRIPT_EXTENSIONS = (".js", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts")
# TypeScript's ESM convention writes the emitted extension in the specifier ("./util.js"
# for util.ts); each is tried with the TypeScript source extensions too.
TYPESCRIPT_SOURCES = {".js": (".ts", ".tsx"), ".mjs": (".mts",), ".cjs": (".cts",)}
JAVASCRIPT_INDEXES = tuple(f"/index{ext}" for ext in JAVASCRIPT_EXTENSIONS)
PYTHON_INIT = "/__init__.py"
# A JavaScript default import binds the module's default export; attribute calls on it are
# reported against the module (``lodash.map``), not against a member named "default".
DEFAULT_EXPORT = "default"
# How many re-exports and base classes receiver resolution follows (a bound, not a policy:
# each step is one import or one base, and a cycle ends earlier).
HIERARCHY_DEPTH = 8
# The base every Python class has; it defines no method a project calls on a receiver.
OBJECT_BASE = "object"
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
    receivers: ReceiverFacts


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
                packages.add(path.removesuffix("__init__.py").rstrip("/"))
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
        stem, suffix = posixpath.splitext(joined)
        if suffix in TYPESCRIPT_SOURCES:
            candidates.extend(stem + ext for ext in TYPESCRIPT_SOURCES[suffix])
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
    if module.language in JAVASCRIPT_FAMILY:
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
    singletons: Mapping[str, str]  # module-level name -> its constructor (Python)
    constructed: Mapping[tuple[str, str], str]  # (unit name, local) -> its constructor
    classes: Mapping[str, ReceiverClass]  # module-level classes
    objects: Mapping[str, ReceiverObject]  # module-level object literals (JavaScript)
    units_at: Mapping[tuple[int, int], str]  # where each unit starts -> its key
    object_of: Mapping[str, str]  # an object literal's method unit -> the object's name


def _scope_for(module: ModuleInput, edges: Sequence[ModuleEdge]) -> _Scope:
    units_by_name = {u.name: u.key for u in module.units}
    functions: set[str] = set()
    variables: set[str] = set()
    for binding in module.bindings:
        if binding.kind in (BINDING_FUNCTION, BINDING_CLASS):
            functions.add(binding.name)
        elif binding.kind == BINDING_VARIABLE:
            variables.add(binding.name)
    imports = _import_table(module)
    edge_map: dict[tuple[str, int, str], ModuleEdge] = {}
    for edge in edges:
        key = (edge.specifier, edge.level, edge.imported)
        if key not in edge_map:
            edge_map[key] = edge
    return _Scope(
        units_by_name,
        frozenset(functions),
        imports,
        frozenset(variables),
        edge_map,
        **_receiver_tables(module),
    )


def _import_table(module: ModuleInput) -> dict[str, _ImportBinding]:
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
    return imports


def _receiver_tables(module: ModuleInput) -> dict[str, Any]:
    """The receiver fields of a module's scope (docs/proposal-receivers.md)."""
    receivers = module.receivers
    units_at = {(u.fact.span.line, u.fact.span.column): u.key for u in module.units}
    object_of = {
        units_at[(line, column)]: o.name
        for o in receivers.objects
        for _method, line, column in o.methods
        if (line, column) in units_at
    }
    return {
        "singletons": dict(receivers.singletons),
        "constructed": {(unit, local): callee for unit, local, callee in receivers.constructed},
        "classes": {c.name: c for c in receivers.classes},
        "objects": {o.name: o for o in receivers.objects},
        "units_at": units_at,
        "object_of": object_of,
    }


@dataclass(frozen=True)
class _Resolution:
    target: Target
    confidence: str
    reason: str


def _builtins_for(language: str) -> frozenset[str]:
    if language == PYTHON:
        return PYTHON_BUILTINS
    if language in JAVASCRIPT_FAMILY:
        return JAVASCRIPT_GLOBALS
    if language == CSHARP:
        return frozenset()  # G1: a C# call of an unknown name stays unresolved
    raise ValueError(f"no built-in names for language {language!r}")


class _Resolver:
    def __init__(self, modules: Sequence[ModuleInput], scopes: Mapping[str, _Scope]) -> None:
        self.scopes = scopes
        self.units_by_path: dict[str, Mapping[str, str]] = {
            path: scope.units_by_name for path, scope in scopes.items()
        }
        self.languages = {m.path: m.language for m in modules}
        self.ancestry: dict[tuple[str, str], frozenset[tuple[str, str]]] = {}

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
        self, path: str, unit: UnitMetrics, dotted: str, *, receiver_self: bool
    ) -> _Resolution:
        scope = self.scopes[path]
        parts = dotted.split(".")
        root = parts[0]
        rest = parts[1:]
        if receiver_self:
            return self._through_self(path, unit, dotted, rest)
        fact = unit.fact
        if root in fact.locals and root not in fact.globals_declared:
            return self._through_local(path, unit, dotted, rest)
        if root in scope.imports:
            exact = root not in scope.variables  # an import the module never rebinds
            return self._through_import(path, scope.imports[root], rest, exact=exact)
        if root in scope.functions:
            return self._through_definition(path, dotted)
        if root in scope.variables:
            return self._through_value(path, root, dotted, rest)
        if root in _builtins_for(self.languages[path]):
            return _Resolution(Target(TARGET_BUILTIN, dotted), CONFIDENCE_RESOLVED, "builtin")
        return _Resolution(
            Target(TARGET_UNRESOLVED, dotted),
            CONFIDENCE_UNRESOLVED,
            "receiver of unknown type",
        )

    # -- receivers (docs/proposal-receivers.md, R1; Python facts only) -------------------

    def _through_self(
        self, path: str, unit: UnitMetrics, dotted: str, rest: list[str]
    ) -> _Resolution:
        """``self.m()`` / ``cls.m()``: resolved when no analyzed subclass overrides ``m``;
        probable when one does."""
        scope = self.scopes[path]
        class_name = unit.fact.class_name
        if class_name is None:
            return self._through_object_this(path, unit, dotted, rest)
        if len(rest) == 1 and class_name in scope.classes:
            key, _why = self._method(path, scope.classes[class_name], rest[0], HIERARCHY_DEPTH)
            if key is not None:
                overriding = self._overriding(path, scope.classes[class_name], rest[0])
                if overriding is None:
                    return _Resolution(
                        Target(TARGET_UNIT, key),
                        CONFIDENCE_RESOLVED,
                        "method of the class or a project base; no analyzed subclass overrides it",
                    )
                return _Resolution(
                    Target(TARGET_UNIT, key),
                    CONFIDENCE_PROBABLE,
                    f"method of the class or a project base, overridden in {overriding}",
                )
            # Not an instance method of the class or its bases (a static method, a
            # property or accessor, or an attribute): the class body decides, as before.
        method = f"{class_name}.{rest[0]}" if len(rest) == 1 else None
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

    def _through_object_this(
        self, path: str, unit: UnitMetrics, dotted: str, rest: list[str]
    ) -> _Resolution:
        """``this.m()`` in a method of a JavaScript object literal: probable, since
        ``this`` depends on how the method is called (``const f = Obj.m; f()`` loses it)."""
        scope = self.scopes[path]
        if len(rest) == 1 and unit.key in scope.object_of:
            found = self._object_method(path, scope.object_of[unit.key], rest[0])
            if found is not None:
                return _Resolution(
                    Target(TARGET_UNIT, found),
                    CONFIDENCE_PROBABLE,
                    "method of the object literal the calling method belongs to; this "
                    "depends on how the method is called",
                )
        return _Resolution(
            Target(TARGET_UNRESOLVED, dotted),
            CONFIDENCE_UNRESOLVED,
            "receiver call outside a class body",
        )

    def _object_method(self, path: str, name: str, method: str) -> str | None:
        """The unit of ``method`` in the module-level object literal ``name``."""
        scope = self.scopes[path]
        for found, line, column in scope.objects[name].methods:
            if found == method and (line, column) in scope.units_at:
                return scope.units_at[(line, column)]
        return None

    def _through_definition(self, path: str, dotted: str) -> _Resolution:
        """``Class.m()`` on a module-level class (receivers R1 and R2)."""
        scope = self.scopes[path]
        if dotted not in scope.units_by_name:
            return _Resolution(
                Target(TARGET_UNRESOLVED, dotted),
                CONFIDENCE_UNRESOLVED,
                "attribute of a module-level definition that is not itself defined",
            )
        return _Resolution(
            Target(TARGET_UNIT, scope.units_by_name[dotted]),
            CONFIDENCE_RESOLVED,
            "call through a module-level class",
        )

    def _through_local(
        self, path: str, unit: UnitMetrics, dotted: str, rest: list[str]
    ) -> _Resolution:
        """``local.m()`` on a local the unit constructs once."""
        scope = self.scopes[path]
        where = unit.name
        if self.languages[path] != PYTHON:
            where = f"{unit.fact.span.line}:{unit.fact.span.column}"
        key = (where, dotted.split(".")[0])
        if len(rest) == 1 and key in scope.constructed:
            found = self._instance_method(path, scope.constructed[key], rest[0])
            if found is not None:
                return _Resolution(
                    Target(TARGET_UNIT, found),
                    CONFIDENCE_RESOLVED,
                    "method of the class the local was constructed from",
                )
        return _Resolution(
            Target(TARGET_UNRESOLVED, dotted),
            CONFIDENCE_UNRESOLVED,
            "method call on a parameter or local value of unknown type",
        )

    def _through_value(self, path: str, root: str, dotted: str, rest: list[str]) -> _Resolution:
        """``value.m()`` on a module-level value: a singleton bound once to a constructor,
        or a JavaScript object literal."""
        scope = self.scopes[path]
        if len(rest) == 1 and root in scope.objects:
            found = self._object_method(path, root, rest[0])
            if found is not None:
                return _Resolution(
                    Target(TARGET_UNIT, found),
                    CONFIDENCE_RESOLVED,
                    "method of a module-level object literal",
                )
        if len(rest) == 1 and root in scope.singletons:
            found = self._instance_method(path, scope.singletons[root], rest[0])
            if found is not None:
                return _Resolution(
                    Target(TARGET_UNIT, found),
                    CONFIDENCE_RESOLVED,
                    "method of the class a module-level singleton was constructed from",
                )
        return _Resolution(
            Target(TARGET_UNRESOLVED, dotted),
            CONFIDENCE_UNRESOLVED,
            "method call on a module-level value of unknown type",
        )

    def _through_import(
        self, path: str, binding: _ImportBinding, rest: list[str], *, exact: bool
    ) -> _Resolution:
        """An attribute call through an import: an imported singleton's method, or a
        function or method the import names exactly (``mod.f()``, ``Class.m()``); probable
        as before when the module rebinds the imported name (``exact`` false)."""
        scope = self.scopes[path]
        if not exact:
            return self._imported(binding, scope, ".".join(rest))
        if len(rest) == 1:
            found = self._imported_receiver(scope, binding, rest[0])
            if found is not None:
                return found
        resolution = self._imported(binding, scope, ".".join(rest))
        # A JavaScript default import's attribute is looked up as a member of the module:
        # a convention, not a binding the import names.
        guessed = self.languages[path] != PYTHON and binding.imported == DEFAULT_EXPORT
        if resolution.target.kind == TARGET_UNIT and not guessed:
            return _Resolution(
                resolution.target,
                CONFIDENCE_RESOLVED,
                f"{resolution.reason}: the import names the module and the attribute exactly",
            )
        return resolution

    def _imported_receiver(
        self, scope: _Scope, binding: _ImportBinding, method: str
    ) -> _Resolution | None:
        """``name.method()`` where ``name`` is an imported singleton or object literal."""
        reached = self._reach(scope, binding, [])
        if reached is None:
            return None
        target, name = reached
        if name in self.scopes[target].objects:
            found = self._object_method(target, name, method)
            if found is not None:
                return _Resolution(
                    Target(TARGET_UNIT, found),
                    CONFIDENCE_RESOLVED,
                    "method of an imported module-level object literal",
                )
        singleton = self._singleton_named(target, name, HIERARCHY_DEPTH)
        if singleton is None:
            return None
        found = self._instance_method(singleton[0], singleton[1], method)
        if found is None:
            return None
        return _Resolution(
            Target(TARGET_UNIT, found),
            CONFIDENCE_RESOLVED,
            "method of the class an imported singleton was constructed from",
        )

    def _reach(
        self, scope: _Scope, binding: _ImportBinding, rest: list[str]
    ) -> tuple[str, str] | None:
        """(analyzed module, name in it) that ``binding.rest`` names; None for anything
        longer than one name in one module."""
        qualified = "." * binding.level + binding.specifier
        submodule = (qualified, binding.level, binding.imported)
        if binding.imported != "" and submodule in scope.module_edges:
            target = scope.module_edges[submodule].target
            if target is None or len(rest) != 1:
                return None
            return target, rest[0]
        whole = (qualified, binding.level, "")
        if whole not in scope.module_edges:
            return None
        target = scope.module_edges[whole].target
        if target is None:
            return None
        if binding.imported in ("", DEFAULT_EXPORT):
            if len(rest) != 1:
                return None
            return target, rest[0]
        if len(rest) != 0:
            return None
        return target, binding.imported

    def _followed(self, path: str, name: str) -> tuple[str, str] | None:
        """Where ``name``, imported into ``path``, comes from."""
        scope = self.scopes[path]
        if name not in scope.imports:
            return None
        return self._reach(scope, scope.imports[name], [])

    def _class_named(self, path: str, name: str, depth: int) -> tuple[str, ReceiverClass] | None:
        scope = self.scopes[path]
        if name in scope.classes:
            return path, scope.classes[name]
        followed = self._followed(path, name)
        if depth == 0 or followed is None:
            return None
        return self._class_named(followed[0], followed[1], depth - 1)

    def _singleton_named(self, path: str, name: str, depth: int) -> tuple[str, str] | None:
        """(module, constructor) of a module-level singleton, through re-exports."""
        scope = self.scopes[path]
        if name in scope.singletons:
            return path, scope.singletons[name]
        followed = self._followed(path, name)
        if depth == 0 or followed is None:
            return None
        return self._singleton_named(followed[0], followed[1], depth - 1)

    def _class_in(self, path: str, dotted: str) -> tuple[str, ReceiverClass] | None:
        """The analyzed module-level class a plain or dotted name in ``path`` names."""
        parts = dotted.split(".")
        if len(parts) == 1:
            return self._class_named(path, parts[0], HIERARCHY_DEPTH)
        scope = self.scopes[path]
        if parts[0] not in scope.imports:
            return None
        reached = self._reach(scope, scope.imports[parts[0]], parts[1:])
        if reached is None:
            return None
        return self._class_named(reached[0], reached[1], HIERARCHY_DEPTH)

    def _instance_method(self, path: str, constructor: str, method: str) -> str | None:
        """The unit of ``method`` on an instance ``constructor`` built in ``path``."""
        found = self._class_in(path, constructor)
        if found is None:
            return None
        key, _why = self._method(found[0], found[1], method, HIERARCHY_DEPTH)
        return key

    def _method(
        self, path: str, owner: ReceiverClass, method: str, depth: int
    ) -> tuple[str | None, str]:
        """(unit key, "") when ``owner`` or a project base defines ``method``, left to
        right; (None, "") when none does; (None, why) when a base that is not an analyzed
        class might."""
        scope = self.scopes[path]
        qualified = f"{owner.name}.{method}"
        if method in owner.methods and qualified in scope.units_by_name:
            return scope.units_by_name[qualified], ""
        if depth == 0:
            return None, f"the bases of {owner.name} are deeper than the analysis follows"
        for base in owner.bases:
            if base == OBJECT_BASE:
                continue
            parent = None
            if base != "":
                parent = self._class_in(path, base)
            if parent is None:
                return None, f"a base of {owner.name} is not an analyzed class"
            key, why = self._method(parent[0], parent[1], method, depth - 1)
            if key is not None or why != "":
                return key, why
        return None, ""

    def _ancestors(self, path: str, owner: ReceiverClass) -> frozenset[tuple[str, str]]:
        key = (path, owner.name)
        if key not in self.ancestry:
            self.ancestry[key] = frozenset()  # a cycle in the bases ends here
            found: set[tuple[str, str]] = set()
            for base in owner.bases:
                parent = None
                if base not in ("", OBJECT_BASE):
                    parent = self._class_in(path, base)
                if parent is not None:
                    found.add((parent[0], parent[1].name))
                    found.update(self._ancestors(parent[0], parent[1]))
            self.ancestry[key] = frozenset(found)
        return self.ancestry[key]

    def _overriding(self, path: str, owner: ReceiverClass, method: str) -> str | None:
        """An analyzed class deriving from ``owner`` whose own body defines ``method``."""
        key = (path, owner.name)
        for other_path, scope in sorted(self.scopes.items()):
            for candidate in scope.classes.values():
                if method in candidate.methods and key in self._ancestors(other_path, candidate):
                    return f"{other_path}::{candidate.name}"
        return None


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
        return resolver.resolve_attribute(
            path, unit, call.callee, receiver_self=call.receiver_self
        ), EDGE_CALL
    if call.shape == CALL_NEW:
        if "." in call.callee:
            return resolver.resolve_attribute(
                path, unit, call.callee, receiver_self=False
            ), EDGE_NEW
        resolution = resolver.resolve_name(path, unit, call.callee)
        assert resolution is not None
        return resolution, EDGE_NEW
    if call.shape != CALL_ARGUMENT:
        raise AssertionError(f"unexpected call shape {call.shape!r}")
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
class SiteResolution:
    """Where one call site (path, call span) resolved to (H4, ASYNC001)."""

    target: Target
    confidence: str


@dataclass(frozen=True)
class CallGraph:
    edges: tuple[CallEdge, ...]
    module_edges: tuple[ModuleEdge, ...]
    unit_keys: tuple[str, ...]
    paths: tuple[str, ...]
    # Every call, attribute-call and construction site, keyed by (path, call span);
    # arguments passed as values are not sites. Not serialized.
    sites: Mapping[tuple[str, Span], SiteResolution]


def _edges(
    aggregated: Mapping[tuple[str, str, str, str, str], tuple[int, Span, str]],
) -> tuple[CallEdge, ...]:
    edges = [
        CallEdge(source, Target(kind, identifier), confidence, edge_kind, count, span, reason)
        for (source, kind, identifier, confidence, edge_kind), (
            count,
            span,
            reason,
        ) in aggregated.items()
    ]
    edges.sort(key=lambda e: (e.source, e.span, e.target.kind, e.target.identifier, e.kind))
    return tuple(edges)


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
    sites: dict[tuple[str, Span], SiteResolution] = {}
    unit_keys: list[str] = []
    for module in ordered:
        for unit in module.units:
            unit_keys.append(unit.key)
            for call in unit.fact.calls:
                classified = _classify(resolver, module.path, unit, call)
                if classified is None:
                    continue
                resolution, edge_kind = classified
                if edge_kind != EDGE_ARGUMENT:
                    sites[(module.path, call.span)] = SiteResolution(
                        resolution.target, resolution.confidence
                    )
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
    return CallGraph(
        edges=_edges(aggregated),
        module_edges=tuple(module_edges),
        unit_keys=tuple(unit_keys),
        paths=tuple(m.path for m in ordered),
        sites=sites,
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
    "SiteResolution",
    "Target",
    "build_call_graph",
]
