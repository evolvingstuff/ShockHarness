"""Python adapter: ``ast`` for structure, ``tokenize`` for comments.

Parseable syntax is whatever the *host* interpreter's ``ast`` accepts; the
report records the host version for that reason. Traversal is iterative so
deeply nested sources cannot exhaust the recursion limit.
"""

import ast
import io
import re
import tokenize

from shockharness.constants import FIRST_COLUMN
from shockharness.ir.model import (
    MODULE_SCOPE,
    Comment,
    ModuleFacts,
    NumericLiteral,
    ParseFailure,
    Span,
    failed_facts,
)
from shockharness.ir.python_async import collect_python_async
from shockharness.ir.python_catches import (
    SCOPE_NODES,
    collect_python_catches,
    collect_python_managers,
    node_span,
    scope_name,
)
from shockharness.ir.python_defaults import collect_python_defaults
from shockharness.ir.python_functions import (
    collect_python_bindings,
    collect_python_functions,
    collect_python_imports,
)
from shockharness.ir.python_guardrails import collect_python_guardrails
from shockharness.ir.python_verification import collect_python_verification
from shockharness.source import SourceText

PARSER_NAME = "python-ast"
ANNOTATION_FIELDS = frozenset({"annotation", "returns"})
NUMERIC_TYPES = (int, float, complex)
# A named constant for the purposes of rules.magic_numbers.named_constant_definitions:
# UPPER_SNAKE_CASE, leading underscores allowed (MAX_PAGES, _PORT_WAIT_SECONDS, N).
CONSTANT_NAME = re.compile(r"_*[A-Z][A-Z0-9_]*")
CONSTANT_VALUE_TYPES = (int, float)  # the definition covers int and float literals
FINAL_ANNOTATION = "Final"


def _is_numeric_constant(node: ast.AST) -> bool:
    # ``type(...) in`` deliberately excludes bool, which subclasses int.
    return isinstance(node, ast.Constant) and type(node.value) in NUMERIC_TYPES


def _fold_unary(node: ast.AST) -> tuple[ast.Constant, bool] | None:
    """If ``node`` is a chain of unary +/- over a numeric constant, return (constant, negated)."""
    negative = False
    current = node
    while isinstance(current, ast.UnaryOp) and isinstance(current.op, ast.USub | ast.UAdd):
        if isinstance(current.op, ast.USub):
            negative = not negative
        current = current.operand
    if current is node or not _is_numeric_constant(current):
        return None
    assert isinstance(current, ast.Constant)
    return current, negative


def _is_final_annotation(annotation: ast.expr) -> bool:
    """``Final``, ``typing.Final``, ``Final[int]``, ``t.Final[float]``."""
    target = annotation.value if isinstance(annotation, ast.Subscript) else annotation
    if isinstance(target, ast.Name):
        return target.id == FINAL_ANNOTATION
    return isinstance(target, ast.Attribute) and target.attr == FINAL_ANNOTATION


# Literal arithmetic accepted in a named constant definition (0.3.0): binary + - * / // % **
# over numeric literals, unary +/- and parentheses (parentheses leave no AST node).
CONSTANT_OPERATORS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)
CONSTANT_UNARY = (ast.UAdd, ast.USub)


def _is_constant_value(value: ast.expr | None) -> bool:
    """The whole right-hand side is an int or float literal, or arithmetic over such
    literals: unary ``+``/``-``, parentheses and the binary operators ``+ - * / // % **``
    (``64 * 1024``, ``-(30 * 60) / 2``). Any name, attribute, call, subscript or
    non-numeric literal in the expression disqualifies the whole definition."""
    if value is None:
        return False
    stack: list[ast.expr] = [value]
    while len(stack) > 0:
        node = stack.pop()
        if isinstance(node, ast.Constant):
            if type(node.value) not in CONSTANT_VALUE_TYPES:
                return False
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, CONSTANT_UNARY):
            stack.append(node.operand)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, CONSTANT_OPERATORS):
            stack.append(node.left)
            stack.append(node.right)
        else:
            return False
    return True


def _constant_definition_values(module: ast.Module) -> set[int]:
    """``id()`` of every literal node of a module-level named constant definition.

    A statement of the module body itself (not nested in an ``if``/``try``/loop):
    ``NAME = <value>`` with one simple UPPER_SNAKE_CASE target, or
    ``name: Final = <value>`` / ``NAME: <annotation> = <value>``, where the value is a
    literal or literal arithmetic (see :func:`_is_constant_value`). Containers, other
    expressions, chained targets, class bodies and function bodies are not covered.
    """
    values: set[int] = set()
    for stmt in module.body:
        if isinstance(stmt, ast.Assign):
            if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
                continue
            if CONSTANT_NAME.fullmatch(stmt.targets[0].id) is None:
                continue
            if _is_constant_value(stmt.value):
                values.update(_literal_ids(stmt.value))
        elif isinstance(stmt, ast.AnnAssign):
            if not isinstance(stmt.target, ast.Name) or not _is_constant_value(stmt.value):
                continue
            named = CONSTANT_NAME.fullmatch(stmt.target.id) is not None
            if named or _is_final_annotation(stmt.annotation):
                assert stmt.value is not None
                values.update(_literal_ids(stmt.value))
    return values


