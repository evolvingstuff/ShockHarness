"""The shapes of Python functions (DUP001, DUP002): what a body is once layout, comments,
the docstring and the names of its own values are set aside.

Tokens come in source order: a node's type, a name (renamed to ``v0``, ``v1``... by first
appearance when it is a parameter or a name the function binds; kept when it is not), an
attribute's name, and a constant's value. A string's mention of the file's own path or of
the function's own name (without leading underscores) is replaced, so that copies that
label themselves (``boundary="app/a.py:run"``, ``"run requires a string"``) compare equal.
"""

import ast

from shockharness.ir.model import SHAPE_FILE, SHAPE_MIN_STATEMENTS, SHAPE_NAME, FunctionShape
from shockharness.ir.python_catches import node_span
from shockharness.source import SourceText

FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
UNDERSCORE = "_"


def _body(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.stmt]:
    """The body without its docstring."""
    body = list(function.body)
    first = body[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
        if isinstance(first.value.value, str):
            return body[1:]
    return body


def _locals_and_statements(
    function: ast.FunctionDef | ast.AsyncFunctionDef, body: list[ast.stmt]
) -> tuple[set[str], int]:
    """The parameters and the names the body binds, and its statement count, in one
    walk."""
    arguments = function.args
    names = {a.arg for a in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]}
    for extra in (arguments.vararg, arguments.kwarg):
        if extra is not None:
            names.add(extra.arg)
    statements = 0
    for statement in body:
        for n in ast.walk(statement):
            if isinstance(n, ast.stmt):
                statements += 1
            elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                names.add(n.id)
    return names, statements


class _Tokens:
    def __init__(self, local: set[str], path: str, name: str) -> None:
        self.local = local
        self.path = path
        self.own = name.lstrip(UNDERSCORE)
        self.renamed: dict[str, str] = {}
        self.tokens: list[str] = []

    def _text(self, value: str) -> str:
        if self.path != "":
            value = value.replace(self.path, SHAPE_FILE)
        if self.own != "":
            value = value.replace(self.own, SHAPE_NAME)
        return value

    def _name(self, name: str) -> str:
        if name not in self.local:
            return name
        if name not in self.renamed:
            self.renamed[name] = f"v{len(self.renamed)}"
        return self.renamed[name]

    def _token(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return self._name(node.id)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str):
                return repr(self._text(node.value))
            return repr(node.value)
        if isinstance(node, ast.Attribute):
            return "." + node.attr
        return type(node).__name__

    def walk(self, body: list[ast.stmt]) -> tuple[str, ...]:
        stack: list[ast.AST] = list(reversed(body))
        while len(stack) > 0:
            node = stack.pop()
            if isinstance(node, ast.expr_context):
                continue
            self.tokens.append(self._token(node))
            stack.extend(reversed(list(ast.iter_child_nodes(node))))
        return tuple(self.tokens)


def collect_python_shapes(
    source: SourceText, module: ast.Module, path: str
) -> tuple[FunctionShape, ...]:
    owners = {
        id(child): node.name
        for node in ast.walk(module)
        if isinstance(node, ast.ClassDef)
        for child in node.body
    }
    shapes: list[FunctionShape] = []
    for node in ast.walk(module):
        if not isinstance(node, FUNCTIONS):
            continue
        body = _body(node)
        local, statements = _locals_and_statements(node, body)
        if statements < SHAPE_MIN_STATEMENTS:
            continue
        tokens = _Tokens(local, path, node.name).walk(body)
        span = node_span(source, node)
        owner = ""
        if id(node) in owners:
            owner = owners[id(node)]
        shapes.append(
            FunctionShape(
                span.line, span.column, span.end_line, node.name, owner, statements, tokens
            )
        )
    shapes.sort(key=lambda s: (s.line, s.column))
    return tuple(shapes)
