"""Verification facts for C# (milestone G4): the suppressions VERIFY002 compares between
revisions and TYPE001 reads, and the test cases and skip markers of NUnit, xUnit, MSTest,
gdUnit4 and GoDotTest (VERIFY001, VERIFY004, ROLE001).

Suppressions:

* ``#pragma warning disable CS8602, IDE0051``: narrow when it names codes, blanket when
  it names none; it holds until ``#pragma warning restore``, so its scope is a region.
* ``#nullable disable`` (with or without ``warnings``/``annotations``): turns the
  compiler's null checking off for a region; it names no code, so it is blanket.
* ``[SuppressMessage("Category", "CA1822:...")]`` and ``UnconditionalSuppressMessage``:
  narrow, naming the check id before the colon. An ``[assembly: ...]`` or
  ``[module: ...]`` one (GlobalSuppressions.cs) covers the whole project and is recorded
  with file scope.
* Comments: ReSharper's ``// ReSharper disable`` and ShockHarness's own directive
  (ir/suppression_directives.py).

Tests:

* A test case is a method with ``[Test]``, ``[TestCase]``, ``[TestCaseSource]`` (NUnit,
  GoDotTest, gdUnit4), ``[Fact]``, ``[Theory]`` (xUnit), ``[TestMethod]`` or
  ``[DataTestMethod]`` (MSTest). Its name is qualified by its class (``MathTests.Adds``).
* An assertion is a call whose method or leftmost receiver is named like one:
  ``Assert.Equal``, ``ClassicAssert.AreEqual``, ``AssertThat(x)`` (gdUnit4),
  ``x.Should()`` (FluentAssertions), ``x.ShouldBe(y)`` (Shouldly), ``mock.Verify(...)`` and
  ``VerifyAdd``/``VerifySet`` (Moq), or a helper named so (``VerifyFade()``).
* A tautology: ``Assert.True(true)``, ``Assert.IsTrue(true)``, ``Assert.That(true)``,
  ``Assert.False(false)``, ``true.ShouldBeTrue()``, and an equality assertion
  (``Equal``, ``AreEqual``, ``Same``, ``AreSame``) of two arguments written the same.
* A skip marker: ``[Ignore]``, ``[Explicit]`` (NUnit, MSTest), ``[IgnoreUntil]``
  (gdUnit4), and ``Skip = "..."`` on ``[Fact]``/``[Theory]`` (xUnit), on a method or a
  class.
"""

import re

from tree_sitter import Node

from shockharness.ir.csharp_defaults import argument_values
from shockharness.ir.csharp_functions import scope_for
from shockharness.ir.csharp_nodes import Field, Kind
from shockharness.ir.csharp_strings import literal_text
from shockharness.ir.model import (
    DIRECTIVE_SCOPE_FILE,
    DIRECTIVE_SCOPE_REGION,
    MARKER_SKIP,
    MODULE_SCOPE,
    CaseFact,
    Comment,
    SkipMarker,
    Span,
    SuppressionDirective,
    Tautology,
    VerificationFacts,
)
from shockharness.ir.suppression_directives import (
    TOOL_NULLABLE_DISABLE,
    TOOL_PRAGMA_WARNING,
    TOOL_SUPPRESS_MESSAGE,
    csharp_directives,
    directive,
)
from shockharness.ir.tree_sitter_common import node_span, node_text
from shockharness.source import SourceText

PRAGMA = "preproc_pragma"
NULLABLE = "preproc_nullable"
GLOBAL_ATTRIBUTE = "global_attribute"
PRAGMA_DISABLE = re.compile(r"#\s*pragma\s+warning\s+disable\b(?P<codes>[^/\n]*)")
NULLABLE_DISABLE = re.compile(r"#\s*nullable\s+disable\b")
SUPPRESS_ATTRIBUTES = frozenset(
    {
        "SuppressMessage",
        "SuppressMessageAttribute",
        "UnconditionalSuppressMessage",
        "UnconditionalSuppressMessageAttribute",
    }
)
CHECK_ID_POSITION = 1  # SuppressMessage(category, checkId, ...)
CODE_SEPARATORS = re.compile(r"[\s,]+")


def _last(dotted: str) -> str:
    _head, _dot, last = dotted.rpartition(".")
    return last


def _pragma(node: Node, source: SourceText) -> list[SuppressionDirective]:
    match = PRAGMA_DISABLE.match(node_text(node).strip())
    if match is None:
        return []
    codes = tuple(c for c in CODE_SEPARATORS.split(match.group("codes")) if c != "")
    text = "#pragma warning disable" + ("" if len(codes) == 0 else " " + ",".join(codes))
    span = node_span(source, node)
    return [directive(TOOL_PRAGMA_WARNING, DIRECTIVE_SCOPE_REGION, codes, text, span)]


