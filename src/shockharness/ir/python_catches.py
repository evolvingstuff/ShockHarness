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
from collections.abc import Mapping
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
    BOUND_ASSIGNMENT,
    BOUND_DEFINITION,
    BOUND_IMPORT,
    BOUND_LOOP_TARGET,
    BOUND_OTHER,
    BOUND_WITH_AS,
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
    ManagerCall,
    ManagerFact,
    NameBinding,
    NameResolution,
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
            self._bind_statement(stmt, top_level=True)
        for node in ast.walk(module):
            if isinstance(node, ast.Import | ast.ImportFrom) and node not in module.body:
                self._bind_import(node, top_level=False)

    def _bind_statement(self, stmt: ast.stmt, *, top_level: bool) -> None:
        if isinstance(stmt, ast.Import | ast.ImportFrom):
            self._bind_import(stmt, top_level=top_level)
        elif isinstance(stmt, ast.ClassDef):
            self.bindings[stmt.name] = _Binding(
                f"{self.module_name}.{stmt.name}", CONFIDENCE_APPROXIMATE
            )
        elif isinstance(stmt, ast.If | ast.Try | ast.TryStar):
            # Imports guarded by version checks or ImportError fallbacks are common
            # at module level; the bodies are scanned as approximate bindings.
            for child in ast.iter_child_nodes(stmt):
                if isinstance(child, ast.stmt):
                    self._bind_statement(child, top_level=False)
        else:
            for name in _assigned_names(stmt):
                # A rebinding (``MyError = ValueError``) is dynamic: unresolved.
                self.bindings[name] = _Binding(None, CONFIDENCE_UNRESOLVED)

    def _bind_import(self, node: ast.Import | ast.ImportFrom, *, top_level: bool) -> None:
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
        return ExceptionIdentity(written, None, CONFIDENCE_UNRESOLVED, broad=False)
    parts = dotted.split(".")
    root = table.resolve_name(parts[0])
    if root.qualified is None:
        return ExceptionIdentity(written, None, CONFIDENCE_UNRESOLVED, broad=False)
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


def classify_statements(
    statements: list[ast.stmt], bound_name: str | None, source: SourceText
) -> HandlerBody:
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
        return _classify_raise(stmt, bound_name, source)
    return HandlerBody(BODY_OTHER, "handler body is not classified")


def _is_bare_raise_block(body: list[ast.stmt]) -> bool:
    return len(body) == 1 and isinstance(body[0], ast.Raise) and body[0].exc is None


def isinstance_guard(statements: list[ast.stmt], bound_name: str | None) -> list[ast.expr] | None:
    """``if not isinstance(<caught>, T): raise`` as the first statement -> ``[T]``
    (or the tuple's members); ``None`` when the handler does not open with that guard."""
    if bound_name is None or len(statements) == 0:
        return None
    guard = statements[0]
    if not isinstance(guard, ast.If) or len(guard.orelse) > 0:
        return None
    if not _is_bare_raise_block(guard.body):
        return None
    test = guard.test
    if not isinstance(test, ast.UnaryOp) or not isinstance(test.op, ast.Not):
        return None
    call = test.operand
    if not isinstance(call, ast.Call) or len(call.keywords) > 0 or len(call.args) != 1 + 1:
        return None
    if not isinstance(call.func, ast.Name) or call.func.id != "isinstance":
        return None
    subject, types = call.args
    if not isinstance(subject, ast.Name) or subject.id != bound_name:
        return None
    if isinstance(types, ast.Tuple):
        return list(types.elts)
    return [types]


def guard_call(statements: list[ast.stmt], bound_name: str | None) -> str | None:
    """The callee, as written, when the first statement is ``callee(<caught>)``."""
    if bound_name is None or len(statements) == 0:
        return None
    first = statements[0]
    if not isinstance(first, ast.Expr) or not isinstance(first.value, ast.Call):
        return None
    call = first.value
    if len(call.args) != 1 or len(call.keywords) > 0:
        return None
    argument = call.args[0]
    if not isinstance(argument, ast.Name) or argument.id != bound_name:
        return None
    return _call_name(call)


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


