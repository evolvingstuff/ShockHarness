"""Guardrail facts for Python (H3; consumed by EXC004, STUB001, ASSERT001, BOOL001 and
IMPORT001 in rules/guardrails.py).

Syntax only:

* **finally exits**: ``return`` anywhere in a ``finally`` block, and ``break``/``continue``
  that are not inside a loop of their own within the block; nested functions, lambdas and
  classes are separate scopes and are skipped (PEP 765 names the same constructs);
* **placeholders**: ``raise NotImplementedError`` (bare or called) and ``raise
  NotImplemented`` (a bug in its own right: ``NotImplemented`` is not an exception), and a
  function whose body is only ``pass``, ``...`` and a docstring. Intentionally abstract
  API is not a placeholder: a function decorated ``@abstractmethod`` or ``@overload``, and
  any method of a class that derives from ``ABC``/``Protocol`` or uses ``ABCMeta``;
* **asserts**: every ``assert`` outside ``if TYPE_CHECKING:``, with whether its test only
  narrows types;
* **Boolean arguments**: a ``True``/``False`` literal passed positionally to a call with
  more than one positional argument;
* **import-time calls**: every call executed when the module is imported: the module body,
  class bodies, decorators and default values evaluated at definition time;
  not function or lambda bodies, and not ``if __name__ == "__main__":`` or ``if
  TYPE_CHECKING:`` blocks.
"""

import ast

from shockharness.constants import EVIDENCE_MAX_CHARS
from shockharness.ir.model import (
    EXIT_BREAK,
    EXIT_CONTINUE,
    EXIT_RETURN,
    MODULE_SCOPE,
    PLACEHOLDER_EMPTY_BODY,
    PLACEHOLDER_NOT_IMPLEMENTED,
    PLACEHOLDER_NOT_IMPLEMENTED_CONSTANT,
    AssertFact,
    BooleanArgument,
    FinallyExit,
    GuardrailFacts,
    ImportTimeCall,
    Placeholder,
)
from shockharness.ir.python_catches import dotted_name, node_span
from shockharness.source import SourceText

ABSTRACT_DECORATORS = frozenset({"abstractmethod", "overload"})
ABSTRACT_BASES = frozenset({"ABC", "Protocol"})
ABSTRACT_METACLASSES = frozenset({"ABCMeta"})
NOT_IMPLEMENTED_ERROR = "NotImplementedError"
NOT_IMPLEMENTED_CONSTANT = "NotImplemented"
TYPE_CHECKING = "TYPE_CHECKING"
MAIN_NAME = "__name__"
MAIN_VALUE = "__main__"
LOOPS = (ast.For, ast.AsyncFor, ast.While)
SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _excerpt(node: ast.AST) -> str:
    text = " ".join(ast.unparse(node).split())
    if len(text) > EVIDENCE_MAX_CHARS:
        return text[:EVIDENCE_MAX_CHARS] + "..."
    return text


def _last_segment(expr: ast.expr) -> str | None:
    """The final name of ``x``, ``a.b.x`` or ``a.b.x(...)``."""
    target = expr.func if isinstance(expr, ast.Call) else expr
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def _is_type_checking(test: ast.expr) -> bool:
    return _last_segment(test) == TYPE_CHECKING and not isinstance(test, ast.Call)


def _is_main_guard(test: ast.expr) -> bool:
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return False
    sides = (test.left, test.comparators[0])
    names = [s for s in sides if isinstance(s, ast.Name) and s.id == MAIN_NAME]
    values = [s for s in sides if isinstance(s, ast.Constant) and s.value == MAIN_VALUE]
    return isinstance(test.ops[0], ast.Eq) and len(names) == 1 and len(values) == 1


# -- finally exits ------------------------------------------------------------------------


def _finally_exits(source: SourceText, module: ast.Module) -> list[FinallyExit]:
    exits: list[FinallyExit] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Try | ast.TryStar):
            for statement in node.finalbody:
                _scan_finally(source, statement, exits, in_loop=False)
    return exits


