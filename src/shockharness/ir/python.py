"""Python adapter: ``ast`` for structure, ``tokenize`` for comments.

Parseable syntax is whatever the *host* interpreter's ``ast`` accepts; the
report records the host version for that reason. Traversal is iterative so
deeply nested sources cannot exhaust the recursion limit.
"""

import ast
import io
import tokenize

from shockharness.constants import FIRST_COLUMN
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

PARSER_NAME = "python-ast"
ANNOTATION_FIELDS = frozenset({"annotation", "returns"})
SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
NUMERIC_TYPES = (int, float, complex)


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


def _span(source: SourceText, node: ast.expr) -> Span:
    end_line = node.end_lineno if node.end_lineno is not None else node.lineno
    end_col = node.end_col_offset if node.end_col_offset is not None else node.col_offset
    return Span(
        line=node.lineno,
        column=source.column_from_byte_offset(node.lineno, node.col_offset),
        end_line=end_line,
        end_column=source.column_from_byte_offset(end_line, end_col),
    )


def _raw(source: SourceText, node: ast.expr) -> str:
    segment = ast.get_source_segment(source.text, node)
    if segment is None:
        return ""
    return segment


def _scope_name(node: ast.AST) -> str:
    if isinstance(node, ast.Lambda):
        return "<lambda>"
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return node.name
    return ANONYMOUS_SCOPE


def _parse(source: SourceText, filename: str) -> ast.Module | ParseFailure:
    # Boundary (declared in .shockharness.toml): external source text.
    try:
        return ast.parse(source.text, filename=filename)
    except SyntaxError as exc:
        span = None
        if exc.lineno is not None:
            column = exc.offset if exc.offset is not None else FIRST_COLUMN
            span = Span(line=exc.lineno, column=column, end_line=exc.lineno, end_column=column)
        return ParseFailure(span=span, message=f"{type(exc).__name__}: {exc.msg}")
    except ValueError as exc:
        # Python 3.11 raises ValueError (not SyntaxError) for NUL bytes in source.
        return ParseFailure(span=None, message=f"ValueError: {exc}")


def _comments(source: SourceText) -> tuple[Comment, ...] | ParseFailure:
    # Boundary (declared in .shockharness.toml): tokenizing external source text.
    found: list[Comment] = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(source.text).readline):
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
    except (tokenize.TokenError, SyntaxError, ValueError) as exc:
        # ValueError covers UnicodeDecodeError, which CPython's tokenizer raises for some
        # inputs (for example a bare CR followed by a multibyte character) even when
        # ast.parse accepted the same text.
        return ParseFailure(span=None, message=f"comment tokenization failed: {exc}")
    return tuple(found)


def _collect_literals(source: SourceText, module: ast.Module) -> tuple[NumericLiteral, ...]:
    literals: list[NumericLiteral] = []
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
                    span=_span(source, node),
                    raw=_raw(source, node),
                    value=value,
                    negated=negated,
                    in_annotation=in_annotation,
                    scope=scope,
                )
            )
            continue
        if _is_numeric_constant(node):
            assert isinstance(node, ast.Constant)
            literals.append(
                NumericLiteral(
                    span=_span(source, node),
                    raw=_raw(source, node),
                    value=node.value,
                    negated=False,
                    in_annotation=in_annotation,
                    scope=scope,
                )
            )
            continue
        child_scope = scope
        if isinstance(node, SCOPE_NODES):
            name = _scope_name(node)
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
        return ModuleFacts(
            language="python",
            parser=PARSER_NAME,
            numeric_literals=(),
            comments=(),
            parse_failure=parsed,
        )
    comments = _comments(source)
    if isinstance(comments, ParseFailure):
        return ModuleFacts(
            language="python",
            parser=PARSER_NAME,
            numeric_literals=(),
            comments=(),
            parse_failure=comments,
        )
    return ModuleFacts(
        language="python",
        parser=PARSER_NAME,
        numeric_literals=_collect_literals(source, parsed),
        comments=comments,
        parse_failure=None,
    )