def _nullable(node: Node, source: SourceText) -> list[SuppressionDirective]:
    written = " ".join(node_text(node).split())
    if NULLABLE_DISABLE.match(written) is None:
        return []
    span = node_span(source, node)
    return [directive(TOOL_NULLABLE_DISABLE, DIRECTIVE_SCOPE_REGION, (), written, span)]


def _check_id(attribute: Node) -> str | None:
    """The check id of a ``SuppressMessage`` (``"CA1822:Mark members as static"`` ->
    ``CA1822``), or ``None`` when it is not a string literal."""
    positional = [
        argument
        for arguments in attribute.named_children
        if arguments.type == Kind.ATTRIBUTE_ARGUMENT_LIST
        for argument in arguments.named_children
        if argument.named_child_count == 1  # a named argument has its name too
    ]
    if len(positional) <= CHECK_ID_POSITION:
        return None
    value = literal_text(positional[CHECK_ID_POSITION].named_children[0])
    if value is None:
        return None
    check, _colon, _title = value.partition(":")
    return check.strip()


def _suppress_message(
    attribute: Node, scope: str, source: SourceText
) -> list[SuppressionDirective]:
    name = attribute.child_by_field_name(Field.NAME)
    if name is None or _last(node_text(name)) not in SUPPRESS_ATTRIBUTES:
        return []
    check = _check_id(attribute)
    codes = () if check is None or check == "" else (check,)
    text = f"[{_last(node_text(name))}({', '.join(codes)})]"
    span = node_span(source, attribute)
    return [directive(TOOL_SUPPRESS_MESSAGE, scope, codes, text, span)]


def _directives(node: Node, source: SourceText) -> list[SuppressionDirective]:
    if node.type == PRAGMA:
        return _pragma(node, source)
    if node.type == NULLABLE:
        return _nullable(node, source)
    if node.type == Kind.ATTRIBUTE:
        parent = node.parent
        outer = parent is not None and parent.type == GLOBAL_ATTRIBUTE
        scope = DIRECTIVE_SCOPE_FILE if outer else DIRECTIVE_SCOPE_REGION
        return _suppress_message(node, scope, source)
    return []


# -- test cases ------------------------------------------------------------------------------

TEST_ATTRIBUTES = frozenset(
    {"Test", "TestCase", "TestCaseSource", "Fact", "Theory", "TestMethod", "DataTestMethod"}
)
SKIP_ATTRIBUTES = frozenset({"Ignore", "IgnoreUntil", "Explicit"})
SKIPPABLE = frozenset({"Fact", "Theory"})  # xUnit: Skip = "reason"
SKIP_ARGUMENT = "Skip"
ATTRIBUTE_SUFFIX = "Attribute"
ASSERTION = re.compile(r"^(?:\w*Assert\w*|Should\w*|Verify\w*)$")
TRUE_CHECKS = frozenset({"True", "IsTrue", "That"})
FALSE_CHECKS = frozenset({"False", "IsFalse"})
SAME_CHECKS = frozenset({"Equal", "AreEqual", "Same", "AreSame", "StrictEqual"})
SAME_ARGUMENTS = 2
BOOLEAN_SELF_CHECKS = {"ShouldBeTrue": "true", "ShouldBeFalse": "false"}
RECEIVER_FIELDS = {
    Kind.MEMBER_ACCESS_EXPRESSION: Field.EXPRESSION,
    Kind.INVOCATION_EXPRESSION: Field.FUNCTION,
}
TRUE = "true"
FALSE = "false"


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _attributes(declaration: Node) -> list[tuple[str, Node]]:
    """(name without namespace or ``Attribute``, node) of each attribute on a declaration."""
    found: list[tuple[str, Node]] = []
    for attribute_list in declaration.named_children:
        if attribute_list.type != Kind.ATTRIBUTE_LIST:
            continue
        for attribute in attribute_list.named_children:
            name = attribute.child_by_field_name(Field.NAME)
            if name is not None:
                found.append((_last(node_text(name)).removesuffix(ATTRIBUTE_SUFFIX), attribute))
    return found


def _attribute_arguments(attribute: Node) -> list[Node]:
    return [
        argument
        for arguments in attribute.named_children
        if arguments.type == Kind.ATTRIBUTE_ARGUMENT_LIST
        for argument in arguments.named_children
    ]


def _skip_reason(attribute: Node, named: str | None) -> tuple[bool, str | None]:
    """(whether the attribute skips, its reason): any skip attribute, or ``Skip = "..."``
    when ``named`` is the argument that skips."""
    for argument in _attribute_arguments(attribute):
        parts = argument.named_children
        last = parts[len(parts) - 1]
        is_named = len(parts) > 1
        if named is None and not is_named:
            return True, literal_text(last)
        if named is not None and is_named and node_text(parts[0]) == named:
            return True, literal_text(last)
    return named is None, None


