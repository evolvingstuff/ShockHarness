"""STATE003 facts: state read outside the lock that guards its writes (Python).

In a class, a lock is an attribute taken as ``with self.<lock>:`` whose name says it is one
(``lock``, ``mutex``, ``cond``, ``guard``, ``sem``). An attribute is guarded when a method
other than a constructor assigns ``self.<attr>`` inside such a ``with``. A read of it
outside every lock is recorded when the value is acted on (it is an ``if`` / ``while`` /
``assert`` / conditional-expression test, or an argument of a call that is not logging) in
a method that does not itself run with the lock held: one named ``*_locked``, or one that
every call in the class (``self.m(...)``) makes under the lock or from such a method, to a
fixpoint. A module works the same way with module-level locks and ``global`` names.
"""

import ast
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from shockharness.ir.model import UnlockedRead
from shockharness.ir.python_catches import node_span
from shockharness.source import SourceText

FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
WITHS = (ast.With, ast.AsyncWith)
TESTED = (ast.If, ast.While, ast.IfExp, ast.Assert)
LOCK_WORDS = ("lock", "mutex", "cond", "guard", "sem")
LOCKED_SUFFIX = "_locked"
CONSTRUCTORS = frozenset({"__init__", "__new__", "__post_init__", "__del__"})
LOGGING = frozenset(
    {"bind", "debug", "info", "warning", "warn", "error", "exception", "critical", "log"}
)
SELF = "self"


def _lock_like(name: str) -> bool:
    lowered = name.lower()
    return any(word in lowered for word in LOCK_WORDS)


