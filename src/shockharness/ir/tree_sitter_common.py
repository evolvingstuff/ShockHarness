"""Helpers every tree-sitter adapter shares (JavaScript, TypeScript, C#): the node kinds
and fields named here are spelled the same in each grammar."""

from collections.abc import Collection

from tree_sitter import Node

from shockharness.constants import EVIDENCE_MAX_CHARS, FIRST_COLUMN, FIRST_LINE
from shockharness.ir.model import ParseFailure, Span
from shockharness.source import SourceText

PARENTHESIZED = "parenthesized_expression"
COMMENT = "comment"
ARGUMENTS = "arguments"
ELLIPSIS = "..."
IDENTIFIER = "identifier"


def node_text(node: Node) -> str:
    if node.text is None:
        return ""
    return node.text.decode("utf-8", errors="replace")


def node_span(source: SourceText, node: Node) -> Span:
    start_line = node.start_point.row + FIRST_LINE
    end_line = node.end_point.row + FIRST_LINE
    return Span(
        line=start_line,
        column=source.column_from_byte_offset(start_line, node.start_point.column),
        end_line=end_line,
        end_column=source.column_from_byte_offset(end_line, node.end_point.column),
    )


def parse_failure(source: SourceText, filename: str, error: Node) -> ParseFailure:
    kind = "missing token" if error.is_missing else "syntax error"
    first_line = node_text(error).split("\n")[0]
    if len(first_line) > EVIDENCE_MAX_CHARS:
        first_line = first_line[:EVIDENCE_MAX_CHARS] + ELLIPSIS
    return ParseFailure(
        span=node_span(source, error),
        message=f"{kind} near {first_line!r} in {filename}",
    )


def collapsed_text(node: Node) -> str:
    """The node's text on one line, cut to the evidence length with an ellipsis."""
    collapsed = " ".join(node_text(node).split())
    if len(collapsed) > EVIDENCE_MAX_CHARS:
        return collapsed[: EVIDENCE_MAX_CHARS - len(ELLIPSIS)] + ELLIPSIS
    return collapsed


def excerpt(node: Node) -> str:
    """The node's text on one line, cut to the evidence length and marked as cut."""
    text = " ".join(node_text(node).split())
    if len(text) > EVIDENCE_MAX_CHARS:
        return text[:EVIDENCE_MAX_CHARS] + ELLIPSIS
    return text


def first_line(node: Node) -> str:
    """The first line of the node's text, cut to the evidence length."""
    first = node_text(node).split("\n")[0].strip()
    if len(first) > EVIDENCE_MAX_CHARS:
        return first[:EVIDENCE_MAX_CHARS]
    return first


def unwrap_parentheses(node: Node) -> Node:
    """The expression inside any number of parentheses."""
    current = node
    while current.type == PARENTHESIZED:
        inner = [c for c in current.named_children if c.type != COMMENT]
        if len(inner) != 1:
            return current
        current = inner[0]
    return current


def call_arguments(call: Node) -> list[Node]:
    """A call's arguments, comments left out."""
    arguments = call.child_by_field_name(ARGUMENTS)
    if arguments is None:
        return []
    return [child for child in arguments.named_children if child.type != COMMENT]


def first_error(root: Node) -> Node | None:
    """The first error or missing node, in source order; None for a clean tree."""
    stack = [root]
    while len(stack) > 0:
        node = stack.pop()
        if node.is_error or node.is_missing:
            return node
        if not node.has_error:
            continue
        stack.extend(reversed(node.children))
    return None


def count_kinds(node: Node, kinds: Collection[str]) -> int:
    """How many nodes of these kinds the subtree holds, the node itself included."""
    count = 0
    stack = [node]
    while len(stack) > 0:
        current = stack.pop()
        if current.type in kinds:
            count += 1
        stack.extend(current.children)
    return count


def root_identifier(node: Node, chains: Collection[str], target_field: str) -> str | None:
    """The identifier a member or element access chain starts from (``a`` of ``a.b[c]``):
    ``chains`` are the grammar's access kinds, ``target_field`` the field naming what is
    accessed."""
    current = node
    while current.type in chains:
        inner = current.child_by_field_name(target_field)
        if inner is None:
            return None
        current = inner
    if current.type == IDENTIFIER:
        return node_text(current)
    return None


def unit_span(source: SourceText, node: Node, root_kind: str) -> Span:
    """A unit's span; the root (``program``, ``compilation_unit``) spans the whole file."""
    if node.type == root_kind:
        last_line = max(source.line_count, FIRST_LINE)
        return Span(FIRST_LINE, FIRST_COLUMN, last_line, len(source.line_text(last_line)) + 1)
    return node_span(source, node)
