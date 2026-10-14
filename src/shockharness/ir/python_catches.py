"""Catch facts for Python: ``except`` / ``except*`` handlers of ``try`` statements.

Exception identities are resolved through the module's imports and class
definitions, best effort, and every resolution carries a confidence:

* ``exact``: a builtin exception name that nothing in the module shadows, or a
  name bound by a module-level absolute import (``from a.b import X``,
  ``import a.b as c`` then ``c.X``).
* ``approximate``: a relative import (``from .errors import X`` gives
  ``".errors.X"``), a class defined in the module itself (qualified with the
  module's path-derived dotted name), or an import nested below module level.
* ``unresolved``: an unbound name, a name rebound by an assignment, a dynamic
  expression (call, subscript, starred), or anything else the resolver does not
  understand. Rules fail closed on unresolved identities.

No analyzed module is ever imported or executed.
"""

import ast
import builtins
import re
from dataclasses import dataclass

from shockharness.ir.model import (
    ANONYMOUS_SCOPE,
    BODY_EMPTY,
    BODY_LOGGING_ONLY,
    BODY_OTHER,
    BODY_RAISE_CHAINED,
    BODY_RAISE_OTHER,
    BODY_RERAISE,
    BODY_RETURN_FALLBACK,
    BROAD_IDENTITIES,
    CATCH_EXCEPT,
    CATCH_EXCEPT_STAR,
    CONFIDENCE_APPROXIMATE,
    CONFIDENCE_EXACT,
    CONFIDENCE_UNRESOLVED,
    MODULE_SCOPE,
    CatchFact,
    ExceptionIdentity,
    HandlerBody,
    Span,
    TryStatement,
)
from shockharness.source import SourceText

BUILTIN_EXCEPTIONS: frozenset[str] = frozenset(
    name
    for name in dir(builtins)
    if isinstance(getattr(builtins, name), type)
    and issubclass(getattr(builtins, name), BaseException)
)
BUILTINS_PREFIX = "builtins."

SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)

# Statements that only emit diagnostics. Logging is never a remedy, so these are
# recognized precisely in order to classify a handler as "logging only".
LOGGING_CALL = re.compile(
    r"^(?:[A-Za-z_][A-Za-z0-9_]*\.)*"
    r"(?:logging|logger|log|LOGGER|LOG|_logger|_log)"
    r"\.(?:debug|info|warning|warn|error|exception|critical|fatal|log)$"
)
LOGGING_EXACT = frozenset(
    {
        "print",
        "warnings.warn",
        "traceback.print_exc",
        "traceback.print_exception",
        "traceback.print_stack",
        "sys.stderr.write",
        "sys.stdout.write",
    }
)

# Expression nodes that execute code of their own inside a statement; a try body
# statement is attributable only when it performs exactly one such operation.
OPERATION_NODES = (
    ast.Call,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
    ast.Lambda,
    ast.Yield,
    ast.YieldFrom,
    ast.Await,
)
COMPOUND_STATEMENTS = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    ast.TryStar,
    ast.Match,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
)
LITERAL_CONTAINERS = (ast.List, ast.Tuple, ast.Set)


@dataclass(frozen=True)
class _Binding:
    qualified: str | None
    confidence: str


def module_dotted_name(relative_path: str) -> str:
    """``src/pkg/mod.py`` -> ``src.pkg.mod``; ``pkg/__init__.py`` -> ``pkg``."""
    path = relative_path.replace("\\", "/")
    for suffix in (".py", ".pyi"):
        if path.endswith(suffix):
            path = path[: len(path) - len(suffix)]
            break
    parts = [part for part in path.split("/") if part != "" and part != "."]
    if len(parts) > 0 and parts[len(parts) - 1] == "__init__":
        parts.pop()
    if len(parts) == 0:
        return relative_path
    return ".".join(parts)


