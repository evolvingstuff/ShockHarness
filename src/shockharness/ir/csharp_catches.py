"""Catch facts for C# (milestone G2): every ``catch`` clause of a ``try``, with the types it
names, its ``when`` filter, what its body does with the exception, and the statements it
protects.

Identities are the type names as written, at approximate confidence, as JavaScript's are:
``using`` directives, global usings and the SDK's implicit usings are not resolved, so a
boundary's qualified name (``System.IO.IOException``) matches ``IOException`` by its last
segments. ``catch { }`` and ``catch (Exception)`` catch everything; a filter that tests the
caught exception's type (``when (e is IOException or TimeoutException)``) narrows the
identities to those types. Godot's engine logs an exception thrown in a callback and
carries on, so a handler that only logs adds nothing and is reported like any other.
"""

import re

from tree_sitter import Node

from shockharness.constants import EVIDENCE_MAX_CHARS
from shockharness.ir.csharp_functions import scope_for
from shockharness.ir.csharp_nodes import Field, Kind
from shockharness.ir.javascript_catches import node_span, node_text
from shockharness.ir.model import (
    BODY_EMPTY,
    BODY_LOGGING_ONLY,
    BODY_OTHER,
    BODY_RAISE_CHAINED,
    BODY_RAISE_OTHER,
    BODY_RERAISE,
    BODY_RETURN_FALLBACK,
    CATCH_CSHARP,
    CONFIDENCE_APPROXIMATE,
    MODULE_SCOPE,
    CatchFact,
    ExceptionIdentity,
    HandlerBody,
    Span,
    TryStatement,
)
from shockharness.ir.tree_sitter_common import count_kinds
from shockharness.source import SourceText

BROAD_TYPES = frozenset({"Exception", "SystemException"})
COMPOUND_STATEMENTS = frozenset(
    {
        Kind.IF_STATEMENT,
        Kind.FOR_STATEMENT,
        Kind.FOREACH_STATEMENT,
        Kind.WHILE_STATEMENT,
        Kind.DO_STATEMENT,
        Kind.TRY_STATEMENT,
        Kind.SWITCH_STATEMENT,
        Kind.USING_STATEMENT,
        Kind.LOCK_STATEMENT,
        Kind.BLOCK,
        Kind.LOCAL_FUNCTION_STATEMENT,
        Kind.CHECKED_STATEMENT,
        Kind.UNSAFE_STATEMENT,
        Kind.FIXED_STATEMENT,
    }
)
CALLS = frozenset({Kind.INVOCATION_EXPRESSION, Kind.OBJECT_CREATION_EXPRESSION})
OPERATIONS = CALLS | frozenset(
    {
        Kind.IMPLICIT_OBJECT_CREATION_EXPRESSION,
        Kind.LAMBDA_EXPRESSION,
        Kind.ANONYMOUS_METHOD_EXPRESSION,
        Kind.AWAIT_EXPRESSION,
    }
)
LITERALS = frozenset(
    {
        Kind.INTEGER_LITERAL,
        Kind.REAL_LITERAL,
        Kind.STRING_LITERAL,
        Kind.VERBATIM_STRING_LITERAL,
        Kind.RAW_STRING_LITERAL,
        Kind.CHARACTER_LITERAL,
        Kind.BOOLEAN_LITERAL,
        Kind.NULL_LITERAL,
        Kind.DEFAULT_EXPRESSION,
    }
)
EMPTY_VALUES = frozenset({"string.Empty", "String.Empty"})
# Calls that only record: Godot's GD.Print family, the console, System.Diagnostics, and
# logger objects (Microsoft.Extensions.Logging, Serilog, NLog spellings).
LOGGING_EXACT = frozenset(
    {
        "GD.Print",
        "GD.PrintErr",
        "GD.PrintRich",
        "GD.PrintRaw",
        "GD.PrintS",
        "GD.PrintT",
        "GD.PushError",
        "GD.PushWarning",
        "Console.WriteLine",
        "Console.Write",
        "Console.Error.WriteLine",
        "Console.Error.Write",
        "Debug.WriteLine",
        "Debug.Print",
        "Trace.WriteLine",
        "Trace.TraceError",
        "Trace.TraceWarning",
        "Trace.TraceInformation",
    }
)
LOGGING_CALL = re.compile(
    r"^(?:[A-Za-z_][A-Za-z0-9_]*\.)*(?:_?logger|_?log|Logger|Log|_?Logger)"
    r"\.(?:Log[A-Za-z]*|Debug|Info|Information|Warn|Warning|Error|Critical|Fatal|Trace|Verbose)$"
)
TYPE_TEST_PATTERNS = frozenset(
    {
        Kind.CONSTANT_PATTERN,
        Kind.TYPE_PATTERN,
        Kind.DECLARATION_PATTERN,
        Kind.RECURSIVE_PATTERN,
    }
)
TYPE_NAMES = frozenset({Kind.IDENTIFIER, Kind.QUALIFIED_NAME, Kind.GENERIC_NAME})
UNCLASSIFIED = HandlerBody(BODY_OTHER, "handler body is not classified")


