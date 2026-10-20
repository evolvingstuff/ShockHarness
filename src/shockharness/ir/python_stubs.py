"""A test file's patches of project code (VERIFY005), and what tells which tests run them.

Patches: ``monkeypatch.setattr(obj, "name", value)`` and ``monkeypatch.setattr("a.b.c",
value)``; ``patch("a.b.c", ...)`` from ``unittest.mock`` or pytest-mock, as a call, a
decorator or a context manager; ``patch.object(obj, "name", ...)``. Each is recorded with
the function it is in. A patch is a tripwire when its stub is there to be not called: it
raises, calls ``pytest.fail``, has a ``side_effect`` that is an exception, or appends to
a list the function then asserts empty.
"""

import ast

from shockharness.ir.model import StubFacts, StubPatch
from shockharness.ir.python_catches import dotted_name, node_span
from shockharness.source import SourceText

FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
MONKEYPATCH = "monkeypatch"
SETATTR = "setattr"
PATCH = "patch"
OBJECT = "object"
FIXTURE = "fixture"
TEST_PREFIX = "test"
FAIL = "fail"
THROW = "throw"
STUB_KEYWORDS = ("new", "value")
SIDE_EFFECT = "side_effect"
EXCEPTION_SUFFIXES = ("Error", "Exception")
RECORDERS = frozenset({"append", "add", "extend"})
STRING_FORM_ARGUMENTS = 2  # setattr("a.b.c", value)
OBJECT_FORM_ARGUMENTS = 3  # setattr(obj, "name", value)
OBJECT_STUB = 2  # the stub's position in setattr(obj, "name", value) and patch.object


def _final(dotted: str) -> str:
    _head, _dot, last = dotted.rpartition(".")
    return last


def _string(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _keyword(call: ast.Call, names: tuple[str, ...]) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg in names:
            return keyword.value
    return None


def _setattr_form(args: list[ast.expr]) -> tuple[str, str, ast.expr | None] | None:
    """``setattr("a.b.c", value)`` or ``setattr(obj, "name", value)``."""
    if len(args) == STRING_FORM_ARGUMENTS:
        dotted = _string(args[0])
        if dotted is not None:
            return "", dotted, args[1]
    if len(args) == OBJECT_FORM_ARGUMENTS:
        name = _string(args[1])
        if name is not None:
            return ast.unparse(args[0]), name, args[OBJECT_STUB]
    return None


def _object_form(call: ast.Call) -> tuple[str, str, ast.expr | None] | None:
    """``patch.object(obj, "name"[, stub])``."""
    args = call.args
    name = _string(args[1]) if len(args) > 1 else None
    if name is None:
        return None
    value = args[OBJECT_STUB] if len(args) > OBJECT_STUB else _keyword(call, STUB_KEYWORDS)
    return ast.unparse(args[0]), name, value


def _dotted_form(call: ast.Call) -> tuple[str, str, ast.expr | None] | None:
    """``patch("a.b.c"[, stub])``."""
    args = call.args
    dotted = _string(args[0]) if len(args) > 0 else None
    if dotted is None:
        return None
    value = args[1] if len(args) > 1 else _keyword(call, STUB_KEYWORDS)
    return "", dotted, value


def _form(call: ast.Call) -> tuple[str, str, ast.expr | None] | None:
    """(target, attribute, stub value) of a patch call, or None for another call."""
    callee = dotted_name(call.func)
    if callee is None:
        return None
    parts = callee.split(".")
    final = parts[len(parts) - 1]
    if final == SETATTR and MONKEYPATCH in parts:
        return _setattr_form(call.args)
    if final == OBJECT and PATCH in parts:
        return _object_form(call)
    if final == PATCH:
        return _dotted_form(call)
    return None


def _raises(node: ast.AST) -> bool:
    for n in ast.walk(node):
        if isinstance(n, ast.Raise):
            return True
        if isinstance(n, ast.Call):
            callee = dotted_name(n.func)
            if callee is not None and _final(callee) in (FAIL, THROW):
                return True
            if isinstance(n.func, ast.Attribute) and n.func.attr == THROW:
                return True
    return False


def _recorded(node: ast.AST) -> set[str]:
    return {
        n.func.value.id
        for n in ast.walk(node)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr in RECORDERS
        and isinstance(n.func.value, ast.Name)
    }


def _empties(test: ast.expr, names: set[str]) -> bool:
    """``not name`` or ``name == []`` (or ``set()``-like empty displays) for a recorder."""
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return isinstance(test.operand, ast.Name) and test.operand.id in names
    if not isinstance(test, ast.Compare) or not isinstance(test.left, ast.Name):
        return False
    empty = [c for c in test.comparators if isinstance(c, ast.List | ast.Set | ast.Tuple)]
    return test.left.id in names and len(empty) == 1 and len(empty[0].elts) == 0


def _asserted_empty(holder: ast.AST, names: set[str]) -> bool:
    return any(isinstance(n, ast.Assert) and _empties(n.test, names) for n in ast.walk(holder))


def _stub_body(holder: ast.AST, value: ast.expr) -> ast.AST:
    """The stub's code: a lambda, or a local def named as the value."""
    if isinstance(value, ast.Name):
        for n in ast.walk(holder):
            if isinstance(n, FUNCTIONS) and n.name == value.id:
                return n
    return value


def _tripwire(holder: ast.AST, call: ast.Call, value: ast.expr | None) -> bool:
    side_effect = _keyword(call, (SIDE_EFFECT,))
    if side_effect is not None:
        name = dotted_name(side_effect.func if isinstance(side_effect, ast.Call) else side_effect)
        if name is not None and name.endswith(EXCEPTION_SUFFIXES):
            return True
    if value is None:
        return False
    body = _stub_body(holder, value)
    if _raises(body):
        return True
    recorded = _recorded(body)
    return len(recorded) > 0 and _asserted_empty(holder, recorded)


def _is_fixture(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in function.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        name = dotted_name(target)
        if name is not None and _final(name) == FIXTURE:
            return True
    return False


def _parameters(function: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, ...]:
    arguments = function.args
    return tuple(a.arg for a in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs])


def collect_python_stubs(source: SourceText, module: ast.Module) -> StubFacts:
    patches: list[StubPatch] = []
    fixtures: list[tuple[int, int, str]] = []
    tests: list[tuple[int, int, tuple[str, ...]]] = []
    for function in ast.walk(module):
        if not isinstance(function, FUNCTIONS):
            continue
        start = node_span(source, function)
        if _is_fixture(function):
            fixtures.append((start.line, start.column, function.name))
        elif function.name.startswith(TEST_PREFIX):
            tests.append((start.line, start.column, _parameters(function)))
        calls = [n for n in ast.walk(function) if isinstance(n, ast.Call)]
        for call in calls:
            form = _form(call)
            if form is None or _owner(function, call) is not function:
                continue
            target, attribute, value = form
            patches.append(
                StubPatch(
                    node_span(source, call),
                    start.line,
                    start.column,
                    target,
                    attribute,
                    _tripwire(function, call, value),
                )
            )
    patches.sort(key=lambda p: p.span)
    return StubFacts(tuple(patches), tuple(sorted(fixtures)), tuple(sorted(tests)))


def _owner(function: ast.AST, call: ast.Call) -> ast.AST:
    """The innermost function holding the call, within ``function`` (its decorators belong
    to it)."""
    owner = function
    for n in ast.walk(function):
        if isinstance(n, FUNCTIONS) and n is not function:
            if any(c is call for c in ast.walk(n)) and not any(c is call for c in n.decorator_list):
                owner = n
    return owner
