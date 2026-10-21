"""JavaScript and TypeScript numbers written as something else (MAGIC005); see ``Disguise``
in the model. The counterpart of :mod:`.python_disguises`, read from the syntax alone."""

import math

from tree_sitter import Node

from shockharness.ir.javascript_catches import node_span, node_text, scope_for
from shockharness.ir.javascript_functions import dotted_name, string_value
from shockharness.ir.javascript_nodes import Field, Kind
from shockharness.ir.javascript_receivers import const_declarators
from shockharness.ir.model import (
    DISGUISE_CONVERSION,
    DISGUISE_INDENT,
    DISGUISE_LENGTH,
    DISGUISE_PARSED,
    MODULE_SCOPE,
    Disguise,
)
from shockharness.ir.python_disguises import NUMBER, SPACE, TEXT_LIMIT, numbers_in
from shockharness.ir.tree_sitter_common import call_arguments
from shockharness.source import SourceText

LENGTH = "length"
CONVERSIONS = frozenset({"Number", "parseInt", "parseFloat"})
PARSE = "JSON.parse"
STRINGIFY = "JSON.stringify"
STRINGIFY_INDENT = 2  # JSON.stringify(value, replacer, space): the position of space
UNARY_PLUS = "+"
BACKTICK = "`"


def _shown(node: Node) -> str:
    text = node_text(node).replace("\n", " ")
    if len(text) > TEXT_LIMIT:
        return text[:TEXT_LIMIT] + "..."
    return text


def _literal_text(node: Node) -> str | None:
    """The text of a string literal, or of a template literal with no substitution."""
    if node.type == Kind.STRING:
        return string_value(node)
    if node.type == Kind.TEMPLATE_STRING:
        if any(c.type == Kind.TEMPLATE_SUBSTITUTION for c in node.named_children):
            return None
        return node_text(node).removeprefix(BACKTICK).removesuffix(BACKTICK)
    return None


def converted_number(text: str) -> int | float | None:
    stripped = text.strip()
    if NUMBER.fullmatch(stripped) is None:
        return None
    value = float(stripped)
    if not math.isfinite(value):
        return None
    if value.is_integer() and "." not in stripped:
        return int(stripped)
    return value


def _call(call: Node, spaces: dict[str, int]) -> tuple[str, tuple[int | float, ...]] | None:
    function = call.child_by_field_name(Field.FUNCTION)
    if function is None:
        return None
    callee = dotted_name(function)
    arguments = call_arguments(call)
    if callee is None or len(arguments) == 0:
        return None
    text = _literal_text(arguments[0])
    if text is not None:
        found = _of_text(callee, text)
        if found is not None:
            return found
    if callee == STRINGIFY and len(arguments) > STRINGIFY_INDENT:
        return _indent(arguments[STRINGIFY_INDENT], spaces)
    return None


def _indent(argument: Node, spaces: dict[str, int]) -> tuple[str, tuple[int, ...]] | None:
    """``"  "``, or a module-level ``const`` bound to a string of spaces."""
    space = _literal_text(argument)
    if space is not None and set(space) == {SPACE}:
        return DISGUISE_INDENT, (len(space),)
    if argument.type == Kind.IDENTIFIER and node_text(argument) in spaces:
        return DISGUISE_INDENT, (spaces[node_text(argument)],)
    return None


def _module_spaces(root: Node) -> dict[str, int]:
    """Module-level ``const NAME = "  "`` (exported or not): name -> its length. A
    ``const`` is never rebound."""
    found: dict[str, int] = {}
    for statement in root.named_children:
        declaration = statement
        if statement.type == Kind.EXPORT_STATEMENT:
            inner = statement.child_by_field_name(Field.DECLARATION)
            if inner is None:
                continue
            declaration = inner
        for name, value in const_declarators(declaration):
            text = _literal_text(value)
            if text is not None and set(text) == {SPACE}:
                found[name] = len(text)
    return found


def _of_text(callee: str, text: str) -> tuple[str, tuple[int | float, ...]] | None:
    """``Number("3000")`` and the like, or ``JSON.parse`` of a literal text."""
    if callee in CONVERSIONS:
        value = converted_number(text)
        if value is not None:
            return DISGUISE_CONVERSION, (value,)
    if callee == PARSE:
        numbers = numbers_in(text)
        if len(numbers) > 0:
            return DISGUISE_PARSED, numbers
    return None


def _length(member: Node) -> tuple[str, tuple[int | float, ...]] | None:
    """``"  ".length`` (whitespace only) or ``[a, b].length``."""
    prop = member.child_by_field_name(Field.PROPERTY)
    receiver = member.child_by_field_name(Field.OBJECT)
    if prop is None or receiver is None or node_text(prop) != LENGTH:
        return None
    text = _literal_text(receiver)
    if text is not None:
        if not text.isspace():
            return None  # a string whose content means something ("YYYY-MM-DD")
        return DISGUISE_LENGTH, (len(text),)
    if receiver.type == Kind.ARRAY:
        elements = [c for c in receiver.named_children if c.type != Kind.COMMENT]
        if not any(e.type == Kind.SPREAD_ELEMENT for e in elements):
            return DISGUISE_LENGTH, (len(elements),)
    return None


def _unary(node: Node) -> tuple[str, tuple[int | float, ...]] | None:
    """``+"30"``."""
    operator = node.child_by_field_name(Field.OPERATOR)
    argument = node.child_by_field_name(Field.ARGUMENT)
    if operator is None or argument is None or node_text(operator) != UNARY_PLUS:
        return None
    text = _literal_text(argument)
    if text is None:
        return None
    value = converted_number(text)
    if value is None:
        return None
    return DISGUISE_CONVERSION, (value,)


def _disguise(node: Node, spaces: dict[str, int]) -> tuple[str, tuple[int | float, ...]] | None:
    if node.type == Kind.CALL_EXPRESSION:
        return _call(node, spaces)
    if node.type == Kind.MEMBER_EXPRESSION:
        return _length(node)
    if node.type == Kind.UNARY_EXPRESSION:
        return _unary(node)
    return None


def collect_javascript_disguises(source: SourceText, root: Node) -> tuple[Disguise, ...]:
    found: list[Disguise] = []
    spaces = _module_spaces(root)
    stack: list[tuple[Node, str]] = [(root, MODULE_SCOPE)]
    while len(stack) > 0:
        node, scope = stack.pop()
        disguise = _disguise(node, spaces)
        if disguise is not None:
            kind, values = disguise
            found.append(Disguise(node_span(source, node), kind, values, _shown(node), scope))
        child_scope = scope_for(node, scope)
        stack.extend((child, child_scope) for child in node.named_children)
    found.sort(key=lambda d: d.span)
    return tuple(found)