def _excerpt(node: Node) -> str:
    first = node_text(node).split("\n")[0].strip()
    return first[:EVIDENCE_MAX_CHARS]


def _statements(block: Node | None) -> list[Node]:
    if block is None:
        return []
    return [c for c in block.named_children if c.type != Kind.COMMENT]


def _value(node: Node) -> Node | None:
    """The single expression a statement or wrapper holds."""
    values = [c for c in node.named_children if c.type != Kind.COMMENT]
    return values[0] if len(values) == 1 else None


def _unwrap(node: Node) -> Node:
    current = node
    while current.type in (Kind.PARENTHESIZED_EXPRESSION, Kind.AWAIT_EXPRESSION):
        inner = _value(current)
        if inner is None:
            return current
        current = inner
    return current


# -- the protected statements -------------------------------------------------------------


def _callee_text(call: Node) -> str:
    if call.type == Kind.OBJECT_CREATION_EXPRESSION:
        constructed = call.child_by_field_name(Field.TYPE)
        if constructed is None:
            return _excerpt(call)
        return "new " + node_text(constructed)
    function = call.child_by_field_name(Field.FUNCTION)
    if function is None:
        return _excerpt(call)
    return node_text(function)


def _operation(span: Span, statement: Node, value: Node) -> TryStatement:
    inner = value
    awaited = 0
    if inner.type == Kind.ASSIGNMENT_EXPRESSION:
        right = inner.child_by_field_name(Field.RIGHT)
        if right is not None:
            inner = right
    if inner.type == Kind.AWAIT_EXPRESSION:
        awaited = 1
    inner = _unwrap(inner)
    if inner.type not in CALLS:
        return TryStatement(span, None, f"statement value is not a call ({inner.type})")
    extra = count_kinds(statement, OPERATIONS) - awaited
    if extra != 1:
        return TryStatement(
            span,
            None,
            f"statement performs {extra} operations; only one can be attributed to the boundary",
        )
    return TryStatement(span, _callee_text(inner), None)


def try_statement(source: SourceText, statement: Node) -> TryStatement:
    """One protected statement, attributed to its single call when it has one."""
    span = node_span(source, statement)
    kind = statement.type
    if kind in COMPOUND_STATEMENTS:
        return TryStatement(
            span, None, f"compound statement ({kind}) wraps more than one operation"
        )
    if kind in (Kind.EXPRESSION_STATEMENT, Kind.RETURN_STATEMENT):
        value = _value(statement)
        if value is None:
            return TryStatement(span, None, f"statement ({kind}) does not perform a call")
        return _operation(span, statement, value)
    if kind == Kind.LOCAL_DECLARATION_STATEMENT:
        return _declaration_operation(span, statement)
    return TryStatement(span, None, f"statement ({kind}) does not perform a call")


def _declaration_operation(span: Span, statement: Node) -> TryStatement:
    declarators = [
        d
        for declaration in statement.named_children
        if declaration.type == Kind.VARIABLE_DECLARATION
        for d in declaration.named_children
        if d.type == Kind.VARIABLE_DECLARATOR
    ]
    if len(declarators) != 1:
        return TryStatement(span, None, "declaration binds more than one variable")
    name = declarators[0].child_by_field_name(Field.NAME)
    values = [c for c in declarators[0].named_children if name is None or c.id != name.id]
    if len(values) != 1:
        return TryStatement(span, None, "declaration has no value")
    return _operation(span, statement, values[0])


# -- the handler body ---------------------------------------------------------------------