def _catch_fact(
    handler: ast.ExceptHandler,
    kind: str,
    scope: str,
    try_statements: tuple[TryStatement, ...],
    table: SymbolTable,
    source: SourceText,
) -> CatchFact:
    identities = handler_identities(handler, table, source)
    body_statements = list(handler.body)
    narrowed_from: str | None = None
    narrowed = isinstance_guard(body_statements, handler.name)
    if narrowed is not None and handler.type is not None:
        # ``except Exception as exc: if not isinstance(exc, T): raise`` catches T.
        narrowed_from = ", ".join(identity.source for identity in identities)
        identities = tuple(resolve_identity(expr, table, source) for expr in narrowed)
        body_statements = body_statements[1:]
    callee = guard_call(body_statements, handler.name)
    guard_body: HandlerBody | None = None
    if callee is not None:
        guard_body = classify_statements(body_statements[1:], handler.name, source)
    return CatchFact(
        span=node_span(source, handler),
        kind=kind,
        scope=scope,
        identities=identities,
        bare=handler.type is None,
        bound_name=handler.name,
        body=classify_statements(body_statements, handler.name, source),
        try_statements=try_statements,
        narrowed_from=narrowed_from,
        guard_call=callee,
        guard_body=guard_body,
    )


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
                catches.append(_catch_fact(handler, kind, scope, statements, table, source))
        child_scope = scope
        if isinstance(node, SCOPE_NODES):
            name = scope_name(node)
            child_scope = name if scope == MODULE_SCOPE else f"{scope}.{name}"
        for child in ast.iter_child_nodes(node):
            stack.append((child, child_scope))
    catches.sort(key=lambda catch: catch.span)
    return tuple(catches)


def _resolve_callee(expr: ast.expr, table: SymbolTable) -> tuple[str | None, str]:
    """``(qualified name, confidence)`` of a dotted callee through the symbol table."""
    dotted = dotted_name(expr)
    if dotted is None:
        return None, CONFIDENCE_UNRESOLVED
    parts = dotted.split(".")
    root = table.resolve_name(parts[0])
    if root.qualified is None:
        return None, CONFIDENCE_UNRESOLVED
    return _normalize(".".join([root.qualified, *parts[1:]])), root.confidence


def _manager_call(expr: ast.expr, table: SymbolTable, source: SourceText) -> ManagerCall | None:
    """``M(T, ...)`` with a dotted callee as a :class:`ManagerCall`; ``None`` otherwise."""
    if not isinstance(expr, ast.Call):
        return None
    callee = dotted_name(expr.func)
    if callee is None:
        return None
    qualified, confidence = _resolve_callee(expr.func, table)
    identities: list[ExceptionIdentity] = []
    unreadable = 0
    for argument in expr.args:
        if dotted_name(argument) is None:
            unreadable += 1
            continue
        identities.append(resolve_identity(argument, table, source))
    return ManagerCall(
        callee=callee,
        qualified=qualified,
        confidence=confidence,
        identities=tuple(identities),
        unreadable_arguments=unreadable,
    )


# Compound statements whose bodies belong to the enclosing scope (a nested def or class
# is a scope of its own and is not entered).
BLOCK_FIELDS: Mapping[type, tuple[str, ...]] = {
    ast.If: ("body", "orelse"),
    ast.For: ("body", "orelse"),
    ast.AsyncFor: ("body", "orelse"),
    ast.While: ("body", "orelse"),
    ast.With: ("body",),
    ast.AsyncWith: ("body",),
    ast.Try: ("body", "orelse", "finalbody"),
    ast.TryStar: ("body", "orelse", "finalbody"),
}
BlockPath = tuple[int, ...]


def _flatten_scope(body: list[ast.stmt]) -> list[tuple[ast.stmt, BlockPath]]:
    """Every statement of a scope body in source order with the path of blocks enclosing
    it (``()`` for the body itself); nested scopes are listed but not entered."""
    flat: list[tuple[ast.stmt, BlockPath]] = []
    stack: list[tuple[ast.stmt, BlockPath]] = [(stmt, ()) for stmt in reversed(body)]
    while len(stack) > 0:
        stmt, path = stack.pop()
        flat.append((stmt, path))
        children: list[tuple[ast.stmt, BlockPath]] = []
        if isinstance(stmt, ast.Try | ast.TryStar):
            for index, handler in enumerate(stmt.handlers):
                handler_path = (*path, id(stmt), index + 1)
                children.extend((child, handler_path) for child in handler.body)
        if isinstance(stmt, ast.Match):
            for index, case in enumerate(stmt.cases):
                children.extend((child, (*path, id(stmt), index)) for child in case.body)
        if type(stmt) in BLOCK_FIELDS:
            for field_index, field_name in enumerate(BLOCK_FIELDS[type(stmt)]):
                block_path = (*path, id(stmt), -(field_index + 1))
                children.extend((child, block_path) for child in getattr(stmt, field_name))
        children.sort(key=lambda entry: (entry[0].lineno, entry[0].col_offset))
        stack.extend(reversed(children))
    return flat


def _walk_pruned(node: ast.AST) -> list[ast.AST]:
    """``ast.walk`` that does not enter nested scopes (defs, classes, lambdas)."""
    found: list[ast.AST] = []
    stack: list[ast.AST] = list(ast.iter_child_nodes(node))
    while len(stack) > 0:
        current = stack.pop()
        if isinstance(current, SCOPE_NODES):
            continue
        found.append(current)
        stack.extend(ast.iter_child_nodes(current))
    return found


