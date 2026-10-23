"""Async lifecycle facts for JavaScript (H4; consumed by ASYNC001 and ASYNC003 in
rules/async_lifecycle.py). JavaScript has no task objects to supervise, so ASYNC002 is
Python only.

Syntax only, per function scope:

* **discarded calls**: a call that is a whole expression statement (``f();``, not
  ``await f();``), and ``void f()``, with whether the enclosing function is ``async``;
* **drawn waits, held calls and callbacks** (ASYNC004): what a function awaits or
  returns that only settles when the page is drawn (an animation's ``.finished``), the
  calls whose promises it waits on, and every function written as a call's argument;
* **settled batches**: ``Promise.allSettled(...)``, with whether its result is thrown away
  (an expression statement, awaited or not) and whether the enclosing function inspects
  results for failure (``.status``, ``.reason``, or a ``"rejected"`` string) or returns
  the batch to its caller.
"""

import re

from tree_sitter import Node

from shockharness.constants import LISTENER_ARGUMENTS, MAX_DRAWN_DEPTH
from shockharness.ir.javascript_catches import node_span, node_text
from shockharness.ir.javascript_functions import string_value
from shockharness.ir.javascript_guardrails import dotted_callee
from shockharness.ir.javascript_nodes import Field, Kind
from shockharness.ir.model import (
    AsyncFacts,
    CallbackArgument,
    DiscardedCall,
    DrawnWait,
    HeldCall,
    RejectionHandler,
    SettledBatch,
)
from shockharness.ir.tree_sitter_common import excerpt
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
# Calls on the event that only silence it.
SILENCERS = frozenset({"preventDefault", "stopPropagation", "stopImmediatePropagation"})
INSPECTION = re.compile(r"\.status\b|\.reason\b|[\"'`]rejected[\"'`]")


def _is_async(function: Node | None) -> bool:
    return function is not None and any(child.type == ASYNC for child in function.children)


def _enclosing_function(node: Node) -> Node | None:
    current = node.parent
    while current is not None:
        if current.type in FUNCTIONS:
            return current
        current = current.parent
    return None


# Where a top-level batch's check is looked for: the nearest block, not the whole module.
BLOCKS = frozenset({Kind.STATEMENT_BLOCK, Kind.PROGRAM})


def _inspection_text(node: Node) -> str | None:
    """Where a failure check counts: the enclosing function; at module top level (a
    script's ``await``), the statement holding the batch and the statements after it in
    the same block (MetaList: a check one line below, inside a top-level ``try``)."""
    function = _enclosing_function(node)
    if function is not None:
        return node_text(function)
    statement = node
    while statement.parent is not None and statement.parent.type not in BLOCKS:
        statement = statement.parent
    if statement.parent is None:
        return None
    following: list[str] = []
    current: Node | None = statement
    while current is not None:
        following.append(node_text(current))
        current = current.next_named_sibling
    return "\n".join(following)


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
        text=excerpt(statement),
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
        text=excerpt(call),
        discarded=consumer is not None and consumer.type == STATEMENT,
        inspected=_inspected(consumer, _enclosing_function(call), _inspection_text(call)),
        cancellation_wait=False,
        span=node_span(source, call),
    )


def _inspected(consumer: Node | None, function: Node | None, scope: str | None) -> bool:
    """The batch is returned (or is a concise arrow's value), or its scope (the enclosing
    function, or at top level what follows it; see :func:`_inspection_text`) checks a
    result for failure."""
    if consumer is None or scope is None:
        return False
    if consumer.type == RETURN:
        return True
    if function is not None and function.type == Kind.ARROW_FUNCTION and consumer.id == function.id:
        return True
    return INSPECTION.search(scope) is not None


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
    if len(named) < LISTENER_ARGUMENTS:
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


# -- ASYNC004: waits on the page being drawn -----------------------------------------------
FINISHED = "finished"  # Animation.finished, ViewTransition.finished
COMBINATORS = frozenset({"Promise.all", "Promise.race", "Promise.allSettled", "Promise.any"})
CHAINS = frozenset({"then", "catch", "finally"})
MAP = "map"
NEW = Kind.NEW_EXPRESSION


def _unwrapped(node: Node) -> Node:
    while node.type == PARENTHESIZED and node.named_child_count > 0:
        node = node.named_children[0]
    return node


def _arguments(call: Node) -> list[Node]:
    arguments = call.child_by_field_name(Field.ARGUMENTS)
    if arguments is None:
        return []
    return [a for a in arguments.named_children if a.type != Kind.COMMENT]


def _member(call: Node) -> tuple[Node, str] | None:
    """(receiver, method) of ``receiver.method(...)``."""
    function = call.child_by_field_name(Field.FUNCTION)
    if function is None or function.type != Kind.MEMBER_EXPRESSION:
        return None
    receiver = function.child_by_field_name(Field.OBJECT)
    method = function.child_by_field_name(Field.PROPERTY)
    if receiver is None or method is None:
        return None
    return receiver, node_text(method)


def _expression_body(function: Node) -> Node | None:
    body = function.child_by_field_name(Field.BODY)
    if function.type != Kind.ARROW_FUNCTION or body is None or body.type == Kind.STATEMENT_BLOCK:
        return None
    return body