def is_literal_like(node: Node) -> bool:
    """A literal, ``default``, ``string.Empty``, a negative number, ``[]``, or an empty
    ``new T()`` / ``new()`` without an initializer."""
    inner = _unwrap(node)
    if inner.type in LITERALS or node_text(inner) in EMPTY_VALUES:
        return True
    if inner.type == Kind.PREFIX_UNARY_EXPRESSION:
        operand = _value(inner)
        return operand is not None and operand.type in (Kind.INTEGER_LITERAL, Kind.REAL_LITERAL)
    if inner.type == Kind.COLLECTION_EXPRESSION:
        return len(_statements(inner)) == 0
    return _is_empty_creation(inner)


def _is_empty_creation(node: Node) -> bool:
    """``new List<int>()`` or ``new()``: no arguments, no initializer."""
    if node.type not in (Kind.OBJECT_CREATION_EXPRESSION, Kind.IMPLICIT_OBJECT_CREATION_EXPRESSION):
        return False
    for child in node.named_children:
        if child.type == Kind.INITIALIZER_EXPRESSION:
            return False
        if child.type == Kind.ARGUMENT_LIST and len(child.named_children) > 0:
            return False
    return True


def _callee(statement: Node) -> str | None:
    if statement.type != Kind.EXPRESSION_STATEMENT:
        return None
    value = _value(statement)
    if value is None or value.type != Kind.INVOCATION_EXPRESSION:
        return None
    function = value.child_by_field_name(Field.FUNCTION)
    return None if function is None else node_text(function)


def is_logging_statement(statement: Node) -> bool:
    name = _callee(statement)
    if name is None:
        return False
    return name in LOGGING_EXACT or LOGGING_CALL.match(name) is not None


def _classify_throw(statement: Node, name: str | None) -> HandlerBody:
    described = _excerpt(statement)
    thrown = _value(statement)
    if thrown is None:
        return HandlerBody(BODY_RERAISE, described)  # `throw;` keeps the exception and its stack
    if thrown.type == Kind.IDENTIFIER and name is not None and node_text(thrown) == name:
        return HandlerBody(
            BODY_RAISE_OTHER,
            f"{described} (resets the stack trace; `throw;` rethrows the exception as it was)",
        )
    if thrown.type == Kind.OBJECT_CREATION_EXPRESSION and _passes_inner(thrown, name):
        return HandlerBody(BODY_RAISE_CHAINED, described)
    return HandlerBody(BODY_RAISE_OTHER, f"{described} (the inner exception is not passed on)")


def _passes_inner(creation: Node, name: str | None) -> bool:
    """``new GameError("...", e)``: the caught exception is an argument (InnerException)."""
    arguments = creation.child_by_field_name(Field.ARGUMENTS)
    if arguments is None or name is None:
        return False
    for argument in arguments.named_children:
        value = _value(argument)
        if value is not None and value.type == Kind.IDENTIFIER and node_text(value) == name:
            return True
    return False


def classify_statements(  # shockharness: ignore[DUP002] reason="C# helpers classify C# handlers"
    statements: list[Node], name: str | None
) -> HandlerBody:
    if len(statements) == 0:
        return HandlerBody(BODY_EMPTY, "handler body is empty; the failure vanishes")
    remaining = [s for s in statements if not is_logging_statement(s)]
    if len(remaining) == 0:
        return HandlerBody(
            BODY_LOGGING_ONLY, "handler only logs; the failure is recorded, not handled"
        )
    if len(remaining) != 1:
        return UNCLASSIFIED
    statement = remaining[0]
    if statement.type == Kind.RETURN_STATEMENT:
        value = _value(statement)
        if value is None or is_literal_like(value):
            return HandlerBody(BODY_RETURN_FALLBACK, node_text(statement).strip())
        return UNCLASSIFIED
    if statement.type == Kind.THROW_STATEMENT:
        return _classify_throw(statement, name)
    return UNCLASSIFIED


def guard_call(statements: list[Node], name: str | None) -> str | None:
    """The callee, as written, when the first statement is ``Callee(<caught>);``."""
    if name is None or len(statements) == 0 or statements[0].type != Kind.EXPRESSION_STATEMENT:
        return None
    value = _value(statements[0])
    if value is None or value.type != Kind.INVOCATION_EXPRESSION:
        return None
    function = value.child_by_field_name(Field.FUNCTION)
    if function is None or _only_argument(value) != name:
        return None
    return node_text(function)


