"""Python modules of the project as property contracts see them (spec P1a).

A call is resolved through the calling file's module-level imports and definitions to a
dotted reference, and the reference to one of: a runtime declaration (``requires`` and the
other three, by the module names ``runtime_module`` gives, whether or not that file is
analyzed), a function of a project module, a library or builtin callee, or nothing the
analysis can name (``unknown``). A method resolves through its receiver when the receiver's
class is exact (docs/proposal-receivers.md, R1): ``self.m()`` in a class no analyzed
subclass overrides ``m`` in, a module-level singleton, a local the function constructs,
``Class.m()`` and ``Class(...).m()``. A project module is one of the analyzed files, or a
file under the analyzed root in the flat or the src layout: a resolved callee's declared
contract is read from it even when only the caller is being analyzed.
"""

import ast
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from shockharness.complexity.callgraph import PYTHON_BUILTINS
from shockharness.contracts.catalog import DECLARATIONS, module_file, read_module
from shockharness.ir.python_receivers import (
    METHOD_INSTANCE,
    METHOD_STATIC,
    THROUGH_CLASS,
    THROUGH_INSTANCE,
    class_methods,
    constructed_locals,
    implicit_parameters,
    is_dotted,
    method_kind,
    receiver_parameter,
    singleton_constructors,
)
from shockharness.rules.defaults import module_names

FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
DEFINITION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
# Compound statements whose bodies still run at module level (if TYPE_CHECKING, try).
MODULE_LEVEL_BLOCKS = (ast.If, ast.Try, ast.With)

# ``Class.method``: a class and one of its methods, after the module.
METHOD_PATH = ("class", "method")

# What a callee resolves to.
RUNTIME = "runtime"
UNIT = "unit"
LIBRARY = "library"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class Module:
    name: str  # the shortest dotted name the file is imported as
    path: str  # project-relative, forward slashes
    tree: ast.Module
    imports: Mapping[str, str]  # local name -> dotted target
    definitions: Mapping[str, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef]
    assigned: frozenset[str]  # other module-level bindings (values, not callees)
    singletons: Mapping[str, ast.expr]  # name -> the callee that built it, bound once


@dataclass(frozen=True)
class Target:
    kind: str
    reference: str  # the dotted reference ("" for unknown)
    why: str  # for unknown: what could not be resolved
    module: Module | None  # for a unit
    function: ast.FunctionDef | ast.AsyncFunctionDef | None
    implicit: int  # leading parameters the call supplies itself (a method's self or cls)


@dataclass(frozen=True)
class Receivers:
    """What one unit's receivers are: the method's own receiver parameter (``self`` /
    ``cls``) in its enclosing class, and the locals it constructs."""

    name: str | None
    owner: ast.ClassDef | None
    through: str  # THROUGH_INSTANCE for self, THROUGH_CLASS for cls
    constructed: Mapping[str, ast.expr]


NO_RECEIVERS = Receivers(None, None, THROUGH_INSTANCE, {})
# A plain base every class has; it defines no method a project calls through a receiver.
OBJECT = "object"


def unknown_target(why: str) -> Target:
    return Target(UNKNOWN, "", why, None, None, 0)


def receivers_of(
    owner: ast.ClassDef | None, function: ast.FunctionDef | ast.AsyncFunctionDef
) -> Receivers:
    """A function's receivers; ``owner`` is the module-level class whose body defines it."""
    kind = method_kind(function)
    through = THROUGH_INSTANCE
    if kind is not None and kind not in (METHOD_INSTANCE, METHOD_STATIC):
        through = THROUGH_CLASS
    name = None
    if owner is not None:
        name = receiver_parameter(function)
    return Receivers(name, owner, through, constructed_locals(function))


def _module_level(statements: Sequence[ast.stmt]) -> list[ast.stmt]:
    """Module-level statements, including those nested in if / try / with blocks."""
    found: list[ast.stmt] = []
    for statement in statements:
        found.append(statement)
        if isinstance(statement, MODULE_LEVEL_BLOCKS):
            nested = [*statement.body]
            if isinstance(statement, ast.If | ast.Try):
                nested.extend(statement.orelse)
            if isinstance(statement, ast.Try):
                nested.extend(statement.finalbody)
                for handler in statement.handlers:
                    nested.extend(handler.body)
            found.extend(_module_level(nested))
    return found


def _package(module: str, is_package: bool) -> list[str]:
    parts = module.split(".")
    if is_package:
        return parts
    return parts[: len(parts) - 1]


