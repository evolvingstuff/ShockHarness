"""Guardrail facts for JavaScript (H3; consumed by EXC004, STUB001, BOOL001 and IMPORT001
in rules/guardrails.py). JavaScript has no removable ``assert`` statement, so ASSERT001
does not apply.

Syntax only:

* **finally exits**: ``return`` anywhere in a ``finally`` clause; an unlabeled ``break``
  not inside a loop or ``switch`` of its own within the clause, an unlabeled ``continue``
  not inside a loop of its own, and a labeled ``break``/``continue`` whose label is not
  declared inside the clause. Nested functions, arrows, methods and classes are skipped;
* **placeholders**: ``throw new SomeError("not implemented")`` where the constructor name
  ends in ``Error`` and the first argument is a string saying "not implemented", "not yet
  implemented", "unimplemented" or starting with "TODO" (any case);
* **Boolean arguments**: a ``true``/``false`` literal passed positionally to a call with
  more than one argument and no spread;
* **import-time calls**: calls in the module's top level, class static blocks and static
  field initializers; not inside functions, arrows, methods or instance field initializers.
"""

import re

from tree_sitter import Node

from shockharness.constants import EVIDENCE_MAX_CHARS
from shockharness.ir.javascript_catches import node_span, node_text
from shockharness.ir.model import (
    EXIT_BREAK,
    EXIT_CONTINUE,
    EXIT_RETURN,
    MODULE_SCOPE,
    PLACEHOLDER_NOT_IMPLEMENTED,
    BooleanArgument,
    FinallyExit,
    GuardrailFacts,
    ImportTimeCall,
    Placeholder,
)
from shockharness.source import SourceText

SCOPES = frozenset(
    {
        "function_declaration",
        "generator_function_declaration",
        "function_expression",
        "function",
        "generator_function",
        "arrow_function",
        "method_definition",
        "class_declaration",
        "class",
    }
)
FUNCTION_NAMES = frozenset({"function_declaration", "generator_function_declaration"})
LOOPS = frozenset({"for_statement", "for_in_statement", "while_statement", "do_statement"})
SWITCH = "switch_statement"
LABELED = "labeled_statement"
LABEL = "statement_identifier"
TRY = "try_statement"
FINALIZER = "finalizer"
THROW = "throw_statement"
NEW = "new_expression"
CALL = "call_expression"
MEMBER = "member_expression"
IDENTIFIER = "identifier"
PROPERTY = "property_identifier"
STRING = "string"
STRING_FRAGMENT = "string_fragment"
BOOLEANS = frozenset({"true", "false"})
SPREAD = "spread_element"
COMMENT = "comment"
FIELD = "field_definition"
STATIC = "static"
ERROR_SUFFIX = "Error"
NOT_IMPLEMENTED = re.compile(r"\bnot\s+(yet\s+)?implemented\b|\bunimplemented\b|^\s*todo\b", re.I)


def _excerpt(node: Node) -> str:
    text = " ".join(node_text(node).split())
    if len(text) > EVIDENCE_MAX_CHARS:
        return text[:EVIDENCE_MAX_CHARS] + "..."
    return text


def dotted_callee(node: Node) -> str | None:
    """``a.b.c`` for identifiers and non-computed member chains, else None."""
    if node.type == IDENTIFIER:
        return node_text(node)
    if node.type != MEMBER:
        return None
    obj = node.child_by_field_name("object")
    prop = node.child_by_field_name("property")
    if obj is None or prop is None or prop.type != PROPERTY:
        return None
    base = dotted_callee(obj)
    if base is None:
        return None
    return f"{base}.{node_text(prop)}"


def _arguments(call: Node) -> list[Node]:
    arguments = call.child_by_field_name("arguments")
    if arguments is None:
        return []
    return [child for child in arguments.named_children if child.type != COMMENT]


# -- finally exits ------------------------------------------------------------------------


def _label(node: Node) -> str | None:
    labels = [child for child in node.named_children if child.type == LABEL]
    if len(labels) == 0:
        return None
    return node_text(labels[0])


