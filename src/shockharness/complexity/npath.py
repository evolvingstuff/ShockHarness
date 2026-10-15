"""NPath estimate, convention ``npath/1``: a bounded count of acyclic paths.

Computed bottom-up on the control tree with every intermediate value clamped
to ``complexity.npath_cap``; nothing is ever enumerated, so the cost is linear
in the tree. The value is an estimate in the sense of the original NPath
definition (infeasible paths are counted, loops count as one branch):

* a block is the product of its statements (an empty block is 1);
* an expression is ``1 + operators`` (each short-circuit operator doubles the
  ways through it) times the product of any conditionals nested in it;
* ``if`` / ``elif``: ``(condition - 1) + then + else`` where a missing ``else``
  counts 1; a loop is the same with its body, a Python loop ``else`` taking
  the place of ``else``; a comprehension ``for`` clause is
  ``(iterable - 1) + body`` (no extra zero-iteration path: it is an
  expression), its ``if`` clauses count like ``if``;
* ``try``: ``body * try_else + sum(handlers)``, then ``* finally``;
* ``match`` / ``switch``: ``(subject - 1) + sum(arms) + 1`` when there is no
  default arm (``+ 0`` with one); an arm is ``(guard - 1) + body``;
* a conditional expression: ``(condition - 1) + then + else``;
* a recursive call or a labeled jump counts 1.

A result at or above the cap is reported as ``>= cap`` with
``saturated = true``; the exact number is never claimed.
"""

from shockharness.ir.model import (
    CASE_DEFAULT,
    CK_CASE,
    CK_CONDITIONAL,
    CK_ELIF,
    CK_EXPR,
    CK_FINALLY,
    CK_HANDLER,
    CK_IF,
    CK_LOOP,
    CK_SWITCH,
    CK_TRY,
    CK_TRY_ELSE,
    LOOP_COMPREHENSION,
    ControlNode,
)

CONVENTION = "npath/1"
_ELSE_INDEX = 1 + 1


def _branching(values: list[int]) -> int:
    """``(condition - 1) + main + else`` for IF/ELIF/LOOP/CONDITIONAL children."""
    condition = values[0]
    main = values[1]
    alternative = values[_ELSE_INDEX] if len(values) > _ELSE_INDEX else 1
    return (condition - 1) + main + alternative


def _combine(node: ControlNode, values: list[int]) -> int:
    kind = node.kind
    if kind == CK_EXPR:
        return (1 + node.operators) * _product(values)
    if kind == CK_LOOP and node.label == LOOP_COMPREHENSION:
        # an expression-level loop: its clauses multiply, no zero-iteration path is added
        return (values[0] - 1) + values[1]
    if kind in (CK_IF, CK_ELIF, CK_LOOP, CK_CONDITIONAL):
        return _branching(values)
    if kind == CK_TRY:
        body = values[0]
        handlers = 0
        try_else = 1
        finally_paths = 1
        for child, value in zip(node.children[1:], values[1:], strict=True):
            if child.kind == CK_HANDLER:
                handlers += value
            elif child.kind == CK_TRY_ELSE:
                try_else = value
            elif child.kind == CK_FINALLY:
                finally_paths = value
        return (body * try_else + handlers) * finally_paths
    if kind == CK_SWITCH:
        subject = values[0]
        arms = sum(values[1:])
        has_default = any(child.label == CASE_DEFAULT for child in node.children)
        return (subject - 1) + arms + (0 if has_default else 1)
    if kind == CK_CASE:
        return (values[0] - 1) + values[1]
    if len(values) == 0:
        return 1
    return _product(values)


def _product(values: list[int]) -> int:
    result = 1
    for value in values:
        result *= value
    return result


def npath(tree: ControlNode, cap: int) -> tuple[int, bool]:
    """``(value clamped to cap, saturated)``."""
    results: dict[int, int] = {}
    stack: list[tuple[ControlNode, bool]] = [(tree, False)]
    while len(stack) > 0:
        node, ready = stack.pop()
        if not ready:
            stack.append((node, True))
            for child in node.children:
                stack.append((child, False))
            continue
        values = [results[id(child)] for child in node.children]
        results[id(node)] = min(_combine(node, values), cap)
    value = results[id(tree)]
    return value, value >= cap