class SymbolTable:
    """Names bound at module level (or by nested imports) and what they refer to."""

    def __init__(self, module: ast.Module, module_name: str) -> None:
        self.bindings: dict[str, _Binding] = {}
        self.module_name = module_name
        for stmt in module.body:
            self._bind_statement(stmt, True)
        for node in ast.walk(module):
            if isinstance(node, ast.Import | ast.ImportFrom) and node not in module.body:
                self._bind_import(node, False)

    def _bind_statement(self, stmt: ast.stmt, top_level: bool) -> None:
        if isinstance(stmt, ast.Import | ast.ImportFrom):
            self._bind_import(stmt, top_level)
        elif isinstance(stmt, ast.ClassDef):
            self.bindings[stmt.name] = _Binding(
                f"{self.module_name}.{stmt.name}", CONFIDENCE_APPROXIMATE
            )
        elif isinstance(stmt, ast.If | ast.Try | ast.TryStar):
            # Imports guarded by version checks or ImportError fallbacks are common
            # at module level; the bodies are scanned as approximate bindings.
            for child in ast.iter_child_nodes(stmt):
                if isinstance(child, ast.stmt):
                    self._bind_statement(child, False)
        else:
            for name in _assigned_names(stmt):
                # A rebinding (``MyError = ValueError``) is dynamic: unresolved.
                self.bindings[name] = _Binding(None, CONFIDENCE_UNRESOLVED)

    def _bind_import(self, node: ast.Import | ast.ImportFrom, top_level: bool) -> None:
        confidence = CONFIDENCE_EXACT if top_level else CONFIDENCE_APPROXIMATE
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname is not None:
                    self.bindings[alias.asname] = _Binding(alias.name, confidence)
                else:
                    root = alias.name.split(".")[0]
                    self.bindings[root] = _Binding(root, confidence)
            return
        prefix = "." * node.level
        if node.module is not None:
            prefix += node.module
        if node.level > 0:
            confidence = CONFIDENCE_APPROXIMATE
        for alias in node.names:
            if alias.name == "*":
                continue
            bound = bound_name(alias)
            if prefix == "" or prefix.endswith("."):
                qualified = prefix + alias.name
            else:
                qualified = f"{prefix}.{alias.name}"
            self.bindings[bound] = _Binding(qualified, confidence)

    def resolve_name(self, name: str) -> _Binding:
        if name in self.bindings:
            return self.bindings[name]
        if name in BUILTIN_EXCEPTIONS:
            return _Binding(name, CONFIDENCE_EXACT)
        return _Binding(None, CONFIDENCE_UNRESOLVED)


def _assigned_names(stmt: ast.stmt) -> list[str]:
    names: list[str] = []
    if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
        return [stmt.name]
    targets: list[ast.expr] = []
    if isinstance(stmt, ast.Assign):
        targets = list(stmt.targets)
    elif isinstance(stmt, ast.AnnAssign | ast.AugAssign):
        targets = [stmt.target]
    for target in targets:
        for node in ast.walk(target):
            if isinstance(node, ast.Name):
                names.append(node.id)
    return names


def bound_name(alias: ast.alias) -> str:
    """The local name an import alias binds: its ``as`` name when present, else the name."""
    if alias.asname is not None:
        return alias.asname
    return alias.name


def dotted_name(expr: ast.expr) -> str | None:
    """``a.b.c`` as text when the expression is a plain name/attribute chain."""
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        base = dotted_name(expr.value)
        if base is None:
            return None
        return f"{base}.{expr.attr}"
    return None


def _normalize(qualified: str) -> str:
    if qualified.startswith(BUILTINS_PREFIX):
        return qualified[len(BUILTINS_PREFIX) :]
    return qualified


def resolve_identity(expr: ast.expr, table: SymbolTable, source: SourceText) -> ExceptionIdentity:
    written = ast.get_source_segment(source.text, expr)
    if written is None:
        written = ""
    dotted = dotted_name(expr)
    if dotted is None:
        return ExceptionIdentity(written, None, CONFIDENCE_UNRESOLVED, False)
    parts = dotted.split(".")
    root = table.resolve_name(parts[0])
    if root.qualified is None:
        return ExceptionIdentity(written, None, CONFIDENCE_UNRESOLVED, False)
    rest = parts[1:]
    qualified = _normalize(".".join([root.qualified, *rest]))
    broad = qualified in BROAD_IDENTITIES
    return ExceptionIdentity(written, qualified, root.confidence, broad)


