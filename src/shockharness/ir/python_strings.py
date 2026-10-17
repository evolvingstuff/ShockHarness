"""Python string facts (MAGIC002): string literals that could be repeated constants."""

import ast
import re

from shockharness.ir.model import (
    STRING_ARGUMENT,
    STRING_COMPARE,
    STRING_KEY,
    STRING_SUBSCRIPT,
    STRING_VALUE,
    StringUse,
)
from shockharness.ir.python_catches import node_span
from shockharness.source import SourceText

DUNDER_ALL = "__all__"
CONSTANT_NAME = re.compile(r"_*[A-Z][A-Z0-9_]*")
DOCSTRING_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def _named(name: str) -> bool:
    return CONSTANT_NAME.fullmatch(name) is not None


def _dotted(node: ast.expr) -> str:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    if len(parts) > 0:
        return "." + ".".join(reversed(parts))
    return ""


def _all_parts(node: ast.AST | None) -> set[int]:
    if node is None:
        return set()
    return {id(part) for part in ast.walk(node)}


def _docstring(node: ast.AST) -> set[int]:
    if not isinstance(node, DOCSTRING_OWNERS) or len(node.body) == 0:
        return set()
    first = node.body[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
        return {id(first.value)}
    return set()


def _assigned(node: ast.AST) -> set[int]:
    """``__all__`` entries, and the value of a named definition (STATUS = "pending"),
    which is the remedy."""
    if isinstance(node, ast.Assign):
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if DUNDER_ALL in names:
            return _all_parts(node.value)
        if any(_named(name) for name in names):
            return {id(node.value)}
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        if _named(node.target.id) and node.value is not None:
            return {id(node.value)}
    return set()


def _annotation_parts(node: ast.AST) -> set[int]:
    if isinstance(node, ast.JoinedStr):
        return _all_parts(node)  # f-string parts
    if isinstance(node, ast.AnnAssign | ast.arg):
        return _all_parts(node.annotation)
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        return _all_parts(node.returns)
    return set()


def _skipped(module: ast.Module) -> set[int]:
    """Ids of string nodes that are never constants: docstrings, f-string parts,
    annotations, ``__all__`` entries, named definitions."""
    skipped: set[int] = set()
    for node in ast.walk(module):
        skipped |= _docstring(node) | _assigned(node) | _annotation_parts(node)
    return skipped


def _compared(node: ast.Compare) -> list[ast.expr]:
    """The operands of a comparison, and the elements of a literal collection among them
    (``x in ("a", "b")``)."""
    operands: list[ast.expr] = []
    for operand in [node.left, *node.comparators]:
        operands.append(operand)
        if isinstance(operand, ast.Tuple | ast.List | ast.Set):
            operands.extend(operand.elts)
    return operands


def _node_contexts(node: ast.AST) -> list[tuple[ast.AST, tuple[str, str]]]:
    if isinstance(node, ast.Call):
        callee = _dotted(node.func)
        arguments = [*node.args, *(k.value for k in node.keywords)]
        return [(argument, (STRING_ARGUMENT, callee)) for argument in arguments]
    if isinstance(node, ast.Subscript):
        return [(node.slice, (STRING_SUBSCRIPT, ""))]
    if isinstance(node, ast.Dict):
        return [(key, (STRING_KEY, "")) for key in node.keys if key is not None]
    if isinstance(node, ast.Compare):
        return [(operand, (STRING_COMPARE, "")) for operand in _compared(node)]
    return []


def _contexts(module: ast.Module) -> dict[int, tuple[str, str]]:
    """The position of each string node that is a direct child of an interesting parent."""
    found: dict[int, tuple[str, str]] = {}
    for node in ast.walk(module):
        for child, context in _node_contexts(node):
            found[id(child)] = context
    return found


def collect_python_strings(source: SourceText, module: ast.Module) -> tuple[StringUse, ...]:
    skipped = _skipped(module)
    contexts = _contexts(module)
    found: list[StringUse] = []
    for node in ast.walk(module):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in skipped:
            continue
        kind, callee = STRING_VALUE, ""
        if id(node) in contexts:
            kind, callee = contexts[id(node)]
        found.append(StringUse(node_span(source, node), node.value, kind, callee))
    return tuple(sorted(found, key=lambda s: s.span))