def _exit_kind(node: ast.AST, in_loop: bool) -> str | None:
    if isinstance(node, ast.Return):
        return EXIT_RETURN
    if in_loop:
        return None
    if isinstance(node, ast.Break):
        return EXIT_BREAK
    if isinstance(node, ast.Continue):
        return EXIT_CONTINUE
    return None


def _scan_finally(
    source: SourceText, node: ast.AST, exits: list[FinallyExit], *, in_loop: bool
) -> None:
    if isinstance(node, SCOPES):
        return
    kind = _exit_kind(node, in_loop)
    if kind is not None:
        exits.append(FinallyExit(kind, node_span(source, node)))
    for field, value in ast.iter_fields(node):
        # The ``else`` of a loop runs after it, outside it: a break there leaves the block.
        inner = in_loop or (isinstance(node, LOOPS) and field == "body")
        children = value if isinstance(value, list) else [value]
        for child in children:
            if isinstance(child, ast.AST):
                _scan_finally(source, child, exits, in_loop=inner)


# -- placeholders -------------------------------------------------------------------------


def _is_abstract_class(node: ast.ClassDef) -> bool:
    for base in node.bases:
        if _last_segment(base) in ABSTRACT_BASES:
            return True
    for keyword in node.keywords:
        if keyword.arg == "metaclass" and _last_segment(keyword.value) in ABSTRACT_METACLASSES:
            return True
    return False


def _is_abstract_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(_last_segment(d) in ABSTRACT_DECORATORS for d in node.decorator_list)


def _is_docstring(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )


def _is_filler(statement: ast.stmt) -> bool:
    if isinstance(statement, ast.Pass):
        return True
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and statement.value.value is Ellipsis
    )


def _body_is_empty(body: list[ast.stmt]) -> bool:
    return all(_is_filler(s) or _is_docstring(s) for s in body) and any(_is_filler(s) for s in body)


def _raised_name(node: ast.Raise) -> str | None:
    if node.exc is None:
        return None
    return _last_segment(node.exc)


def _qualified(scope: str, name: str) -> str:
    return name if scope == MODULE_SCOPE else f"{scope}.{name}"


class _Placeholders:
    def __init__(self, source: SourceText) -> None:
        self.source = source
        self.found: list[Placeholder] = []

    def visit(self, node: ast.AST, scope: str, *, abstract: bool) -> None:
        if isinstance(node, ast.ClassDef):
            inner = _qualified(scope, node.name)
            for child in node.body:
                self.visit(child, inner, abstract=_is_abstract_class(node))
            return
        if isinstance(node, FUNCTIONS):
            self._function(node, scope, abstract=abstract)
            return
        if isinstance(node, ast.Raise) and not abstract:
            self._raise(node, scope)
        for child in ast.iter_child_nodes(node):
            self.visit(child, scope, abstract=abstract)

    def _function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, scope: str, *, abstract: bool
    ) -> None:
        inner = _qualified(scope, node.name)
        skip = abstract
        if _is_abstract_function(node):
            skip = True
        if not skip and _body_is_empty(node.body):
            self.found.append(
                Placeholder(
                    PLACEHOLDER_EMPTY_BODY,
                    f"def {node.name}(...): {_excerpt(node.body[len(node.body) - 1])}",
                    inner,
                    node_span(self.source, node),
                )
            )
        for child in node.body:
            self.visit(child, inner, abstract=skip)

    def _raise(self, node: ast.Raise, scope: str) -> None:
        name = _raised_name(node)
        kind = None
        if name == NOT_IMPLEMENTED_ERROR:
            kind = PLACEHOLDER_NOT_IMPLEMENTED
        elif name == NOT_IMPLEMENTED_CONSTANT:
            kind = PLACEHOLDER_NOT_IMPLEMENTED_CONSTANT
        if kind is not None:
            self.found.append(
                Placeholder(kind, _excerpt(node), scope, node_span(self.source, node))
            )


