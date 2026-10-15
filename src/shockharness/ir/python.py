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


def _is_constant_value(value: ast.expr | None) -> bool:
    """An int or float literal, optionally under one unary minus: the whole right-hand side."""
    if value is None:
        return False
    inner = value
    if isinstance(value, ast.UnaryOp) and isinstance(value.op, ast.USub):
        inner = value.operand
    return isinstance(inner, ast.Constant) and type(inner.value) in CONSTANT_VALUE_TYPES


def _constant_definition_values(module: ast.Module) -> set[int]:
    """``id()`` of every value node that is a module-level named constant definition.

    A statement of the module body itself (not nested in an ``if``/``try``/loop):
    ``NAME = <literal>`` with one simple UPPER_SNAKE_CASE target, or
    ``name: Final = <literal>`` / ``NAME: <annotation> = <literal>``. Containers,
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
                values.add(id(stmt.value))
        elif isinstance(stmt, ast.AnnAssign):
            if not isinstance(stmt.target, ast.Name) or not _is_constant_value(stmt.value):
                continue
            named = CONSTANT_NAME.fullmatch(stmt.target.id) is not None
            if named or _is_final_annotation(stmt.annotation):
                values.add(id(stmt.value))
    return values


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
        parse_failure=None,
    )
