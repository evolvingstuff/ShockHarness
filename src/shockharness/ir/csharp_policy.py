"""Module-state, start-up, process, predicate and import facts for C# (milestone G3, part
two).

* STATE001: a ``static`` field that is neither ``readonly`` nor ``const`` is process-wide
  mutable state, C#'s module global; it is a binding, and the functions that assign it
  are its writers (``Instance = this;`` included).
* IMPORT001: what runs when a type is first used, C#'s import time: calls in ``static``
  field initializers and in static constructors.
* PROCESS001: calls whose last name is a process API (``Process.Start``, Godot's
  ``OS.Execute``, ``OS.CreateProcess``, ``OS.ExecuteWithPipe``), with whether the
  command is built from data, whether the result is dropped, returned, or its
  ``ExitCode`` read in the same function.
* STUB003: a method named as a check (``IsReady``, ``CanInteract``, ``Validate``) whose
  whole body returns ``true``, and every class with its bases.
* STUB002: ``using`` directives, as module imports of their namespace.
"""

import re

from tree_sitter import Node

from shockharness.ir.csharp_defaults import argument_values
from shockharness.ir.csharp_functions import FUNCTION_TYPES, TYPE_DECLARATIONS, scope_for
from shockharness.ir.csharp_nodes import Field, Kind
from shockharness.ir.csharp_receivers import simple_type
from shockharness.ir.csharp_strings import literal_text
from shockharness.ir.model import (
    BINDING_VARIABLE,
    IMPORT_MODULE,
    MODULE_SCOPE,
    NO_CATALOG,
    NO_GUARDRAILS,
    CatalogFacts,
    ClassDecl,
    ConstantPredicate,
    GuardrailFacts,
    ImportFact,
    ImportTimeCall,
    ModuleBinding,
    ProcessCall,
)
from shockharness.ir.tree_sitter_common import node_span, node_text
from shockharness.source import SourceText

STATIC = "static"
FIXED = frozenset({"readonly", "const"})
PROCESS_APIS = frozenset({"Start", "Execute", "CreateProcess", "ExecuteWithPipe"})
SHELLS = frozenset({"cmd", "cmd.exe", "sh", "bash", "/bin/sh", "/bin/bash", "powershell", "pwsh"})
SHELL_FLAGS = frozenset({"-c", "/c", "/C", "-Command"})
EXIT_CODE = "ExitCode"
CHECK_ABSENT = "absent"
PREDICATE = re.compile(
    r"^(Is|Has|Can|Should)[A-Z_]|^(Check|Validate|Verify|Authori[sz]e|Authenticate|Allow)"
)
TRUE = "true"
USING = "using_directive"
TEXT_LIMIT = 120


def _modifiers(node: Node) -> frozenset[str]:
    return frozenset(node_text(c) for c in node.children if c.type == Kind.MODIFIER)


def _text(node: Node) -> str:
    return " ".join(node_text(node).split())[:TEXT_LIMIT]


def _callee(call: Node) -> str:
    """The callee as written (``Process.Start``, ``OS.Execute``, ``new Process``)."""
    if call.type == Kind.OBJECT_CREATION_EXPRESSION:
        typed = call.child_by_field_name(Field.TYPE)
        if typed is None:
            return ""
        return "new " + node_text(typed)
    function = call.child_by_field_name(Field.FUNCTION)
    if function is None:
        return ""
    return node_text(function).split("<", 1)[0]


# -- STATE001 and IMPORT001 -------------------------------------------------------------------


def _static_fields(node: Node, source: SourceText) -> list[ModuleBinding]:
    modifiers = _modifiers(node)
    if STATIC not in modifiers or len(modifiers & FIXED) > 0:
        return []
    bindings: list[ModuleBinding] = []
    for declaration in node.named_children:
        if declaration.type != Kind.VARIABLE_DECLARATION:
            continue
        for declarator in declaration.named_children:
            name = declarator.child_by_field_name(Field.NAME)
            if declarator.type == Kind.VARIABLE_DECLARATOR and name is not None:
                span = node_span(source, name)
                bindings.append(
                    ModuleBinding(node_text(name), BINDING_VARIABLE, mutable=True, span=span)
                )
    return bindings


