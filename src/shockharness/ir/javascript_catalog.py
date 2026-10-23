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

from shockharness.ir.javascript_catches import node_span, node_text
from shockharness.ir.javascript_guardrails import dotted_callee
from shockharness.ir.javascript_nodes import Field, Kind
from shockharness.ir.model import (
    CHECK_ABSENT,
    OPEN_READ,
    OPEN_UNKNOWN,
    OPEN_WRITE,
    RETRY_LOOP,
    TYPE_ESCAPE_ANY,
    TYPE_ESCAPE_CAST,
    TYPE_ESCAPE_NON_NULL,
    BatchLoop,
    CatalogFacts,
    ClassDecl,
    ConstantPredicate,
    OpenMode,
    ProcessCall,
    RetryFact,
    SleepCall,
    TypeEscape,
)
from shockharness.ir.tree_sitter_common import call_arguments, excerpt
from shockharness.source import SourceText

PROCESS_NAMES = frozenset({"exec", "execSync", "execFile", "execFileSync", "spawn", "spawnSync"})
CLASSES = frozenset({Kind.CLASS_DECLARATION, Kind.ABSTRACT_CLASS_DECLARATION, Kind.CLASS})
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
LOOPS = frozenset(
    {Kind.FOR_STATEMENT, Kind.FOR_IN_STATEMENT, Kind.WHILE_STATEMENT, Kind.DO_STATEMENT}
)
PREDEFINED_TYPE = Kind.PREDEFINED_TYPE
ANY = "any"
AS_EXPRESSION = Kind.AS_EXPRESSION
TYPE_ASSERTION = Kind.TYPE_ASSERTION
NON_NULL = Kind.NON_NULL_EXPRESSION
CONST = "const"
TYPE_SUFFIX = "_type"
TYPE_ANNOTATION = Kind.TYPE_ANNOTATION
TYPE_NODES = frozenset({TYPE_ANNOTATION, Kind.TYPE_ARGUMENTS, Kind.CONSTRAINT, Kind.DEFAULT_TYPE})
ANNOTATED = frozenset(
    {
        Kind.REQUIRED_PARAMETER,
        Kind.OPTIONAL_PARAMETER,
        Kind.VARIABLE_DECLARATOR,
        Kind.PUBLIC_FIELD_DEFINITION,
        Kind.PROPERTY_SIGNATURE,
        Kind.TYPE_PARAMETER,
    }
)
# Nodes around a type that are not the type itself: `: T` and a type parameter's `= T`.
WRAPPING_TYPES = frozenset({TYPE_ANNOTATION, Kind.DEFAULT_TYPE})
COMMENT_NODE = Kind.COMMENT
ITERATING = frozenset({Kind.FOR_STATEMENT, Kind.FOR_IN_STATEMENT})
CALL = Kind.CALL_EXPRESSION
NEW = Kind.NEW_EXPRESSION
AWAIT = Kind.AWAIT_EXPRESSION
STATEMENT = Kind.EXPRESSION_STATEMENT
TEMPLATE = Kind.TEMPLATE_STRING
SUBSTITUTION = Kind.TEMPLATE_SUBSTITUTION
BINARY = Kind.BINARY_EXPRESSION
STRING = Kind.STRING
OBJECT = Kind.OBJECT
PAIR = Kind.PAIR
TRY = Kind.TRY_STATEMENT
CATCH = Kind.CATCH_CLAUSE
TRUE = Kind.TRUE
SET_TIMEOUT = "setTimeout"
PROMISE = "Promise"
STATUS = re.compile(r"\.status\b")
LOGGING = re.compile(r"^console\.\w+$")
PREDICATE = re.compile(
    r"^(is|has|can|should)[A-Z_]|^(check|validate|verify|authori[sz]e|authenticate|allow)"
)
EXITS = frozenset({Kind.THROW_STATEMENT, Kind.RETURN_STATEMENT, Kind.BREAK_STATEMENT})


def _callee(call: Node) -> str | None:
    function = call.child_by_field_name(Field.FUNCTION)
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
    key = pair.child_by_field_name(Field.KEY)
    value = pair.child_by_field_name(Field.VALUE)
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
    arguments = call_arguments(call)
    parent = call.parent
    if parent is not None and parent.type == AWAIT:
        parent = parent.parent
    function = _enclosing_function(call)
    return ProcessCall(
        callee=callee,
        text=excerpt(call),
        shell=_shell(arguments),
        interpolated=len(arguments) > 0 and _interpolated(arguments[0]),
        check=CHECK_ABSENT,
        discarded=parent is not None and parent.type == STATEMENT,
        status_read=function is not None and STATUS.search(node_text(function)) is not None,
        returned=_returned(parent, function),
        span=node_span(source, call),
    )


