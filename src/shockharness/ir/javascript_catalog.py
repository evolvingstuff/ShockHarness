"""API-catalog facts for JavaScript (H5; consumed by PROCESS001, SLEEP001, RETRY001,
BATCH001 and STUB003 in rules/api_catalog.py). TYPE001's JavaScript half waits for the
TypeScript adapter (H-TS).

Syntax only:

* **process calls**: calls whose last callee segment is ``exec``, ``execSync``,
  ``execFile``, ``execFileSync``, ``spawn`` or ``spawnSync``; the rule keeps those whose
  resolved callee is in its catalog. Recorded: ``{shell: true}``, an interpolated command
  (a template with substitutions, or ``+`` with a non-string operand), whether the result
  is thrown away, and whether the enclosing function reads ``.status``;
* **sleeps**: ``new Promise((r) => setTimeout(r, ...))`` and ``await setTimeout(...)``
  (``timers/promises``), with whether they sit in a loop;
* **retries**: ``while (true)`` / ``for (;;)`` whose body catches in a ``catch`` that
  never throws, returns or breaks;
* **batch loops**: a ``for`` / ``for...of`` / ``for...in`` loop whose body has a
  ``catch`` that is empty, only continues, or only logs (``console.*``);
* **constant predicates**: a function, method or arrow named as a check whose body only
  returns ``true``.
"""

import re

from tree_sitter import Node

from shockharness.constants import EVIDENCE_MAX_CHARS
from shockharness.ir.javascript_catches import node_span, node_text
from shockharness.ir.javascript_guardrails import dotted_callee
from shockharness.ir.model import (
    CHECK_ABSENT,
    RETRY_LOOP,
    TYPE_ESCAPE_ANY,
    TYPE_ESCAPE_CAST,
    TYPE_ESCAPE_NON_NULL,
    BatchLoop,
    CatalogFacts,
    ConstantPredicate,
    ProcessCall,
    RetryFact,
    SleepCall,
    TypeEscape,
)
from shockharness.source import SourceText

PROCESS_NAMES = frozenset({"exec", "execSync", "execFile", "execFileSync", "spawn", "spawnSync"})
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
LOOPS = frozenset({"for_statement", "for_in_statement", "while_statement", "do_statement"})
PREDEFINED_TYPE = "predefined_type"
ANY = "any"
AS_EXPRESSION = "as_expression"
TYPE_ASSERTION = "type_assertion"
NON_NULL = "non_null_expression"
CONST = "const"
TYPE_SUFFIX = "_type"
TYPE_ANNOTATION = "type_annotation"
TYPE_NODES = frozenset({TYPE_ANNOTATION, "type_arguments", "constraint", "default_type"})
ANNOTATED = frozenset(
    {
        "required_parameter",
        "optional_parameter",
        "variable_declarator",
        "public_field_definition",
        "property_signature",
        "type_parameter",
    }
)
# Nodes around a type that are not the type itself: `: T` and a type parameter's `= T`.
WRAPPING_TYPES = frozenset({TYPE_ANNOTATION, "default_type"})
COMMENT_NODE = "comment"
ITERATING = frozenset({"for_statement", "for_in_statement"})
CALL = "call_expression"
NEW = "new_expression"
AWAIT = "await_expression"
STATEMENT = "expression_statement"
TEMPLATE = "template_string"
SUBSTITUTION = "template_substitution"
BINARY = "binary_expression"
STRING = "string"
OBJECT = "object"
PAIR = "pair"
TRY = "try_statement"
CATCH = "catch_clause"
TRUE = "true"
SET_TIMEOUT = "setTimeout"
PROMISE = "Promise"
STATUS = re.compile(r"\.status\b")
LOGGING = re.compile(r"^console\.\w+$")
PREDICATE = re.compile(
    r"^(is|has|can|should)[A-Z_]|^(check|validate|verify|authori[sz]e|authenticate|allow)"
)
EXITS = frozenset({"throw_statement", "return_statement", "break_statement"})


def _excerpt(node: Node) -> str:
    text = " ".join(node_text(node).split())
    if len(text) > EVIDENCE_MAX_CHARS:
        return text[:EVIDENCE_MAX_CHARS] + "..."
    return text


def _arguments(call: Node) -> list[Node]:
    arguments = call.child_by_field_name("arguments")
    if arguments is None:
        return []
    return [child for child in arguments.named_children if child.type != "comment"]


def _callee(call: Node) -> str | None:
    function = call.child_by_field_name("function")
    if function is None:
        return None
    return dotted_callee(function)


def _last(callee: str) -> str:
    _receiver, _dot, last = callee.rpartition(".")
    return last


