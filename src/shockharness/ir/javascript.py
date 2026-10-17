"""JavaScript adapter built on tree-sitter with the pinned JavaScript grammar.

tree-sitter recovers from syntax errors instead of raising. Any ``ERROR`` or
``MISSING`` node anywhere in the tree is therefore treated as a parse failure
(spec section 3); a tree with error nodes is never analyzed as if complete.
"""

import re
from importlib import metadata

import tree_sitter_javascript
import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

from shockharness.constants import (
    EVIDENCE_MAX_CHARS,
    RADIX_BINARY,
    RADIX_DECIMAL,
    RADIX_HEX,
    RADIX_OCTAL,
)
from shockharness.ir.javascript_async import collect_javascript_async
from shockharness.ir.javascript_catalog import collect_javascript_catalog
from shockharness.ir.javascript_catches import (
    collect_javascript_catches,
    node_span,
    node_text,
    scope_for,
)
from shockharness.ir.javascript_dataflow import collect_javascript_dataflow
from shockharness.ir.javascript_defaults import collect_javascript_defaults
from shockharness.ir.javascript_functions import (
    collect_javascript_bindings,
    collect_javascript_functions,
    collect_javascript_imports,
)
from shockharness.ir.javascript_guardrails import collect_javascript_guardrails
from shockharness.ir.javascript_verification import collect_javascript_verification
from shockharness.ir.model import (
    MODULE_SCOPE,
    AsyncFacts,
    CatalogFacts,
    Comment,
    GuardrailFacts,
    ModuleFacts,
    NumericLiteral,
    ParseFailure,
    failed_facts,
)
from shockharness.source import SourceText

_LANGUAGE = Language(tree_sitter_javascript.language())
_PARSER = Parser(_LANGUAGE)
# H-TS: TypeScript and TSX have their own grammars; the facts are read by the same
# extractors, whose node types the TypeScript grammar shares with JavaScript.
_TYPESCRIPT_PARSER = Parser(Language(tree_sitter_typescript.language_typescript()))
_TSX_PARSER = Parser(Language(tree_sitter_typescript.language_tsx()))
TSX_SUFFIX = ".tsx"

PARSER_NAME = "tree-sitter-javascript " + metadata.version("tree-sitter-javascript")
TYPESCRIPT_PARSER_NAME = "tree-sitter-typescript " + metadata.version("tree-sitter-typescript")
JAVASCRIPT_LANGUAGE = "javascript"
TYPESCRIPT_LANGUAGE = "typescript"

NUMBER = "number"
UNARY = "unary_expression"
COMMENT = "comment"
# TypeScript nodes whose subtree is a type: a number in one (`type Port = 8080`, `x: 5`,
# `f<3>()`) is a literal type, reported as in a type annotation like Python's Literal[8080].
TYPE_CONTEXTS = frozenset(
    {
        "type_annotation",
        "omitting_type_annotation",
        "opting_type_annotation",
        "adding_type_annotation",
        "asserts_annotation",
        "type_predicate_annotation",
        "type_alias_declaration",
        "interface_declaration",
        "type_arguments",
        "type_parameters",
        "literal_type",
    }
)
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


# Literal arithmetic accepted in a named constant definition (0.3.0): binary + - * / % **
# over numeric literals, unary +/- and parentheses.
BINARY = "binary_expression"
PARENTHESIZED = "parenthesized_expression"
CONSTANT_OPERATORS = frozenset({"+", "-", "*", "/", "%", "**"})


def _is_constant_value(value: Node | None) -> bool:
    """The whole right-hand side is a numeric literal, or arithmetic over numeric
    literals: unary ``+``/``-``, parentheses and the binary operators ``+ - * / % **``
    (``64 * 1024``, ``-(30 * 60) / 2``). Any identifier, member, call, subscript or
    non-numeric literal in the expression disqualifies the whole definition."""
    if value is None:
        return False
    stack: list[Node] = [value]
    while len(stack) > 0:
        children = _constant_operands(stack.pop())
        if children is None:
            return False
        stack.extend(children)
    return True


def _constant_operands(node: Node) -> list[Node] | None:
    """The operands of a node accepted in a constant value (none for a number), or
    ``None`` when the node disqualifies the definition."""
    if node.type == NUMBER:
        return []
    if node.type == UNARY:
        operator = node.child_by_field_name("operator")
        argument = node.child_by_field_name("argument")
        if operator is None or argument is None or node_text(operator) not in SIGN_OPERATORS:
            return None
        return [argument]
    if node.type == PARENTHESIZED:
        inner = [child for child in node.named_children if child.type != COMMENT]
        return inner if len(inner) == 1 else None
    if node.type == BINARY:
        operator = node.child_by_field_name("operator")
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if operator is None or left is None or right is None:
            return None
        return [left, right] if node_text(operator) in CONSTANT_OPERATORS else None
    return None