def _markers(declaration: Node, test: str, source: SourceText) -> list[SkipMarker]:
    found: list[SkipMarker] = []
    for name, attribute in _attributes(declaration):
        if name in SKIP_ATTRIBUTES:
            skips, reason = _skip_reason(attribute, None)
        elif name in SKIPPABLE:
            skips, reason = _skip_reason(attribute, SKIP_ARGUMENT)
        else:
            continue
        if skips:
            text = _collapse(node_text(attribute))
            span = node_span(source, attribute)
            found.append(SkipMarker(MARKER_SKIP, test, text, reason, span))
    return found


def _leftmost(receiver: Node | None) -> Node | None:
    """The start of a receiver chain: ``x`` in ``x.Should().Be``."""
    while receiver is not None and receiver.type in RECEIVER_FIELDS:
        receiver = receiver.child_by_field_name(RECEIVER_FIELDS[receiver.type])
    return receiver


def _callee_names(call: Node) -> tuple[str, str, Node | None]:
    """(method name, leftmost receiver as written or "", leftmost receiver) of a call."""
    function = call.child_by_field_name(Field.FUNCTION)
    if function is None:
        return "", "", None
    if function.type != Kind.MEMBER_ACCESS_EXPRESSION:
        return node_text(function).split("<", 1)[0], "", None
    name = function.child_by_field_name(Field.NAME)
    receiver = _leftmost(function.child_by_field_name(Field.EXPRESSION))
    method = ""
    if name is not None:
        method = node_text(name).split("<", 1)[0]
    root = ""
    if receiver is not None:
        root = node_text(receiver)
    return method, root, receiver


def _is_assertion(method: str, root: str) -> bool:
    return ASSERTION.match(method) is not None or ASSERTION.match(root) is not None


def _is_tautology(call: Node, method: str, receiver: Node | None) -> bool:
    if method in BOOLEAN_SELF_CHECKS:
        return receiver is not None and node_text(receiver) == BOOLEAN_SELF_CHECKS[method]
    values = [node_text(v) for v in argument_values(call)]
    if len(values) == 0:
        return False
    if method in TRUE_CHECKS:
        return values[0] == TRUE
    if method in FALSE_CHECKS:
        return values[0] == FALSE
    return method in SAME_CHECKS and len(values) >= SAME_ARGUMENTS and values[0] == values[1]


def _case(method: Node, name: str, source: SourceText) -> CaseFact:
    body = method.child_by_field_name(Field.BODY)
    assertions = 0
    tautologies: list[Tautology] = []
    stack: list[Node] = []
    if body is not None:
        stack.append(body)
    while len(stack) > 0:
        node = stack.pop()
        stack.extend(node.children)
        if node.type != Kind.INVOCATION_EXPRESSION:
            continue
        called, root, receiver = _callee_names(node)
        if not _is_assertion(called, root):
            continue
        assertions += 1
        if _is_tautology(node, called, receiver):
            tautologies.append(Tautology(_collapse(node_text(node)), node_span(source, node)))
    empty = (
        body is not None
        and body.type == Kind.BLOCK
        and all(c.type == Kind.COMMENT for c in body.named_children)
    )
    span = node_span(source, method)
    return CaseFact(
        name=name,
        span=Span(span.line, span.column, span.line, span.column),
        assertions=assertions,
        tautologies=tuple(sorted(tautologies, key=lambda t: (t.span, t.text))),
        body_empty=empty,
    )


class _Tests:
    def __init__(self, source: SourceText) -> None:
        self.source = source
        self.cases: list[CaseFact] = []
        self.markers: list[SkipMarker] = []

    def visit(self, node: Node, name: str) -> None:
        if node.type == Kind.METHOD_DECLARATION:
            if any(attribute in TEST_ATTRIBUTES for attribute, _node in _attributes(node)):
                self.cases.append(_case(node, name, self.source))
            self.markers.extend(_markers(node, name, self.source))
        elif node.type == Kind.CLASS_DECLARATION:
            self.markers.extend(_markers(node, name, self.source))


def collect_csharp_verification(
    source: SourceText, root: Node, comments: tuple[Comment, ...]
) -> VerificationFacts:
    found = list(csharp_directives(comments))
    tests = _Tests(source)
    stack = [(root, MODULE_SCOPE)]
    while len(stack) > 0:
        node, scope = stack.pop()
        inner = scope_for(node, scope)
        found.extend(_directives(node, source))
        tests.visit(node, inner)
        stack.extend((child, inner) for child in node.children)
    found.sort(key=lambda d: (d.span, d.tool, d.text))
    return VerificationFacts(
        markers=tuple(sorted(tests.markers, key=lambda m: (m.span, m.test))),
        suppressions=tuple(found),
        cases=tuple(sorted(tests.cases, key=lambda c: (c.span, c.name))),
    )
