"""Python modules of the project as property contracts see them (spec P1a).

A call is resolved through the calling file's module-level imports and definitions to a
dotted reference, and the reference to one of: a runtime declaration (``requires`` and the
other three, by the module names ``runtime_module`` gives, whether or not that file is
analyzed), a function of a project module, a library or builtin callee, or nothing the
analysis can name (``unknown``). A project module is one of the analyzed files, or a
file under the analyzed root in the flat or the src layout: a resolved callee's declared
contract is read from it even when only the caller is being analyzed.
"""

import ast
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from shockharness.complexity.callgraph import PYTHON_BUILTINS
from shockharness.contracts.catalog import DECLARATIONS, module_file, read_module
from shockharness.rules.defaults import module_names

FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
DEFINITION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
# Compound statements whose bodies still run at module level (if TYPE_CHECKING, try).
MODULE_LEVEL_BLOCKS = (ast.If, ast.Try, ast.With)

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


@dataclass(frozen=True)
class Target:
    kind: str
    reference: str  # the dotted reference ("" for unknown)
    why: str  # for unknown: what could not be resolved
    module: Module | None  # for a unit
    function: ast.FunctionDef | ast.AsyncFunctionDef | None


def unknown_target(why: str) -> Target:
    return Target(UNKNOWN, "", why, None, None)


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
    return Module(name, path, tree, imports, definitions, frozenset(assigned - set(definitions)))


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
        for path, tree in sorted(analyzed.items()):
            names = module_names(path)
            module = build_module(_shortest(names), path, tree)
            self.by_path[path] = module
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
            return Target(kind, reference, "", None, None)
        parts = reference.split(".")
        split = self._split(parts)
        if split is None:
            unreadable = [m for m in self.unreadable if reference.startswith(m + ".")]
            if len(unreadable) > 0:
                return unknown_target(self.unreadable[unreadable[0]])
            return Target(LIBRARY, reference, "", None, None)
        module, rest = split
        return self._member(module, rest, seen | {reference})

    def _member(self, module: Module, rest: list[str], seen: frozenset[str]) -> Target:
        first = rest[0]
        if first in module.definitions:
            node = module.definitions[first]
            if len(rest) == 1 and isinstance(node, FUNCTION_NODES):
                return Target(UNIT, f"{module.name}.{first}", "", module, node)
            # A class (its constructor) or a method through the class: not resolved in P1a.
            return unknown_target(f"{module.name}.{'.'.join(rest)} is not a module function")
        if first in module.imports:
            return self.resolve(".".join([module.imports[first], *rest[1:]]), seen)
        return unknown_target(f"{module.name} defines no function {'.'.join(rest)}")

    def callee(self, module: Module, func: ast.expr, local: frozenset[str]) -> Target:
        """What the callee expression of a call in ``module`` resolves to."""
        chain: list[str] = []
        node = func
        while isinstance(node, ast.Attribute):
            chain.insert(0, node.attr)
            node = node.value
        if not isinstance(node, ast.Name):
            return unknown_target("the callee is computed")
        return self._named(module, node.id, chain, local)

    def _named(self, module: Module, root: str, chain: list[str], local: frozenset[str]) -> Target:
        dotted = ".".join([root, *chain])
        if root in local:
            return unknown_target(f"{dotted}(...) is called on a local value, not resolved")
        if root in module.imports:
            return self.resolve(".".join([module.imports[root], *chain]), frozenset())
        if root in module.definitions:
            return self.resolve(f"{module.name}.{dotted}", frozenset())
        if root in module.assigned:
            return unknown_target(f"{dotted} is called through a module-level value")
        if root in PYTHON_BUILTINS and len(chain) == 0:
            return Target(LIBRARY, root, "", None, None)
        return unknown_target(f"{dotted} is not imported or defined")
