"""JavaScript and TypeScript sentinel facts (MAGIC003): small numeric literals standing for
a value. The counterpart of ir/python_sentinels.py."""

import re
from collections.abc import Callable

from tree_sitter import Node

from shockharness.constants import EVIDENCE_MAX_CHARS
from shockharness.ir.javascript_catches import (
    FIELD_DEFINITIONS,
    FIELD_NAME_FIELDS,
    TYPE_WRAPPERS,
    node_span,
    node_text,
)
from shockharness.ir.javascript_functions import dotted_name
from shockharness.ir.javascript_nodes import Field, Kind
from shockharness.ir.javascript_numbers import parse_js_number
from shockharness.ir.model import (
    SENTINEL_ARGUMENT,
    SENTINEL_ASSIGN,
    SENTINEL_ENTRY,
    SENTINEL_RETURN,
    SentinelUse,
)
from shockharness.source import SourceText

CONSTANT_NAME = re.compile(r"_*[A-Z][A-Z0-9_]*")
SIGNS = frozenset({"-", "+"})
NUMBER = Kind.NUMBER
CALLS = frozenset({Kind.CALL_EXPRESSION, Kind.NEW_EXPRESSION})


def _unwrapped(node: Node) -> Node | None:
    """The value inside parentheses and TypeScript type wrappers (``-1 as number``)."""
    current = node
    while current.type in TYPE_WRAPPERS or current.type == Kind.PARENTHESIZED_EXPRESSION:
        inner = [c for c in current.named_children if c.type != Kind.COMMENT]
        if len(inner) == 0:
            return None
        current = inner[0]
    return current


def _signed(node: Node) -> tuple[Node, bool] | None:
    """(the number under a chain of unary signs, negated); None for any other operator."""
    negative = False
    current = node
    while current.type == Kind.UNARY_EXPRESSION:
        operator = current.child_by_field_name(Field.OPERATOR)
        argument = current.child_by_field_name(Field.ARGUMENT)
        if operator is None or argument is None or node_text(operator) not in SIGNS:
            return None
        if node_text(operator) == "-":
            negative = not negative
        inner = _unwrapped(argument)
        if inner is None:
            return None
        current = inner
    return current, negative


def _number(node: Node | None) -> float | None:
    """The value of a numeric literal, unary signs and type wrappers folded in."""
    if node is None:
        return None
    unwrapped = _unwrapped(node)
    signed = None if unwrapped is None else _signed(unwrapped)
    if signed is None:
        return None
    number, negative = signed
    if number.type != NUMBER or not number.is_named:
        return None
    value = float(parse_js_number(node_text(number)))
    if negative:
        return -value
    return value


def _excerpt(node: Node) -> str:
    return " ".join(node_text(node).split("\n")[0].split())[:EVIDENCE_MAX_CHARS]


def _named(target: Node | None) -> bool:
    """An UPPER_SNAKE_CASE name (NO_SELECTION = -1) is the name MAGIC003 asks for."""
    if target is None:
        return False
    name = target
    if target.type == Kind.MEMBER_EXPRESSION:
        prop = target.child_by_field_name(Field.PROPERTY)
        if prop is None:
            return False
        name = prop
    return CONSTANT_NAME.fullmatch(node_text(name)) is not None


class _Collector:
    def __init__(self, source: SourceText) -> None:
        self.source = source
        self.found: list[SentinelUse] = []

    def add(self, value_node: Node | None, kind: str, target: str) -> None:
        value = _number(value_node)
        if value is None or value_node is None:
            return
        span = node_span(self.source, value_node)
        self.found.append(SentinelUse(span, value, _excerpt(value_node), kind, target))

    def assigned(self, target: Node | None, value: Node | None) -> None:
        if target is not None and not _named(target):
            self.add(value, SENTINEL_ASSIGN, _excerpt(target))

    def call(self, node: Node) -> None:
        function = node.child_by_field_name(Field.FUNCTION)
        if function is None:
            function = node.child_by_field_name(Field.CONSTRUCTOR)
        arguments = node.child_by_field_name(Field.ARGUMENTS)
        callee = None if function is None else dotted_name(function)
        if callee is None or arguments is None or arguments.type != Kind.ARGUMENTS:
            return
        for argument in arguments.named_children:
            self.add(argument, SENTINEL_ARGUMENT, callee)

    def visit(self, node: Node) -> None:
        if node.type in VISITORS:
            VISITORS[node.type](self, node)


def _declarator(collector: _Collector, node: Node) -> None:
    collector.assigned(node.child_by_field_name(Field.NAME), node.child_by_field_name(Field.VALUE))


def _assignment(collector: _Collector, node: Node) -> None:
    collector.assigned(node.child_by_field_name(Field.LEFT), node.child_by_field_name(Field.RIGHT))


def _field(collector: _Collector, node: Node) -> None:
    name = node.child_by_field_name(FIELD_NAME_FIELDS[node.type])
    collector.assigned(name, node.child_by_field_name(Field.VALUE))


def _return(collector: _Collector, node: Node) -> None:
    values = [c for c in node.named_children if c.type != Kind.COMMENT]
    if len(values) == 1:
        collector.add(values[0], SENTINEL_RETURN, "")


def _arrow(collector: _Collector, node: Node) -> None:
    body = node.child_by_field_name(Field.BODY)
    if body is not None and body.type != Kind.STATEMENT_BLOCK:
        collector.add(body, SENTINEL_RETURN, "")


def _call(collector: _Collector, node: Node) -> None:
    collector.call(node)


def _pair(collector: _Collector, node: Node) -> None:
    key = node.child_by_field_name(Field.KEY)
    if key is not None:
        collector.add(node.child_by_field_name(Field.VALUE), SENTINEL_ENTRY, _excerpt(key))


VISITORS: dict[str, Callable[[_Collector, Node], None]] = {
    Kind.VARIABLE_DECLARATOR: _declarator,
    Kind.ASSIGNMENT_EXPRESSION: _assignment,
    Kind.RETURN_STATEMENT: _return,
    Kind.ARROW_FUNCTION: _arrow,
    Kind.PAIR: _pair,
    **{kind: _field for kind in FIELD_DEFINITIONS},
    **{kind: _call for kind in CALLS},
}


def collect_javascript_sentinels(source: SourceText, root: Node) -> tuple[SentinelUse, ...]:
    collector = _Collector(source)
    stack: list[Node] = [root]
    while len(stack) > 0:
        node = stack.pop()
        collector.visit(node)
        stack.extend(node.named_children)
    return tuple(sorted(collector.found, key=lambda s: s.span))
