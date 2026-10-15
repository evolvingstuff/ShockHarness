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
from shockharness.ir.javascript_functions import (
    collect_javascript_bindings,
    collect_javascript_functions,
    collect_javascript_imports,
)
from shockharness.ir.model import (
    MODULE_SCOPE,
    Comment,
    ModuleFacts,
    NumericLiteral,
    ParseFailure,
    failed_facts,
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
# A named constant for rules.magic_numbers.named_constant_definitions: UPPER_SNAKE_CASE with
# leading underscores allowed; only `const` (and `export const`) at module scope qualifies.
CONSTANT_NAME = re.compile(r"_*[A-Z][A-Z0-9_]*")
LEXICAL_DECLARATION = "lexical_declaration"
EXPORT_STATEMENT = "export_statement"
VARIABLE_DECLARATOR = "variable_declarator"
CONST_KIND = "const"
MINUS = "-"


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


def _is_constant_value(value: Node | None) -> bool:
    """A numeric literal, optionally under one unary minus: the whole right-hand side."""
    if value is None:
        return False
    if value.type == NUMBER:
        return True
    if value.type != UNARY:
        return False
    operator = value.child_by_field_name("operator")
    argument = value.child_by_field_name("argument")
    return (
        operator is not None
        and argument is not None
        and node_text(operator) == MINUS
        and argument.type == NUMBER
    )


def _const_declaration(statement: Node) -> Node | None:
    """``const ...`` or ``export const ...`` -> the lexical_declaration node, else None."""
    declaration = statement
    if statement.type == EXPORT_STATEMENT:
        exported = statement.child_by_field_name("declaration")
        if exported is None:
            return None
        declaration = exported
    if declaration.type != LEXICAL_DECLARATION:
        return None
    kind = declaration.child_by_field_name("kind")
    if kind is None or node_text(kind) != CONST_KIND:
        return None
    return declaration


def _constant_definition_values(root: Node) -> set[int]:
    """Node ids of every value that is a module-level named constant definition:
    each declarator of a ``const``/``export const`` statement of the program itself
    whose name is UPPER_SNAKE_CASE and whose value is a numeric literal (optionally
    negated). ``let``/``var``, block-nested declarations, containers and expressions
    are not covered."""
    values: set[int] = set()
    for statement in root.named_children:
        declaration = _const_declaration(statement)
        if declaration is None:
            continue
        for declarator in declaration.named_children:
            if declarator.type != VARIABLE_DECLARATOR:
                continue
            name = declarator.child_by_field_name("name")
            value = declarator.child_by_field_name("value")
            if name is None or name.type != "identifier":
                continue
            if CONSTANT_NAME.fullmatch(node_text(name)) is None:
                continue
            if _is_constant_value(value):
                assert value is not None
                values.add(value.id)
    return values


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
        return failed_facts(
            "javascript",
            PARSER_NAME,
            ParseFailure(
                span=node_span(source, error),
                message=f"{kind} near {first_line!r} in {filename}",
            ),
        )

    literals: list[NumericLiteral] = []
    comments: list[Comment] = []
    definitions = _constant_definition_values(root)
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
                    constant_definition=node.id in definitions,
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
                    constant_definition=node.id in definitions,
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
        functions=collect_javascript_functions(source, root, tuple(comments)),
        imports=collect_javascript_imports(source, root),
        bindings=collect_javascript_bindings(source, root),
        parse_failure=None,
    )