def handler_identities(
    handler: ast.ExceptHandler, table: SymbolTable, source: SourceText
) -> tuple[ExceptionIdentity, ...]:
    if handler.type is None:
        return ()
    if isinstance(handler.type, ast.Tuple):
        return tuple(resolve_identity(elt, table, source) for elt in handler.type.elts)
    return (resolve_identity(handler.type, table, source),)


def is_pass(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Pass):
        return True
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and stmt.value.value is Ellipsis
    )


def _call_name(call: ast.Call) -> str | None:
    return dotted_name(call.func)


def is_logging_statement(stmt: ast.stmt) -> bool:
    if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
        return False
    name = _call_name(stmt.value)
    if name is None:
        return False
    return name in LOGGING_EXACT or LOGGING_CALL.match(name) is not None


def _folded_numeric(expr: ast.expr) -> bool:
    current = expr
    while isinstance(current, ast.UnaryOp) and isinstance(current.op, ast.USub | ast.UAdd):
        current = current.operand
    return isinstance(current, ast.Constant) and type(current.value) in (int, float, complex)


def is_literal_like(expr: ast.expr | None) -> bool:
    """A value fabricated in place: constants and containers made only of constants."""
    if expr is None:
        return True
    if isinstance(expr, ast.Constant) or _folded_numeric(expr):
        return True
    if isinstance(expr, LITERAL_CONTAINERS):
        return all(is_literal_like(elt) for elt in expr.elts)
    if isinstance(expr, ast.Dict):
        return all(key is not None and is_literal_like(key) for key in expr.keys) and all(
            is_literal_like(value) for value in expr.values
        )
    return False


def describe_statement(stmt: ast.stmt, source: SourceText) -> str:
    text = ast.get_source_segment(source.text, stmt)
    if text is None:
        return type(stmt).__name__
    return text.split("\n")[0].strip()


def classify_handler(handler: ast.ExceptHandler, source: SourceText) -> HandlerBody:
    statements = list(handler.body)
    if all(is_pass(stmt) for stmt in statements):
        return HandlerBody(BODY_EMPTY, "handler body is pass/...; the failure vanishes")
    remaining = [s for s in statements if not is_pass(s) and not is_logging_statement(s)]
    if len(remaining) == 0:
        return HandlerBody(
            BODY_LOGGING_ONLY, "handler only logs; the failure is recorded, not handled"
        )
    if len(remaining) != 1:
        return HandlerBody(BODY_OTHER, "handler body is not classified")
    stmt = remaining[0]
    if isinstance(stmt, ast.Return) and is_literal_like(stmt.value):
        return HandlerBody(BODY_RETURN_FALLBACK, describe_statement(stmt, source))
    if isinstance(stmt, ast.Raise):
        return _classify_raise(stmt, handler.name, source)
    return HandlerBody(BODY_OTHER, "handler body is not classified")


def _classify_raise(stmt: ast.Raise, bound_name: str | None, source: SourceText) -> HandlerBody:
    if stmt.exc is None:
        return HandlerBody(BODY_RERAISE, "bare raise")
    if isinstance(stmt.exc, ast.Name) and bound_name is not None and stmt.exc.id == bound_name:
        return HandlerBody(BODY_RERAISE, f"raise {bound_name}")
    described = describe_statement(stmt, source)
    if stmt.cause is None:
        return HandlerBody(
            BODY_RAISE_OTHER, f"{described} (no 'from' clause; cause is not preserved)"
        )
    if isinstance(stmt.cause, ast.Constant) and stmt.cause.value is None:
        return HandlerBody(BODY_RAISE_OTHER, f"{described} ('from None' discards the cause)")
    if isinstance(stmt.cause, ast.Name) and bound_name is not None and stmt.cause.id == bound_name:
        return HandlerBody(BODY_RAISE_CHAINED, described)
    return HandlerBody(BODY_RAISE_OTHER, f"{described} (cause is not the caught exception)")


