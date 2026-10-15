"""Cognitive complexity, convention ``cognitive/1``.

Implemented from the public description of cognitive complexity (structural
increments, nesting increments, and increments for interruptions of linear
flow). It is **not** a SonarSource score: the published algorithm leaves
several constructs to each implementation, and this convention measures
nested functions separately (see ``docs/complexity.md``). The rules:

* ``+1`` for each ``if``, loop, ``match``/``switch``, ``except``/``catch``
  handler and conditional expression, **plus the current nesting level**;
  each of these also raises the nesting level for everything inside it
  (its condition included).
* ``+1`` with no nesting increment for each ``elif`` / ``else if``, each
  ``else`` (of an ``if`` and of a Python loop) and a Python ``try/else``
  body. Their contents are nested one level deeper than the construct they
  belong to, exactly like the ``then`` branch.
* ``+1`` for each maximal run of one short-circuit operator in source order
  (``a and b and c or d`` is two runs; ``a && (b || c) && d`` is three),
  ``+1`` per logical assignment (``||=``, ``&&=``, ``??=``), ``+1`` for a
  direct recursive call, ``+1`` for a labeled ``break``/``continue``.
* ``try`` bodies, ``finally`` bodies, ``with`` blocks, parentheses and plain
  blocks add nothing and do not nest. ``case`` arms add nothing beyond the
  ``switch``.
* A nested function, lambda, arrow or class is a separate unit: nothing of
  its body is counted here and it does not raise the nesting level of its
  surroundings.
* A comprehension belongs to the unit that contains it. Its ``for`` clauses
  add nothing and do not nest (a generator expression is linear, idiomatic
  code); each of its ``if`` clauses counts as an ``if`` (``+1`` plus nesting).
"""

from shockharness.ir.model import (
    CK_CONDITIONAL,
    CK_ELIF,
    CK_EXPR,
    CK_HANDLER,
    CK_IF,
    CK_JUMP,
    CK_LOOP,
    CK_RECURSION,
    CK_SWITCH,
    CK_TRY_ELSE,
    LOOP_COMPREHENSION,
    ControlNode,
)

CONVENTION = "cognitive/1"
STRUCTURAL_KINDS = frozenset({CK_SWITCH, CK_HANDLER, CK_CONDITIONAL})
# IF/ELIF/LOOP children: condition, main block, then an optional else part.
_ELSE_INDEX = 1 + 1


def cognitive(tree: ControlNode) -> int:
    total = 0
    # (node, nesting level in force at the node, increment taken when the node is reached)
    stack: list[tuple[ControlNode, int, int]] = [(tree, 0, 0)]
    while len(stack) > 0:
        node, nesting, bonus = stack.pop()
        total += bonus
        kind = node.kind
        if kind == CK_LOOP and node.label == LOOP_COMPREHENSION:
            # A comprehension ``for`` clause is linear, idiomatic code: its ``if`` clauses
            # count, the clause itself does not and does not nest.
            for child in node.children:
                stack.append((child, nesting, 0))
        elif kind in (CK_IF, CK_ELIF, CK_LOOP):
            if kind == CK_ELIF:
                total += 1
            else:
                total += 1 + nesting
            inner = nesting + 1
            for index, child in enumerate(node.children):
                if index < _ELSE_INDEX:
                    stack.append((child, inner, 0))
                elif child.kind == CK_ELIF:
                    stack.append((child, nesting, 0))
                else:
                    stack.append((child, inner, 1))
        elif kind in STRUCTURAL_KINDS:
            total += 1 + nesting
            for child in node.children:
                stack.append((child, nesting + 1, 0))
        elif kind == CK_EXPR:
            total += node.sequences
            for child in node.children:
                stack.append((child, nesting, 0))
        elif kind in (CK_RECURSION, CK_JUMP):
            total += 1
        elif kind == CK_TRY_ELSE:
            total += 1
            for child in node.children:
                stack.append((child, nesting + 1, 0))
        else:
            for child in node.children:
                stack.append((child, nesting, 0))
    return total
