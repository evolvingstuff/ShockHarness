"""Uses of Python functions the call graph does not record (DEAD001, DEAD002).

A function passed, stored or bound instead of called (``handlers = {"x": on_x}``,
``Thread(target=run)``, ``explain=evidence.reasons_for``) is a reference from the unit
that names it. An attribute read or written outside a call (``obj.name``), or named by a
literal in ``getattr`` and its relatives, is a member reference: it may reach any method
or function of that name. Registration without a call: a decorator other than the ones
that only change how a function is called (``staticmethod``, ``property`` ...), and a
module-level ``__all__``.
"""

import ast
from dataclasses import dataclass

from shockharness.constants import FIRST_COLUMN, FIRST_LINE
from shockharness.ir.model import DeclaredFunction, UsageFacts, UsageReference
from shockharness.ir.python_catches import bound_name, node_span
from shockharness.ir.python_functions import import_binding
from shockharness.ir.python_receivers import decorator_name, is_dotted
from shockharness.source import SourceText

FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
# Decorators that change how a function is called or cached, not whether something calls
# it: the function is still reached only through calls or attribute reads.
TRANSPARENT_DECORATORS = frozenset(
    {
        "staticmethod",
        "classmethod",
        "property",
        "cached_property",
        "setter",
        "getter",
        "deleter",
        "cache",
        "lru_cache",
        "wraps",
        "abstractmethod",
        "override",
        "overload",
        "final",
    }
)
# getattr(obj, "name") and its relatives name an attribute by a literal.
ATTRIBUTE_FUNCTIONS = frozenset({"getattr", "hasattr", "setattr", "delattr"})
ATTRIBUTE_ARGUMENT = 1
EXPORTS = "__all__"
DECORATOR = "decorator @"
EXPORTED = "listed in __all__"

Unit = tuple[int, int]