def _self_attribute(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        if node.value.id == SELF:
            return node.attr
    return None


def _taken(statement: ast.With | ast.AsyncWith, members: bool) -> set[str]:
    """The names a ``with`` takes: ``self.<attr>`` (members) or module names."""
    found: set[str] = set()
    for item in statement.items:
        expression = item.context_expr
        name = _self_attribute(expression) if members else None
        if not members and isinstance(expression, ast.Name):
            name = expression.id
        if name is not None:
            found.add(name)
    return found


@dataclass(frozen=True)
class _Locks:
    names: frozenset[str]
    members: bool  # self.<lock> rather than a module name

    def spelled(self, name: str) -> str:
        return f"{SELF}.{name}" if self.members else name


def _walk(
    function: ast.FunctionDef | ast.AsyncFunctionDef, locks: _Locks
) -> Iterator[tuple[ast.AST, bool]]:
    """Every node of the function with whether one of the locks is held there (nested
    functions and classes left out)."""
    stack: list[tuple[ast.AST, bool]] = [(statement, False) for statement in function.body]
    while len(stack) > 0:
        node, held = stack.pop()
        if isinstance(node, SCOPES):
            continue
        yield node, held
        if isinstance(node, WITHS) and len(_taken(node, members=locks.members) & locks.names) > 0:
            stack.extend((item.context_expr, held) for item in node.items)
            stack.extend((statement, True) for statement in node.body)
            continue
        stack.extend((child, held) for child in ast.iter_child_nodes(node))


def _callee(call: ast.Call) -> str | None:
    function = call.func
    if isinstance(function, ast.Attribute):
        return function.attr
    if isinstance(function, ast.Name):
        return function.id
    return None


def _acted_on(parents: dict[ast.AST, ast.AST], node: ast.AST) -> bool:
    """The read is a test, or an argument of a call that is not logging."""
    child = node
    while child in parents:
        parent = parents[child]
        if isinstance(parent, TESTED) and child is parent.test:
            return True
        if isinstance(parent, ast.Call) and child is not parent.func:
            return _callee(parent) not in LOGGING
        if isinstance(parent, ast.stmt):
            return False
        child = parent
    return False


def _assigned(node: ast.AST) -> list[ast.expr]:
    if isinstance(node, ast.Assign):
        return list(node.targets)
    if isinstance(node, ast.AugAssign | ast.AnnAssign):
        return [node.target]
    return []


def _writes_under(
    function: ast.FunctionDef | ast.AsyncFunctionDef, locks: _Locks
) -> Iterator[tuple[ast.expr, ast.stmt]]:
    """(target, statement) for every assignment the function makes holding a lock."""
    for node, held in _walk(function, locks):
        if held and isinstance(node, ast.stmt):
            for target in _assigned(node):
                yield target, node


class _Class:
    def __init__(self, source: SourceText, cls: ast.ClassDef) -> None:
        self.source = source
        self.cls = cls
        self.methods = [m for m in cls.body if isinstance(m, FUNCTIONS)]
        names: set[str] = set()
        for method in self.methods:
            for node in ast.walk(method):
                if isinstance(node, WITHS):
                    names.update(_taken(node, members=True))
        self.locks = _Locks(frozenset(n for n in names if _lock_like(n)), members=True)

    def guarded(self) -> dict[str, tuple[str, ast.stmt]]:
        """attribute -> (the method that writes it under a lock, the write)."""
        found: dict[str, tuple[str, ast.stmt]] = {}
        for method in self.methods:
            if method.name in CONSTRUCTORS:
                continue
            for target, statement in _writes_under(method, self.locks):
                name = _self_attribute(target)
                if name is not None and name not in self.locks.names and name not in found:
                    found[name] = (method.name, statement)
        return found

    def _calls(self) -> list[tuple[str, str, bool]]:
        """(callee, caller, under a lock) for every ``self.m(...)`` of a method here."""
        names = {m.name for m in self.methods}
        found: list[tuple[str, str, bool]] = []
        for method in self.methods:
            for node, held in _walk(method, self.locks):
                callee = _self_attribute(node.func) if isinstance(node, ast.Call) else None
                if callee is not None and callee in names:
                    found.append((callee, method.name, held))
        return found

    def held_methods(self) -> set[str]:
        held = {m.name for m in self.methods if m.name.endswith(LOCKED_SUFFIX)}
        calls = self._calls()
        callees = {callee for callee, _caller, _under in calls}
        changed = True
        while changed:
            changed = False
            for callee in callees - held:
                sites = [(caller, under) for c, caller, under in calls if c == callee]
                if all(under or caller in held for caller, under in sites):
                    held.add(callee)
                    changed = True
        return held

    def reads(self, parents: dict[ast.AST, ast.AST]) -> list[UnlockedRead]:
        if len(self.locks.names) == 0:
            return []
        guarded = self.guarded()
        skipped = self.held_methods() | CONSTRUCTORS
        methods = [m for m in self.methods if m.name not in skipped]
        return [read for m in methods for read in self._method_reads(m, guarded, parents)]

    def _method_reads(
        self,
        method: ast.FunctionDef | ast.AsyncFunctionDef,
        guarded: dict[str, tuple[str, ast.stmt]],
        parents: dict[ast.AST, ast.AST],
    ) -> list[UnlockedRead]:
        found: list[UnlockedRead] = []
        seen: set[str] = set()
        for node, held in _walk(method, self.locks):
            if held or not isinstance(node, ast.Attribute) or not isinstance(node.ctx, ast.Load):
                continue
            name = _self_attribute(node)
            if name is None or name not in guarded or name in seen:
                continue
            if _acted_on(parents, node):
                seen.add(name)
                writer, write = guarded[name]
                scope = f"{self.cls.name}.{method.name}"
                found.append(self._read(node, scope, f"{SELF}.{name}", writer, write))
        return found

    def _read(
        self, node: ast.expr, scope: str, name: str, writer: str, write: ast.stmt
    ) -> UnlockedRead:
        return _unlocked(self.source, node, scope, name, self.locks, writer, write)


def _unlocked(
    source: SourceText,
    node: ast.expr,
    scope: str,
    name: str,
    locks: _Locks,
    writer: str,
    write: ast.stmt,
) -> UnlockedRead:
    return UnlockedRead(
        span=node_span(source, node),
        scope=scope,
        name=name,
        locks=tuple(sorted(locks.spelled(lock) for lock in locks.names)),
        writer=writer,
        written=node_span(source, write),
    )


def _declared(function: ast.AST) -> set[str]:
    return {
        name for node in ast.walk(function) if isinstance(node, ast.Global) for name in node.names
    }


def _stored(function: ast.AST) -> set[str]:
    return {
        node.id
        for node in ast.walk(function)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    }


class _Module:
    def __init__(self, source: SourceText, module: ast.Module) -> None:
        self.source = source
        self.functions = [f for f in module.body if isinstance(f, FUNCTIONS)]
        names = {
            target.id
            for statement in module.body
            if isinstance(statement, ast.Assign)
            for target in statement.targets
            if isinstance(target, ast.Name) and _lock_like(target.id)
        }
        self.locks = _Locks(frozenset(names), members=False)

    def guarded(self) -> dict[str, tuple[str, ast.stmt]]:
        found: dict[str, tuple[str, ast.stmt]] = {}
        for function in self.functions:
            declared = _declared(function)
            for target, statement in _writes_under(function, self.locks):
                if (
                    isinstance(target, ast.Name)
                    and target.id in declared
                    and target.id not in found
                ):
                    found[target.id] = (function.name, statement)
        return found

    def reads(self, parents: dict[ast.AST, ast.AST]) -> list[UnlockedRead]:
        if len(self.locks.names) == 0:
            return []
        guarded = self.guarded()
        return [r for f in self.functions for r in self._function_reads(f, guarded, parents)]

    def _function_reads(
        self,
        function: ast.FunctionDef | ast.AsyncFunctionDef,
        guarded: dict[str, tuple[str, ast.stmt]],
        parents: dict[ast.AST, ast.AST],
    ) -> list[UnlockedRead]:
        shadowed = _stored(function) - _declared(function)
        found: list[UnlockedRead] = []
        seen: set[str] = set()
        for node, held in _walk(function, self.locks):
            if held or not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load):
                continue
            name = node.id
            if name not in guarded or name in shadowed or name in seen:
                continue
            writer, write = guarded[name]
            if writer != function.name and _acted_on(parents, node):
                seen.add(name)
                found.append(
                    _unlocked(self.source, node, function.name, name, self.locks, writer, write)
                )
        return found


def collect_python_unlocked_reads(
    source: SourceText, module: ast.Module
) -> tuple[UnlockedRead, ...]:
    parents = {
        child: parent for parent in ast.walk(module) for child in ast.iter_child_nodes(parent)
    }
    found: Sequence[UnlockedRead] = _Module(source, module).reads(parents)
    classes = [node for node in ast.walk(module) if isinstance(node, ast.ClassDef)]
    found = [*found, *(read for cls in classes for read in _Class(source, cls).reads(parents))]
    return tuple(sorted(found, key=lambda read: read.span))