def _statement_value(stmt: ast.stmt) -> ast.expr | None:
    if isinstance(stmt, ast.Expr | ast.Return | ast.Assign | ast.AugAssign):
        return stmt.value
    if isinstance(stmt, ast.AnnAssign):
        return stmt.value
    return None


def try_statement(stmt: ast.stmt, source: SourceText) -> TryStatement:
    span = node_span(source, stmt)
    if isinstance(stmt, ast.Import | ast.ImportFrom):
        return TryStatement(span, describe_statement(stmt, source), None)
    if isinstance(stmt, COMPOUND_STATEMENTS):
        kind = type(stmt).__name__.lower()
        return TryStatement(
            span, None, f"compound statement ({kind}) wraps more than one operation"
        )
    value = _statement_value(stmt)
    if value is None:
        kind = type(stmt).__name__.lower()
        return TryStatement(span, None, f"statement ({kind}) does not perform a call")
    inner = value.value if isinstance(value, ast.Await) else value
    if not isinstance(inner, ast.Call):
        kind = type(inner).__name__.lower()
        return TryStatement(span, None, f"statement value is not a call ({kind})")
    operations = [node for node in ast.walk(stmt) if isinstance(node, OPERATION_NODES)]
    awaited = 1 if isinstance(value, ast.Await) else 0
    extra = len(operations) - awaited
    if extra != 1:
        return TryStatement(
            span,
            None,
            f"statement performs {extra} operations; only one can be attributed to the boundary",
        )
    operation = _call_name(inner)
    if operation is None:
        operation = describe_statement(stmt, source)
    return TryStatement(span, operation, None)


def node_span(source: SourceText, node: ast.stmt | ast.expr | ast.excepthandler) -> Span:
    # ``ast`` sets end positions on every statement, expression and handler it parses; the
    # Optional in the type stubs covers hand-built nodes, which this tool never creates.
    end_line = node.end_lineno
    end_col = node.end_col_offset
    assert end_line is not None and end_col is not None, "parsed node without an end position"
    return Span(
        line=node.lineno,
        column=source.column_from_byte_offset(node.lineno, node.col_offset),
        end_line=end_line,
        end_column=source.column_from_byte_offset(end_line, end_col),
    )


def scope_name(node: ast.AST) -> str:
    if isinstance(node, ast.Lambda):
        return "<lambda>"
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return node.name
    return ANONYMOUS_SCOPE


def collect_python_catches(
    source: SourceText, module: ast.Module, relative_path: str
) -> tuple[CatchFact, ...]:
    table = SymbolTable(module, module_dotted_name(relative_path))
    catches: list[CatchFact] = []
    stack: list[tuple[ast.AST, str]] = [(module, MODULE_SCOPE)]
    while len(stack) > 0:
        node, scope = stack.pop()
        if isinstance(node, ast.Try | ast.TryStar):
            kind = CATCH_EXCEPT_STAR if isinstance(node, ast.TryStar) else CATCH_EXCEPT
            statements = tuple(try_statement(stmt, source) for stmt in node.body)
            for handler in node.handlers:
                identities = handler_identities(handler, table, source)
                catches.append(
                    CatchFact(
                        span=node_span(source, handler),
                        kind=kind,
                        scope=scope,
                        identities=identities,
                        bare=handler.type is None,
                        bound_name=handler.name,
                        body=classify_handler(handler, source),
                        try_statements=statements,
                    )
                )
        child_scope = scope
        if isinstance(node, SCOPE_NODES):
            name = scope_name(node)
            child_scope = name if scope == MODULE_SCOPE else f"{scope}.{name}"
        for child in ast.iter_child_nodes(node):
            stack.append((child, child_scope))
    catches.sort(key=lambda catch: catch.span)
    return tuple(catches)
