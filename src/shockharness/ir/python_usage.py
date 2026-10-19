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

from shockharness.constants import FIRST_COLUMN, FIRST_LINE
from shockharness.ir.model import DeclaredFunction, UsageFacts, UsageReference
from shockharness.ir.python_catches import bound_name, node_span
from shockharness.ir.python_functions import import_binding
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


def _decorator_name(decorator: ast.expr) -> str:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return ""


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


def _bindable(module: ast.Module) -> frozenset[str]:
    """Names a bare reference may mean a project function by: every def in the file and
    every name an import binds."""
    names: set[str] = set()
    for node in ast.walk(module):
        if isinstance(node, FUNCTIONS):
            names.add(node.name)
        elif isinstance(node, ast.Import):
            names.update(import_binding(alias) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update(bound_name(alias) for alias in node.names)
    return frozenset(names)


def _imported(module: ast.Module) -> frozenset[str]:
    return frozenset(
        bound_name(alias)
        for node in ast.walk(module)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    )


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


def _registration(
    node: ast.FunctionDef | ast.AsyncFunctionDef, top_level: bool, exports: frozenset[str]
) -> str:
    for decorator in node.decorator_list:
        name = _decorator_name(decorator)
        if name not in TRANSPARENT_DECORATORS:
            return DECORATOR + name
    if top_level and node.name in exports:
        return EXPORTED
    return ""


class _Collector:
    def __init__(self, source: SourceText, module: ast.Module) -> None:
        self.source = source
        self.exports = _exports(module)
        self.bindable = _bindable(module)
        self.imported = _imported(module)
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
            if not callee:
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
        return UsageFacts(declared=tuple(self.declared), references=tuple(references))


def collect_python_usage(source: SourceText, module: ast.Module) -> UsageFacts:
    return _Collector(source, module).run()
