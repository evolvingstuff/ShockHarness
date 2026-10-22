"""Guardrail and discarded-call facts for C# (milestone G2, part two).

* RESULT001 reads the calls whose result an expression statement throws away
  (``name.Trim();``, ``velocity.Normalized();``). An explicit discard (``_ = F();``) says
  the result is unwanted and is not one.
* BOOL001 reads a ``true``/``false`` passed positionally to a call with more than one
  positional argument (``AddChild(node, true)``); a named argument (``enabled: true``)
  says what it switches and is not one.
* STUB001 reads ``throw new NotImplementedException(...)``, as a statement or an
  expression (``=> throw new NotImplementedException()``). An empty method body is not a
  placeholder: Godot's script template writes empty ``_Ready`` and ``_Process``, and an
  empty virtual hook is a deliberate default.
"""

from tree_sitter import Node

from shockharness.constants import EVIDENCE_MAX_CHARS
from shockharness.ir.csharp_functions import FUNCTION_TYPES, dotted_name, scope_for
from shockharness.ir.csharp_nodes import Field, Kind
from shockharness.ir.javascript_catches import node_span, node_text
from shockharness.ir.model import (
    MODULE_SCOPE,
    NO_GUARDRAILS,
    PLACEHOLDER_NOT_IMPLEMENTED,
    AsyncFacts,
    BooleanArgument,
    DiscardedCall,
    GuardrailFacts,
    Placeholder,
)
from shockharness.source import SourceText

DYNAMIC = "<dynamic>"
NOT_IMPLEMENTED = frozenset({"NotImplementedException", "System.NotImplementedException"})
ASYNC_MODIFIER = "async"
THROWS = frozenset({Kind.THROW_STATEMENT, Kind.THROW_EXPRESSION})
CALLS = frozenset({Kind.INVOCATION_EXPRESSION, Kind.OBJECT_CREATION_EXPRESSION})


def _excerpt(node: Node) -> str:
    first = node_text(node).split("\n")[0].strip()
    return first[:EVIDENCE_MAX_CHARS]


def _positional(call: Node) -> list[Node] | None:
    """The positional argument nodes of a call, or ``None`` when it has none to read."""
    arguments = call.child_by_field_name(Field.ARGUMENTS)
    if arguments is None:
        return None
    return [
        a
        for a in arguments.named_children
        if a.type == Kind.ARGUMENT and a.child_by_field_name(Field.NAME) is None
    ]


def _callee(call: Node) -> str:
    """The dotted callee as written (``GD.Print``, ``this.Hit``), or ``<dynamic>``."""
    if call.type == Kind.OBJECT_CREATION_EXPRESSION:
        constructed = call.child_by_field_name(Field.TYPE)
        if constructed is None:
            return DYNAMIC
        return "new " + node_text(constructed)
    function = call.child_by_field_name(Field.FUNCTION)
    if function is None:
        return DYNAMIC
    if function.type in (Kind.IDENTIFIER, Kind.GENERIC_NAME):
        return node_text(function).split("<", 1)[0]
    dotted = dotted_name(function)
    if dotted is not None:
        return dotted
    name = function.child_by_field_name(Field.NAME)
    if function.type != Kind.MEMBER_ACCESS_EXPRESSION or name is None:
        return DYNAMIC
    # A method of a call's result (`GetNode<Area2D>("Hitbox").SetDeferred(...)`): the
    # receiver is not a name, the method is.
    return f"{DYNAMIC}.{node_text(name).split('<', 1)[0]}"


def _value(node: Node) -> Node | None:
    values = [c for c in node.named_children if c.type != Kind.COMMENT]
    return values[0] if len(values) == 1 else None


def _is_async(node: Node) -> bool:
    return any(
        node_text(c) == ASYNC_MODIFIER
        for c in node.children
        if c.type == Kind.MODIFIER or not c.is_named
    )


def _throws_not_implemented(node: Node) -> bool:
    thrown = _value(node)
    if thrown is None or thrown.type != Kind.OBJECT_CREATION_EXPRESSION:
        return False
    constructed = thrown.child_by_field_name(Field.TYPE)
    return constructed is not None and node_text(constructed) in NOT_IMPLEMENTED