def _from_target(node: ast.ImportFrom, package: list[str]) -> str | None:
    """The absolute module of ``from ... import``; None when a relative import climbs
    above the project's top package."""
    if node.level == 0:
        return node.module
    climb = node.level - 1
    if climb > len(package):
        return None
    base = package[: len(package) - climb]
    if node.module is not None:
        base = [*base, node.module]
    return ".".join(base)


def _local_name(alias: ast.alias) -> str:
    """The name ``import a.b`` / ``import a as b`` / ``from m import a as b`` binds."""
    if alias.asname is not None:
        return alias.asname
    return alias.name.split(".")[0]


def _import_target(alias: ast.alias) -> str:
    """What ``import a.b as m`` binds (the module a.b); ``import a.b`` binds the package a."""
    if alias.asname is not None:
        return alias.name
    return alias.name.split(".")[0]


def _import_bindings(statement: ast.stmt, package: list[str]) -> list[tuple[str, str]]:
    """(local name, dotted target) for each name an import statement binds."""
    if isinstance(statement, ast.Import):
        return [(_local_name(a), _import_target(a)) for a in statement.names]
    if not isinstance(statement, ast.ImportFrom):
        return []
    origin = _from_target(statement, package)
    if origin is None:
        return []
    return [(_local_name(a), f"{origin}.{a.name}") for a in statement.names if a.name != "*"]


def _assigned_names(statement: ast.stmt) -> list[str]:
    targets: list[ast.expr] = []
    if isinstance(statement, ast.Assign):
        targets = statement.targets
    elif isinstance(statement, ast.AnnAssign | ast.AugAssign):
        targets = [statement.target]
    return [n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)]


def build_module(name: str, path: str, tree: ast.Module) -> Module:
    package = _package(name, path.endswith("__init__.py"))
    imports: dict[str, str] = {}
    definitions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef] = {}
    assigned: set[str] = set()
    for statement in _module_level(tree.body):
        imports.update(_import_bindings(statement, package))
        if isinstance(statement, DEFINITION_NODES):
            definitions[statement.name] = statement
        assigned.update(_assigned_names(statement))
    singletons = singleton_constructors(tree)
    values = frozenset(assigned - set(definitions))
    return Module(name, path, tree, imports, definitions, values, singletons)


def _shortest(names: frozenset[str]) -> str:
    return min(names, key=lambda name: (len(name), name))


