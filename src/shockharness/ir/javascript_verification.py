"""Verification facts for JavaScript sources (H2): skip and focus markers, test cases,
suppression directives.

Suites and tests follow the Jest / Mocha / Vitest / Jasmine call conventions:
``describe(name, fn)``, ``it(name, fn)`` and ``test(name, fn)``, with ``.skip`` and
``.only`` variants and the ``xdescribe`` / ``xit`` / ``xtest`` (skip) and ``fdescribe`` /
``fit`` (focus) spellings. A test's qualified name joins the enclosing suite names with
``" > "``; a name that is not a string literal (or a template without substitutions)
is ``<dynamic>``.

Assertions counted anywhere in a test's callback: calls whose callee is an identifier
starting with ``expect`` or ``assert`` (each ``expect(...)`` once, however long its
matcher chain), and ``assert.<method>(...)`` calls. Tautologies:
``expect(L).toBe(L)`` / ``toEqual`` / ``toStrictEqual`` with the same literal on both
sides, ``expect(L).toBeTruthy()`` on a truthy literal, ``expect(L).toBeFalsy()`` on a
falsy literal, ``assert(L)`` / ``assert.ok(L)`` on a truthy literal, and
``assert.equal`` / ``strictEqual`` / ``deepEqual`` / ``deepStrictEqual`` on the same
literal twice.
"""

from collections.abc import Sequence

from tree_sitter import Node

from shockharness.constants import EQUALITY_OPERANDS
from shockharness.ir.javascript_catches import node_span, node_text
from shockharness.ir.javascript_nodes import Field, Kind
from shockharness.ir.model import (
    MARKER_FOCUS,
    MARKER_SKIP,
    CaseFact,
    Comment,
    SkipMarker,
    Span,
    Tautology,
    VerificationFacts,
)
from shockharness.ir.suppression_directives import javascript_directives
from shockharness.source import SourceText

SUITE = "describe"
TESTS = frozenset({"it", "test"})
CALLEES = frozenset({SUITE, *TESTS})
PREFIXED = {
    "xdescribe": (SUITE, MARKER_SKIP),
    "xit": ("it", MARKER_SKIP),
    "xtest": ("test", MARKER_SKIP),
    "fdescribe": (SUITE, MARKER_FOCUS),
    "fit": ("it", MARKER_FOCUS),
}
MEMBER_MARKERS = {"skip": MARKER_SKIP, "only": MARKER_FOCUS}
NAME_SEPARATOR = " > "
DYNAMIC_NAME = "<dynamic>"

CALL = Kind.CALL_EXPRESSION
MEMBER = Kind.MEMBER_EXPRESSION
IDENTIFIER = Kind.IDENTIFIER
STRING = Kind.STRING
TEMPLATE = Kind.TEMPLATE_STRING
SUBSTITUTION = Kind.TEMPLATE_SUBSTITUTION
STATEMENT_BLOCK = Kind.STATEMENT_BLOCK
COMMENT = Kind.COMMENT
FUNCTIONS = frozenset({Kind.ARROW_FUNCTION, Kind.FUNCTION_EXPRESSION, Kind.FUNCTION})
LITERALS = frozenset({Kind.NUMBER, STRING, TEMPLATE, Kind.TRUE, Kind.FALSE, Kind.NULL})
FALSY_KEYWORDS = frozenset({Kind.FALSE, Kind.NULL})
EXPECT_PREFIX = "expect"
ASSERT = "assert"
EQUALITY_MATCHERS = frozenset({"toBe", "toEqual", "toStrictEqual"})
TRUTHY_MATCHER = "toBeTruthy"
FALSY_MATCHER = "toBeFalsy"
ASSERT_TRUTH = frozenset({"ok"})
ASSERT_EQUALITY = frozenset({"equal", "strictEqual", "deepEqual", "deepStrictEqual"})
# Characters that make a numeric literal's digits non-zero (hex digits included); the
# prefix letters of 0x/0o/0b, an exponent and a BigInt suffix are not digits.
NONZERO_DIGITS = frozenset("123456789abcdef")
NUMBER_PREFIXES = ("0x", "0o", "0b")
EXPONENT = "e"


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _arguments(call: Node) -> list[Node]:
    arguments = call.child_by_field_name(Field.ARGUMENTS)
    if arguments is None:
        return []
    return [child for child in arguments.named_children if child.type != COMMENT]