def _enclosing(node: Node, types: frozenset[str]) -> Node | None:
    current = node.parent
    while current is not None:
        if current.type in types:
            return current
        if current.type in FUNCTIONS:
            return None
        current = current.parent
    return None


def _enclosing_function(node: Node) -> Node | None:
    current = node.parent
    while current is not None:
        if current.type in FUNCTIONS:
            return current
        current = current.parent
    return None


def _interpolated(node: Node) -> bool:
    if node.type == TEMPLATE:
        return any(child.type == SUBSTITUTION for child in node.named_children)
    if node.type == BINARY:
        return any(child.type not in (STRING, TEMPLATE) for child in node.named_children)
    return False


def _is_shell_true(pair: Node) -> bool:
    """``shell: true`` in an options object."""
    if pair.type != PAIR:
        return False
    key = pair.child_by_field_name("key")
    value = pair.child_by_field_name("value")
    return (
        key is not None and value is not None and node_text(key) == "shell" and value.type == TRUE
    )


def _shell(arguments: list[Node]) -> bool:
    return any(
        _is_shell_true(pair)
        for argument in arguments
        if argument.type == OBJECT
        for pair in argument.named_children
    )


def _process(source: SourceText, call: Node, callee: str) -> ProcessCall:
    arguments = _arguments(call)
    parent = call.parent
    if parent is not None and parent.type == AWAIT:
        parent = parent.parent
    function = _enclosing_function(call)
    return ProcessCall(
        callee=callee,
        text=_excerpt(call),
        shell=_shell(arguments),
        interpolated=len(arguments) > 0 and _interpolated(arguments[0]),
        check=CHECK_ABSENT,
        discarded=parent is not None and parent.type == STATEMENT,
        status_read=function is not None and STATUS.search(node_text(function)) is not None,
        span=node_span(source, call),
    )


def _promise_sleep(new: Node) -> bool:
    """``new Promise((resolve) => setTimeout(resolve, ...))``."""
    constructor = new.child_by_field_name("constructor")
    if constructor is None or node_text(constructor) != PROMISE:
        return False
    return SET_TIMEOUT in node_text(new)


def _sleep(source: SourceText, node: Node) -> SleepCall | None:
    if node.type == NEW and _promise_sleep(node):
        callee = PROMISE
    elif node.type == CALL and _callee(node) == SET_TIMEOUT and node.parent is not None:
        if node.parent.type != AWAIT:
            return None
        callee = SET_TIMEOUT
    else:
        return None
    return SleepCall(
        callee, _excerpt(node), _enclosing(node, LOOPS) is not None, node_span(source, node)
    )


def _catches(loop: Node) -> list[Node]:
    """``catch`` clauses in the loop body, outside nested functions and loops."""
    body = loop.child_by_field_name("body")
    found: list[Node] = []
    if body is None:
        return found
    stack: list[Node] = [body]
    while len(stack) > 0:
        node = stack.pop()
        if node.type == CATCH:
            found.append(node)
        if node.type in FUNCTIONS or (node.type in LOOPS and node.id != loop.id):
            continue
        stack.extend(node.children)
    return found


def _gives_up(catch: Node) -> bool:
    stack: list[Node] = list(catch.children)
    while len(stack) > 0:
        node = stack.pop()
        if node.type in EXITS:
            return True
        if node.type in FUNCTIONS:
            continue
        stack.extend(node.children)
    return False


def _swallowing(catch: Node) -> bool:
    body = catch.child_by_field_name("body")
    if body is None:
        return False
    for statement in body.named_children:
        if statement.type in ("comment", "continue_statement", "empty_statement"):
            continue
        if statement.type == STATEMENT and statement.named_child_count > 0:
            call = statement.named_children[0]
            callee = _callee(call) if call.type == CALL else None
            if callee is not None and LOGGING.match(callee) is not None:
                continue
        return False
    return True


def _forever(loop: Node) -> bool:
    if loop.type == "while_statement":
        condition = loop.child_by_field_name("condition")
        return condition is not None and node_text(condition).strip("() \n") == TRUE
    if loop.type == "for_statement":
        condition = loop.child_by_field_name("condition")
        return condition is None or node_text(condition).strip("; \n") in ("", TRUE)
    return False


def _predicate_name(node: Node) -> str | None:
    name = node.child_by_field_name("name")
    if name is not None:
        return node_text(name)
    parent = node.parent
    if (
        node.type == "arrow_function"
        and parent is not None
        and parent.type == "variable_declarator"
    ):
        declared = parent.child_by_field_name("name")
        if declared is not None:
            return node_text(declared)
    return None


