"""Maximum decision nesting depth, convention ``nesting/1``.

The depth of a unit is the deepest chain of decision constructs: ``if``
(``elif``/``else if`` and ``else`` branches sit at the same depth as the
``then`` branch), loops, ``match``/``switch`` (their arms), ``except``/``catch``
handlers, conditional expressions and comprehension ``if`` clauses. A unit
with no decision has depth 0. Syntactic wrappers add nothing: parentheses,
``with`` blocks, plain blocks, ``try`` bodies, ``try/else`` and ``finally``
bodies, labels, and comprehension ``for`` clauses. Nested units are measured
on their own.
"""

from shockharness.ir.model import (
    CK_CONDITIONAL,
    CK_ELIF,
    CK_HANDLER,
    CK_IF,
    CK_LOOP,
    CK_SWITCH,
    LOOP_COMPREHENSION,
    ControlNode,
)

CONVENTION = "nesting/1"
NESTING_KINDS = frozenset({CK_IF, CK_LOOP, CK_SWITCH, CK_HANDLER, CK_CONDITIONAL})
_ELSE_INDEX = 1 + 1


def nesting_depth(tree: ControlNode) -> int:
    deepest = 0
    stack: list[tuple[ControlNode, int]] = [(tree, 0)]
    while len(stack) > 0:
        node, depth = stack.pop()
        kind = node.kind
        if kind == CK_LOOP and node.label == LOOP_COMPREHENSION:
            for child in node.children:
                stack.append((child, depth))
        elif kind in NESTING_KINDS or kind == CK_ELIF:
            inner = depth + 1
            if inner > deepest:
                deepest = inner
            for index, child in enumerate(node.children):
                if child.kind == CK_ELIF and index >= _ELSE_INDEX:
                    stack.append((child, depth))
                else:
                    stack.append((child, inner))
        else:
            for child in node.children:
                stack.append((child, depth))
    return deepest
