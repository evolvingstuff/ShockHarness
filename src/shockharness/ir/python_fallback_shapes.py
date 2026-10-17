"""DEF002 shapes spelled with statements (spec 21.1 decision 34).

* The membership fallback as two statements: ``if k in m: return m[k]`` followed by
  ``return v``, and ``if k not in m: return v`` followed by ``return m[k]``. Both are
  ``m.get(k, v)`` spelled out, like the ``m[k] if k in m else v`` ternary.
* A fallback helper: a module-level function whose body, after a docstring and any
  leading checks that only raise, returns a lookup with a default that is one of its
  parameters (``m.get(k, default)``, ``getattr(o, a, default)``, either membership
  form, or ``try: return m[k]`` with a handler returning the default). Such a helper is
  ``m.get(k, v)`` under another name: the default is chosen at each call site.
"""

import ast
import itertools
from dataclasses import dataclass

from shockharness.constants import (
    GETATTR_WITH_FALLBACK_ARITY,
    LOOKUP_WITH_FALLBACK_ARITY,
    MEMBERSHIP_RETURN_STATEMENTS,
)

GET = "get"
GETATTR = "getattr"
# The exceptions a missing key, index or attribute raises.
MISSING_ERRORS = frozenset({"KeyError", "LookupError", "IndexError", "AttributeError"})


@dataclass(frozen=True)
class MembershipReturn:
    """``if`` + ``return`` spelling of ``m[k] if k in m else v``."""

    test: ast.Compare
    key: ast.expr
    mapping: ast.expr
    missing: ast.expr


@dataclass(frozen=True)
class FallbackHelper:
    name: str
    parameter: str
    index: int
    line: int


def _same(a: ast.AST, b: ast.AST) -> bool:
    return ast.dump(a) == ast.dump(b)


def _membership(test: ast.expr) -> tuple[ast.Compare, bool] | None:
    """(the comparison, True for ``in``) of ``k in m`` / ``k not in m``."""
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return None
    op = test.ops[0]
    if isinstance(op, ast.In):
        return test, True
    if isinstance(op, ast.NotIn):
        return test, False
    return None


def _returned(statements: list[ast.stmt]) -> ast.expr | None:
    """The value of a block that is one ``return value``."""
    if len(statements) != 1 or not isinstance(statements[0], ast.Return):
        return None
    return statements[0].value


def _lookup_of(value: ast.expr | None, test: ast.Compare) -> bool:
    """``value`` is ``m[k]`` for the ``k in m`` of ``test``."""
    if not isinstance(value, ast.Subscript):
        return False
    return _same(value.value, test.comparators[0]) and _same(value.slice, test.left)


def membership_return(first: ast.stmt, second: ast.stmt) -> MembershipReturn | None:
    """The fallback the pair ``first``, ``second`` spells, if it is one."""
    if not isinstance(first, ast.If) or len(first.orelse) != 0:
        return None
    if not isinstance(second, ast.Return) or second.value is None:
        return None
    membership = _membership(first.test)
    branch = _returned(first.body)
    if membership is None or branch is None:
        return None
    test, positive = membership
    present, missing = second.value, branch
    if positive:
        present, missing = branch, second.value
    if not _lookup_of(present, test):
        return None
    return MembershipReturn(test, test.left, test.comparators[0], missing)


def membership_returns(block: list[ast.stmt]) -> list[MembershipReturn]:
    found: list[MembershipReturn] = []
    for first, second in itertools.pairwise(block):
        shape = membership_return(first, second)
        if shape is not None:
            found.append(shape)
    return found


def _is_docstring(statement: ast.stmt) -> bool:
    return isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)


def _raises_only(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.If)
        and len(statement.orelse) == 0
        and all(isinstance(inner, ast.Raise) for inner in statement.body)
    )


def _lookup_body(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.stmt]:
    """The body after a docstring and the leading checks that only raise."""
    body = list(function.body)
    if len(body) > 0 and _is_docstring(body[0]):
        body = body[1:]
    while len(body) > 1 and _raises_only(body[0]):
        body = body[1:]
    return body


def _handled_missing(handler: ast.ExceptHandler) -> bool:
    caught = handler.type
    names: list[ast.expr] = []
    if isinstance(caught, ast.Tuple):
        names = list(caught.elts)
    elif caught is not None:
        names = [caught]
    return len(names) > 0 and all(isinstance(n, ast.Name) and n.id in MISSING_ERRORS for n in names)


def _call_default(value: ast.expr) -> ast.expr | None:
    """The default of ``m.get(k, v)`` / ``getattr(o, a, v)``."""
    if not isinstance(value, ast.Call) or len(value.keywords) > 0:
        return None
    function = value.func
    arity = len(value.args)
    if isinstance(function, ast.Attribute) and function.attr == GET:
        if arity == LOOKUP_WITH_FALLBACK_ARITY:
            return value.args[arity - 1]
    if isinstance(function, ast.Name) and function.id == GETATTR:
        if arity == GETATTR_WITH_FALLBACK_ARITY:
            return value.args[arity - 1]
    return None


def _ternary_default(value: ast.expr) -> ast.expr | None:
    """The default of ``m[k] if k in m else v`` (either polarity)."""
    if not isinstance(value, ast.IfExp):
        return None
    membership = _membership(value.test)
    if membership is None:
        return None
    test, positive = membership
    present, missing = value.orelse, value.body
    if positive:
        present, missing = value.body, value.orelse
    if not _lookup_of(present, test):
        return None
    return missing


def _try_default(statement: ast.stmt) -> ast.expr | None:
    """The default of ``try: return m[k]`` / ``except KeyError: return v``."""
    if not isinstance(statement, ast.Try) or len(statement.handlers) != 1:
        return None
    if len(statement.orelse) != 0 or len(statement.finalbody) != 0:
        return None
    looked_up = _returned(statement.body)
    handler = statement.handlers[0]
    if not isinstance(looked_up, ast.Subscript | ast.Attribute) or not _handled_missing(handler):
        return None
    return _returned(handler.body)


def _helper_default(function: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.expr | None:
    body = _lookup_body(function)
    if len(body) == MEMBERSHIP_RETURN_STATEMENTS:
        first, second = body
        shape = membership_return(first, second)
        if shape is None:
            return None
        return shape.missing
    if len(body) != 1:
        return None
    if isinstance(body[0], ast.Try):
        return _try_default(body[0])
    value = _returned(body)
    if value is None:
        return None
    default = _call_default(value)
    if default is None:
        default = _ternary_default(value)
    return default


def fallback_helpers(module: ast.Module) -> dict[str, FallbackHelper]:
    """Module-level functions that are a lookup with a caller-chosen default."""
    found: dict[str, FallbackHelper] = {}
    for statement in module.body:
        if not isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        default = _helper_default(statement)
        positional = [a.arg for a in statement.args.posonlyargs + statement.args.args]
        if not isinstance(default, ast.Name) or default.id not in positional:
            continue
        found[statement.name] = FallbackHelper(
            statement.name, default.id, positional.index(default.id), statement.lineno
        )
    return found


def helper_default(call: ast.Call, helper: FallbackHelper) -> ast.expr | None:
    """The default a call passes to the helper, positionally or by keyword."""
    if any(isinstance(argument, ast.Starred) for argument in call.args):
        return None
    if helper.index < len(call.args):
        return call.args[helper.index]
    for keyword in call.keywords:
        if keyword.arg == helper.parameter:
            return keyword.value
    return None