def _returned(parent: Node | None, function: Node | None) -> bool:
    """``return spawnSync(...)``, or ``const r = spawnSync(...)`` and later ``return r``."""
    if parent is None:
        return False
    if parent.type == Kind.RETURN_STATEMENT:
        return True
    name = parent.child_by_field_name(Field.NAME)
    if parent.type != Kind.VARIABLE_DECLARATOR or name is None or function is None:
        return False
    stack: list[Node] = [function]
    while len(stack) > 0:
        node = stack.pop()
        stack.extend(node.named_children)
        values = [c for c in node.named_children if c.type != Kind.COMMENT]
        if node.type == Kind.RETURN_STATEMENT and len(values) == 1:
            if node_text(values[0]) == node_text(name):
                return True
    return False


def _promise_sleep(new: Node) -> bool:
    """``new Promise((resolve) => setTimeout(resolve, ...))``."""
    constructor = new.child_by_field_name(Field.CONSTRUCTOR)
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
        callee,
        excerpt(node),
        _enclosing(node, LOOPS) is not None,
        _zero_delay(node),
        node_span(source, node),
    )


ZERO = "0"
TIMER_DELAY = 1  # setTimeout(callback, delay): the delay's position
PROMISES_DELAY = 0  # timers/promises setTimeout(delay, value)


def _timer_calls(node: Node) -> list[Node]:
    """The ``setTimeout(...)`` calls in a sleep: the node itself, or inside the Promise."""
    found: list[Node] = []
    stack = [node]
    while len(stack) > 0:
        current = stack.pop()
        stack.extend(current.named_children)
        if current.type == CALL and _callee(current) == SET_TIMEOUT:
            found.append(current)
    return found


def _zero_delay(node: Node) -> bool:
    """A delay that is ``0`` or left out: ``setTimeout(resolve)``, ``setTimeout(r, 0)``,
    an awaited ``setTimeout(0)`` from timers/promises."""
    position = PROMISES_DELAY if node.type == CALL else TIMER_DELAY
    timers = _timer_calls(node)
    if len(timers) != 1:
        return False
    arguments = call_arguments(timers[0])
    return len(arguments) <= position or node_text(arguments[position]) == ZERO


def _catches(loop: Node) -> list[Node]:
    """``catch`` clauses in the loop body, outside nested functions and loops."""
    body = loop.child_by_field_name(Field.BODY)
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
    body = catch.child_by_field_name(Field.BODY)
    if body is None:
        return False
    for statement in body.named_children:
        if statement.type in (Kind.COMMENT, Kind.CONTINUE_STATEMENT, Kind.EMPTY_STATEMENT):
            continue
        if statement.type == STATEMENT and statement.named_child_count > 0:
            call = statement.named_children[0]
            callee = _callee(call) if call.type == CALL else None
            if callee is not None and LOGGING.match(callee) is not None:
                continue
        return False
    return True


def _forever(loop: Node) -> bool:
    if loop.type == Kind.WHILE_STATEMENT:
        condition = loop.child_by_field_name(Field.CONDITION)
        return condition is not None and node_text(condition).strip("() \n") == TRUE
    if loop.type == Kind.FOR_STATEMENT:
        condition = loop.child_by_field_name(Field.CONDITION)
        return condition is None or node_text(condition).strip("; \n") in ("", TRUE)
    return False


def _predicate_name(node: Node) -> str | None:
    name = node.child_by_field_name(Field.NAME)
    if name is not None:
        return node_text(name)
    parent = node.parent
    if (
        node.type == Kind.ARROW_FUNCTION
        and parent is not None
        and parent.type == Kind.VARIABLE_DECLARATOR
    ):
        declared = parent.child_by_field_name(Field.NAME)
        if declared is not None:
            return node_text(declared)
    return None


def _returns_true(function: Node) -> bool:
    body = function.child_by_field_name(Field.BODY)
    if body is None:
        return False
    if body.type == TRUE:
        return True  # (x) => true
    statements = [c for c in body.named_children if c.type != Kind.COMMENT]
    if len(statements) != 1 or statements[0].type != Kind.RETURN_STATEMENT:
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
    return [BatchLoop(excerpt(node).split("{")[0].strip(), node_span(source, node))]


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
        return [TypeEscape(TYPE_ESCAPE_ANY, excerpt(_type_context(node)), node_span(source, node))]
    if node.type == AS_EXPRESSION:
        asserted = node.children[len(node.children) - 1]
        parent = node.parent
        # `as const` asserts nothing; `x as unknown as T` is one assertion, reported once.
        if node_text(asserted) == CONST or (parent is not None and parent.type == AS_EXPRESSION):
            return []
        return [TypeEscape(TYPE_ESCAPE_CAST, excerpt(node), node_span(source, node))]
    if node.type == TYPE_ASSERTION:
        return [TypeEscape(TYPE_ESCAPE_CAST, excerpt(node), node_span(source, node))]
    if node.type == NON_NULL:
        return [TypeEscape(TYPE_ESCAPE_NON_NULL, excerpt(node), node_span(source, node))]
    return []