def _literal_name(node: Node) -> str | None:
    """The value of a string literal or a template without substitutions."""
    if node.type == STRING or (
        node.type == TEMPLATE and not any(c.type == SUBSTITUTION for c in node.named_children)
    ):
        text = node_text(node)
        return text[1 : len(text) - 1]
    return None


def _callee(call: Node) -> tuple[str, str | None] | None:
    """(``describe``|``it``|``test``, marker kind or None) for a suite or test call."""
    function = call.child_by_field_name(Field.FUNCTION)
    if function is None:
        return None
    if function.type == IDENTIFIER:
        name = node_text(function)
        if name in CALLEES:
            return name, None
        return PREFIXED.get(name)  # xit, fdescribe, ...; None: not a test call
    if function.type != MEMBER:
        return None
    target = function.child_by_field_name(Field.OBJECT)
    member = function.child_by_field_name(Field.PROPERTY)
    if target is None or member is None or target.type != IDENTIFIER:
        return None
    base = node_text(target)
    marker = node_text(member)
    if base in CALLEES and marker in MEMBER_MARKERS:
        return base, MEMBER_MARKERS[marker]
    return None


def _is_truthy_literal(node: Node) -> bool:
    if node.type == Kind.TRUE:
        return True
    if node.type in (STRING, TEMPLATE):
        name = _literal_name(node)
        return name is not None and name != ""
    if node.type == Kind.NUMBER:
        digits = node_text(node).lower().replace("_", "").rstrip("n")
        for prefix in NUMBER_PREFIXES:
            if digits.startswith(prefix):
                digits = digits[len(prefix) :]
                return any(ch in NONZERO_DIGITS for ch in digits)
        mantissa = digits.split(EXPONENT)[0]
        return any(ch in NONZERO_DIGITS for ch in mantissa)
    return False


def _is_falsy_literal(node: Node) -> bool:
    if node.type in FALSY_KEYWORDS:
        return True
    return node.type in LITERALS and not _is_truthy_literal(node)


def _same_literal(left: Node, right: Node) -> bool:
    return (
        left.type in LITERALS
        and left.type == right.type
        and _collapse(node_text(left)) == _collapse(node_text(right))
    )


def _expect_argument(node: Node | None) -> Node | None:
    """The single literal argument of ``expect(L)``, else None."""
    if node is None or node.type != CALL:
        return None
    function = node.child_by_field_name(Field.FUNCTION)
    if function is None or function.type != IDENTIFIER or node_text(function) != EXPECT_PREFIX:
        return None
    arguments = _arguments(node)
    if len(arguments) != 1 or arguments[0].type not in LITERALS:
        return None
    return arguments[0]


def _is_tautology(call: Node) -> bool:
    function = call.child_by_field_name(Field.FUNCTION)
    if function is None:
        return False
    arguments = _arguments(call)
    if function.type == IDENTIFIER:
        return (
            node_text(function) == ASSERT
            and len(arguments) == 1
            and _is_truthy_literal(arguments[0])
        )
    if function.type != MEMBER:
        return False
    target = function.child_by_field_name(Field.OBJECT)
    member = function.child_by_field_name(Field.PROPERTY)
    if target is None or member is None:
        return False
    method = node_text(member)
    if target.type == IDENTIFIER and node_text(target) == ASSERT:
        if method in ASSERT_TRUTH and len(arguments) == 1:
            return _is_truthy_literal(arguments[0])
        if method in ASSERT_EQUALITY and len(arguments) == EQUALITY_OPERANDS:
            return _same_literal(arguments[0], arguments[1])
        return False
    expected = _expect_argument(target)
    if expected is None:
        return False
    if method in EQUALITY_MATCHERS and len(arguments) == 1:
        return _same_literal(expected, arguments[0])
    if method == TRUTHY_MATCHER and len(arguments) == 0:
        return _is_truthy_literal(expected)
    if method == FALSY_MATCHER and len(arguments) == 0:
        return _is_falsy_literal(expected)
    return False


