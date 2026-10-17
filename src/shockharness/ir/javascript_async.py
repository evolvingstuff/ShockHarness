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
from shockharness.ir.javascript_functions import string_value
from shockharness.ir.javascript_guardrails import dotted_callee
from shockharness.ir.javascript_nodes import Field, Kind
from shockharness.ir.model import AsyncFacts, DiscardedCall, RejectionHandler, SettledBatch
from shockharness.source import SourceText

FUNCTIONS = frozenset(
    {
        Kind.FUNCTION_DECLARATION,
        Kind.GENERATOR_FUNCTION_DECLARATION,
        Kind.FUNCTION_EXPRESSION,
        Kind.FUNCTION,
        Kind.GENERATOR_FUNCTION,
        Kind.ARROW_FUNCTION,
        Kind.METHOD_DEFINITION,
    }
)
CALL = Kind.CALL_EXPRESSION
STATEMENT = Kind.EXPRESSION_STATEMENT
AWAIT = Kind.AWAIT_EXPRESSION
UNARY = Kind.UNARY_EXPRESSION
RETURN = Kind.RETURN_STATEMENT
PARENTHESIZED = Kind.PARENTHESIZED_EXPRESSION
ASYNC = "async"
VOID = "void"
ALL_SETTLED = "Promise.allSettled"
DYNAMIC = "<dynamic>"
# Global listeners for rejections nothing handled (ASYNC001 trusts a reporting one).
UNHANDLED_REJECTION = "unhandledrejection"
NODE_UNHANDLED_REJECTION = "unhandledRejection"
REJECTION_REGISTRATIONS = frozenset(
    {
        *(
            (f"{target}.addEventListener", UNHANDLED_REJECTION)
            for target in ("window", "self", "globalThis")
        ),
        ("addEventListener", UNHANDLED_REJECTION),
        *(
            (f"process.{method}", NODE_UNHANDLED_REJECTION)
            for method in ("on", "once", "addListener", "prependListener")
        ),
    }
)
REJECTION_PROPERTIES = frozenset(
    f"{target}.onunhandledrejection" for target in ("window", "self", "globalThis")
)
REJECTION_ARGUMENTS = ("event", "handler")
# Calls on the event that only silence it.
SILENCERS = frozenset({"preventDefault", "stopPropagation", "stopImmediatePropagation"})
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
    function = call.child_by_field_name(Field.FUNCTION)
    if function is None:
        return DYNAMIC
    dotted = dotted_callee(function)
    if dotted is None:
        return DYNAMIC
    return dotted


def _argument_count(call: Node) -> int | None:
    """The call's arguments, or None for a spread argument or a tagged template."""
    arguments = call.child_by_field_name(Field.ARGUMENTS)
    if arguments is None or arguments.type != Kind.ARGUMENTS:
        return None
    named = [child for child in arguments.named_children if child.type != Kind.COMMENT]
    if any(child.type == Kind.SPREAD_ELEMENT for child in named):
        return None
    return len(named)


def _in_try_body(node: Node) -> bool:
    """In the block of a ``try`` that has a ``catch``, within the enclosing function."""
    current = node
    parent = node.parent
    while parent is not None and parent.type not in FUNCTIONS:
        handler = parent.child_by_field_name(Field.HANDLER)
        if parent.type == Kind.TRY_STATEMENT and handler is not None:
            if parent.child_by_field_name(Field.BODY) == current:
                return True
        current = parent
        parent = parent.parent
    return False


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
        arguments=_argument_count(call),
        in_try=_in_try_body(statement),
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
        cancellation_wait=False,
        span=node_span(source, call),
    )


def _inspected(consumer: Node | None, function: Node | None) -> bool:
    """The batch is returned (or is a concise arrow's value), or the enclosing function
    checks a result for failure."""
    if consumer is None or function is None:
        return False
    if consumer.type == RETURN:
        return True
    if function.type == Kind.ARROW_FUNCTION and consumer.id == function.id:
        return True
    return INSPECTION.search(node_text(function)) is not None


def _handler_reports(handler: Node) -> bool:
    """A handler that does more than ``event.preventDefault()``; a named one is assumed
    to (its body is elsewhere)."""
    if handler.type not in FUNCTIONS:
        return True
    stack = list(handler.named_children)
    while len(stack) > 0:
        node = stack.pop()
        if node.type == CALL:
            function = node.child_by_field_name(Field.FUNCTION)
            prop = None
            if function is not None and function.type == Kind.MEMBER_EXPRESSION:
                prop = function.child_by_field_name(Field.PROPERTY)
            if prop is None or node_text(prop) not in SILENCERS:
                return True
        stack.extend(node.named_children)
    return False


def _registered_handler(call: Node) -> Node | None:
    """The handler of ``X.addEventListener("unhandledrejection", h)`` or
    ``process.on("unhandledRejection", h)``, for a global ``X``."""
    function = call.child_by_field_name(Field.FUNCTION)
    arguments = call.child_by_field_name(Field.ARGUMENTS)
    if function is None or arguments is None:
        return None
    named = [child for child in arguments.named_children if child.type != Kind.COMMENT]
    if len(named) < len(REJECTION_ARGUMENTS):
        return None
    event = string_value(named[0])
    if event is None or (node_text(function), event) not in REJECTION_REGISTRATIONS:
        return None
    return named[1]


def _rejection_handler(source: SourceText, node: Node) -> RejectionHandler | None:
    if node.type == CALL:
        handler = _registered_handler(node)
    elif node.type == Kind.ASSIGNMENT_EXPRESSION:
        left = node.child_by_field_name(Field.LEFT)
        handler = None
        if left is not None and node_text(left) in REJECTION_PROPERTIES:
            handler = node.child_by_field_name(Field.RIGHT)
    else:
        return None
    if handler is None:
        return None
    return RejectionHandler(node_span(source, node), _handler_reports(handler))


def collect_javascript_async(source: SourceText, root: Node) -> AsyncFacts:
    discarded: list[DiscardedCall] = []
    settled: list[SettledBatch] = []
    handlers: list[RejectionHandler] = []
    stack: list[Node] = [root]
    while len(stack) > 0:
        node = stack.pop()
        handler = _rejection_handler(source, node)
        if handler is not None:
            handlers.append(handler)
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
        rejection_handlers=tuple(sorted(handlers, key=lambda h: h.span)),
    )