def _class_name(node: Node) -> str | None:
    """A class's name, or the variable an anonymous class expression is assigned to."""
    name = node.child_by_field_name(Field.NAME)
    parent = node.parent
    if name is None and parent is not None and parent.type == Kind.VARIABLE_DECLARATOR:
        name = parent.child_by_field_name(Field.NAME)
    if name is None:
        return None
    return node_text(name)


def _owner(method: Node) -> str | None:
    """The class whose body defines ``method``."""
    body = method.parent
    if method.type != Kind.METHOD_DEFINITION or body is None or body.parent is None:
        return None
    if body.parent.type not in CLASSES:
        return None
    return _class_name(body.parent)


def _predicate(source: SourceText, node: Node) -> list[ConstantPredicate]:
    if node.type not in FUNCTIONS:
        return []
    name = _predicate_name(node)
    if name is None or PREDICATE.match(name) is None or not _returns_true(node):
        return []
    return [ConstantPredicate(name, _owner(node), node_span(source, node))]


def _bases(node: Node) -> tuple[str, ...]:
    """``extends X`` of a class (JavaScript, and TypeScript's extends clause)."""
    for heritage in node.named_children:
        if heritage.type != Kind.CLASS_HERITAGE:
            continue
        for part in heritage.named_children:
            if part.type == Kind.EXTENDS_CLAUSE:
                value = part.child_by_field_name(Field.VALUE)
                if value is not None:
                    return (node_text(value),)
            elif part.type != Kind.IMPLEMENTS_CLAUSE and part.type != Kind.COMMENT:
                return (node_text(part),)
    return ()


def _class(source: SourceText, node: Node) -> list[ClassDecl]:
    if node.type not in CLASSES:
        return []
    name = _class_name(node)
    if name is None:
        return []
    return [ClassDecl(name, _bases(node), node_span(source, node))]


# CALL001: Node's open calls, whose flags (the second argument) decide whether they write.
OPENS = frozenset({"open", "openSync"})
# Node's flag strings ("r", "r+", "rs+", "w", "wx", "a+", ...); w, a or + writes.
NODE_FLAGS = re.compile(r"[rwa][sx]?\+?")
WRITE_FLAGS = re.compile(r"[wa+]")
FLAGS_INDEX = 1


def _open_mode(source: SourceText, node: Node) -> OpenMode | None:
    if node.type != Kind.CALL_EXPRESSION:
        return None
    function = node.child_by_field_name(Field.FUNCTION)
    callee = None if function is None else dotted_callee(function)
    if callee is None:
        return None
    _owner, _dot, method = callee.rpartition(".")
    if method not in OPENS:
        return None
    arguments = call_arguments(node)
    span = node_span(source, node)
    if len(arguments) <= FLAGS_INDEX:
        return OpenMode(span, OPEN_READ)
    flags = arguments[FLAGS_INDEX]
    text = node_text(flags).strip("'\"")
    if flags.type != Kind.STRING or NODE_FLAGS.fullmatch(text) is None:
        return OpenMode(span, OPEN_UNKNOWN)
    if WRITE_FLAGS.search(text) is None:
        return OpenMode(span, OPEN_READ)
    return OpenMode(span, OPEN_WRITE)


def collect_javascript_catalog(source: SourceText, root: Node) -> CatalogFacts:
    processes: list[ProcessCall] = []
    sleeps: list[SleepCall] = []
    retries: list[RetryFact] = []
    batches: list[BatchLoop] = []
    predicates: list[ConstantPredicate] = []
    classes: list[ClassDecl] = []
    escapes: list[TypeEscape] = []
    opens: list[OpenMode] = []
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
        classes.extend(_class(source, node))
        escapes.extend(_type_escape(source, node))
        mode = _open_mode(source, node)
        if mode is not None:
            opens.append(mode)
    return CatalogFacts(
        process_calls=tuple(sorted(processes, key=lambda p: (p.span, p.callee))),
        sleeps=tuple(sorted(sleeps, key=lambda s: (s.span, s.callee))),
        retries=tuple(sorted(retries, key=lambda r: (r.span, r.kind))),
        batch_loops=tuple(sorted(batches, key=lambda b: b.span)),
        type_escapes=tuple(sorted(escapes, key=lambda t: (t.span, t.kind))),
        constant_predicates=tuple(sorted(predicates, key=lambda c: c.span)),
        classes=tuple(sorted(classes, key=lambda c: c.span)),
        open_modes=tuple(sorted(opens, key=lambda o: o.span)),
    )
