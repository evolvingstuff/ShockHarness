"""Cyclomatic complexity, convention ``cyclomatic/1``.

``1 + `` the number of decision points in the unit's control tree:

* each ``if``, ``elif`` / ``else if`` (an ``else`` adds nothing);
* each loop (``for``, ``while``, ``do``, ``for..in``/``of``, each comprehension
  ``for`` clause) and each ``if`` clause of a comprehension;
* each ``except`` / ``catch`` handler (``finally`` and ``try/else`` add nothing);
* each ``case`` arm of ``match`` / ``switch`` other than the default arm;
* each conditional expression (``a if c else b``, ``c ? a : b``);
* with ``complexity.cyclomatic_counts_boolean_operators = true`` (the default),
  each binary short-circuit operator (``and``/``or``, ``&&``/``||``/``??``,
  ``&&=``/``||=``/``??=``). Optional chaining (``?.``) is never counted.

Nested units are not included: they have their own number.
"""

from shockharness.ir.model import (
    CASE_DEFAULT,
    CK_CASE,
    CK_CONDITIONAL,
    CK_ELIF,
    CK_EXPR,
    CK_HANDLER,
    CK_IF,
    CK_LOOP,
    ControlNode,
)

CONVENTION = "cyclomatic/1"
BASE = 1
DECISION_KINDS = frozenset({CK_IF, CK_ELIF, CK_LOOP, CK_HANDLER, CK_CONDITIONAL})


def cyclomatic(tree: ControlNode, count_boolean_operators: bool) -> int:
    total = BASE
    stack = [tree]
    while len(stack) > 0:
        node = stack.pop()
        if node.kind in DECISION_KINDS or (node.kind == CK_CASE and node.label != CASE_DEFAULT):
            total += 1
        elif node.kind == CK_EXPR and count_boolean_operators:
            total += node.operators
        stack.extend(node.children)
    return total
