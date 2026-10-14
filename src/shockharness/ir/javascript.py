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
    RADIX_BINARY,
    RADIX_DECIMAL,
    RADIX_HEX,
    RADIX_OCTAL,
)
from shockharness.ir.javascript_catches import (
    collect_javascript_catches,
    node_span,
    node_text,
    scope_for,
)
from shockharness.ir.javascript_defaults import collect_javascript_defaults
from shockharness.ir.model import (
    MODULE_SCOPE,
    Comment,
    ModuleFacts,
    NumericLiteral,
    ParseFailure,
)
from shockharness.source import SourceText

_LANGUAGE = Language(tree_sitter_javascript.language())
_PARSER = Parser(_LANGUAGE)

PARSER_NAME = "tree-sitter-javascript " + metadata.version("tree-sitter-javascript")

NUMBER = "number"
UNARY = "unary_expression"
COMMENT = "comment"
SIGN_OPERATORS = frozenset({"-", "+"})

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


def _fold_unary(node: Node) -> tuple[Node, bool] | None:
    negative = False
    current = node
    while current.type == UNARY:
        operator = current.child_by_field_name("operator")
        argument = current.child_by_field_name("argument")
        if operator is None or argument is None or node_text(operator) not in SIGN_OPERATORS:
            return None
        if node_text(operator) == "-":
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


def extract_javascript_facts(source: SourceText, filename: str) -> ModuleFacts:
    tree = _PARSER.parse(source.text.encode("utf-8"))
    root = tree.root_node
    error = _first_error(root)
    if error is not None:
        kind = "missing token" if error.is_missing else "syntax error"
        first_line = node_text(error).split("\n")[0]
        if len(first_line) > EVIDENCE_MAX_CHARS:
            first_line = first_line[:EVIDENCE_MAX_CHARS] + "..."
        return ModuleFacts(
            language="javascript",
            parser=PARSER_NAME,
            numeric_literals=(),
            comments=(),
            catches=(),
            defaults=(),
            parse_failure=ParseFailure(
                span=node_span(source, error),
                message=f"{kind} near {first_line!r} in {filename}",
            ),
        )

    literals: list[NumericLiteral] = []
    comments: list[Comment] = []
    stack: list[tuple[Node, str]] = [(root, MODULE_SCOPE)]
    while len(stack) > 0:
        node, scope = stack.pop()
        if node.type == COMMENT:
            comments.append(Comment(span=node_span(source, node), text=node_text(node)))
            continue
        folded = _fold_unary(node)
        if folded is not None:
            number, negated = folded
            value = parse_js_number(node_text(number))
            if negated:
                value = -value
            literals.append(
                NumericLiteral(
                    span=node_span(source, node),
                    raw=node_text(node),
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
                    span=node_span(source, node),
                    raw=node_text(node),
                    value=parse_js_number(node_text(node)),
                    negated=False,
                    in_annotation=False,
                    scope=scope,
                )
            )
            continue
        child_scope = scope_for(node, scope)
        for child in reversed(node.children):
            stack.append((child, child_scope))

    literals.sort(key=lambda lit: lit.span)
    comments.sort(key=lambda comment: comment.span)
    return ModuleFacts(
        language="javascript",
        parser=PARSER_NAME,
        numeric_literals=tuple(literals),
        comments=tuple(comments),
        catches=collect_javascript_catches(source, root),
        defaults=collect_javascript_defaults(source, root),
        parse_failure=None,
    )
