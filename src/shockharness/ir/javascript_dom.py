"""DOM001 facts (decision 27): an ``instanceof`` test on an event target that guards a
later ``.closest(...)`` on the same value.

A delegated click handler that starts ``if (!(event.target instanceof HTMLElement))
return;`` drops a click whose target is an ``SVGElement`` (an icon inside a button),
although ``closest`` is defined on every ``Element``. Recorded, per function body: the
negated test followed by an early exit and, later in the same block, ``X.closest(...)``;
and the positive test whose consequence calls ``X.closest(...)``. ``X`` is
``<expression>.target`` or a local assigned from one. Which classes count is the rule's
catalog (rules.dom.classes).
"""

from collections.abc import Iterator

from tree_sitter import Node

from shockharness.ir.javascript_catches import TYPE_WRAPPERS, node_span, node_text
from shockharness.ir.javascript_nodes import Field, Kind
from shockharness.ir.model import ElementGuard
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
EXITS = frozenset(
    {Kind.RETURN_STATEMENT, Kind.THROW_STATEMENT, Kind.CONTINUE_STATEMENT, Kind.BREAK_STATEMENT}
)
TARGET_SUFFIX = ".target"
CLOSEST = "closest"
COMMENT = Kind.COMMENT


def _named(node: Node) -> list[Node]:
    return [child for child in node.named_children if child.type != COMMENT]


def _unwrap(node: Node) -> Node:
    current = node
    while current.type == Kind.PARENTHESIZED_EXPRESSION or current.type in TYPE_WRAPPERS:
        inner = _named(current)
        if len(inner) == 0:
            return current
        current = inner[0]
    return current


def _instanceof(node: Node) -> tuple[Node, str, bool] | None:
    """(the test node, its subject text, negated) for ``X instanceof C`` or
    ``!(X instanceof C)``; the class is read by the caller from the test node."""
    current = _unwrap(node)
    negated = False
    while current.type == Kind.UNARY_EXPRESSION:
        operator = current.child_by_field_name(Field.OPERATOR)
        argument = current.child_by_field_name(Field.ARGUMENT)
        if operator is None or argument is None or node_text(operator) != "!":
            return None
        negated = not negated
        current = _unwrap(argument)
    operator = current.child_by_field_name(Field.OPERATOR)
    left = current.child_by_field_name(Field.LEFT)
    if current.type != Kind.BINARY_EXPRESSION or operator is None or left is None:
        return None
    if node_text(operator) != Kind.INSTANCEOF:
        return None
    return current, node_text(_unwrap(left)), negated


def _exits(node: Node | None) -> bool:
    if node is None:
        return False
    last = node
    if node.type == Kind.STATEMENT_BLOCK:
        statements = _named(node)
        if len(statements) == 0:
            return False
        last = statements[len(statements) - 1]
    return last.type in EXITS


def _is_closest_on(node: Node, subject: str) -> bool:
    """``subject.closest(...)``."""
    if node.type != Kind.CALL_EXPRESSION:
        return False
    function = node.child_by_field_name(Field.FUNCTION)
    if function is None or function.type != Kind.MEMBER_EXPRESSION:
        return False
    prop = function.child_by_field_name(Field.PROPERTY)
    obj = function.child_by_field_name(Field.OBJECT)
    if prop is None or obj is None or node_text(prop) != CLOSEST:
        return False
    return node_text(_unwrap(obj)) == subject


def _closest_calls(nodes: list[Node], subject: str) -> Iterator[Node]:
    """``subject.closest(...)`` calls anywhere in ``nodes``."""
    stack = list(reversed(nodes))
    while len(stack) > 0:
        node = stack.pop()
        if _is_closest_on(node, subject):
            yield node
        stack.extend(reversed(_named(node)))


def _target_locals(block: list[Node]) -> set[str]:
    """Locals of the block assigned from an event target (``const t = event.target``)."""
    names: set[str] = set()
    for statement in block:
        if statement.type not in (Kind.LEXICAL_DECLARATION, Kind.VARIABLE_DECLARATION):
            continue
        for declarator in _named(statement):
            name = declarator.child_by_field_name(Field.NAME)
            value = declarator.child_by_field_name(Field.VALUE)
            if name is None or value is None or name.type != Kind.IDENTIFIER:
                continue
            if node_text(_unwrap(value)).endswith(TARGET_SUFFIX):
                names.add(node_text(name))
    return names


def _guarded_calls(block: list[Node], index: int, negated: bool, subject: str) -> list[Node]:
    """The ``.closest`` calls the test at ``block[index]`` guards: after an early exit for
    a negated test, inside the consequence for a positive one."""
    consequence = block[index].child_by_field_name(Field.CONSEQUENCE)
    if negated and _exits(consequence):
        return list(_closest_calls(block[index + 1 :], subject))
    if not negated and consequence is not None:
        return list(_closest_calls([consequence], subject))
    return []


def _guard(
    source: SourceText, block: list[Node], index: int, targets: set[str]
) -> ElementGuard | None:
    condition = block[index].child_by_field_name(Field.CONDITION)
    test = None if condition is None else _instanceof(condition)
    if test is None:
        return None
    node, subject, negated = test
    if not (subject.endswith(TARGET_SUFFIX) or subject in targets):
        return None
    calls = _guarded_calls(block, index, negated, subject)
    right = node.child_by_field_name(Field.RIGHT)
    if len(calls) == 0 or right is None:
        return None
    return ElementGuard(
        span=node_span(source, node),
        subject=subject,
        class_name=node_text(right),
        closest=node_span(source, calls[0]),
    )


def _block_guards(source: SourceText, block: list[Node]) -> list[ElementGuard]:
    targets = _target_locals(block)
    found: list[ElementGuard] = []
    for index, statement in enumerate(block):
        if statement.type != Kind.IF_STATEMENT:
            continue
        guard = _guard(source, block, index, targets)
        if guard is not None:
            found.append(guard)
    return found


def collect_element_guards(source: SourceText, root: Node) -> tuple[ElementGuard, ...]:
    found: list[ElementGuard] = []
    stack: list[Node] = [root]
    while len(stack) > 0:
        node = stack.pop()
        stack.extend(node.named_children)
        if node.type not in FUNCTIONS:
            continue
        body = node.child_by_field_name(Field.BODY)
        if body is not None and body.type == Kind.STATEMENT_BLOCK:
            found.extend(_block_guards(source, _named(body)))
    return tuple(sorted(found, key=lambda g: g.span))