def _target_names(target: ast.expr) -> list[str]:
    return [node.id for node in ast.walk(target) if isinstance(node, ast.Name)]


Binding = tuple[str, ManagerCall | None, str]


def _binding_of(
    stmt: ast.stmt, name: str, table: SymbolTable, source: SourceText
) -> Binding | None:
    """``(kind, call, value as written)`` when ``stmt`` itself binds ``name``."""
    if isinstance(stmt, ast.Assign | ast.AnnAssign):
        return _assignment_binding(stmt, name, table, source)
    if isinstance(stmt, ast.Import | ast.ImportFrom):
        if any(_import_binds(stmt, alias, name) for alias in stmt.names):
            return BOUND_IMPORT, None, describe_statement(stmt, source)
        return None
    if isinstance(stmt, ast.With | ast.AsyncWith):
        return _with_binding(stmt, name, table, source)
    kind = _header_binding_kind(stmt, name)
    if kind is None:
        return None
    return kind, None, describe_statement(stmt, source)


def _assignment_binding(
    stmt: ast.Assign | ast.AnnAssign, name: str, table: SymbolTable, source: SourceText
) -> Binding | None:
    targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
    if not any(name in _target_names(target) for target in targets):
        return None
    simple = len(targets) == 1 and isinstance(targets[0], ast.Name)
    if stmt.value is None or not simple:
        return BOUND_OTHER, None, describe_statement(stmt, source)
    value = ast.get_source_segment(source.text, stmt.value)
    if value is None:
        value = ""
    return BOUND_ASSIGNMENT, _manager_call(stmt.value, table, source), value.split("\n")[0]


def _with_binding(
    stmt: ast.With | ast.AsyncWith, name: str, table: SymbolTable, source: SourceText
) -> Binding | None:
    for item in stmt.items:
        if item.optional_vars is not None and name in _target_names(item.optional_vars):
            call = _manager_call(item.context_expr, table, source)
            return BOUND_WITH_AS, call, describe_statement(stmt, source)
    return None


def _header_binding_kind(stmt: ast.stmt, name: str) -> str | None:
    """The binding kind of a statement whose header (not its body) binds ``name``."""
    if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return BOUND_DEFINITION if stmt.name == name else None
    if isinstance(stmt, ast.For | ast.AsyncFor):
        return BOUND_LOOP_TARGET if name in _target_names(stmt.target) else None
    if isinstance(stmt, ast.AugAssign):
        return BOUND_OTHER if name in _target_names(stmt.target) else None
    if isinstance(stmt, ast.Global | ast.Nonlocal):
        return BOUND_OTHER if name in stmt.names else None
    if isinstance(stmt, ast.Try | ast.TryStar):
        return BOUND_OTHER if any(h.name == name for h in stmt.handlers) else None
    return None


def _import_binds(stmt: ast.Import | ast.ImportFrom, alias: ast.alias, name: str) -> bool:
    if alias.asname is not None:
        return alias.asname == name
    if isinstance(stmt, ast.Import):
        return alias.name.split(".")[0] == name
    return alias.name == name


def _walrus_binds(stmt: ast.stmt, name: str) -> bool:
    return any(
        isinstance(node, ast.NamedExpr)
        and isinstance(node.target, ast.Name)
        and node.target.id == name
        for node in _walk_pruned(stmt)
    )


def _parameter_names(scope_node: ast.AST) -> frozenset[str]:
    if not isinstance(scope_node, ast.FunctionDef | ast.AsyncFunctionDef):
        return frozenset()
    arguments = scope_node.args
    names = [a.arg for a in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]]
    if arguments.vararg is not None:
        names.append(arguments.vararg.arg)
    if arguments.kwarg is not None:
        names.append(arguments.kwarg.arg)
    return frozenset(names)


def _comprehension_targets(statements: list[ast.stmt]) -> frozenset[str]:
    names: set[str] = set()
    for stmt in statements:
        for node in _walk_pruned(stmt):
            if isinstance(node, ast.comprehension):
                names.update(_target_names(node.target))
    return frozenset(names)


def _dominates(binding_path: BlockPath, with_path: BlockPath) -> bool:
    return with_path[: len(binding_path)] == binding_path


def _module_call_bindings(
    module: ast.Module, table: SymbolTable, source: SourceText
) -> dict[str, list[tuple[int, ManagerCall]]]:
    """Every ``name = M(...)`` and ``with M(...) as name`` in the module, by name, keyed
    by the binding statement's id so a scope's own bindings can be told apart."""
    found: dict[str, list[tuple[int, ManagerCall]]] = {}
    for node in ast.walk(module):
        for name, expr in _call_binding_candidates(node):
            call = _manager_call(expr, table, source)
            if call is not None:
                _append_binding(found, name, id(node), call)
    return found


