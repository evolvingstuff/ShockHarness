"""JavaScript and TypeScript string facts (MAGIC002), the counterpart of
ir/python_strings.py.

Recorded: plain string literals and templates without substitutions. Never recorded:
import and export specifiers, ``require(...)`` / ``import(...)`` arguments, directives
(``"use strict"``), the parts of a template with substitutions, and anything inside a
TypeScript type (``type Mode = "a" | "b"``)."""

import re

from tree_sitter import Node

from shockharness.ir.javascript_catches import node_span, node_text
from shockharness.ir.javascript_functions import dotted_name, string_value
from shockharness.ir.javascript_nodes import Field, Kind
from shockharness.ir.model import (
    STRING_ARGUMENT,
    STRING_COMPARE,
    STRING_JSX,
    STRING_KEY,
    STRING_SUBSCRIPT,
    STRING_VALUE,
    StringUse,
)
from shockharness.source import SourceText

COMPARISONS = frozenset({"===", "!==", "==", "!="})
CONSTANT_NAME = re.compile(r"_*[A-Z][A-Z0-9_]*")
MODULE_LOADERS = frozenset({"require", Kind.IMPORT})
TYPE_NODES = frozenset(
    {
        Kind.TYPE_ANNOTATION,
        Kind.TYPE_ALIAS_DECLARATION,
        Kind.INTERFACE_DECLARATION,
        Kind.TYPE_ARGUMENTS,
        Kind.TYPE_PARAMETERS,
        Kind.LITERAL_TYPE,
    }
)
JSX_ATTRIBUTES = frozenset({Kind.JSX_ATTRIBUTE})


def _template_value(node: Node) -> str | None:
    """The text of a template without substitutions (`` `pending` ``)."""
    if any(child.type == Kind.TEMPLATE_SUBSTITUTION for child in node.named_children):
        return None
    text = node_text(node)
    return text[1 : len(text) - 1]


def _value(node: Node) -> str | None:
    if node.type == Kind.STRING:
        return string_value(node)
    if node.type == Kind.TEMPLATE_STRING:
        return _template_value(node)
    return None


def _in_type(node: Node) -> bool:
    current = node.parent
    while current is not None:
        if current.type in TYPE_NODES:
            return True
        current = current.parent
    return False


def _call_context(parent: Node) -> tuple[str, str] | None:
    """For a string in ``arguments``: (kind, callee), or None for a module loader."""
    call = parent.parent
    if call is None:
        return (STRING_ARGUMENT, "")
    function = call.child_by_field_name(Field.FUNCTION)
    if function is None:
        function = call.child_by_field_name(Field.CONSTRUCTOR)
    if function is None:
        return (STRING_ARGUMENT, "")
    if function.type == Kind.IMPORT or node_text(function) in MODULE_LOADERS:
        return None
    dotted = dotted_name(function)
    if dotted is None:
        return (STRING_ARGUMENT, node_text(function))
    return (STRING_ARGUMENT, dotted)


def _context(node: Node) -> tuple[str, str] | None:
    """(kind, callee) of a string node, or None when it is never a constant."""
    parent = node.parent
    if parent is None:
        return (STRING_VALUE, "")
    if parent.type in (Kind.IMPORT_STATEMENT, Kind.EXPORT_STATEMENT, Kind.EXPRESSION_STATEMENT):
        return None  # a module specifier, or a directive / bare statement
    if parent.type == Kind.ARGUMENTS:
        return _call_context(parent)
    name = parent.child_by_field_name(Field.NAME)
    if parent.type == Kind.VARIABLE_DECLARATOR and name is not None:
        if CONSTANT_NAME.fullmatch(node_text(name)) is not None:
            return None  # a named definition (const STATUS = "pending"), the remedy
    return (_position(node, parent), "")


def _position(node: Node, parent: Node) -> str:
    """The kind of a string that is not an argument."""
    if parent.type == Kind.PAIR and parent.child_by_field_name(Field.KEY) == node:
        return STRING_KEY
    if parent.type == Kind.SUBSCRIPT_EXPRESSION:
        return STRING_SUBSCRIPT
    if parent.type in JSX_ATTRIBUTES:
        return STRING_JSX
    if parent.type == Kind.SWITCH_CASE:
        return STRING_COMPARE
    operator = parent.child_by_field_name(Field.OPERATOR)
    if parent.type == Kind.BINARY_EXPRESSION and operator is not None:
        if node_text(operator) in COMPARISONS:
            return STRING_COMPARE
    return STRING_VALUE


def collect_javascript_strings(source: SourceText, root: Node) -> tuple[StringUse, ...]:
    found: list[StringUse] = []
    stack: list[Node] = [root]
    while len(stack) > 0:
        node = stack.pop()
        value = _value(node)
        if value is None:
            stack.extend(node.named_children)
            continue
        context = _context(node)
        if context is None or _in_type(node):
            continue
        kind, callee = context
        found.append(StringUse(node_span(source, node), value, kind, callee))
    return tuple(sorted(found, key=lambda s: s.span))