class ProjectIndex:
    """Project modules by dotted name, loaded on demand; analyzed files win over disk."""

    def __init__(
        self, root: Path, analyzed: Mapping[str, ast.Module], runtime: frozenset[str]
    ) -> None:
        self.root = root
        self.runtime = runtime
        self.by_path: dict[str, Module] = {}
        self.by_name: dict[str, Module | None] = {}
        self.unreadable: dict[str, str] = {}
        self.analyzed: list[Module] = []
        self.ancestry: dict[tuple[str, str], frozenset[tuple[str, str]]] = {}
        for path, tree in sorted(analyzed.items()):
            names = module_names(path)
            module = build_module(_shortest(names), path, tree)
            self.by_path[path] = module
            self.analyzed.append(module)
            for name in names:
                self.by_name[name] = module

    def is_runtime(self, module: Module) -> bool:
        return len(module_names(module.path) & self.runtime) > 0

    def module(self, dotted: str) -> Module | None:
        if dotted not in self.by_name:
            self.by_name[dotted] = self._load(dotted)
        return self.by_name[dotted]

    def _load(self, dotted: str) -> Module | None:
        found = module_file(self.root, dotted.split("."))
        if found is None:
            return None
        path = found.relative_to(self.root).as_posix()
        if path in self.by_path:
            return self.by_path[path]
        tree, why = read_module(found)
        if tree is None:
            self.unreadable[dotted] = why
            return None
        module = build_module(_shortest(module_names(path)), path, tree)
        self.by_path[path] = module
        return module

    def _split(self, parts: list[str]) -> tuple[Module, list[str]] | None:
        """The longest project-module prefix of ``parts`` and the names after it."""
        for end in reversed(range(1, len(parts))):
            module = self.module(".".join(parts[:end]))
            if module is not None:
                return module, parts[end:]
        return None

    def resolve(self, reference: str, seen: frozenset[str]) -> Target:
        if reference in seen:
            return unknown_target(f"the imports of {reference} form a cycle")
        module_part, _dot, last = reference.rpartition(".")
        if module_part in self.runtime:
            kind = RUNTIME if last in DECLARATIONS else LIBRARY  # enable, report: plain calls
            return Target(kind, reference, "", None, None, 0)
        parts = reference.split(".")
        split = self._split(parts)
        if split is None:
            unreadable = [m for m in self.unreadable if reference.startswith(m + ".")]
            if len(unreadable) > 0:
                return unknown_target(self.unreadable[unreadable[0]])
            return Target(LIBRARY, reference, "", None, None, 0)
        module, rest = split
        return self._member(module, rest, seen | {reference})

    def _member(self, module: Module, rest: list[str], seen: frozenset[str]) -> Target:
        first = rest[0]
        if first in module.definitions:
            node = module.definitions[first]
            if len(rest) == 1 and isinstance(node, FUNCTION_NODES):
                return Target(UNIT, f"{module.name}.{first}", "", module, node, 0)
            if len(rest) == len(METHOD_PATH) and isinstance(node, ast.ClassDef):
                return self.method(module, node, rest[1], THROUGH_CLASS)
            # A class (its constructor): not a contract unit.
            return unknown_target(f"{module.name}.{'.'.join(rest)} is not a module function")
        if first in module.singletons and len(rest) == len(METHOD_PATH):
            return self.on_instance(module, module.singletons[first], rest[1], first)
        if first in module.imports:
            return self.resolve(".".join([module.imports[first], *rest[1:]]), seen)
        if first in module.assigned:
            return unknown_target(
                f"{'.'.join(rest[1:])}(...) is called on {module.name}.{first}, a module-level "
                "value that is not one constructor call bound once"
            )
        return unknown_target(f"{module.name} defines no function {'.'.join(rest)}")

    def callee(
        self, module: Module, func: ast.expr, local: frozenset[str], receivers: Receivers
    ) -> Target:
        """What the callee expression of a call in ``module`` resolves to."""
        chain: list[str] = []
        node = func
        while isinstance(node, ast.Attribute):
            chain.insert(0, node.attr)
            node = node.value
        if isinstance(node, ast.Call) and len(chain) == 1 and is_dotted(node.func):
            return self.on_instance(module, node.func, chain[0], f"{ast.unparse(node.func)}(...)")
        if not isinstance(node, ast.Name):
            return unknown_target("the callee is computed")
        if len(chain) == 1:
            method = self._local_receiver(module, node.id, chain[0], receivers)
            if method is not None:
                return method
        if node.id in local:
            dotted = ".".join([node.id, *chain])
            return unknown_target(f"{dotted}(...) is called on a local value, not resolved")
        return self._named(module, node.id, chain)

    def _local_receiver(
        self, module: Module, root: str, method: str, receivers: Receivers
    ) -> Target | None:
        """``self.method()`` / ``cls.method()`` and ``local.method()`` on a constructed
        local; None for any other root."""
        if root == receivers.name and receivers.owner is not None:
            return self.through_receiver(module, receivers.owner, method, receivers.through)
        if root in receivers.constructed:
            return self.on_instance(module, receivers.constructed[root], method, root)
        return None

    def _named(self, module: Module, root: str, chain: list[str]) -> Target:
        """A call through a module-level name: an import, a definition, a singleton."""
        dotted = ".".join([root, *chain])
        if root in module.imports:
            return self.resolve(".".join([module.imports[root], *chain]), frozenset())
        if root in module.definitions:
            return self.resolve(f"{module.name}.{dotted}", frozenset())
        if root in module.singletons and len(chain) == 1:
            return self.on_instance(module, module.singletons[root], chain[0], root)
        if root in module.assigned:
            return unknown_target(f"{dotted} is called through a module-level value")
        if root in PYTHON_BUILTINS and len(chain) == 0:
            return Target(LIBRARY, root, "", None, None, 0)
        return unknown_target(f"{dotted} is not imported or defined")

    # -- methods through their receivers (docs/proposal-receivers.md, R1) ---------------

    def class_of(self, module: Module, expr: ast.expr) -> tuple[Module, ast.ClassDef] | None:
        """The project class a plain or dotted name in ``module`` names, through imports."""
        parts = ast.unparse(expr).split(".")
        root = parts[0]
        if root in module.definitions and len(parts) == 1:
            node = module.definitions[root]
            if isinstance(node, ast.ClassDef):
                return module, node
            return None
        if root in module.imports:
            return self._class_reference(".".join([module.imports[root], *parts[1:]]), frozenset())
        return None

    def _class_reference(
        self, reference: str, seen: frozenset[str]
    ) -> tuple[Module, ast.ClassDef] | None:
        if reference in seen:
            return None
        split = self._split(reference.split("."))
        if split is None:
            return None
        module, rest = split
        if len(rest) != 1:
            return None
        if rest[0] in module.definitions:
            node = module.definitions[rest[0]]
            if isinstance(node, ast.ClassDef):
                return module, node
            return None
        if rest[0] in module.imports:
            return self._class_reference(module.imports[rest[0]], seen | {reference})
        return None

    def on_instance(self, module: Module, constructor: ast.expr, method: str, what: str) -> Target:
        """``what.method()`` where ``what`` was built by calling ``constructor``."""
        found = self.class_of(module, constructor)
        if found is None:
            return unknown_target(
                f"{what}.{method}(...) is called on an instance of "
                f"{ast.unparse(constructor)}, which is not a project class"
            )
        return self.method(found[0], found[1], method, THROUGH_INSTANCE)

    def through_receiver(
        self, module: Module, owner: ast.ClassDef, method: str, through: str
    ) -> Target:
        """``self.method()`` / ``cls.method()``: the class's method, unless an analyzed
        subclass overrides it (the receiver may be an instance of that subclass)."""
        target = self.method(module, owner, method, through)
        if target.kind != UNIT:
            return target
        overriding = self._overriding(module, owner, method)
        if overriding is not None:
            return unknown_target(
                f"{module.name}.{owner.name}.{method} is overridden in {overriding}; "
                "the receiver may be an instance of it"
            )
        return target

    def method(self, module: Module, owner: ast.ClassDef, name: str, through: str) -> Target:
        found = self._lookup(module, owner, name, through, frozenset())
        if found is None:
            return unknown_target(f"{module.name}.{owner.name} defines no method {name}")
        return found

    def _lookup(
        self,
        module: Module,
        owner: ast.ClassDef,
        name: str,
        through: str,
        seen: frozenset[tuple[str, str]],
    ) -> Target | None:
        """The method ``name`` in ``owner`` or its project bases, left to right; None
        when no class there defines it; unknown when a base the analysis cannot read
        might."""
        key = (module.path, owner.name)
        if key in seen:
            return unknown_target(f"the bases of {module.name}.{owner.name} form a cycle")
        methods = class_methods(owner)
        if name in methods:
            return self._method_target(module, owner, methods[name], through)
        for base in owner.bases:
            if isinstance(base, ast.Name) and base.id == OBJECT:
                continue
            found = None
            if is_dotted(base):
                found = self.class_of(module, base)
            if found is None:
                return unknown_target(
                    f"{module.name}.{owner.name} does not define {name}, and its base "
                    f"{ast.unparse(base)} is not a project class"
                )
            target = self._lookup(found[0], found[1], name, through, seen | {key})
            if target is not None:
                return target
        return None

    def _method_target(
        self,
        module: Module,
        owner: ast.ClassDef,
        function: ast.FunctionDef | ast.AsyncFunctionDef,
        through: str,
    ) -> Target:
        reference = f"{module.name}.{owner.name}.{function.name}"
        kind = method_kind(function)
        if kind is None:
            return unknown_target(f"{reference} is a property, not a method")
        return Target(UNIT, reference, "", module, function, implicit_parameters(kind, through))

    def _ancestors(self, module: Module, owner: ast.ClassDef) -> frozenset[tuple[str, str]]:
        """Every project class ``owner`` derives from, through the bases the analysis
        can read."""
        key = (module.path, owner.name)
        if key not in self.ancestry:
            self.ancestry[key] = frozenset()  # a cycle in the bases ends here
            found: set[tuple[str, str]] = set()
            for base in owner.bases:
                parent = None
                if is_dotted(base):
                    parent = self.class_of(module, base)
                if parent is not None:
                    found.add((parent[0].path, parent[1].name))
                    found.update(self._ancestors(parent[0], parent[1]))
            self.ancestry[key] = frozenset(found)
        return self.ancestry[key]

    def _overriding(self, module: Module, owner: ast.ClassDef, name: str) -> str | None:
        """An analyzed class that derives from ``owner`` and defines ``name`` itself."""
        key = (module.path, owner.name)
        for candidate in self.analyzed:
            for node in candidate.tree.body:
                if not isinstance(node, ast.ClassDef) or name not in class_methods(node):
                    continue
                if key in self._ancestors(candidate, node):
                    return f"{candidate.name}.{node.name}"
        return None