def _exports(module: ast.Module) -> frozenset[str]:
    """The strings of every module-level ``__all__ = [...]`` / ``__all__ += [...]``."""
    names: set[str] = set()
    for statement in module.body:
        value: ast.expr | None = None
        if (
            isinstance(statement, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == EXPORTS for t in statement.targets)
        ) or (
            isinstance(statement, ast.AugAssign | ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == EXPORTS
        ):
            value = statement.value
        if value is None:
            continue
        names.update(
            node.value
            for node in ast.walk(value)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        )
    return frozenset(names)


def _annotations(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> list[ast.expr]:
    """Parameter and return annotations, evaluated with the def (``Depends(handler)`` in
    an ``Annotated`` parameter names a function a framework calls)."""
    arguments = node.args
    parameters = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
    for extra in (arguments.vararg, arguments.kwarg):
        if extra is not None:
            parameters.append(extra)
    found = [p.annotation for p in parameters if p.annotation is not None]
    if not isinstance(node, ast.Lambda) and node.returns is not None:
        found.append(node.returns)
    return found


def _class_names(node: ast.expr) -> set[str]:
    """The final names an annotation or a constructor call mentions (``C | None``,
    ``Optional[C]``, ``mod.C(...)``)."""
    if isinstance(node, ast.Call):
        node = node.func
    names: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            names.add(n.id)
        elif isinstance(n, ast.Attribute):
            names.add(n.attr)
    return names


@dataclass
class _Scan:
    """What one walk over the module gives the collector. ``bindable``: names a bare
    reference may mean a project function by (every def, every name an import binds);
    ``imported`` and ``modules``: the names ``from ... import`` and ``import`` bind;
    ``bound``: for each name the file binds, the classes its annotations and constructor
    calls mention; ``handoffs``: (root name, value) of each ``root.attribute = value``."""

    bindable: set[str]
    imported: set[str]
    modules: set[str]
    bound: dict[str, set[str]]
    handoffs: list[tuple[str, ast.expr]]

    def bind(self, target: ast.expr, mentioned: set[str]) -> None:
        if isinstance(target, ast.Name):
            if target.id not in self.bound:
                self.bound[target.id] = set()
            self.bound[target.id].update(mentioned)

    def assignment(self, node: ast.Assign) -> None:
        if isinstance(node.value, ast.Call):
            self.bind(node.targets[0], _class_names(node.value))
        for target in node.targets:
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                self.handoffs.append((target.value.id, node.value))

    def handed(self) -> set[str]:
        """Classes whose instances are assigned to an attribute of an imported module."""
        found: set[str] = set()
        for root, value in self.handoffs:
            if root not in self.modules:
                continue
            if isinstance(value, ast.Call):
                found.update(_class_names(value))
            elif isinstance(value, ast.Name) and value.id in self.bound:
                found.update(self.bound[value.id])
        return found


def _scan(module: ast.Module) -> _Scan:
    scan = _Scan(set(), set(), set(), {}, [])
    for node in ast.walk(module):
        if isinstance(node, FUNCTIONS):
            scan.bindable.add(node.name)
        elif isinstance(node, ast.Import):
            scan.modules.update(import_binding(alias) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            scan.imported.update(bound_name(alias) for alias in node.names)
        elif isinstance(node, ast.AnnAssign):
            scan.bind(node.target, _class_names(node.annotation))
        elif isinstance(node, ast.Assign):
            scan.assignment(node)
    scan.bindable.update(scan.modules, scan.imported)
    return scan


def _registration(
    node: ast.FunctionDef | ast.AsyncFunctionDef, top_level: bool, exports: frozenset[str]
) -> str:
    for decorator in node.decorator_list:
        name = decorator_name(decorator)
        if name not in TRANSPARENT_DECORATORS:
            return DECORATOR + name
    if top_level and node.name in exports:
        return EXPORTED
    return ""


class _Collector:
    def __init__(self, source: SourceText, module: ast.Module) -> None:
        self.source = source
        self.exports = _exports(module)
        self.scan = _scan(module)
        self.bindable = frozenset(self.scan.bindable)
        self.imported = frozenset(self.scan.imported)
        self.top_level = {id(statement) for statement in module.body}
        self.declared: list[DeclaredFunction] = []
        self.references: set[UsageReference] = set()
        self.stack: list[tuple[ast.AST, Unit, bool]] = [(module, (FIRST_LINE, FIRST_COLUMN), False)]

    def _push(self, nodes: list[ast.AST], unit: Unit) -> None:
        for node in reversed(nodes):
            self.stack.append((node, unit, False))

    def _scope(self, node: ast.AST, unit: Unit) -> None:
        """Decorators, defaults and bases are evaluated in the enclosing unit; the body is
        the scope's own unit."""
        assert isinstance(node, SCOPES)
        span = node_span(self.source, node)
        own = (span.line, span.column)
        outer: list[ast.AST] = []
        if not isinstance(node, ast.Lambda):
            outer.extend(node.decorator_list)
        if isinstance(node, ast.ClassDef):
            outer.extend(node.bases)
            outer.extend(keyword.value for keyword in node.keywords)
            self._push(outer, unit)
            self._push(list(node.body), own)
            return
        outer.extend(node.args.defaults)
        outer.extend(d for d in node.args.kw_defaults if d is not None)
        outer.extend(_annotations(node))
        self._push(outer, unit)
        if isinstance(node, ast.Lambda):
            self._push([node.body], own)
            return
        registered = _registration(node, id(node) in self.top_level, self.exports)
        self.declared.append(DeclaredFunction(span.line, span.column, registered))
        self._push(list(node.body), own)

    def _call(self, node: ast.Call, unit: Unit) -> None:
        self.stack.append((node.func, unit, True))
        if (
            isinstance(node.func, ast.Name)
            and node.func.id in ATTRIBUTE_FUNCTIONS
            and len(node.args) > ATTRIBUTE_ARGUMENT
        ):
            named = node.args[ATTRIBUTE_ARGUMENT]
            if isinstance(named, ast.Constant) and isinstance(named.value, str):
                self.references.add(UsageReference(unit[0], unit[1], named.value, member=True))
        self._push([*node.args, *(keyword.value for keyword in node.keywords)], unit)

    def _visit(self, node: ast.AST, unit: Unit, callee: bool) -> None:
        if isinstance(node, SCOPES):
            self._scope(node, unit)
            return
        if isinstance(node, ast.Call):
            self._call(node, unit)
            return
        if isinstance(node, ast.Name):
            if not callee and isinstance(node.ctx, ast.Load) and node.id in self.bindable:
                self.references.add(UsageReference(unit[0], unit[1], node.id, member=False))
            return
        if isinstance(node, ast.Attribute):
            # A method called on a call's result (`Guard(x).check()`) is named here: the
            # call graph records such a callee as an excerpt, not by its name.
            if not callee or not is_dotted(node.value):
                self.references.add(UsageReference(unit[0], unit[1], node.attr, member=True))
            self.stack.append((node.value, unit, False))
            return
        self._push(list(ast.iter_child_nodes(node)), unit)

    def run(self) -> UsageFacts:
        # A name __all__ lists that the file imports is re-exported: a use of it.
        for name in sorted(self.exports & self.imported):
            self.references.add(UsageReference(FIRST_LINE, FIRST_COLUMN, name, member=False))
        while len(self.stack) > 0:
            node, unit, callee = self.stack.pop()
            self._visit(node, unit, callee)
        references = sorted(self.references, key=lambda r: (r.line, r.column, r.name, r.member))
        handed = tuple(sorted(self.scan.handed()))
        return UsageFacts(
            declared=tuple(self.declared), references=tuple(references), handed=handed
        )


def collect_python_usage(source: SourceText, module: ast.Module) -> UsageFacts:
    return _Collector(source, module).run()
