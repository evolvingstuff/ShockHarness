"""STATE002 facts: a shared object published before it is initialized (Python).

In one function, ``G = Thing(...)`` (``G`` named by a ``global`` statement of the
function) or ``self.X = Thing(...)`` (in a method that is not a constructor), followed by
a later statement of the same function that writes an attribute of it (``G.field =
...``). Between the two, another thread that reads the shared name sees the object
without the field. From MetaList: ``get_encryption_service_with_token`` published the
service, then set its ``dek``, so a concurrent cache hit got ``dek = None``.

"Newly constructed" is a call whose callee's last name is capitalized (a class). The
statements are taken in source order, nested functions and classes excluded; a
``return`` or another assignment to the name ends the window.
"""

import ast
from dataclasses import dataclass

from shockharness.constants import EVIDENCE_MAX_CHARS
from shockharness.ir.model import EarlyPublication
from shockharness.ir.python_catches import node_span
from shockharness.source import SourceText

SELF = "self"
SELF_PREFIX = "self."
CONSTRUCTORS = frozenset({"__init__", "__new__", "__post_init__", "setUp", "setup_method"})
NESTED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


@dataclass(frozen=True)
class _Published:
    statement: ast.stmt


def _callee_name(func: ast.expr) -> str:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _constructed(value: ast.expr | None) -> bool:
    """A call whose callee's last name is capitalized: a class being instantiated."""
    if not isinstance(value, ast.Call):
        return False
    name = _callee_name(value.func)
    return name != "" and name[0].isupper()


def _statements(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.stmt]:
    """The function's statements in source order, nested scopes excluded."""
    found: list[ast.stmt] = []
    stack: list[ast.AST] = list(function.body)
    while len(stack) > 0:
        node = stack.pop()
        if isinstance(node, NESTED_SCOPES):
            continue
        if isinstance(node, ast.stmt):
            found.append(node)
        stack.extend(child for child in ast.iter_child_nodes(node) if isinstance(child, ast.stmt))
    return sorted(found, key=lambda s: (s.lineno, s.col_offset))


def _shared_name(target: ast.expr, names: frozenset[str], in_method: bool) -> str | None:
    """The shared name an assignment target binds: a declared global, or ``self.X``."""
    if isinstance(target, ast.Name) and target.id in names:
        return target.id
    if in_method and isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
        if target.value.id == SELF:
            return SELF_PREFIX + target.attr
    return None


def _owner(target: ast.expr) -> str | None:
    """Whose attribute a target writes: ``G.x`` -> ``G``; ``self.X.y`` -> ``self.X``."""
    if not isinstance(target, ast.Attribute):
        return None
    owner = target.value
    if isinstance(owner, ast.Name):
        return owner.id
    if isinstance(owner, ast.Attribute) and isinstance(owner.value, ast.Name):
        if owner.value.id == SELF:
            return SELF_PREFIX + owner.attr
    return None


def _targets(statement: ast.stmt) -> tuple[list[ast.expr], ast.expr | None]:
    if isinstance(statement, ast.Assign):
        return list(statement.targets), statement.value
    if isinstance(statement, ast.AnnAssign | ast.AugAssign):
        return [statement.target], statement.value
    return [], None


def _excerpt(source: SourceText, statement: ast.stmt) -> str:
    return source.excerpt(statement.lineno)[:EVIDENCE_MAX_CHARS]


class _Function:
    def __init__(self, source: SourceText, function: ast.FunctionDef | ast.AsyncFunctionDef):
        self.source = source
        self.body = _statements(function)
        self.names = frozenset(n for s in self.body if isinstance(s, ast.Global) for n in s.names)
        self.in_method = function.name not in CONSTRUCTORS
        self.published: dict[str, _Published] = {}
        self.found: list[EarlyPublication] = []

    def scan(self) -> list[EarlyPublication]:
        for statement in self.body:
            if isinstance(statement, ast.Return):
                self.published = {}
                continue
            targets, value = _targets(statement)
            for target in targets:
                self._write(statement, target)
            for target in targets:
                self._bind(statement, target, value)
        return self.found

    def _write(self, statement: ast.stmt, target: ast.expr) -> None:
        owner = _owner(target)
        if owner is None or owner not in self.published:
            return
        first = self.published[owner].statement
        del self.published[owner]
        self.found.append(
            EarlyPublication(
                name=owner,
                published=node_span(self.source, first),
                written=node_span(self.source, statement),
                publish_text=_excerpt(self.source, first),
                write_text=_excerpt(self.source, statement),
            )
        )

    def _bind(self, statement: ast.stmt, target: ast.expr, value: ast.expr | None) -> None:
        name = _shared_name(target, self.names, self.in_method)
        if name is None:
            return
        if _constructed(value) and not isinstance(statement, ast.AugAssign):
            self.published[name] = _Published(statement)
        elif name in self.published:
            del self.published[name]


def collect_python_publications(
    source: SourceText, module: ast.Module
) -> tuple[EarlyPublication, ...]:
    found: list[EarlyPublication] = []
    for node in ast.walk(module):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            found.extend(_Function(source, node).scan())
    return tuple(sorted(found, key=lambda p: p.published))