# -- asserts ------------------------------------------------------------------------------


def _narrows(test: ast.expr) -> bool:
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And):
        return all(_narrows(value) for value in test.values)
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        right = test.comparators[0]
        return (
            isinstance(test.ops[0], ast.IsNot)
            and isinstance(right, ast.Constant)
            and right.value is None
        )
    return (
        isinstance(test, ast.Call)
        and isinstance(test.func, ast.Name)
        and test.func.id == "isinstance"
    )


def _asserts(source: SourceText, module: ast.Module) -> list[AssertFact]:
    found: list[AssertFact] = []
    stack: list[ast.AST] = [module]
    while len(stack) > 0:
        node = stack.pop()
        if isinstance(node, ast.If) and _is_type_checking(node.test):
            stack.extend(node.orelse)
            continue
        if isinstance(node, ast.Assert):
            found.append(AssertFact(_excerpt(node), _narrows(node.test), node_span(source, node)))
        stack.extend(ast.iter_child_nodes(node))
    return found


# -- Boolean arguments --------------------------------------------------------------------


def _is_boolean(expr: ast.expr) -> bool:
    return isinstance(expr, ast.Constant) and isinstance(expr.value, bool)


def _boolean_arguments(source: SourceText, module: ast.Module) -> list[BooleanArgument]:
    found: list[BooleanArgument] = []
    for node in ast.walk(module):
        if not isinstance(node, ast.Call) or len(node.args) <= 1:
            continue
        if any(isinstance(arg, ast.Starred) for arg in node.args):
            continue
        callee = dotted_name(node.func)
        if callee is None:
            continue
        for position, arg in enumerate(node.args):
            if _is_boolean(arg):
                found.append(
                    BooleanArgument(callee, position, _excerpt(node), node_span(source, arg))
                )
    return found


# -- import-time calls --------------------------------------------------------------------


def _definition_time(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> list[ast.AST]:
    """The parts of a function definition evaluated when the ``def`` runs."""
    parts: list[ast.AST] = [*node.args.defaults]
    parts.extend(d for d in node.args.kw_defaults if d is not None)
    if isinstance(node, FUNCTIONS):
        parts.extend(node.decorator_list)
    return parts


def _import_time_calls(source: SourceText, module: ast.Module) -> list[ImportTimeCall]:
    found: list[ImportTimeCall] = []
    stack: list[ast.AST] = list(module.body)
    while len(stack) > 0:
        node = stack.pop()
        if isinstance(node, ast.If) and (_is_main_guard(node.test) or _is_type_checking(node.test)):
            stack.extend(node.orelse)
            continue
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            stack.extend(_definition_time(node))
            continue
        if isinstance(node, ast.Call):
            callee = dotted_name(node.func)
            if callee is not None:
                found.append(ImportTimeCall(callee, _excerpt(node), node_span(source, node)))
        stack.extend(ast.iter_child_nodes(node))
    return found


def collect_python_guardrails(source: SourceText, module: ast.Module) -> GuardrailFacts:
    placeholders = _Placeholders(source)
    for statement in module.body:
        placeholders.visit(statement, MODULE_SCOPE, abstract=False)
    return GuardrailFacts(
        finally_exits=tuple(sorted(_finally_exits(source, module), key=lambda f: f.span)),
        placeholders=tuple(sorted(placeholders.found, key=lambda p: (p.span, p.kind))),
        asserts=tuple(sorted(_asserts(source, module), key=lambda a: a.span)),
        boolean_arguments=tuple(
            sorted(_boolean_arguments(source, module), key=lambda b: (b.span, b.position))
        ),
        import_time_calls=tuple(
            sorted(_import_time_calls(source, module), key=lambda c: (c.span, c.callee))
        ),
    )
