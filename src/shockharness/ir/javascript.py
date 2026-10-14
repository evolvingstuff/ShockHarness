"""JavaScript adapter built on tree-sitter with the pinned JavaScript grammar.

tree-sitter recovers from syntax errors instead of raising. Any ``ERROR`` or
``MISSING`` node anywhere in the tree is therefore treated as a parse failure
(spec section 3); a tree with error nodes is never analyzed as if complete.
"""

import re
from importlib import metadata

import tree_sitter_javascript
from tree_sitter import Language, Node, Parser

from shockharness.constants import (
    EVIDENCE_MAX_CHARS,
    FIRST_LINE,
    RADIX_BINARY,
    RADIX_DECIMAL,
    RADIX_HEX,
    RADIX_OCTAL,
)
from shockharness.ir.model import (
    ANONYMOUS_SCOPE,
    MODULE_SCOPE,
    Comment,
    ModuleFacts,
    NumericLiteral,
    ParseFailure,
    Span,
)
from shockharness.source import SourceText

_LANGUAGE = Language(tree_sitter_javascript.language())
_PARSER = Parser(_LANGUAGE)

PARSER_NAME = "tree-sitter-javascript " + metadata.version("tree-sitter-javascript")

NUMBER = "number"
UNARY = "unary_expression"
COMMENT = "comment"
SIGN_OPERATORS = frozenset({"-", "+"})
NAMED_SCOPE_TYPES = frozenset(
    {
        "function_declaration",
        "generator_function_declaration",
        "class_declaration",
        "method_definition",
    }
)
ANONYMOUS_FUNCTION_TYPES = frozenset(
    {"arrow_function", "function_expression", "generator_function", "class"}
)

LEGACY_OCTAL = re.compile(r"0[0-7]+")
DECIMAL_INTEGER = re.compile(r"[0-9]+")


def parse_js_number(raw: str) -> int | float:
    """Decode a JavaScript numeric literal the grammar has already accepted.

    Handles ``_`` separators, ``0x``/``0o``/``0b`` prefixes, legacy octal
    (``017``), BigInt ``n`` suffix, and decimal/exponent floats. Because the
    token is grammar-validated, no branch here can fail.
    """
    text = raw.replace("_", "").lower()
    if text.endswith("n"):
        text = text[: len(text) - len("n")]
    if text.startswith("0x"):
        return int(text[len("0x") :], RADIX_HEX)
    if text.startswith("0o"):
        return int(text[len("0o") :], RADIX_OCTAL)
    if text.startswith("0b"):
        return int(text[len("0b") :], RADIX_BINARY)
    if LEGACY_OCTAL.fullmatch(text) is not None:
        return int(text, RADIX_OCTAL)
    if DECIMAL_INTEGER.fullmatch(text) is not None:
        return int(text, RADIX_DECIMAL)
    return float(text)


def _span(source: SourceText, node: Node) -> Span:
    start_line = node.start_point.row + FIRST_LINE
    end_line = node.end_point.row + FIRST_LINE
    return Span(
        line=start_line,
        column=source.column_from_byte_offset(start_line, node.start_point.column),
        end_line=end_line,
        end_column=source.column_from_byte_offset(end_line, node.end_point.column),
    )


def _text(node: Node) -> str:
    if node.text is None:
        return ""
    return node.text.decode("utf-8", errors="replace")


def _fold_unary(node: Node) -> tuple[Node, bool] | None:
    negative = False
    current = node
    while current.type == UNARY:
        operator = current.child_by_field_name("operator")
        argument = current.child_by_field_name("argument")
        if operator is None or argument is None or _text(operator) not in SIGN_OPERATORS:
            return None
        if _text(operator) == "-":
            negative = not negative
        current = argument
    if current is node or current.type != NUMBER:
        return None
    return current, negative


def _first_error(root: Node) -> Node | None:
    stack = [root]
    while len(stack) > 0:
        node = stack.pop()
        if node.is_error or node.is_missing:
            return node
        if not node.has_error:
            continue
        for child in reversed(node.children):
            stack.append(child)
    return None


def _scope_for(node: Node, scope: str) -> str:
    if node.type in NAMED_SCOPE_TYPES:
        name_node = node.child_by_field_name("name")
        name = ANONYMOUS_SCOPE if name_node is None else _text(name_node)
    elif node.type in ANONYMOUS_FUNCTION_TYPES:
        name = _binding_name(node)
    else:
        return scope
    if scope == MODULE_SCOPE:
        return name
    return f"{scope}.{name}"


def _binding_name(node: Node) -> str:
    """Best-effort name for an anonymous function: the declarator or property it is bound to."""
    parent = node.parent
    if parent is None:
        return ANONYMOUS_SCOPE
    if parent.type in ("variable_declarator", "pair", "field_definition", "assignment_expression"):
        field = "left" if parent.type == "assignment_expression" else "name"
        if parent.type == "pair":
            field = "key"
        if parent.type == "field_definition":
            field = "property"
        name_node = parent.child_by_field_name(field)
        if name_node is not None:
            return _text(name_node)
    return ANONYMOUS_SCOPE


def extract_javascript_facts(source: SourceText, filename: str) -> ModuleFacts:
    tree = _PARSER.parse(source.text.encode("utf-8"))
    root = tree.root_node
    error = _first_error(root)
    if error is not None:
        kind = "missing token" if error.is_missing else "syntax error"
        first_line = _text(error).split("\n")[0]
        if len(first_line) > EVIDENCE_MAX_CHARS:
            first_line = first_line[:EVIDENCE_MAX_CHARS] + "..."
        return ModuleFacts(
            language="javascript",
            parser=PARSER_NAME,
            numeric_literals=(),
            comments=(),
            parse_failure=ParseFailure(
                span=_span(source, error),
                message=f"{kind} near {first_line!r} in {filename}",
            ),
        )

    literals: list[NumericLiteral] = []
    comments: list[Comment] = []
    stack: list[tuple[Node, str]] = [(root, MODULE_SCOPE)]
    while len(stack) > 0:
        node, scope = stack.pop()
        if node.type == COMMENT:
            comments.append(Comment(span=_span(source, node), text=_text(node)))
            continue
        folded = _fold_unary(node)
        if folded is not None:
            number, negated = folded
            value = parse_js_number(_text(number))
            if negated:
                value = -value
            literals.append(
                NumericLiteral(
                    span=_span(source, node),
                    raw=_text(node),
                    value=value,
                    negated=negated,
                    in_annotation=False,
                    scope=scope,
                )
            )
            continue
        if node.type == NUMBER:
            literals.append(
                NumericLiteral(
                    span=_span(source, node),
                    raw=_text(node),
                    value=parse_js_number(_text(node)),
                    negated=False,
                    in_annotation=False,
                    scope=scope,
                )
            )
            continue
        child_scope = _scope_for(node, scope)
        for child in reversed(node.children):
            stack.append((child, child_scope))

    literals.sort(key=lambda lit: lit.span)
    comments.sort(key=lambda comment: comment.span)
    return ModuleFacts(
        language="javascript",
        parser=PARSER_NAME,
        numeric_literals=tuple(literals),
        comments=tuple(comments),
        parse_failure=None,
    )
