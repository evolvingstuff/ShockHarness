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
from shockharness.ir.model import ElementGuard
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
EXITS = frozenset({"return_statement", "throw_statement", "continue_statement", "break_statement"})
TARGET_SUFFIX = ".target"
CLOSEST = "closest"
COMMENT = "comment"


def _named(node: Node) -> list[Node]:
    return [child for child in node.named_children if child.type != COMMENT]


def _unwrap(node: Node) -> Node:
    current = node
    while current.type == "parenthesized_expression" or current.type in TYPE_WRAPPERS:
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
    while current.type == "unary_expression":
        operator = current.child_by_field_name("operator")
        argument = current.child_by_field_name("argument")
        if operator is None or argument is None or node_text(operator) != "!":
            return None
        negated = not negated
        current = _unwrap(argument)
    operator = current.child_by_field_name("operator")
    left = current.child_by_field_name("left")
    if current.type != "binary_expression" or operator is None or left is None:
        return None
    if node_text(operator) != "instanceof":
        return None
    return current, node_text(_unwrap(left)), negated


def _exits(node: Node | None) -> bool:
    if node is None:
        return False
    last = node
    if node.type == "statement_block":
        statements = _named(node)
        if len(statements) == 0:
            return False
        last = statements[len(statements) - 1]
    return last.type in EXITS


def _is_closest_on(node: Node, subject: str) -> bool:
    """``subject.closest(...)``."""
    if node.type != "call_expression":
        return False
    function = node.child_by_field_name("function")
    if function is None or function.type != "member_expression":
        return False
    prop = function.child_by_field_name("property")
    obj = function.child_by_field_name("object")
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
        if statement.type not in ("lexical_declaration", "variable_declaration"):
            continue
        for declarator in _named(statement):
            name = declarator.child_by_field_name("name")
            value = declarator.child_by_field_name("value")
            if name is None or value is None or name.type != "identifier":
                continue
            if node_text(_unwrap(value)).endswith(TARGET_SUFFIX):
                names.add(node_text(name))
    return names


def _guarded_calls(block: list[Node], index: int, negated: bool, subject: str) -> list[Node]:
    """The ``.closest`` calls the test at ``block[index]`` guards: after an early exit for
    a negated test, inside the consequence for a positive one."""
    consequence = block[index].child_by_field_name("consequence")
    if negated and _exits(consequence):
        return list(_closest_calls(block[index + 1 :], subject))
    if not negated and consequence is not None:
        return list(_closest_calls([consequence], subject))
    return []


def _guard(
    source: SourceText, block: list[Node], index: int, targets: set[str]
) -> ElementGuard | None:
    condition = block[index].child_by_field_name("condition")
    test = None if condition is None else _instanceof(condition)
    if test is None:
        return None
    node, subject, negated = test
    if not (subject.endswith(TARGET_SUFFIX) or subject in targets):
        return None
    calls = _guarded_calls(block, index, negated, subject)
    right = node.child_by_field_name("right")
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
        if statement.type != "if_statement":
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
        body = node.child_by_field_name("body")
        if body is not None and body.type == "statement_block":
            found.extend(_block_guards(source, _named(body)))
    return tuple(sorted(found, key=lambda g: g.span))
