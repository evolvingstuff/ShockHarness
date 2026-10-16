"""Verification facts for Python sources (H2): skip markers, test cases, suppressions.

Tests follow pytest's and unittest's collection conventions: a module-level function
whose name starts with ``test``, and a ``test*`` method of a class whose name starts
with ``Test`` or that derives from a ``*TestCase`` base (nested test classes included).

Skip markers: ``pytest.mark.skip`` / ``skipif`` / ``xfail`` (also through
``from pytest import mark``), ``unittest.skip`` / ``skipIf`` / ``skipUnless`` /
``expectedFailure`` (also imported by name from ``unittest``) as decorators of a test
or a test class; a ``pytestmark = ...`` assignment at module or class level; and a
``pytest.skip(...)``, ``pytest.xfail(...)`` or ``self.skipTest(...)`` call that is a
statement directly in a test's body.

Assertions counted anywhere in a test's body: ``assert`` statements, calls whose callee
name starts with ``assert`` (``self.assertEqual``, ``mock.assert_called_once``,
``assert_frame_equal``), and ``with pytest.raises / pytest.warns /
pytest.deprecated_call``. Tautologies: ``assert <truthy constant>``, ``assert c == c``
or ``assert c is c`` on equal constants, ``self.assertTrue(<truthy constant>)``, and
``self.assertEqual`` / ``assertIs`` on two equal constants.
"""

import ast
from collections.abc import Sequence

from shockharness.constants import EQUALITY_OPERANDS
from shockharness.ir.model import (
    MARKER_SKIP,
    MARKER_XFAIL,
    MODULE_SCOPE,
    CaseFact,
    Comment,
    SkipMarker,
    Span,
    Tautology,
    VerificationFacts,
)
from shockharness.ir.python_catches import node_span
from shockharness.ir.suppression_directives import python_directives
from shockharness.source import SourceText

TEST_PREFIX = "test"
TEST_CLASS_PREFIX = "Test"
TESTCASE_SUFFIX = "TestCase"
PYTESTMARK = "pytestmark"
PYTEST_MARK = "pytest.mark"
PYTEST_MARKERS = {"skip": MARKER_SKIP, "skipif": MARKER_SKIP, "xfail": MARKER_XFAIL}
UNITTEST = "unittest"
UNITTEST_MARKERS = {
    "skip": MARKER_SKIP,
    "skipIf": MARKER_SKIP,
    "skipUnless": MARKER_SKIP,
    "expectedFailure": MARKER_XFAIL,
}
SKIP_CALLS = {
    "pytest.skip": MARKER_SKIP,
    "pytest.xfail": MARKER_XFAIL,
    "self.skipTest": MARKER_SKIP,
}
ASSERTION_CONTEXTS = frozenset({"pytest.raises", "pytest.warns", "pytest.deprecated_call"})
ASSERT_PREFIX = "assert"
REASON_KEYWORD = "reason"
TRUTH_ASSERTS = frozenset({"assertTrue"})
EQUALITY_ASSERTS = frozenset({"assertEqual", "assertEquals", "assertIs"})
CONSTANT_TYPES = (bool, int, float, complex, str, bytes)


def dotted_name(node: ast.expr) -> str | None:
    """``a.b.c`` for a chain of names and attributes, ``None`` for anything else."""
    parts: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    parts.reverse()
    return ".".join(parts)


def _text(node: ast.AST) -> str:
    return " ".join(ast.unparse(node).split())


class _Imports:
    """Names bound by ``from unittest import skip`` and ``from pytest import mark``."""

    def __init__(self, module: ast.Module) -> None:
        self.unittest: dict[str, str] = {}  # local name -> unittest name
        self.marks: set[str] = set()  # local names bound to pytest.mark
        for statement in module.body:
            if not isinstance(statement, ast.ImportFrom) or statement.level != 0:
                continue
            for alias in statement.names:
                local = alias.name
                if alias.asname is not None:
                    local = alias.asname
                if statement.module == UNITTEST and alias.name in UNITTEST_MARKERS:
                    self.unittest[local] = alias.name
                if statement.module == "pytest" and alias.name == "mark":
                    self.marks.add(local)

    def marker_kind(self, dotted: str) -> str | None:
        head, _, last = dotted.rpartition(".")
        if last in PYTEST_MARKERS and (head == PYTEST_MARK or head in self.marks):
            return PYTEST_MARKERS[last]
        if head == UNITTEST and last in UNITTEST_MARKERS:
            return UNITTEST_MARKERS[last]
        if head == "" and last in self.unittest:
            return UNITTEST_MARKERS[self.unittest[last]]
        return None