def _calls_in(node: Node, source: SourceText) -> list[ImportTimeCall]:
    """Every call under ``node``, lambdas and local functions excluded (they run later)."""
    found: list[ImportTimeCall] = []
    stack = [node]
    while len(stack) > 0:
        current = stack.pop()
        if current.type in FUNCTION_TYPES:
            continue
        if current.type == Kind.INVOCATION_EXPRESSION:
            found.append(
                ImportTimeCall(_callee(current), _text(current), node_span(source, current))
            )
        stack.extend(current.children)
    return found


def _startup_calls(node: Node, source: SourceText) -> list[ImportTimeCall]:
    """Calls in a ``static`` field's initializers or a static constructor's body."""
    if node.type == Kind.FIELD_DECLARATION and STATIC in _modifiers(node):
        return [
            c
            for d in node.named_children
            if d.type == Kind.VARIABLE_DECLARATION
            for c in _calls_in(d, source)
        ]
    if node.type == Kind.CONSTRUCTOR_DECLARATION and STATIC in _modifiers(node):
        body = node.child_by_field_name(Field.BODY)
        if body is None:
            return []
        return _calls_in(body, source)
    return []


# -- PROCESS001 -------------------------------------------------------------------------------


def _is_built(argument: Node) -> bool:
    """A command built from data: an interpolated string with holes, or a concatenation."""
    if argument.type == Kind.INTERPOLATED_STRING_EXPRESSION:
        return any(c.type == "interpolation" for c in argument.named_children)
    if argument.type == Kind.BINARY_EXPRESSION:
        operator = argument.child_by_field_name(Field.OPERATOR)
        return operator is not None and node_text(operator) == "+"
    return False


def _shell(arguments: list[Node]) -> bool:
    """``Process.Start("sh", "-c ...")``, ``OS.Execute("cmd", new[] { "/c", ... })``."""
    if len(arguments) == 0:
        return False
    program = literal_text(arguments[0])
    if program is None or program not in SHELLS:
        return False
    rest = " ".join(node_text(a) for a in arguments[1:])
    return any(flag in rest for flag in SHELL_FLAGS)


def _process_call(call: Node, function: Node, source: SourceText) -> ProcessCall | None:
    callee = _callee(call)
    _receiver, _dot, last = callee.rpartition(".")
    if last not in PROCESS_APIS:
        return None
    arguments = argument_values(call)
    statement = call.parent
    returned = statement is not None and statement.type in (
        Kind.RETURN_STATEMENT,
        Kind.ARROW_EXPRESSION_CLAUSE,
    )
    return ProcessCall(
        callee=callee,
        text=_text(call),
        shell=_shell(arguments),
        interpolated=any(_is_built(a) for a in arguments),
        check=CHECK_ABSENT,
        discarded=statement is not None and statement.type == Kind.EXPRESSION_STATEMENT,
        status_read=EXIT_CODE in node_text(function),
        returned=returned,
        span=node_span(source, call),
    )


# -- STUB003 ----------------------------------------------------------------------------------


def _returns_true(method: Node) -> bool:
    """The method's whole body is ``=> true`` or ``{ return true; }``."""
    body = method.child_by_field_name(Field.BODY)
    if body is None:
        return False
    parts = _parts(body)
    if body.type != Kind.ARROW_EXPRESSION_CLAUSE:
        if len(parts) != 1 or parts[0].type != Kind.RETURN_STATEMENT:
            return False
        parts = _parts(parts[0])
    return len(parts) == 1 and node_text(parts[0]) == TRUE


def _parts(node: Node) -> list[Node]:
    return [c for c in node.named_children if c.type != Kind.COMMENT]


# -- the walk ---------------------------------------------------------------------------------


