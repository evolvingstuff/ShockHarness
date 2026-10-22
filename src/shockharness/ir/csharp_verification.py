"""Verification facts for C# (milestone G4): the suppressions VERIFY002 compares between
revisions and TYPE001 reads.

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
"""

import re

from tree_sitter import Node

from shockharness.ir.csharp_nodes import Field, Kind
from shockharness.ir.csharp_strings import literal_text
from shockharness.ir.model import (
    DIRECTIVE_SCOPE_FILE,
    DIRECTIVE_SCOPE_REGION,
    Comment,
    SuppressionDirective,
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


def collect_csharp_verification(
    source: SourceText, root: Node, comments: tuple[Comment, ...]
) -> VerificationFacts:
    found = list(csharp_directives(comments))
    stack = [root]
    while len(stack) > 0:
        node = stack.pop()
        found.extend(_directives(node, source))
        stack.extend(node.children)
    found.sort(key=lambda d: (d.span, d.tool, d.text))
    return VerificationFacts(markers=(), suppressions=tuple(found), cases=())