def _only_argument(call: Node) -> str | None:
    """The text of a call's one argument, or ``None`` when it has another number."""
    arguments = call.child_by_field_name(Field.ARGUMENTS)
    if arguments is None:
        return None
    values = [_value(a) for a in arguments.named_children if a.type == Kind.ARGUMENT]
    if len(values) != 1 or values[0] is None:
        return None
    return node_text(values[0])


# -- identities -----------------------------------------------------------------------------


def _identity(written: str) -> ExceptionIdentity:
    _namespace, _dot, last = written.rpartition(".")
    return ExceptionIdentity(written, written, CONFIDENCE_APPROXIMATE, broad=last in BROAD_TYPES)


def _tested_types(pattern: Node) -> list[str] | None:
    """The types an ``is`` pattern tests (``IOException or TimeoutException``), or ``None``
    when the pattern tests anything else."""
    if pattern.type == Kind.OR_PATTERN:
        left = pattern.child_by_field_name(Field.LEFT)
        right = pattern.child_by_field_name(Field.RIGHT)
        if left is None or right is None:
            return None
        first = _tested_types(left)
        second = _tested_types(right)
        if first is None or second is None:
            return None
        return first + second
    if pattern.type not in TYPE_TEST_PATTERNS:
        return None
    typed = pattern.child_by_field_name(Field.TYPE)
    if typed is None:
        typed = _value(pattern)
    if typed is None or typed.type not in TYPE_NAMES:
        return None
    return [node_text(typed)]


def _filter_types(clause: Node, name: str | None) -> list[str] | None:
    """``when (e is T or U)``: the types a filter narrows the catch to."""
    filters = [c for c in clause.named_children if c.type == Kind.CATCH_FILTER_CLAUSE]
    if len(filters) != 1 or name is None:
        return None
    test = _value(filters[0])
    if test is None:
        return None
    test = _unwrap(test)
    subject = test.child_by_field_name(Field.EXPRESSION)
    pattern = test.child_by_field_name(Field.PATTERN)
    if test.type != Kind.IS_PATTERN_EXPRESSION or subject is None or pattern is None:
        return None
    if node_text(subject) != name:
        return None
    return _tested_types(pattern)


def _declaration(clause: Node) -> tuple[str | None, str | None]:
    """(type as written, bound name) of ``catch (T e)``; both ``None`` for ``catch { }``."""
    for child in clause.named_children:
        if child.type == Kind.CATCH_DECLARATION:
            typed = child.child_by_field_name(Field.TYPE)
            name = child.child_by_field_name(Field.NAME)
            return (
                None if typed is None else node_text(typed),
                None if name is None else node_text(name),
            )
    return None, None


def _catch(source: SourceText, scope: str, protected: list[Node], clause: Node) -> CatchFact:
    written, name = _declaration(clause)
    statements = _statements(clause.child_by_field_name(Field.BODY))
    narrowed = _filter_types(clause, name)
    identities: tuple[ExceptionIdentity, ...] = ()
    narrowed_from: str | None = None
    if narrowed is not None:
        identities = tuple(_identity(t) for t in narrowed)
        narrowed_from = written
    elif written is not None:
        identities = (_identity(written),)
    guard = guard_call(statements, name)
    return CatchFact(
        span=node_span(source, clause),
        kind=CATCH_CSHARP,
        scope=scope,
        identities=identities,
        bare=written is None,
        bound_name=name,
        body=classify_statements(statements, name),
        try_statements=tuple(try_statement(source, s) for s in protected),
        narrowed_from=narrowed_from,
        guard_call=guard,
        guard_body=None if guard is None else classify_statements(statements[1:], name),
    )


def collect_csharp_catches(source: SourceText, root: Node) -> tuple[CatchFact, ...]:
    facts: list[CatchFact] = []
    stack: list[tuple[Node, str]] = [(root, MODULE_SCOPE)]
    while len(stack) > 0:
        node, scope = stack.pop()
        if node.type == Kind.TRY_STATEMENT:
            protected = _statements(node.child_by_field_name(Field.BODY))
            for clause in node.named_children:
                if clause.type == Kind.CATCH_CLAUSE:
                    facts.append(_catch(source, scope, protected, clause))
        child_scope = scope_for(node, scope)
        stack.extend((child, child_scope) for child in reversed(node.children))
    facts.sort(key=lambda fact: fact.span)
    return tuple(facts)