class _Collector:
    def __init__(self, source: SourceText) -> None:
        self.source = source
        self.bindings: list[ModuleBinding] = []
        self.startup: list[ImportTimeCall] = []
        self.processes: list[ProcessCall] = []
        self.predicates: list[ConstantPredicate] = []
        self.classes: list[ClassDecl] = []
        self.imports: list[ImportFact] = []

    def visit(self, node: Node, scope: str, function: Node | None) -> None:
        kind = node.type
        if kind == Kind.FIELD_DECLARATION:
            self.bindings.extend(_static_fields(node, self.source))
        self.startup.extend(_startup_calls(node, self.source))
        if (
            kind in (Kind.INVOCATION_EXPRESSION, Kind.OBJECT_CREATION_EXPRESSION)
            and function is not None
        ):
            found = _process_call(node, function, self.source)
            if found is not None:
                self.processes.append(found)
        elif kind == Kind.METHOD_DECLARATION:
            self._predicate(node, scope)
        elif kind in TYPE_DECLARATIONS and kind != Kind.ENUM_DECLARATION:
            self._class(node, scope)
        elif kind == USING:
            self._using(node)

    def _predicate(self, method: Node, scope: str) -> None:
        name = method.child_by_field_name(Field.NAME)
        if name is None or PREDICATE.match(node_text(name)) is None or not _returns_true(method):
            return
        owner = scope if scope != MODULE_SCOPE else None
        self.predicates.append(
            ConstantPredicate(node_text(name), owner, node_span(self.source, method))
        )

    def _class(self, declaration: Node, scope: str) -> None:
        bases = tuple(
            typed
            for child in declaration.named_children
            if child.type == "base_list"
            for typed in (simple_type(b) for b in child.named_children)
            if typed is not None
        )
        span = node_span(self.source, declaration)
        self.classes.append(ClassDecl(scope_for(declaration, scope), bases, span))

    def _using(self, directive: Node) -> None:
        names = [
            c for c in directive.named_children if c.type in (Kind.IDENTIFIER, Kind.QUALIFIED_NAME)
        ]
        if len(names) == 0:
            return
        namespace = node_text(names[len(names) - 1])
        span = node_span(self.source, directive)
        self.imports.append(ImportFact(span, IMPORT_MODULE, namespace, 0, ()))


def collect_csharp_policy(
    source: SourceText, root: Node, booleans: GuardrailFacts
) -> tuple[tuple[ModuleBinding, ...], GuardrailFacts, CatalogFacts, tuple[ImportFact, ...]]:
    """The bindings, the guardrail facts (``booleans`` holds the placeholders and Boolean
    arguments already read), the catalog facts and the imports."""
    collector = _Collector(source)
    stack: list[tuple[Node, str, Node | None]] = [(root, MODULE_SCOPE, None)]
    while len(stack) > 0:
        node, scope, function = stack.pop()
        collector.visit(node, scope, function)
        inner = scope_for(node, scope)
        holder = node if node.type in FUNCTION_TYPES else function
        stack.extend((child, inner, holder) for child in reversed(node.children))
    guardrails = GuardrailFacts(
        finally_exits=NO_GUARDRAILS.finally_exits,
        placeholders=booleans.placeholders,
        asserts=NO_GUARDRAILS.asserts,
        boolean_arguments=booleans.boolean_arguments,
        import_time_calls=tuple(sorted(collector.startup, key=lambda c: c.span)),
        element_guards=NO_GUARDRAILS.element_guards,
        early_publications=NO_GUARDRAILS.early_publications,
        unlocked_reads=NO_GUARDRAILS.unlocked_reads,
    )
    catalog = CatalogFacts(
        process_calls=tuple(sorted(collector.processes, key=lambda c: c.span)),
        sleeps=NO_CATALOG.sleeps,
        retries=NO_CATALOG.retries,
        batch_loops=NO_CATALOG.batch_loops,
        type_escapes=NO_CATALOG.type_escapes,
        constant_predicates=tuple(sorted(collector.predicates, key=lambda p: p.span)),
        classes=tuple(collector.classes),
    )
    return tuple(collector.bindings), guardrails, catalog, tuple(collector.imports)