def _call_binding_candidates(node: ast.AST) -> list[tuple[str, ast.expr]]:
    """``(name, bound expression)`` for a simple assignment or a ``with ... as name``."""
    if isinstance(node, ast.Assign | ast.AnnAssign):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if len(targets) == 1 and isinstance(targets[0], ast.Name) and node.value is not None:
            return [(targets[0].id, node.value)]
        return []
    if isinstance(node, ast.With | ast.AsyncWith):
        return [
            (item.optional_vars.id, item.context_expr)
            for item in node.items
            if isinstance(item.optional_vars, ast.Name)
        ]
    return []


def _append_binding(
    found: dict[str, list[tuple[int, ManagerCall]]], name: str, stmt_id: int, call: ManagerCall
) -> None:
    if name not in found:
        found[name] = []
    found[name].append((stmt_id, call))


def _resolve_name(
    name: str,
    with_index: int,
    flat: list[tuple[ast.stmt, BlockPath]],
    scope_node: ast.AST,
    table: SymbolTable,
    source: SourceText,
    module_calls: Mapping[str, list[tuple[int, ManagerCall]]],
) -> NameResolution:
    with_path = flat[with_index][1]
    preceding: list[NameBinding] = []
    seen_ids: set[int] = set()
    for stmt, path in flat[:with_index]:
        bound = _binding_of(stmt, name, table, source)
        if bound is None and _walrus_binds(stmt, name):
            bound = (BOUND_OTHER, None, describe_statement(stmt, source))
        if bound is None:
            continue
        kind, call, value = bound
        seen_ids.add(id(stmt))
        preceding.append(NameBinding(kind, stmt.lineno, call, value, _dominates(path, with_path)))
    elsewhere: tuple[ManagerCall, ...] = ()
    if name in module_calls:
        elsewhere = tuple(call for stmt_id, call in module_calls[name] if stmt_id not in seen_ids)
    return NameResolution(
        name=name,
        preceding=tuple(preceding),
        parameter=name in _parameter_names(scope_node),
        comprehension_target=name in _comprehension_targets([stmt for stmt, _ in flat]),
        elsewhere=elsewhere,
    )


def _manager_fact(
    item: ast.withitem,
    stmt: ast.With | ast.AsyncWith,
    scope: str,
    resolution: NameResolution | None,
    table: SymbolTable,
    source: SourceText,
) -> ManagerFact | None:
    call = _manager_call(item.context_expr, table, source)
    if resolution is not None:
        callee = resolution.name
    elif call is not None:
        callee = call.callee
    else:
        return None
    bound: str | None = None
    if isinstance(item.optional_vars, ast.Name):
        bound = item.optional_vars.id
    return ManagerFact(
        span=node_span(source, stmt),
        scope=scope,
        callee=callee,
        call=call,
        resolution=resolution,
        bound_name=bound,
        body_statements=tuple(try_statement(s, source) for s in stmt.body),
    )


def collect_python_managers(
    source: SourceText, module: ast.Module, relative_path: str
) -> tuple[ManagerFact, ...]:
    """Every ``with`` item whose context expression is a call (resolved with its
    positional arguments) or a plain name (resolved to the bindings of that name in
    the enclosing scope); the rules decide which ones are catches."""
    table = SymbolTable(module, module_dotted_name(relative_path))
    module_calls = _module_call_bindings(module, table, source)
    managers: list[ManagerFact] = []
    stack: list[tuple[ast.AST, str]] = [(module, MODULE_SCOPE)]
    while len(stack) > 0:
        node, scope = stack.pop()
        child_scope = scope
        if isinstance(node, SCOPE_NODES):
            name = scope_name(node)
            child_scope = name if scope == MODULE_SCOPE else f"{scope}.{name}"
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            managers.extend(_scope_managers(node, child_scope, table, source, module_calls))
        for child in ast.iter_child_nodes(node):
            stack.append((child, child_scope))
    managers.sort(key=lambda fact: fact.span)
    return tuple(managers)


def _scope_managers(
    node: ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    scope: str,
    table: SymbolTable,
    source: SourceText,
    module_calls: Mapping[str, list[tuple[int, ManagerCall]]],
) -> list[ManagerFact]:
    """The manager facts of every ``with`` in one scope's body (nested scopes excluded)."""
    found: list[ManagerFact] = []
    flat = _flatten_scope(list(node.body))
    for index, (stmt, _) in enumerate(flat):
        if not isinstance(stmt, ast.With | ast.AsyncWith):
            continue
        for item in stmt.items:
            resolution: NameResolution | None = None
            if isinstance(item.context_expr, ast.Name):
                resolution = _resolve_name(
                    item.context_expr.id, index, flat, node, table, source, module_calls
                )
            fact = _manager_fact(item, stmt, scope, resolution, table, source)
            if fact is not None:
                found.append(fact)
    return found