def _is_assertion(call: Node) -> bool:
    function = call.child_by_field_name(Field.FUNCTION)
    if function is None:
        return False
    if function.type == IDENTIFIER:
        name = node_text(function)
        return name.startswith((EXPECT_PREFIX, ASSERT))
    if function.type == MEMBER:
        target = function.child_by_field_name(Field.OBJECT)
        return target is not None and target.type == IDENTIFIER and node_text(target) == ASSERT
    return False


def _body_empty(callback: Node) -> bool:
    body = callback.child_by_field_name(Field.BODY)
    if body is None or body.type != STATEMENT_BLOCK:
        return False
    return all(child.type == COMMENT for child in body.named_children)


def _case(source: SourceText, call: Node, callback: Node, name: str) -> CaseFact:
    assertions = 0
    tautologies: list[Tautology] = []
    stack: list[Node] = [callback]
    while len(stack) > 0:
        node = stack.pop()
        if node.type == CALL:
            if _is_assertion(node):
                assertions += 1
            if _is_tautology(node):
                tautologies.append(Tautology(_collapse(node_text(node)), node_span(source, node)))
        stack.extend(reversed(node.children))
    span = node_span(source, call)
    return CaseFact(
        name=name,
        span=Span(span.line, span.column, span.line, span.column),
        assertions=assertions,
        tautologies=tuple(sorted(tautologies, key=lambda t: (t.span, t.text))),
        body_empty=_body_empty(callback),
    )


def _marker_text(call: Node, name: str) -> str:
    function = call.child_by_field_name(Field.FUNCTION)
    assert function is not None
    return f"{_collapse(node_text(function))}({name!r})"


def collect_javascript_verification(
    source: SourceText, root: Node, comments: Sequence[Comment]
) -> VerificationFacts:
    markers: list[SkipMarker] = []
    cases: list[CaseFact] = []
    stack: list[tuple[Node, tuple[str, ...]]] = [(root, ())]
    while len(stack) > 0:
        node, suites = stack.pop()
        child_suites = suites
        if node.type == CALL:
            callee = _callee(node)
            if callee is not None:
                base, marker = callee
                arguments = _arguments(node)
                name = DYNAMIC_NAME
                if len(arguments) > 0:
                    literal = _literal_name(arguments[0])
                    if literal is not None:
                        name = literal
                qualified = NAME_SEPARATOR.join((*suites, name))
                if marker is not None:
                    function = node.child_by_field_name(Field.FUNCTION)
                    assert function is not None
                    markers.append(
                        SkipMarker(
                            kind=marker,
                            test=qualified,
                            text=_marker_text(node, name),
                            reason=None,
                            span=node_span(source, function),
                        )
                    )
                if base == SUITE:
                    child_suites = (*suites, name)
                else:
                    callbacks = [a for a in arguments if a.type in FUNCTIONS]
                    if len(callbacks) > 0:
                        cases.append(_case(source, node, callbacks[0], qualified))
        for child in reversed(node.children):
            stack.append((child, child_suites))
    markers.sort(key=lambda m: (m.span, m.text))
    cases.sort(key=lambda c: (c.span, c.name))
    return VerificationFacts(
        markers=tuple(markers),
        suppressions=javascript_directives(comments),
        cases=tuple(cases),
    )