def _literal_ids(value: ast.expr) -> set[int]:
    """``id()`` of every literal node of an accepted constant value, as the literal
    collector sees them: a unary chain over a literal is folded into one node."""
    ids: set[int] = set()
    stack: list[ast.expr] = [value]
    while len(stack) > 0:
        node = stack.pop()
        if isinstance(node, ast.BinOp):
            stack.append(node.left)
            stack.append(node.right)
        elif isinstance(node, ast.UnaryOp) and _fold_unary(node) is None:
            stack.append(node.operand)  # a sign over an expression, not over a literal
        else:
            ids.add(id(node))
    return ids


def _raw(source: SourceText, node: ast.expr) -> str:
    segment = ast.get_source_segment(source.text, node)
    if segment is None:
        return ""
    return segment


def _parse(source: SourceText, filename: str) -> ast.Module | ParseFailure:
    # Boundary (declared in .shockharness.toml): external source text.
    try:
        return ast.parse(source.text, filename=filename)
    except SyntaxError as exc:
        span = None
        if exc.lineno is not None and exc.offset is not None:
            span = Span(
                line=exc.lineno, column=exc.offset, end_line=exc.lineno, end_column=exc.offset
            )
        return ParseFailure(span=span, message=f"{type(exc).__name__}: {exc.msg}")
    except ValueError as exc:
        # Python 3.11 raises ValueError (not SyntaxError) for NUL bytes in source.
        return ParseFailure(span=None, message=f"ValueError: {exc}")


def _comments(source: SourceText) -> tuple[Comment, ...] | ParseFailure:
    # Boundary (declared in .shockharness.toml): tokenizing external source text. Only
    # the call that drives the tokenizer is inside the try; building facts is not.
    reader = io.StringIO(source.text).readline
    tokens = tokenize.generate_tokens(reader)
    try:
        materialized = list(tokens)
    except (tokenize.TokenError, SyntaxError, ValueError) as exc:
        # ValueError covers UnicodeDecodeError, which CPython's tokenizer raises for some
        # inputs (for example a bare CR followed by a multibyte character) even when
        # ast.parse accepted the same text.
        return ParseFailure(span=None, message=f"comment tokenization failed: {exc}")
    found: list[Comment] = []
    for token in materialized:
        if token.type != tokenize.COMMENT:
            continue
        start_line, start_col = token.start
        end_line, end_col = token.end
        found.append(
            Comment(
                span=Span(
                    line=start_line,
                    column=start_col + FIRST_COLUMN,
                    end_line=end_line,
                    end_column=end_col + FIRST_COLUMN,
                ),
                text=token.string,
            )
        )
    return tuple(found)


def _collect_literals(source: SourceText, module: ast.Module) -> tuple[NumericLiteral, ...]:
    literals: list[NumericLiteral] = []
    definitions = _constant_definition_values(module)
    stack: list[tuple[ast.AST, str, bool]] = [(module, MODULE_SCOPE, False)]
    while len(stack) > 0:
        node, scope, in_annotation = stack.pop()
        folded = _fold_unary(node)
        if folded is not None:
            constant, negated = folded
            assert isinstance(node, ast.expr)
            value = constant.value
            if negated:
                value = -value
            literals.append(
                NumericLiteral(
                    span=node_span(source, node),
                    raw=_raw(source, node),
                    value=value,
                    negated=negated,
                    in_annotation=in_annotation,
                    scope=scope,
                    constant_definition=id(node) in definitions,
                )
            )
            continue
        if _is_numeric_constant(node):
            assert isinstance(node, ast.Constant)
            literals.append(
                NumericLiteral(
                    span=node_span(source, node),
                    raw=_raw(source, node),
                    value=node.value,
                    negated=False,
                    in_annotation=in_annotation,
                    scope=scope,
                    constant_definition=id(node) in definitions,
                )
            )
            continue
        child_scope = scope
        if isinstance(node, SCOPE_NODES):
            name = scope_name(node)
            child_scope = name if scope == MODULE_SCOPE else f"{scope}.{name}"
        for field_name, value in ast.iter_fields(node):
            child_annotation = in_annotation or field_name in ANNOTATION_FIELDS
            if isinstance(value, ast.AST):
                stack.append((value, child_scope, child_annotation))
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, ast.AST):
                        stack.append((item, child_scope, child_annotation))
    literals.sort(key=lambda lit: lit.span)
    return tuple(literals)


def extract_python_facts(source: SourceText, filename: str) -> ModuleFacts:
    parsed = _parse(source, filename)
    if isinstance(parsed, ParseFailure):
        return failed_facts("python", PARSER_NAME, parsed)
    comments = _comments(source)
    if isinstance(comments, ParseFailure):
        return failed_facts("python", PARSER_NAME, comments)
    return ModuleFacts(
        language="python",
        parser=PARSER_NAME,
        numeric_literals=_collect_literals(source, parsed),
        comments=comments,
        catches=collect_python_catches(source, parsed, filename),
        managers=collect_python_managers(source, parsed, filename),
        defaults=collect_python_defaults(source, parsed),
        functions=collect_python_functions(source, parsed, comments),
        imports=collect_python_imports(source, parsed),
        bindings=collect_python_bindings(source, parsed),
        verification=collect_python_verification(source, parsed, comments),
        guardrails=collect_python_guardrails(source, parsed),
        asynchrony=collect_python_async(source, parsed),
        parse_failure=None,
    )