class _FinallyScan:
    def __init__(self, source: SourceText) -> None:
        self.source = source
        self.exits: list[FinallyExit] = []

    def scan(self, node: Node, labels: frozenset[str], *, in_loop: bool, in_switch: bool) -> None:
        if node.type in SCOPES:
            return
        if node.type == "return_statement":
            self.exits.append(FinallyExit(EXIT_RETURN, node_span(self.source, node)))
        elif node.type in ("break_statement", "continue_statement"):
            self._jump(node, labels, in_loop=in_loop, in_switch=in_switch)
        inner_loop = in_loop or node.type in LOOPS
        inner_switch = in_switch or node.type == SWITCH
        inner_labels = labels
        if node.type == LABELED:
            declared = _label(node)
            if declared is not None:
                inner_labels = labels | {declared}
        for child in node.children:
            self.scan(child, inner_labels, in_loop=inner_loop, in_switch=inner_switch)

    def _jump(self, node: Node, labels: frozenset[str], *, in_loop: bool, in_switch: bool) -> None:
        kind = EXIT_BREAK if node.type == "break_statement" else EXIT_CONTINUE
        label = _label(node)
        if label is not None:
            leaves = label not in labels
        elif kind == EXIT_BREAK:
            leaves = not (in_loop or in_switch)
        else:
            leaves = not in_loop
        if leaves:
            self.exits.append(FinallyExit(kind, node_span(self.source, node)))


# -- placeholders -------------------------------------------------------------------------


def _string_value(node: Node) -> str | None:
    if node.type != STRING:
        return None
    return "".join(node_text(c) for c in node.named_children if c.type == STRING_FRAGMENT)


def _not_implemented(throw: Node) -> bool:
    created = [child for child in throw.named_children if child.type == NEW]
    if len(created) != 1:
        return False
    constructor = created[0].child_by_field_name("constructor")
    if constructor is None or not node_text(constructor).endswith(ERROR_SUFFIX):
        return False
    arguments = _arguments(created[0])
    if len(arguments) == 0:
        return False
    message = _string_value(arguments[0])
    return message is not None and NOT_IMPLEMENTED.search(message) is not None


def _scope_name(node: Node, scope: str) -> str:
    if node.type not in FUNCTION_NAMES and node.type != "method_definition":
        return scope
    name = node.child_by_field_name("name")
    if name is None:
        return scope
    if scope == MODULE_SCOPE:
        return node_text(name)
    return f"{scope}.{node_text(name)}"


# -- import-time calls --------------------------------------------------------------------


def _runs_at_import(node: Node) -> bool:
    """False for code that runs later: function bodies, methods, instance fields."""
    if node.type in SCOPES and node.type not in ("class_declaration", "class"):
        return False
    if node.type == FIELD:
        return any(child.type == STATIC for child in node.children)
    return True


def collect_javascript_guardrails(source: SourceText, root: Node) -> GuardrailFacts:
    finally_scan = _FinallyScan(source)
    placeholders: list[Placeholder] = []
    booleans: list[BooleanArgument] = []
    stack: list[tuple[Node, str]] = [(root, MODULE_SCOPE)]
    while len(stack) > 0:
        node, scope = stack.pop()
        inner = _scope_name(node, scope)
        if node.type == TRY:
            finalizer = node.child_by_field_name(FINALIZER)
            if finalizer is not None:
                for child in finalizer.named_children:
                    finally_scan.scan(child, frozenset(), in_loop=False, in_switch=False)
        elif node.type == THROW and _not_implemented(node):
            placeholders.append(
                Placeholder(
                    PLACEHOLDER_NOT_IMPLEMENTED, _excerpt(node), scope, node_span(source, node)
                )
            )
        elif node.type == CALL:
            booleans.extend(_booleans(source, node))
        for child in reversed(node.children):
            stack.append((child, inner))
    return GuardrailFacts(
        finally_exits=tuple(sorted(finally_scan.exits, key=lambda f: f.span)),
        placeholders=tuple(sorted(placeholders, key=lambda p: (p.span, p.kind))),
        asserts=(),
        boolean_arguments=tuple(sorted(booleans, key=lambda b: (b.span, b.position))),
        import_time_calls=tuple(
            sorted(_import_time(source, root), key=lambda c: (c.span, c.callee))
        ),
    )


def _booleans(source: SourceText, call: Node) -> list[BooleanArgument]:
    arguments = _arguments(call)
    function = call.child_by_field_name("function")
    if len(arguments) <= 1 or function is None:
        return []
    if any(argument.type == SPREAD for argument in arguments):
        return []
    callee = dotted_callee(function)
    if callee is None:
        return []
    return [
        BooleanArgument(callee, position, _excerpt(call), node_span(source, argument))
        for position, argument in enumerate(arguments)
        if argument.type in BOOLEANS
    ]


def _import_time(source: SourceText, root: Node) -> list[ImportTimeCall]:
    found: list[ImportTimeCall] = []
    stack: list[Node] = list(root.children)
    while len(stack) > 0:
        node = stack.pop()
        if not _runs_at_import(node):
            continue
        if node.type == CALL:
            function = node.child_by_field_name("function")
            callee = None
            if function is not None:
                callee = dotted_callee(function)
            if callee is not None:
                found.append(ImportTimeCall(callee, _excerpt(node), node_span(source, node)))
        stack.extend(node.children)
    return found