def _string_constant(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _reason(call: ast.Call) -> str | None:
    """The ``reason=`` keyword, else the first string-literal positional argument."""
    for keyword in call.keywords:
        if keyword.arg == REASON_KEYWORD:
            return _string_constant(keyword.value)
    for argument in call.args:
        text = _string_constant(argument)
        if text is not None:
            return text
    return None


def _decorator_marker(
    source: SourceText, decorator: ast.expr, test: str, imports: _Imports
) -> SkipMarker | None:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    dotted = dotted_name(target)
    if dotted is None:
        return None
    kind = imports.marker_kind(dotted)
    if kind is None:
        return None
    reason = _reason(decorator) if isinstance(decorator, ast.Call) else None
    return SkipMarker(
        kind=kind,
        test=test,
        text=_text(decorator),
        reason=reason,
        span=node_span(source, decorator),
    )


def _pytestmark_markers(
    source: SourceText, statement: ast.stmt, test: str, imports: _Imports
) -> list[SkipMarker]:
    """``pytestmark = pytest.mark.skip(...)`` or a list/tuple of marks."""
    if not isinstance(statement, ast.Assign):
        return []
    if not any(isinstance(t, ast.Name) and t.id == PYTESTMARK for t in statement.targets):
        return []
    values: Sequence[ast.expr] = [statement.value]
    if isinstance(statement.value, ast.List | ast.Tuple):
        values = statement.value.elts
    markers: list[SkipMarker] = []
    for value in values:
        marker = _decorator_marker(source, value, test, imports)
        if marker is not None:
            markers.append(marker)
    return markers


def _is_truthy_constant(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, CONSTANT_TYPES)
        and bool(node.value) is True
    )


def _equal_constants(left: ast.expr, right: ast.expr) -> bool:
    """Two literal constants of the same type and value (``None`` included)."""
    if not isinstance(left, ast.Constant) or not isinstance(right, ast.Constant):
        return False
    if left.value is None or right.value is None:
        return left.value is None and right.value is None
    return (
        isinstance(left.value, CONSTANT_TYPES)
        and type(left.value) is type(right.value)
        and left.value == right.value
    )


def _assert_is_tautology(statement: ast.Assert) -> bool:
    test = statement.test
    if _is_truthy_constant(test):
        return True
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        operator = test.ops[0]
        if isinstance(operator, ast.Eq | ast.Is):
            return _equal_constants(test.left, test.comparators[0])
    return False


def _call_is_tautology(call: ast.Call) -> bool:
    if not isinstance(call.func, ast.Attribute):
        return False
    name = call.func.attr
    if name in TRUTH_ASSERTS and len(call.args) == 1:
        return _is_truthy_constant(call.args[0])
    if name in EQUALITY_ASSERTS and len(call.args) == EQUALITY_OPERANDS:
        return _equal_constants(call.args[0], call.args[1])
    return False


def _is_assertion_call(call: ast.Call) -> bool:
    dotted = dotted_name(call.func)
    if dotted is None:
        return False
    _, _, last = dotted.rpartition(".")
    return last.startswith(ASSERT_PREFIX)


def _body_empty(body: Sequence[ast.stmt]) -> bool:
    """Only ``pass``, ``...`` or a docstring: the test checks nothing."""
    for statement in body:
        if isinstance(statement, ast.Pass):
            continue
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
            continue
        return False
    return True


