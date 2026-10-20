"""Python sentinel facts (MAGIC003): small numeric literals standing for a value."""

import ast
import re

from shockharness.constants import EVIDENCE_MAX_CHARS
from shockharness.ir.model import (
    SENTINEL_ARGUMENT,
    SENTINEL_ASSIGN,
    SENTINEL_ENTRY,
    SENTINEL_RETURN,
    SentinelUse,
)
from shockharness.ir.python_catches import dotted_name, node_span
from shockharness.source import SourceText

# An UPPER_SNAKE_CASE target is the name MAGIC003 asks for (NO_SELECTION = -1).
CONSTANT_NAME = re.compile(r"_*[A-Z][A-Z0-9_]*")
NUMERIC_TYPES = (int, float)
DOUBLE_STAR = "**"


def _number(node: ast.expr | None) -> float | None:
    """The value of a numeric literal, a chain of unary signs folded in; None otherwise."""
    if node is None:
        return None
    negative = False
    current = node
    while isinstance(current, ast.UnaryOp) and isinstance(current.op, ast.USub | ast.UAdd):
        if isinstance(current.op, ast.USub):
            negative = not negative
        current = current.operand
    if not isinstance(current, ast.Constant) or type(current.value) not in NUMERIC_TYPES:
        return None
    number = current.value
    assert isinstance(number, int | float), "NUMERIC_TYPES are int and float"
    value = float(number)
    if negative:
        return -value
    return value


def _text(source: SourceText, node: ast.expr) -> str:
    line = source.line_text(node.lineno).encode("utf-8")
    end = len(line)
    if node.end_lineno == node.lineno and node.end_col_offset is not None:
        end = node.end_col_offset
    text = " ".join(line[node.col_offset : end].decode("utf-8").split())
    return text[:EVIDENCE_MAX_CHARS]


def _named(target: ast.expr) -> bool:
    """A constant definition (or a field named like one): the value already has a name."""
    name = target.id if isinstance(target, ast.Name) else None
    if isinstance(target, ast.Attribute):
        name = target.attr
    return name is not None and CONSTANT_NAME.fullmatch(name) is not None


class _Collector:
    def __init__(self, source: SourceText) -> None:
        self.source = source
        self.found: list[SentinelUse] = []

    def add(self, value_node: ast.expr | None, kind: str, target: str) -> None:
        value = _number(value_node)
        if value is None or value_node is None:
            return
        raw = _text(self.source, value_node)
        self.found.append(SentinelUse(node_span(self.source, value_node), value, raw, kind, target))

    def assign(self, targets: list[ast.expr], value: ast.expr | None) -> None:
        for target in targets:
            if isinstance(target, ast.Name | ast.Attribute | ast.Subscript) and not _named(target):
                self.add(value, SENTINEL_ASSIGN, _text(self.source, target))

    def call(self, node: ast.Call) -> None:
        callee = dotted_name(node.func)
        if callee is None:
            return
        for argument in node.args:
            self.add(argument, SENTINEL_ARGUMENT, callee)
        for keyword in node.keywords:
            name = DOUBLE_STAR
            if keyword.arg is not None:
                name = keyword.arg
            self.add(keyword.value, SENTINEL_ARGUMENT, f"{callee}={name}")

    def visit(self, node: ast.AST) -> None:
        if isinstance(node, ast.Assign):
            self.assign(list(node.targets), node.value)
        elif isinstance(node, ast.AnnAssign | ast.NamedExpr):
            self.assign([node.target], node.value)
        elif isinstance(node, ast.Return):
            self.add(node.value, SENTINEL_RETURN, "")
        elif isinstance(node, ast.Lambda):
            self.add(node.body, SENTINEL_RETURN, "")
        elif isinstance(node, ast.Call):
            self.call(node)
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if key is not None:
                    self.add(value, SENTINEL_ENTRY, _text(self.source, key))


def collect_python_sentinels(source: SourceText, module: ast.Module) -> tuple[SentinelUse, ...]:
    collector = _Collector(source)
    for node in ast.walk(module):
        collector.visit(node)
    return tuple(sorted(collector.found, key=lambda s: s.span))