def _bound_value(node: Node, name: str) -> Node | None:
    """The value of ``const name = ...`` in the function enclosing ``node``."""
    function = _enclosing_function(node)
    if function is None:
        return None
    stack = [function]
    while len(stack) > 0:
        current = stack.pop()
        if current.type == Kind.VARIABLE_DECLARATOR:
            bound = current.child_by_field_name(Field.NAME)
            value = current.child_by_field_name(Field.VALUE)
            if bound is not None and value is not None and node_text(bound) == name:
                return value
        stack.extend(c for c in current.named_children if c.type not in FUNCTIONS)
    return None


def _drawn(node: Node, depth: int) -> bool:
    """Whether ``node`` is a promise that settles only when the page is drawn."""
    expression = _unwrapped(node)
    if depth > MAX_DRAWN_DEPTH:
        return False
    if expression.type == Kind.MEMBER_EXPRESSION:
        method = expression.child_by_field_name(Field.PROPERTY)
        return method is not None and node_text(method) == FINISHED
    if expression.type == Kind.IDENTIFIER:
        value = _bound_value(expression, node_text(expression))
        return value is not None and _drawn(value, depth + 1)
    if expression.type != CALL:
        return False
    return _drawn_call(expression, depth)


def _drawn_call(call: Node, depth: int) -> bool:
    member = _member(call)
    if member is not None and member[1] in CHAINS:
        return _drawn(member[0], depth + 1)
    if member is not None and member[1] == MAP:
        callbacks = [_expression_body(a) for a in _arguments(call) if a.type in FUNCTIONS]
        return any(body is not None and _drawn(body, depth + 1) for body in callbacks)
    if _callee(call) not in COMBINATORS:
        return False
    arguments = _arguments(call)
    if len(arguments) == 0:
        return False
    batch = _unwrapped(arguments[0])
    if batch.type == Kind.ARRAY:
        return any(_drawn(element, depth + 1) for element in batch.named_children)
    return _drawn(batch, depth + 1)


def _held(node: Node) -> list[Node]:
    """The calls whose promises waiting on ``node`` waits on."""
    expression = _unwrapped(node)
    if expression.type == NEW:
        return [expression]
    if expression.type != CALL:
        return []
    member = _member(expression)
    if member is not None and member[1] in CHAINS:
        return [expression, *_held(member[0])]
    if _callee(expression) in COMBINATORS:
        arguments = _arguments(expression)
        batch = _unwrapped(arguments[0]) if len(arguments) > 0 else None
        if batch is not None and batch.type == Kind.ARRAY:
            return [held for element in batch.named_children for held in _held(element)]
    return [expression]


def _waited_on(node: Node) -> Node | None:
    """What a function waits on or hands back at ``node``: an awaited or returned
    expression, or an arrow's expression body."""
    if node.type in (AWAIT, RETURN) and node.named_child_count > 0:
        return node.named_children[0]
    if node.type == Kind.ARROW_FUNCTION:
        return _expression_body(node)
    return None


def _callbacks(source: SourceText, call: Node) -> list[CallbackArgument]:
    arguments = _arguments(call)
    if not any(a.type in FUNCTIONS for a in arguments):
        return []
    first = arguments[0]
    label = string_value(first)
    if label is None:
        label = excerpt(first)
    return [
        CallbackArgument(_callee(call), index, len(arguments), node_span(source, a), label)
        for index, a in enumerate(arguments)
        if a.type in FUNCTIONS
    ]


def _wait_facts(
    source: SourceText, node: Node, drawn: list[DrawnWait], held: list[HeldCall]
) -> None:
    """ASYNC004's facts at ``node`` when it waits on something: a drawn wait, held calls."""
    waited = _waited_on(node)
    if waited is None:
        return
    if _drawn(waited, 0):
        drawn.append(DrawnWait(node_span(source, waited), excerpt(waited)))
    held.extend(HeldCall(node_span(source, call)) for call in _held(waited))


def collect_javascript_async(source: SourceText, root: Node) -> AsyncFacts:
    discarded: list[DiscardedCall] = []
    settled: list[SettledBatch] = []
    handlers: list[RejectionHandler] = []
    drawn: list[DrawnWait] = []
    held: list[HeldCall] = []
    callbacks: list[CallbackArgument] = []
    stack: list[Node] = [root]
    while len(stack) > 0:
        node = stack.pop()
        _wait_facts(source, node, drawn, held)
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
            callbacks.extend(_callbacks(source, node))
        stack.extend(node.children)
    return AsyncFacts(
        discarded_calls=tuple(sorted(discarded, key=lambda d: (d.span, d.callee))),
        settled_batches=tuple(sorted(settled, key=lambda s: (s.span, s.callee))),
        rejection_handlers=tuple(sorted(handlers, key=lambda h: h.span)),
        drawn_waits=tuple(sorted(drawn, key=lambda d: d.span)),
        held_calls=tuple(sorted(set(held), key=lambda h: h.span)),
        callbacks=tuple(sorted(callbacks, key=lambda c: (c.span, c.index))),
    )