def _case(
    source: SourceText, function: ast.FunctionDef | ast.AsyncFunctionDef, name: str
) -> CaseFact:
    assertions = 0
    tautologies: list[Tautology] = []
    stack: list[ast.AST] = list(reversed(function.body))
    while len(stack) > 0:
        node = stack.pop()
        if isinstance(node, ast.Assert):
            assertions += 1
            if _assert_is_tautology(node):
                tautologies.append(Tautology(_text(node), node_span(source, node)))
        elif isinstance(node, ast.Call):
            if _is_assertion_call(node):
                assertions += 1
                if _call_is_tautology(node):
                    tautologies.append(Tautology(_text(node), node_span(source, node)))
        elif isinstance(node, ast.With | ast.AsyncWith):
            for item in node.items:
                context = item.context_expr
                if isinstance(context, ast.Call):
                    dotted = dotted_name(context.func)
                    if dotted in ASSERTION_CONTEXTS:
                        assertions += 1
        stack.extend(reversed(list(ast.iter_child_nodes(node))))
    return CaseFact(
        name=name,
        span=_def_span(source, function),
        assertions=assertions,
        tautologies=tuple(tautologies),
        body_empty=_body_empty(function.body),
    )


def _def_span(source: SourceText, function: ast.FunctionDef | ast.AsyncFunctionDef) -> Span:
    """The ``def`` line of a function (not its decorators), as the test's location."""
    span = node_span(source, function)
    return Span(span.line, span.column, span.line, span.column)


def _skip_call_markers(
    source: SourceText, function: ast.FunctionDef | ast.AsyncFunctionDef, name: str
) -> list[SkipMarker]:
    markers: list[SkipMarker] = []
    for statement in function.body:
        if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
            continue
        call = statement.value
        dotted = dotted_name(call.func)
        if dotted is None or dotted not in SKIP_CALLS:
            continue
        markers.append(
            SkipMarker(
                kind=SKIP_CALLS[dotted],
                test=name,
                text=_text(call),
                reason=_reason(call),
                span=node_span(source, call),
            )
        )
    return markers


def _is_test_class(node: ast.ClassDef) -> bool:
    if node.name.startswith(TEST_CLASS_PREFIX):
        return True
    for base in node.bases:
        dotted = dotted_name(base)
        if dotted is not None and dotted.endswith(TESTCASE_SUFFIX):
            return True
    return False


def _is_test_function(node: ast.stmt) -> bool:
    return isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith(
        TEST_PREFIX
    )


def collect_python_verification(
    source: SourceText, module: ast.Module, comments: Sequence[Comment]
) -> VerificationFacts:
    imports = _Imports(module)
    markers: list[SkipMarker] = []
    cases: list[CaseFact] = []
    # (statements, qualifier) pairs: the module body, then the bodies of test classes.
    stack: list[tuple[Sequence[ast.stmt], str]] = [(module.body, "")]
    while len(stack) > 0:
        body, qualifier = stack.pop()
        scope = MODULE_SCOPE if qualifier == "" else qualifier
        for statement in body:
            markers.extend(_pytestmark_markers(source, statement, scope, imports))
            if isinstance(statement, ast.ClassDef) and _is_test_class(statement):
                name = statement.name if qualifier == "" else f"{qualifier}.{statement.name}"
                for decorator in statement.decorator_list:
                    marker = _decorator_marker(source, decorator, name, imports)
                    if marker is not None:
                        markers.append(marker)
                stack.append((statement.body, name))
                continue
            if not _is_test_function(statement):
                continue
            assert isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef)
            name = statement.name if qualifier == "" else f"{qualifier}.{statement.name}"
            for decorator in statement.decorator_list:
                marker = _decorator_marker(source, decorator, name, imports)
                if marker is not None:
                    markers.append(marker)
            markers.extend(_skip_call_markers(source, statement, name))
            cases.append(_case(source, statement, name))
    markers.sort(key=lambda m: (m.span, m.text))
    cases.sort(key=lambda c: (c.span, c.name))
    return VerificationFacts(
        markers=tuple(markers),
        suppressions=python_directives(comments),
        cases=tuple(cases),
    )