def _returns_true(function: Node) -> bool:
    body = function.child_by_field_name("body")
    if body is None:
        return False
    if body.type == TRUE:
        return True  # (x) => true
    statements = [c for c in body.named_children if c.type != "comment"]
    if len(statements) != 1 or statements[0].type != "return_statement":
        return False
    values = statements[0].named_children
    return len(values) == 1 and values[0].type == TRUE


def _process_call(source: SourceText, node: Node) -> ProcessCall | None:
    if node.type != CALL:
        return None
    callee = _callee(node)
    if callee is None or _last(callee) not in PROCESS_NAMES:
        return None
    return _process(source, node, callee)


def _retry_loop(source: SourceText, node: Node) -> list[RetryFact]:
    if node.type not in LOOPS or not _forever(node):
        return []
    if all(_gives_up(c) for c in _catches(node)):
        return []
    text = "while (true) { try ... catch ... }"
    return [RetryFact(RETRY_LOOP, "", text, node_span(source, node))]


def _batch_loop(source: SourceText, node: Node) -> list[BatchLoop]:
    if node.type not in ITERATING or not any(_swallowing(c) for c in _catches(node)):
        return []
    return [BatchLoop(_excerpt(node).split("{")[0].strip(), node_span(source, node))]


def _type_context(node: Node) -> Node:
    """What an ``any`` annotates: the parameter, variable or member when the type annotates
    one (``raw: any``), else the whole type (``Map<string, any>``)."""
    current = node
    while current.parent is not None and (
        current.parent.type in TYPE_NODES or current.parent.type.endswith(TYPE_SUFFIX)
    ):
        current = current.parent
    parent = current.parent
    if current.type in WRAPPING_TYPES and parent is not None and parent.type in ANNOTATED:
        return parent
    if current.type in WRAPPING_TYPES:
        named = [c for c in current.named_children if c.type != COMMENT_NODE]
        return named[0] if len(named) == 1 else current
    return current


def _type_escape(source: SourceText, node: Node) -> list[TypeEscape]:
    """TypeScript's escapes from the type checker (none exist in JavaScript's grammar)."""
    if node.type == PREDEFINED_TYPE and node_text(node) == ANY:
        return [TypeEscape(TYPE_ESCAPE_ANY, _excerpt(_type_context(node)), node_span(source, node))]
    if node.type == AS_EXPRESSION:
        asserted = node.children[len(node.children) - 1]
        parent = node.parent
        # `as const` asserts nothing; `x as unknown as T` is one assertion, reported once.
        if node_text(asserted) == CONST or (parent is not None and parent.type == AS_EXPRESSION):
            return []
        return [TypeEscape(TYPE_ESCAPE_CAST, _excerpt(node), node_span(source, node))]
    if node.type == TYPE_ASSERTION:
        return [TypeEscape(TYPE_ESCAPE_CAST, _excerpt(node), node_span(source, node))]
    if node.type == NON_NULL:
        return [TypeEscape(TYPE_ESCAPE_NON_NULL, _excerpt(node), node_span(source, node))]
    return []


def _predicate(source: SourceText, node: Node) -> list[ConstantPredicate]:
    if node.type not in FUNCTIONS:
        return []
    name = _predicate_name(node)
    if name is None or PREDICATE.match(name) is None or not _returns_true(node):
        return []
    return [ConstantPredicate(name, node_span(source, node))]


def collect_javascript_catalog(source: SourceText, root: Node) -> CatalogFacts:
    processes: list[ProcessCall] = []
    sleeps: list[SleepCall] = []
    retries: list[RetryFact] = []
    batches: list[BatchLoop] = []
    predicates: list[ConstantPredicate] = []
    escapes: list[TypeEscape] = []
    stack: list[Node] = [root]
    while len(stack) > 0:
        node = stack.pop()
        stack.extend(node.children)
        process = _process_call(source, node)
        if process is not None:
            processes.append(process)
        sleep = _sleep(source, node)
        if sleep is not None:
            sleeps.append(sleep)
        retries.extend(_retry_loop(source, node))
        batches.extend(_batch_loop(source, node))
        predicates.extend(_predicate(source, node))
        escapes.extend(_type_escape(source, node))
    return CatalogFacts(
        process_calls=tuple(sorted(processes, key=lambda p: (p.span, p.callee))),
        sleeps=tuple(sorted(sleeps, key=lambda s: (s.span, s.callee))),
        retries=tuple(sorted(retries, key=lambda r: (r.span, r.kind))),
        batch_loops=tuple(sorted(batches, key=lambda b: b.span)),
        type_escapes=tuple(sorted(escapes, key=lambda t: (t.span, t.kind))),
        constant_predicates=tuple(sorted(predicates, key=lambda c: c.span)),
    )
