"""Async lifecycle facts for JavaScript (H4; consumed by ASYNC001 and ASYNC003 in
rules/async_lifecycle.py). JavaScript has no task objects to supervise, so ASYNC002 is
Python only.

Syntax only, per function scope:

* **discarded calls**: a call that is a whole expression statement (``f();``, not
  ``await f();``), and ``void f()``, with whether the enclosing function is ``async``;
* **settled batches**: ``Promise.allSettled(...)``, with whether its result is thrown away
  (an expression statement, awaited or not) and whether the enclosing function inspects
  results for failure (``.status``, ``.reason``, or a ``"rejected"`` string) or returns
  the batch to its caller.
"""

import re

from tree_sitter import Node

from shockharness.constants import EVIDENCE_MAX_CHARS
from shockharness.ir.javascript_catches import node_span, node_text
from shockharness.ir.javascript_guardrails import dotted_callee
from shockharness.ir.model import AsyncFacts, DiscardedCall, SettledBatch
from shockharness.source import SourceText

FUNCTIONS = frozenset(
    {
        "function_declaration",
        "generator_function_declaration",
        "function_expression",
        "function",
        "generator_function",
        "arrow_function",
        "method_definition",
    }
)
CALL = "call_expression"
STATEMENT = "expression_statement"
AWAIT = "await_expression"
UNARY = "unary_expression"
RETURN = "return_statement"
PARENTHESIZED = "parenthesized_expression"
ASYNC = "async"
VOID = "void"
ALL_SETTLED = "Promise.allSettled"
DYNAMIC = "<dynamic>"
INSPECTION = re.compile(r"\.status\b|\.reason\b|[\"'`]rejected[\"'`]")


def _excerpt(node: Node) -> str:
    text = " ".join(node_text(node).split())
    if len(text) > EVIDENCE_MAX_CHARS:
        return text[:EVIDENCE_MAX_CHARS] + "..."
    return text


def _is_async(function: Node | None) -> bool:
    return function is not None and any(child.type == ASYNC for child in function.children)


def _enclosing_function(node: Node) -> Node | None:
    current = node.parent
    while current is not None:
        if current.type in FUNCTIONS:
            return current
        current = current.parent
    return None


def _consumer(node: Node) -> Node | None:
    """The node that uses ``node``'s value, looking through ``await`` and parentheses."""
    current = node.parent
    while current is not None and current.type in (AWAIT, PARENTHESIZED):
        current = current.parent
    return current


def _is_void(node: Node) -> bool:
    return node.type == UNARY and any(child.type == VOID for child in node.children)


def _callee(call: Node) -> str:
    function = call.child_by_field_name("function")
    if function is None:
        return DYNAMIC
    dotted = dotted_callee(function)
    if dotted is None:
        return DYNAMIC
    return dotted


def _discarded(source: SourceText, call: Node) -> DiscardedCall | None:
    parent = call.parent
    if parent is None:
        return None
    void = _is_void(parent)
    statement = parent.parent if void else parent
    if statement is None or statement.type != STATEMENT:
        return None
    return DiscardedCall(
        callee=_callee(call),
        text=_excerpt(statement),
        void=void,
        in_async=_is_async(_enclosing_function(call)),
        bound_by=None,
        span=node_span(source, call),
    )


def _settled(source: SourceText, call: Node) -> SettledBatch | None:
    if _callee(call) != ALL_SETTLED:
        return None
    consumer = _consumer(call)
    return SettledBatch(
        callee=ALL_SETTLED,
        text=_excerpt(call),
        discarded=consumer is not None and consumer.type == STATEMENT,
        inspected=_inspected(consumer, _enclosing_function(call)),
        span=node_span(source, call),
    )


def _inspected(consumer: Node | None, function: Node | None) -> bool:
    """The batch is returned (or is a concise arrow's value), or the enclosing function
    checks a result for failure."""
    if consumer is None or function is None:
        return False
    if consumer.type == RETURN:
        return True
    if function.type == "arrow_function" and consumer.id == function.id:
        return True
    return INSPECTION.search(node_text(function)) is not None


def collect_javascript_async(source: SourceText, root: Node) -> AsyncFacts:
    discarded: list[DiscardedCall] = []
    settled: list[SettledBatch] = []
    stack: list[Node] = [root]
    while len(stack) > 0:
        node = stack.pop()
        if node.type == CALL:
            dropped = _discarded(source, node)
            if dropped is not None:
                discarded.append(dropped)
            batch = _settled(source, node)
            if batch is not None:
                settled.append(batch)
        stack.extend(node.children)
    return AsyncFacts(
        discarded_calls=tuple(sorted(discarded, key=lambda d: (d.span, d.callee))),
        settled_batches=tuple(sorted(settled, key=lambda s: (s.span, s.callee))),
    )