class _Collector:
    def __init__(self, source: SourceText) -> None:
        self.source = source
        self.discarded: list[DiscardedCall] = []
        self.booleans: list[BooleanArgument] = []
        self.placeholders: list[Placeholder] = []

    def visit(self, node: Node, scope: str, flags: tuple[bool, bool]) -> None:
        in_async, in_try = flags
        if node.type == Kind.EXPRESSION_STATEMENT:
            call = _value(node)
            if call is not None and call.type == Kind.INVOCATION_EXPRESSION:
                self._discarded(call, in_async, in_try)
        elif node.type in CALLS:
            self._booleans(node)
        elif node.type in THROWS and _throws_not_implemented(node):
            self.placeholders.append(
                Placeholder(
                    PLACEHOLDER_NOT_IMPLEMENTED, _excerpt(node), scope, node_span(self.source, node)
                )
            )

    def _discarded(self, call: Node, in_async: bool, in_try: bool) -> None:
        positional = _positional(call)
        self.discarded.append(
            DiscardedCall(
                callee=_callee(call),
                text=_excerpt(call),
                void=False,
                in_async=in_async,
                bound_by=None,
                arguments=None if positional is None else len(positional),
                in_try=in_try,
                span=node_span(self.source, call),
            )
        )

    def _booleans(self, call: Node) -> None:
        positional = _positional(call)
        if positional is None or len(positional) <= 1:  # one positional argument says itself
            return
        callee = _callee(call)
        for position, argument in enumerate(positional):
            value = _value(argument)
            if value is not None and value.type == Kind.BOOLEAN_LITERAL:
                self.booleans.append(
                    BooleanArgument(
                        callee=callee,
                        position=position,
                        text=_excerpt(call),
                        span=node_span(self.source, value),
                    )
                )


def _inner_flags(node: Node, flags: tuple[bool, bool]) -> tuple[bool, bool]:
    """(in an async function, in the body of a try that has a handler) for a child of ``node``."""
    in_async, in_try = flags
    if node.type in FUNCTION_TYPES:
        return _is_async(node), False
    if node.type == Kind.TRY_STATEMENT and any(
        c.type == Kind.CATCH_CLAUSE for c in node.named_children
    ):
        return in_async, True
    if node.type in (Kind.CATCH_CLAUSE, Kind.FINALLY_CLAUSE):
        return in_async, False
    return in_async, in_try


def collect_csharp_guardrails(source: SourceText, root: Node) -> tuple[GuardrailFacts, AsyncFacts]:
    """The guardrail facts, and the async facts holding the discarded calls RESULT001
    reads (C# has no settled batches or rejection handlers to record)."""
    collector = _Collector(source)
    stack: list[tuple[Node, str, tuple[bool, bool]]] = [(root, MODULE_SCOPE, (False, False))]
    while len(stack) > 0:
        node, scope, flags = stack.pop()
        collector.visit(node, scope, flags)
        child_scope = scope_for(node, scope)
        inner = _inner_flags(node, flags)
        stack.extend((child, child_scope, inner) for child in reversed(node.children))
    guardrails = GuardrailFacts(
        finally_exits=NO_GUARDRAILS.finally_exits,
        placeholders=tuple(sorted(collector.placeholders, key=lambda p: (p.span, p.kind))),
        asserts=NO_GUARDRAILS.asserts,
        boolean_arguments=tuple(sorted(collector.booleans, key=lambda b: (b.span, b.position))),
        import_time_calls=NO_GUARDRAILS.import_time_calls,
        element_guards=NO_GUARDRAILS.element_guards,
        early_publications=NO_GUARDRAILS.early_publications,
        unlocked_reads=NO_GUARDRAILS.unlocked_reads,
        exit_exceptions=NO_GUARDRAILS.exit_exceptions,
    )
    asynchrony = AsyncFacts(
        discarded_calls=tuple(sorted(collector.discarded, key=lambda c: c.span)),
        settled_batches=(),
        rejection_handlers=(),
    )
    return guardrails, asynchrony