def _literal_ids(value: Node) -> set[int]:
    """Ids of every literal node of an accepted constant value, as the literal
    collector records them: a unary chain over a number is one node."""
    ids: set[int] = set()
    stack: list[Node] = [value]
    while len(stack) > 0:
        node = stack.pop()
        if node.type == NUMBER or _fold_unary(node) is not None:
            ids.add(node.id)
            continue
        if node.type == UNARY:
            argument = node.child_by_field_name("argument")
            assert argument is not None
            stack.append(argument)
            continue
        stack.extend(child for child in node.named_children if child.type != COMMENT)
    return ids


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
    """Node ids of every literal of a module-level named constant definition: each
    declarator of a ``const``/``export const`` statement of the program itself whose
    name is UPPER_SNAKE_CASE and whose value is a numeric literal or literal arithmetic
    (see :func:`_is_constant_value`). ``let``/``var``, block-nested declarations,
    containers and other expressions are not covered."""
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
                values.update(_literal_ids(value))
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
    return _extract_facts(source, filename, _PARSER, PARSER_NAME, JAVASCRIPT_LANGUAGE)


def extract_typescript_facts(source: SourceText, filename: str) -> ModuleFacts:
    parser = _TSX_PARSER if filename.endswith(TSX_SUFFIX) else _TYPESCRIPT_PARSER
    return _extract_facts(source, filename, parser, TYPESCRIPT_PARSER_NAME, TYPESCRIPT_LANGUAGE)


def _extract_facts(
    source: SourceText, filename: str, parser: Parser, parser_name: str, language: str
) -> ModuleFacts:
    tree = parser.parse(source.text.encode("utf-8"))
    root = tree.root_node
    error = _first_error(root)
    if error is not None:
        return failed_facts(language, parser_name, _parse_failure(source, filename, error))
    literals, comments = _literals_and_comments(source, root)
    guardrails, asynchrony, catalog = _policy_facts(source, root)
    return ModuleFacts(
        language=language,
        parser=parser_name,
        numeric_literals=literals,
        comments=comments,
        catches=collect_javascript_catches(source, root),
        managers=(),  # JavaScript has no exception-capturing context manager idiom
        defaults=collect_javascript_defaults(source, root),
        functions=collect_javascript_functions(source, root, comments),
        imports=collect_javascript_imports(source, root),
        bindings=collect_javascript_bindings(source, root),
        verification=collect_javascript_verification(source, root, comments),
        guardrails=guardrails,
        asynchrony=asynchrony,
        catalog=catalog,
        dataflow=collect_javascript_dataflow(source, root),
        parse_failure=None,
    )


def _parse_failure(source: SourceText, filename: str, error: Node) -> ParseFailure:
    kind = "missing token" if error.is_missing else "syntax error"
    first_line = node_text(error).split("\n")[0]
    if len(first_line) > EVIDENCE_MAX_CHARS:
        first_line = first_line[:EVIDENCE_MAX_CHARS] + "..."
    return ParseFailure(
        span=node_span(source, error),
        message=f"{kind} near {first_line!r} in {filename}",
    )


def _literals_and_comments(
    source: SourceText, root: Node
) -> tuple[tuple[NumericLiteral, ...], tuple[Comment, ...]]:
    """Every numeric literal (a unary sign chain folded into one) and every comment."""
    literals: list[NumericLiteral] = []
    comments: list[Comment] = []
    definitions = _constant_definition_values(root)
    stack: list[tuple[Node, str, bool]] = [(root, MODULE_SCOPE, False)]
    while len(stack) > 0:
        node, scope, in_annotation = stack.pop()
        if node.type == COMMENT:
            comments.append(Comment(span=node_span(source, node), text=node_text(node)))
            continue
        literal = _literal(
            source, node, scope, in_annotation=in_annotation, definition=node.id in definitions
        )
        if literal is not None:
            literals.append(literal)
            continue
        child_scope = scope_for(node, scope)
        child_annotation = in_annotation or node.type in TYPE_CONTEXTS
        for child in reversed(node.children):
            stack.append((child, child_scope, child_annotation))
    literals.sort(key=lambda lit: lit.span)
    comments.sort(key=lambda comment: comment.span)
    return tuple(literals), tuple(comments)


def _literal(
    source: SourceText, node: Node, scope: str, *, in_annotation: bool, definition: bool
) -> NumericLiteral | None:
    """The literal ``node`` is: a number, or a unary sign chain over one."""
    folded = _fold_unary(node)
    if folded is not None:
        number, negated = folded
        return _numeric(
            source,
            node,
            number,
            scope,
            negated=negated,
            in_annotation=in_annotation,
            definition=definition,
        )
    # The TypeScript grammar also has an anonymous `number` keyword token (`x: number`).
    if node.type == NUMBER and node.is_named:
        return _numeric(
            source,
            node,
            node,
            scope,
            negated=False,
            in_annotation=in_annotation,
            definition=definition,
        )
    return None


def _numeric(
    source: SourceText,
    node: Node,
    number: Node,
    scope: str,
    *,
    negated: bool,
    in_annotation: bool,
    definition: bool,
) -> NumericLiteral:
    value = parse_js_number(node_text(number))
    return NumericLiteral(
        span=node_span(source, node),
        raw=node_text(node),
        value=-value if negated else value,
        negated=negated,
        in_annotation=in_annotation,
        scope=scope,
        constant_definition=definition,
    )


def _policy_facts(
    source: SourceText, root: Node
) -> tuple[GuardrailFacts, AsyncFacts, CatalogFacts]:
    """The H3-H5 facts: guardrails, async lifecycle, API catalog."""
    return (
        collect_javascript_guardrails(source, root),
        collect_javascript_async(source, root),
        collect_javascript_catalog(source, root),
    )
