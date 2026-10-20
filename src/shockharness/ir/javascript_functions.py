"""Function facts for JavaScript: every unit's control tree, size, calls and writes.

Units are the program, each class body (field initializers and static blocks),
each function declaration or expression, generator, arrow function and method.
The traversal is iterative and stops at nested units, exactly as the Python
adapter does, so the two languages produce the same tree for equivalent code.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from tree_sitter import Node

from shockharness.constants import FIRST_COLUMN, FIRST_LINE
from shockharness.ir.javascript_catches import (
    FIELD_DEFINITIONS,
    TYPED_PARAMETERS,
    is_this_parameter,
    node_span,
    node_text,
    parameter_parts,
    scope_for,
)
from shockharness.ir.javascript_nodes import Field, Kind
from shockharness.ir.lines import logical_line_count
from shockharness.ir.model import (
    BINDING_CLASS,
    BINDING_FUNCTION,
    BINDING_IMPORT,
    BINDING_VARIABLE,
    CALL_ARGUMENT,
    CALL_ATTRIBUTE,
    CALL_DYNAMIC,
    CALL_NAME,
    CALL_NEW,
    CASE_DEFAULT,
    CK_BLOCK,
    CK_CASE,
    CK_CONDITIONAL,
    CK_ELIF,
    CK_EXPR,
    CK_FINALLY,
    CK_HANDLER,
    CK_IF,
    CK_JUMP,
    CK_LOOP,
    CK_RECURSION,
    CK_SWITCH,
    CK_TRY,
    IMPORT_DYNAMIC,
    IMPORT_MODULE,
    IMPORT_NAMES,
    IMPORT_REEXPORT,
    LOOP_DO,
    LOOP_FOR,
    LOOP_WHILE,
    MODULE_SCOPE,
    UNIT_ARROW,
    UNIT_CLASS,
    UNIT_FUNCTION,
    UNIT_METHOD,
    UNIT_MODULE,
    WRITE_ASSIGN,
    WRITE_MUTATE,
    CallSite,
    Comment,
    ControlNode,
    FunctionFact,
    ImportFact,
    ModuleBinding,
    Span,
)
from shockharness.ir.python_functions import count_runs, nested_line_exclusions
from shockharness.ir.tree_sitter_common import (
    first_line,
    root_identifier,
    unit_span,
    unwrap_parentheses,
)
from shockharness.source import SourceText

# The member and element access kinds an access chain is made of.
MEMBER_CHAINS = (Kind.MEMBER_EXPRESSION, Kind.SUBSCRIPT_EXPRESSION)
FUNCTION_TYPES = frozenset(
    {
        Kind.FUNCTION_DECLARATION,
        Kind.GENERATOR_FUNCTION_DECLARATION,
        Kind.FUNCTION_EXPRESSION,
        Kind.GENERATOR_FUNCTION,
        Kind.ARROW_FUNCTION,
        Kind.METHOD_DEFINITION,
    }
)
GENERATOR_TYPES = frozenset({Kind.GENERATOR_FUNCTION_DECLARATION, Kind.GENERATOR_FUNCTION})
CLASS_TYPES = frozenset({Kind.CLASS_DECLARATION, Kind.ABSTRACT_CLASS_DECLARATION, Kind.CLASS})
# Units that are expressions: their first and last lines usually carry the parent's code too.
EXPRESSION_UNIT_TYPES = frozenset(
    {Kind.ARROW_FUNCTION, Kind.FUNCTION_EXPRESSION, Kind.GENERATOR_FUNCTION, Kind.CLASS}
)
UNIT_TYPES = FUNCTION_TYPES | CLASS_TYPES
LOOP_STATEMENTS = frozenset(
    {Kind.FOR_STATEMENT, Kind.FOR_IN_STATEMENT, Kind.WHILE_STATEMENT, Kind.DO_STATEMENT}
)
NESTED_DECLARATIONS = frozenset(
    {Kind.FUNCTION_DECLARATION, Kind.GENERATOR_FUNCTION_DECLARATION}
) | (CLASS_TYPES - {Kind.CLASS})
STATEMENT_TYPES = frozenset(
    {
        Kind.EXPRESSION_STATEMENT,
        Kind.LEXICAL_DECLARATION,
        Kind.VARIABLE_DECLARATION,
        Kind.IF_STATEMENT,
        Kind.FOR_STATEMENT,
        Kind.FOR_IN_STATEMENT,
        Kind.WHILE_STATEMENT,
        Kind.DO_STATEMENT,
        Kind.TRY_STATEMENT,
        Kind.SWITCH_STATEMENT,
        Kind.RETURN_STATEMENT,
        Kind.THROW_STATEMENT,
        Kind.BREAK_STATEMENT,
        Kind.CONTINUE_STATEMENT,
        Kind.LABELED_STATEMENT,
        Kind.WITH_STATEMENT,
        Kind.DEBUGGER_STATEMENT,
        Kind.EXPORT_STATEMENT,
        Kind.IMPORT_STATEMENT,
        Kind.CLASS_DECLARATION,
        Kind.ABSTRACT_CLASS_DECLARATION,
        Kind.FUNCTION_DECLARATION,
        Kind.GENERATOR_FUNCTION_DECLARATION,
        Kind.STATEMENT_BLOCK,
    }
)
BOOLEAN_OPERATORS = frozenset({"&&", "||", "??"})
LOGICAL_ASSIGNMENTS = frozenset({"&&=", "||=", "??="})
MUTATING_METHODS = frozenset(
    {
        "push",
        "pop",
        "shift",
        "unshift",
        "splice",
        "sort",
        "reverse",
        "fill",
        "copyWithin",
        "set",
        "delete",
        "clear",
        "add",
    }
)
MUTABLE_CONSTRUCTORS = frozenset({"Map", "Set", "WeakMap", "WeakSet", "Array", "Object"})
DECLARATION_TYPES = frozenset({Kind.LEXICAL_DECLARATION, Kind.VARIABLE_DECLARATION})
PATTERN_SKIP = frozenset({Kind.COMMENT, Kind.PROPERTY_IDENTIFIER})
RECEIVER = "this"
REQUIRE = "require"
OBJECT_ASSIGN = "Object.assign"
IMPORT_CALL = Kind.IMPORT
STRING = Kind.STRING
STRING_FRAGMENT = Kind.STRING_FRAGMENT
DEFAULT_EXPORT = "default"
STAR = "*"

_T_STATEMENTS = "statements"
_T_STATEMENT = "statement"
_T_EXPRESSION = "expression"


@dataclass
class Builder:
    kind: str
    label: str
    children: list["Builder"]
    operators: int
    sequences: int
    labeled: bool
    frozen: ControlNode | None


def new_builder(kind: str, label: str) -> Builder:
    return Builder(kind, label, [], 0, 0, labeled=False, frozen=None)


@dataclass(frozen=True)
class UnitInfo:
    node: Node
    name: str
    kind: str
    class_name: str | None


def _is_async(node: Node) -> bool:
    return any(child.type == "async" for child in node.children if not child.is_named)


def _unit_kind(node: Node) -> str:
    if node.type == Kind.PROGRAM:
        return UNIT_MODULE
    if node.type in CLASS_TYPES:
        return UNIT_CLASS
    if node.type == Kind.ARROW_FUNCTION:
        return UNIT_ARROW
    if node.type == Kind.METHOD_DEFINITION:
        return UNIT_METHOD
    return UNIT_FUNCTION


def discover_units(root: Node) -> list[UnitInfo]:
    units: list[UnitInfo] = [UnitInfo(root, MODULE_SCOPE, UNIT_MODULE, None)]
    stack: list[tuple[Node, str, str | None]] = [(root, MODULE_SCOPE, None)]
    while len(stack) > 0:
        node, scope, class_name = stack.pop()
        child_scope = scope
        child_class = class_name
        if node.is_named and node.type in UNIT_TYPES:
            child_scope = scope_for(node, scope)
            units.append(UnitInfo(node, child_scope, _unit_kind(node), class_name))
            child_class = child_scope if node.type in CLASS_TYPES else None
        for child in reversed(node.children):
            stack.append((child, child_scope, child_class))
    units.sort(key=lambda u: (u.node.start_byte, -u.node.end_byte))
    return units


def string_value(node: Node) -> str | None:
    """The text of a plain string literal (``"a"``, ``'a'``), or ``None`` for anything else."""
    if node.type != STRING:
        return None
    fragments = [c for c in node.named_children if c.type == STRING_FRAGMENT]
    if len(fragments) == 0:
        return ""
    if len(fragments) > 1 or any(c.type == Kind.ESCAPE_SEQUENCE for c in node.named_children):
        return "".join(node_text(c) for c in node.named_children if c.type != Kind.COMMENT)
    return node_text(fragments[0])


def dotted_name(node: Node) -> str | None:
    parts: list[str] = []
    current = node
    while current.type == Kind.MEMBER_EXPRESSION:
        prop = current.child_by_field_name(Field.PROPERTY)
        obj = current.child_by_field_name(Field.OBJECT)
        if prop is None or obj is None or prop.type == Kind.PRIVATE_PROPERTY_IDENTIFIER:
            if (
                prop is not None
                and prop.type == Kind.PRIVATE_PROPERTY_IDENTIFIER
                and obj is not None
            ):
                parts.append(node_text(prop))
                current = obj
                continue
            return None
        parts.append(node_text(prop))
        current = obj
    if current.type not in (Kind.IDENTIFIER, RECEIVER):
        return None
    parts.append(node_text(current))
    parts.reverse()
    return ".".join(parts)


def _boolean_operators(root: Node) -> tuple[list[str], list[Node]]:
    """Operators of a ``&&``/``||``/``??`` chain in source order, and its non-boolean leaves."""
    operators: list[str] = []
    leaves: list[Node] = []
    stack: list[Node | str] = [root]
    while len(stack) > 0:
        item = stack.pop()
        if isinstance(item, str):
            operators.append(item)
            continue
        unwrapped = unwrap_parentheses(item)
        if unwrapped.type == Kind.BINARY_EXPRESSION:
            operator = unwrapped.child_by_field_name(Field.OPERATOR)
            left = unwrapped.child_by_field_name(Field.LEFT)
            right = unwrapped.child_by_field_name(Field.RIGHT)
            if (
                operator is not None
                and left is not None
                and right is not None
                and node_text(operator) in BOOLEAN_OPERATORS
            ):
                stack.append(right)
                stack.append(node_text(operator))
                stack.append(left)
                continue
        leaves.append(item)
    return operators, leaves


def pattern_names(pattern: Node) -> list[str]:
    """Every identifier a binding pattern introduces (``{a, b: c, ...d}``, ``[e = 1]``)."""
    names: list[str] = []
    stack = [pattern]
    while len(stack) > 0:
        node = stack.pop()
        if node.type in (Kind.IDENTIFIER, Kind.SHORTHAND_PROPERTY_IDENTIFIER_PATTERN):
            names.append(node_text(node))
        elif node.type == Kind.PAIR_PATTERN:
            value = node.child_by_field_name(Field.VALUE)
            if value is not None:
                stack.append(value)
        elif node.type == Kind.ASSIGNMENT_PATTERN:
            left = node.child_by_field_name(Field.LEFT)
            if left is not None:
                stack.append(left)
        elif node.type in TYPED_PARAMETERS:
            binding, _default = parameter_parts(node)
            stack.append(binding)
        elif node.type in (
            Kind.OBJECT_PATTERN,
            Kind.ARRAY_PATTERN,
            Kind.REST_PATTERN,
            Kind.FORMAL_PARAMETERS,
        ):
            stack.extend(reversed(node.named_children))
    return names


class _UnitCollector:
    def __init__(self, source: SourceText, unit: UnitInfo) -> None:
        self.source = source
        self.unit = unit
        self.root = new_builder(CK_BLOCK, "")
        self.builders: list[Builder] = [self.root]
        self.calls: list[CallSite] = []
        self.locals: set[str] = set()
        self.assign_candidates: list[str] = []
        self.mutate_candidates: list[str] = []
        self.statements = 0
        self.own_name = _own_name(unit)

    def _new(self, kind: str, label: str, parent: Builder) -> Builder:
        builder = new_builder(kind, label)
        parent.children.append(builder)
        self.builders.append(builder)
        return builder

    def _push_statements(
        self, stack: list[tuple[str, Node, Builder]], statements: Sequence[Node], parent: Builder
    ) -> None:
        for statement in reversed(statements):
            stack.append((_T_STATEMENT, statement, parent))

    def _push_block(
        self, stack: list[tuple[str, Node, Builder]], body: Node, parent: Builder
    ) -> None:
        """A statement body: a block's statements, or the single statement itself."""
        if body.type == Kind.STATEMENT_BLOCK:
            self._push_statements(
                stack, [c for c in body.named_children if c.type != Kind.COMMENT], parent
            )
        else:
            stack.append((_T_STATEMENT, body, parent))

    def _expr(
        self, stack: list[tuple[str, Node, Builder]], node: Node | None, parent: Builder
    ) -> None:
        if node is not None:
            stack.append((_T_EXPRESSION, node, parent))

    # -- statements ---------------------------------------------------------

    def _statement(
        self, stack: list[tuple[str, Node, Builder]], node: Node, parent: Builder
    ) -> None:
        kind = node.type
        if kind in (Kind.COMMENT, Kind.EMPTY_STATEMENT):
            return
        if kind == Kind.STATEMENT_BLOCK:
            self._push_block(stack, node, parent)
            return
        self.statements += 1
        if kind == Kind.IF_STATEMENT:
            self._if(stack, node, parent, CK_IF)
        elif kind in LOOP_STATEMENTS:
            self._loop(stack, node, parent)
        elif kind == Kind.TRY_STATEMENT:
            self._try(stack, node, parent)
        elif kind == Kind.SWITCH_STATEMENT:
            self._switch(stack, node, parent)
        elif kind == Kind.LABELED_STATEMENT:
            body = node.child_by_field_name(Field.BODY)
            if body is not None:
                self.statements -= 1
                stack.append((_T_STATEMENT, body, parent))
        elif kind == Kind.WITH_STATEMENT:
            expression = self._new(CK_EXPR, "", parent)
            body = node.child_by_field_name(Field.BODY)
            if body is not None:
                self._push_block(stack, body, parent)
            self._expr(stack, node.child_by_field_name(Field.OBJECT), expression)
        elif kind in (Kind.BREAK_STATEMENT, Kind.CONTINUE_STATEMENT):
            if node.child_by_field_name(Field.LABEL) is not None:
                jump = self._new(CK_JUMP, "", parent)
                jump.labeled = True
        elif kind in NESTED_DECLARATIONS:
            self._nested_declaration(stack, node, parent)
        elif kind == Kind.EXPORT_STATEMENT:
            declaration = node.child_by_field_name(Field.DECLARATION)
            value = node.child_by_field_name(Field.VALUE)
            if declaration is not None:
                self.statements -= 1
                stack.append((_T_STATEMENT, declaration, parent))
            elif value is not None:
                self._expr(stack, value, self._new(CK_EXPR, "", parent))
        elif kind == Kind.IMPORT_STATEMENT:
            for name in _import_bound_names(node):
                self.locals.add(name)
        elif kind in DECLARATION_TYPES:
            self._declaration(stack, node, parent)
        elif kind == Kind.CLASS_STATIC_BLOCK:
            body = node.child_by_field_name(Field.BODY)
            if body is not None:
                self._push_block(stack, body, parent)
        elif kind in FIELD_DEFINITIONS:
            self._expr(stack, node.child_by_field_name(Field.VALUE), self._new(CK_EXPR, "", parent))
        else:
            expression = self._new(CK_EXPR, "", parent)
            for child in reversed(node.named_children):
                if child.type != Kind.COMMENT:
                    self._expr(stack, child, expression)

    def _declaration(
        self, stack: list[tuple[str, Node, Builder]], node: Node, parent: Builder
    ) -> None:
        expression = self._new(CK_EXPR, "", parent)
        for declarator in reversed(node.named_children):
            if declarator.type != Kind.VARIABLE_DECLARATOR:
                continue
            name = declarator.child_by_field_name(Field.NAME)
            value = declarator.child_by_field_name(Field.VALUE)
            if name is not None:
                self.locals.update(pattern_names(name))
                self._expr(stack, name, expression)
            self._expr(stack, value, expression)

    def _nested_declaration(
        self, stack: list[tuple[str, Node, Builder]], node: Node, parent: Builder
    ) -> None:
        name = node.child_by_field_name(Field.NAME)
        if name is not None:
            self.locals.add(node_text(name))
        expression = self._new(CK_EXPR, "", parent)
        if node.type in CLASS_TYPES:
            # extends clause is evaluated here; the body is the class unit
            for child in reversed(node.named_children):
                if child.type == Kind.CLASS_HERITAGE:
                    self._expr(stack, child, expression)
        else:
            parameters = node.child_by_field_name(Field.PARAMETERS)
            if parameters is not None:
                self._parameter_defaults(stack, parameters, expression)

    def _parameter_defaults(
        self, stack: list[tuple[str, Node, Builder]], parameters: Node, parent: Builder
    ) -> None:
        """Default-value expressions of a nested unit's parameters belong to this unit."""
        for child in reversed(parameters.named_children):
            _binding, default = parameter_parts(child)
            if default is not None:
                self._expr(stack, default, parent)

    def _if(
        self, stack: list[tuple[str, Node, Builder]], node: Node, parent: Builder, kind: str
    ) -> None:
        builder = self._new(kind, "", parent)
        condition = self._new(CK_EXPR, "", builder)
        self._expr(stack, node.child_by_field_name(Field.CONDITION), condition)
        then_block = self._new(CK_BLOCK, "", builder)
        alternative = node.child_by_field_name(Field.ALTERNATIVE)
        if alternative is not None:
            inner = [c for c in alternative.named_children if c.type != Kind.COMMENT]
            if len(inner) == 1 and inner[0].type == Kind.IF_STATEMENT:
                self.statements += 1
                self._if(stack, inner[0], builder, CK_ELIF)
            else:
                else_block = self._new(CK_BLOCK, "", builder)
                for child in inner:
                    self._push_block(stack, child, else_block)
        consequence = node.child_by_field_name(Field.CONSEQUENCE)
        if consequence is not None:
            self._push_block(stack, consequence, then_block)

    def _loop(self, stack: list[tuple[str, Node, Builder]], node: Node, parent: Builder) -> None:
        label = LOOP_FOR
        if node.type == Kind.WHILE_STATEMENT:
            label = LOOP_WHILE
        elif node.type == Kind.DO_STATEMENT:
            label = LOOP_DO
        loop = self._new(CK_LOOP, label, parent)
        condition = self._new(CK_EXPR, "", loop)
        body_block = self._new(CK_BLOCK, "", loop)
        body = node.child_by_field_name(Field.BODY)
        if body is not None:
            self._push_block(stack, body, body_block)
        if node.type == Kind.FOR_IN_STATEMENT:
            left = node.child_by_field_name(Field.LEFT)
            if left is not None:
                self.locals.update(pattern_names(left))
            self._expr(stack, node.child_by_field_name(Field.RIGHT), condition)
            self._expr(stack, left, condition)
        elif node.type == Kind.FOR_STATEMENT:
            initializer = node.child_by_field_name(Field.INITIALIZER)
            if initializer is not None and initializer.type in DECLARATION_TYPES:
                for declarator in initializer.named_children:
                    name = declarator.child_by_field_name(Field.NAME)
                    if name is not None:
                        self.locals.update(pattern_names(name))
            self._expr(stack, node.child_by_field_name(Field.INCREMENT), condition)
            self._expr(stack, node.child_by_field_name(Field.CONDITION), condition)
            self._expr(stack, initializer, condition)
        else:
            self._expr(stack, node.child_by_field_name(Field.CONDITION), condition)

    def _try(self, stack: list[tuple[str, Node, Builder]], node: Node, parent: Builder) -> None:
        builder = self._new(CK_TRY, "", parent)
        body = self._new(CK_BLOCK, "", builder)
        handler = node.child_by_field_name(Field.HANDLER)
        finalizer = node.child_by_field_name(Field.FINALIZER)
        handler_block: Builder | None = None
        if handler is not None:
            handler_block = self._new(CK_HANDLER, "", builder)
            parameter = handler.child_by_field_name(Field.PARAMETER)
            if parameter is not None:
                self.locals.update(pattern_names(parameter))
        finally_block: Builder | None = None
        if finalizer is not None:
            finally_block = self._new(CK_FINALLY, "", builder)
            finally_body = finalizer.child_by_field_name(Field.BODY)
            if finally_body is not None:
                self._push_block(stack, finally_body, finally_block)
        if handler is not None and handler_block is not None:
            handler_body = handler.child_by_field_name(Field.BODY)
            if handler_body is not None:
                self._push_block(stack, handler_body, handler_block)
        try_body = node.child_by_field_name(Field.BODY)
        if try_body is not None:
            self._push_block(stack, try_body, body)

    def _switch(self, stack: list[tuple[str, Node, Builder]], node: Node, parent: Builder) -> None:
        builder = self._new(CK_SWITCH, "", parent)
        subject = self._new(CK_EXPR, "", builder)
        body = node.child_by_field_name(Field.BODY)
        cases: list[tuple[Node, Builder, Builder]] = []
        if body is not None:
            for case in body.named_children:
                if case.type not in (Kind.SWITCH_CASE, Kind.SWITCH_DEFAULT):
                    continue
                label = CASE_DEFAULT if case.type == Kind.SWITCH_DEFAULT else ""
                case_builder = self._new(CK_CASE, label, builder)
                guard = self._new(CK_EXPR, "", case_builder)
                case_body = self._new(CK_BLOCK, "", case_builder)
                cases.append((case, guard, case_body))
        for case, guard, case_body in reversed(cases):
            statements = [c for c in case.named_children if c.type != Kind.COMMENT]
            value = case.child_by_field_name(Field.VALUE)
            if value is not None:
                statements = [c for c in statements if c.id != value.id]
            self._push_statements(stack, statements, case_body)
            self._expr(stack, value, guard)
        self._expr(stack, node.child_by_field_name(Field.VALUE), subject)

    # -- expressions --------------------------------------------------------

    def _expression(
        self, stack: list[tuple[str, Node, Builder]], node: Node, parent: Builder
    ) -> None:
        kind = node.type
        if kind == Kind.COMMENT:
            return
        if kind in UNIT_TYPES:
            # The body is a separate unit; parameter defaults are evaluated here.
            parameters = node.child_by_field_name(Field.PARAMETERS)
            if parameters is not None:
                self._parameter_defaults(stack, parameters, parent)
            return
        if kind == Kind.BINARY_EXPRESSION:
            operator = node.child_by_field_name(Field.OPERATOR)
            if operator is not None and node_text(operator) in BOOLEAN_OPERATORS:
                operators, leaves = _boolean_operators(node)
                parent.operators += len(operators)
                parent.sequences += count_runs(operators)
                for leaf in reversed(leaves):
                    self._expr(stack, leaf, parent)
                return
        elif kind == Kind.AUGMENTED_ASSIGNMENT_EXPRESSION:
            operator = node.child_by_field_name(Field.OPERATOR)
            if operator is not None and node_text(operator) in LOGICAL_ASSIGNMENTS:
                parent.operators += 1
                parent.sequences += 1
            self._write(node.child_by_field_name(Field.LEFT), WRITE_ASSIGN)
        elif kind == Kind.ASSIGNMENT_EXPRESSION:
            left = node.child_by_field_name(Field.LEFT)
            self._write(left, WRITE_ASSIGN)
            if left is not None and left.type in (Kind.OBJECT_PATTERN, Kind.ARRAY_PATTERN):
                for name in pattern_names(left):
                    self._write_name(name)
        elif kind == Kind.UPDATE_EXPRESSION:
            self._write(node.child_by_field_name(Field.ARGUMENT), WRITE_ASSIGN)
        elif kind == Kind.UNARY_EXPRESSION:
            operator = node.child_by_field_name(Field.OPERATOR)
            argument = node.child_by_field_name(Field.ARGUMENT)
            if operator is not None and node_text(operator) == "delete" and argument is not None:
                self._write(argument, WRITE_MUTATE)
        elif kind == Kind.TERNARY_EXPRESSION:
            conditional = self._new(CK_CONDITIONAL, "", parent)
            condition = self._new(CK_EXPR, "", conditional)
            then_part = self._new(CK_EXPR, "", conditional)
            else_part = self._new(CK_EXPR, "", conditional)
            self._expr(stack, node.child_by_field_name(Field.ALTERNATIVE), else_part)
            self._expr(stack, node.child_by_field_name(Field.CONSEQUENCE), then_part)
            self._expr(stack, node.child_by_field_name(Field.CONDITION), condition)
            return
        elif kind in (Kind.CALL_EXPRESSION, Kind.NEW_EXPRESSION):
            self._call(node, parent)
        for child in reversed(node.named_children):
            self._expr(stack, child, parent)

    def _write(self, target: Node | None, kind: str) -> None:
        if target is None:
            return
        if target.type == Kind.IDENTIFIER:
            if kind == WRITE_ASSIGN:
                self._write_name(node_text(target))
            return
        root = root_identifier(target, MEMBER_CHAINS, Field.OBJECT)
        if root is not None and target.type in (Kind.MEMBER_EXPRESSION, Kind.SUBSCRIPT_EXPRESSION):
            self.mutate_candidates.append(root)

    def _write_name(self, name: str) -> None:
        self.assign_candidates.append(name)

    def _call(self, node: Node, parent: Builder) -> None:
        span = node_span(self.source, node)
        arguments = node.child_by_field_name(Field.ARGUMENTS)
        if node.type == Kind.NEW_EXPRESSION:
            self._new_call(node, span)
            self._arguments(arguments)
            return
        function = node.child_by_field_name(Field.FUNCTION)
        if function is None:
            return
        callee = unwrap_parentheses(function)
        if callee.type == IMPORT_CALL:
            return  # dynamic import: an import fact, not a call
        if callee.type == Kind.IDENTIFIER:
            name = node_text(callee)
            if name == REQUIRE:
                return  # CommonJS import: an import fact, not a call
            self.calls.append(CallSite(span, name, CALL_NAME, receiver_self=False))
            if name == self.own_name:
                self._new(CK_RECURSION, "", parent)
        elif callee.type == Kind.MEMBER_EXPRESSION:
            self._member_call(callee, span, arguments, parent)
        else:
            self.calls.append(CallSite(span, first_line(callee), CALL_DYNAMIC, receiver_self=False))
        self._arguments(arguments)

    def _new_call(self, node: Node, span: Span) -> None:
        constructor = node.child_by_field_name(Field.CONSTRUCTOR)
        if constructor is None:
            return
        dotted = dotted_name(unwrap_parentheses(constructor))
        if dotted is None:
            self.calls.append(
                CallSite(span, first_line(constructor), CALL_DYNAMIC, receiver_self=False)
            )
        else:
            self.calls.append(CallSite(span, dotted, CALL_NEW, receiver_self=False))

    def _member_call(
        self, callee: Node, span: Span, arguments: Node | None, parent: Builder
    ) -> None:
        dotted = dotted_name(callee)
        if dotted is None:
            self.calls.append(CallSite(span, first_line(callee), CALL_DYNAMIC, receiver_self=False))
            return
        receiver = dotted.split(".")[0] == RECEIVER
        self.calls.append(CallSite(span, dotted, CALL_ATTRIBUTE, receiver))
        if receiver and self.unit.kind == UNIT_METHOD and dotted == f"{RECEIVER}.{self.own_name}":
            self._new(CK_RECURSION, "", parent)
        self._mutation_through_call(callee, dotted, arguments)

    def _mutation_through_call(self, callee: Node, dotted: str, arguments: Node | None) -> None:
        """``x.push(v)`` and ``Object.assign(x, ...)`` write to ``x``."""
        prop = callee.child_by_field_name(Field.PROPERTY)
        obj = callee.child_by_field_name(Field.OBJECT)
        if prop is not None and obj is not None and obj.type == Kind.IDENTIFIER:
            if node_text(prop) in MUTATING_METHODS:
                self.mutate_candidates.append(node_text(obj))
        if dotted != OBJECT_ASSIGN or arguments is None:
            return
        first = [a for a in arguments.named_children if a.type != Kind.COMMENT]
        if len(first) > 0 and first[0].type == Kind.IDENTIFIER:
            self.mutate_candidates.append(node_text(first[0]))

    def _arguments(self, arguments: Node | None) -> None:
        if arguments is None:
            return
        for argument in arguments.named_children:
            if argument.type == Kind.IDENTIFIER:
                self.calls.append(
                    CallSite(
                        node_span(self.source, argument),
                        node_text(argument),
                        CALL_ARGUMENT,
                        receiver_self=False,
                    )
                )
            elif argument.type == Kind.SPREAD_ELEMENT:
                inner = [c for c in argument.named_children if c.type != Kind.COMMENT]
                if len(inner) == 1 and inner[0].type == Kind.IDENTIFIER:
                    self.calls.append(
                        CallSite(
                            node_span(self.source, inner[0]),
                            node_text(inner[0]),
                            CALL_ARGUMENT,
                            receiver_self=False,
                        )
                    )

    # -- driver -------------------------------------------------------------

    def _seed(self, stack: list[tuple[str, Node, Builder]]) -> None:
        """Push the unit's own body: parameters bind locals, the body is a block or expression."""
        node = self.unit.node
        if node.type in FUNCTION_TYPES:
            for field_name in (Field.PARAMETERS, Field.PARAMETER):
                bound = node.child_by_field_name(field_name)
                if bound is not None:
                    self.locals.update(pattern_names(bound))
            body = node.child_by_field_name(Field.BODY)
            if body is None:
                return
            if body.type == Kind.STATEMENT_BLOCK:
                self._push_block(stack, body, self.root)
            else:
                self._expr(stack, body, self._new(CK_EXPR, "", self.root))
            return
        container = node
        if node.type in CLASS_TYPES:
            body = node.child_by_field_name(Field.BODY)
            if body is None:
                return
            container = body
        members = [c for c in container.named_children if c.type != Kind.COMMENT]
        self._push_statements(stack, members, self.root)

    def _method_member(
        self, stack: list[tuple[str, Node, Builder]], node: Node, parent: Builder
    ) -> None:
        """A method of a class body: one statement of the class unit, its own unit otherwise."""
        self.statements += 1
        self.locals.add(_method_name(node))
        parameters = node.child_by_field_name(Field.PARAMETERS)
        if parameters is not None:
            self._parameter_defaults(stack, parameters, self._new(CK_EXPR, "", parent))

    def run(self) -> None:
        stack: list[tuple[str, Node, Builder]] = []
        self._seed(stack)
        while len(stack) > 0:
            task, payload, parent = stack.pop()
            if task != _T_STATEMENT:
                self._expression(stack, payload, parent)
            elif payload.type == Kind.METHOD_DEFINITION:
                self._method_member(stack, payload, parent)
            else:
                self._statement(stack, payload, parent)

    def freeze(self) -> ControlNode:
        return freeze_builders(self.builders, self.root)

    def writes(self) -> tuple[tuple[str, str], ...]:
        found: list[tuple[str, str]] = []
        for name in self.assign_candidates:
            if name not in self.locals:
                found.append((name, WRITE_ASSIGN))
        for name in self.mutate_candidates:
            if name not in self.locals:
                found.append((name, WRITE_MUTATE))
        return tuple(sorted(set(found)))


_STATEMENT_BLOCKS = frozenset({CK_BLOCK, CK_HANDLER, CK_FINALLY})


def _trivial_expr(node: ControlNode) -> bool:
    return node.kind == CK_EXPR and node.operators == 0 and len(node.children) == 0


def freeze_builders(builders: Sequence["Builder"], root: "Builder") -> ControlNode:
    """Freeze a unit's builders into its control tree, innermost first; trivial
    expressions drop out of statement blocks."""
    for builder in reversed(builders):
        children = tuple(c.frozen for c in builder.children if c.frozen is not None)
        if builder.kind in _STATEMENT_BLOCKS:
            children = tuple(c for c in children if not _trivial_expr(c))
        builder.frozen = ControlNode(
            builder.kind,
            children,
            builder.operators,
            builder.sequences,
            builder.label,
            builder.labeled,
        )
    assert root.frozen is not None
    return root.frozen


def _method_name(node: Node) -> str:
    name = node.child_by_field_name(Field.NAME)
    if name is None:
        return ""
    return node_text(name)


def _own_name(unit: UnitInfo) -> str | None:
    node = unit.node
    if node.type == Kind.METHOD_DEFINITION:
        return _method_name(node)
    if node.type in FUNCTION_TYPES:
        name = node.child_by_field_name(Field.NAME)
        if name is not None:
            return node_text(name)
        parent = node.parent
        if parent is not None and parent.type == Kind.VARIABLE_DECLARATOR:
            bound = parent.child_by_field_name(Field.NAME)
            if bound is not None and bound.type == Kind.IDENTIFIER:
                return node_text(bound)
    return None


def _parameter_count(node: Node) -> int:
    if node.type not in FUNCTION_TYPES:
        return 0
    parameters = node.child_by_field_name(Field.PARAMETERS)
    if parameters is None:
        # `x => ...`: a single parameter without parentheses
        return 1 if node.child_by_field_name(Field.PARAMETER) is not None else 0
    return sum(
        1 for c in parameters.named_children if c.type != Kind.COMMENT and not is_this_parameter(c)
    )


def _is_generator(node: Node) -> bool:
    if node.type in GENERATOR_TYPES:
        return True
    if node.type == Kind.METHOD_DEFINITION:
        return any(c.type == "*" for c in node.children if not c.is_named)
    return False


def collect_javascript_functions(
    source: SourceText, root: Node, comments: Sequence[Comment]
) -> tuple[FunctionFact, ...]:
    units = discover_units(root)
    spans = [unit_span(source, unit.node, Kind.PROGRAM) for unit in units]
    facts: list[FunctionFact] = []
    for index, unit in enumerate(units):
        collector = _UnitCollector(source, unit)
        collector.run()
        tree = collector.freeze()
        span = spans[index]
        nested = nested_line_exclusions(
            span,
            [
                (
                    other,
                    units[other_index].node.type
                    in (
                        Kind.ARROW_FUNCTION,
                        Kind.FUNCTION_EXPRESSION,
                        Kind.GENERATOR_FUNCTION,
                        Kind.CLASS,
                    ),
                )
                for other_index, other in enumerate(spans)
                if other_index != index
            ],
        )
        facts.append(
            FunctionFact(
                name=unit.name,
                kind=unit.kind,
                is_async=_is_async(unit.node),
                is_generator=_is_generator(unit.node),
                span=span,
                parameters=_parameter_count(unit.node),
                statements=collector.statements,
                logical_lines=logical_line_count(source, comments, span, nested),
                control=tree,
                calls=tuple(sorted(collector.calls, key=lambda c: c.span)),
                class_name=unit.class_name,
                locals=frozenset(collector.locals),
                globals_declared=frozenset(),
                writes=collector.writes(),
            )
        )
    return tuple(facts)


# -- imports and bindings ---------------------------------------------------


TYPE_KEYWORD = "type"


def _import_bound_names(statement: Node) -> list[str]:
    names: list[str] = []
    for fact in _import_statement(SourceText.from_text(""), statement):
        for _imported, local in fact.names:
            if (local != STAR and local != "") or local != STAR:
                names.append(local)
    return [n for n in names if n != ""]


def _local_name(name: Node, alias: Node | None) -> str:
    """The local binding of an import/export specifier: its alias when one is written."""
    if alias is not None:
        return node_text(alias)
    return node_text(name)


def _type_only(node: Node) -> bool:
    """TypeScript's ``import type ...``, ``export type ... from`` and ``{type X}``: erased by
    the compiler, so no runtime import (and no module-graph edge)."""
    return any(not child.is_named and child.type == TYPE_KEYWORD for child in node.children)


def _only_types(clause: Node, specifier_type: str) -> bool:
    """A ``{...}`` clause whose specifiers are all type-only (TypeScript elides it)."""
    specifiers = [c for c in clause.named_children if c.type == specifier_type]
    return len(specifiers) > 0 and all(_type_only(c) for c in specifiers)


def _specifier_names(clause: Node, specifier_type: str) -> list[tuple[str, str]]:
    """``{a, b as c}`` of an import or export clause as (name, local) pairs."""
    names: list[tuple[str, str]] = []
    for specifier in clause.named_children:
        if specifier.type != specifier_type or _type_only(specifier):
            continue
        name = specifier.child_by_field_name(Field.NAME)
        if name is None:
            continue
        names.append(
            (node_text(name), _local_name(name, specifier.child_by_field_name(Field.ALIAS)))
        )
    return names


def _namespace_name(node: Node) -> str | None:
    inner = [c for c in node.named_children if c.type == Kind.IDENTIFIER]
    if len(inner) == 1:
        return node_text(inner[0])
    return None


def _import_clause(span: Span, module: str, clause: Node) -> list[ImportFact]:
    facts: list[ImportFact] = []
    names: list[tuple[str, str]] = []
    for child in clause.named_children:
        if child.type == Kind.IDENTIFIER:
            names.append((DEFAULT_EXPORT, node_text(child)))
        elif child.type == Kind.NAMESPACE_IMPORT:
            namespace = _namespace_name(child)
            if namespace is not None:
                facts.append(ImportFact(span, IMPORT_MODULE, module, 0, (("", namespace),)))
        elif child.type == Kind.NAMED_IMPORTS:
            if _only_types(child, Kind.IMPORT_SPECIFIER) and len(clause.named_children) == 1:
                return []
            names.extend(_specifier_names(child, Kind.IMPORT_SPECIFIER))
    if len(names) > 0 or len(facts) == 0:
        facts.append(ImportFact(span, IMPORT_NAMES, module, 0, tuple(names)))
    return facts


def _statement_module(statement: Node) -> str | None:
    """The literal specifier of an import/export statement, if it has one."""
    source_node = statement.child_by_field_name(Field.SOURCE)
    if source_node is None:
        return None
    return string_value(source_node)


def _import_statement(source: SourceText, statement: Node) -> list[ImportFact]:
    span = Span(FIRST_LINE, FIRST_COLUMN, FIRST_LINE, FIRST_COLUMN)
    if source.text != "":
        span = node_span(source, statement)
    required = [c for c in statement.named_children if c.type == Kind.IMPORT_REQUIRE_CLAUSE]
    if len(required) > 0:
        return _require_clause(span, required[0])
    module = _statement_module(statement)
    if module is None or _type_only(statement):
        return []
    clauses = [c for c in statement.named_children if c.type == Kind.IMPORT_CLAUSE]
    if len(clauses) == 0:
        return [ImportFact(span, IMPORT_MODULE, module, 0, ())]
    return _import_clause(span, module, clauses[0])


def _require_clause(span: Span, clause: Node) -> list[ImportFact]:
    """TypeScript's ``import fs = require("fs")``: the whole module under one name."""
    source_node = clause.child_by_field_name(Field.SOURCE)
    names = [c for c in clause.named_children if c.type == Kind.IDENTIFIER]
    if source_node is None or len(names) != 1:
        return []
    module = string_value(source_node)
    if module is None:
        return []
    return [ImportFact(span, IMPORT_MODULE, module, 0, (("", node_text(names[0])),))]


def _export_statement(source: SourceText, statement: Node) -> list[ImportFact]:
    module = _statement_module(statement)
    if module is None or _type_only(statement):
        return []
    names: list[tuple[str, str]] = []
    for child in statement.named_children:
        if child.type == Kind.EXPORT_CLAUSE:
            if _only_types(child, Kind.EXPORT_SPECIFIER):
                return []
            names.extend(_specifier_names(child, Kind.EXPORT_SPECIFIER))
        elif child.type == Kind.NAMESPACE_EXPORT:
            namespace = _namespace_name(child)
            if namespace is not None:
                names.append((STAR, namespace))
    if len(names) == 0:
        names.append((STAR, STAR))
    return [ImportFact(node_span(source, statement), IMPORT_REEXPORT, module, 0, tuple(names))]


def _require_target(call: Node) -> tuple[str | None, bool]:
    """(module specifier, is_require) for ``require(...)`` and ``import(...)`` calls."""
    function = call.child_by_field_name(Field.FUNCTION)
    arguments = call.child_by_field_name(Field.ARGUMENTS)
    if function is None or arguments is None:
        return None, False
    callee = unwrap_parentheses(function)
    if (
        callee.type == Kind.IDENTIFIER and node_text(callee) == REQUIRE
    ) or callee.type == IMPORT_CALL:
        pass
    else:
        return None, False
    actual = [a for a in arguments.named_children if a.type != Kind.COMMENT]
    if len(actual) == 0:
        return None, True
    return string_value(actual[0]), True


def collect_javascript_imports(source: SourceText, root: Node) -> tuple[ImportFact, ...]:
    imports: list[ImportFact] = []
    stack = [root]
    while len(stack) > 0:
        node = stack.pop()
        if node.type == Kind.IMPORT_STATEMENT:
            imports.extend(_import_statement(source, node))
            continue
        if node.type == Kind.EXPORT_STATEMENT:
            imports.extend(_export_statement(source, node))
        if node.type == Kind.CALL_EXPRESSION:
            module, is_import = _require_target(node)
            if is_import:
                span = node_span(source, node)
                if module is None:
                    imports.append(ImportFact(span, IMPORT_DYNAMIC, first_line(node), 0, ()))
                else:
                    imports.append(
                        ImportFact(span, _require_kind(node), module, 0, _require_names(node))
                    )
                continue
        for child in reversed(node.children):
            stack.append(child)
    imports.sort(key=lambda i: i.span)
    return tuple(imports)


def _require_kind(call: Node) -> str:
    parent = call.parent
    if parent is not None and parent.type == Kind.VARIABLE_DECLARATOR:
        name = parent.child_by_field_name(Field.NAME)
        if name is not None and name.type == Kind.OBJECT_PATTERN:
            return IMPORT_NAMES
    return IMPORT_MODULE


def _require_names(call: Node) -> tuple[tuple[str, str], ...]:
    parent = call.parent
    if parent is None or parent.type != Kind.VARIABLE_DECLARATOR:
        return ()
    name = parent.child_by_field_name(Field.NAME)
    if name is None:
        return ()
    if name.type == Kind.IDENTIFIER:
        return (("", node_text(name)),)
    if name.type == Kind.OBJECT_PATTERN:
        names: list[tuple[str, str]] = []
        for child in name.named_children:
            if child.type == Kind.SHORTHAND_PROPERTY_IDENTIFIER_PATTERN:
                names.append((node_text(child), node_text(child)))
            elif child.type == Kind.PAIR_PATTERN:
                key = child.child_by_field_name(Field.KEY)
                value = child.child_by_field_name(Field.VALUE)
                if key is not None and value is not None and value.type == Kind.IDENTIFIER:
                    names.append((node_text(key), node_text(value)))
        return tuple(names)
    return ()


def _is_mutable_value(value: Node | None) -> bool:
    if value is None:
        return False
    unwrapped = unwrap_parentheses(value)
    if unwrapped.type in (Kind.OBJECT, Kind.ARRAY):
        return True
    if unwrapped.type == Kind.NEW_EXPRESSION:
        constructor = unwrapped.child_by_field_name(Field.CONSTRUCTOR)
        return constructor is not None and node_text(constructor) in MUTABLE_CONSTRUCTORS
    return False


def _declarator_bindings(declarator: Node, reassignable: bool, span: Span) -> list[ModuleBinding]:
    name = declarator.child_by_field_name(Field.NAME)
    value = declarator.child_by_field_name(Field.VALUE)
    if name is None:
        return []
    if value is not None and value.type == Kind.CALL_EXPRESSION:
        _module, is_import = _require_target(value)
        if is_import:
            return [
                ModuleBinding(local, BINDING_IMPORT, mutable=False, span=span)
                for _imported, local in _require_names(value)
            ]
    if name.type == Kind.IDENTIFIER and value is not None:
        if value.type in FUNCTION_TYPES:
            return [ModuleBinding(node_text(name), BINDING_FUNCTION, mutable=False, span=span)]
        if value.type in CLASS_TYPES:
            return [ModuleBinding(node_text(name), BINDING_CLASS, mutable=False, span=span)]
    mutable = reassignable or _is_mutable_value(value)
    return [ModuleBinding(bound, BINDING_VARIABLE, mutable, span) for bound in pattern_names(name)]


def _declaration_bindings(node: Node, span: Span) -> list[ModuleBinding]:
    kind_node = node.child_by_field_name(Field.KIND)
    reassignable = node.type == Kind.VARIABLE_DECLARATION or (
        kind_node is not None and node_text(kind_node) != "const"
    )
    found: list[ModuleBinding] = []
    for declarator in node.named_children:
        if declarator.type == Kind.VARIABLE_DECLARATOR:
            found.extend(_declarator_bindings(declarator, reassignable, span))
    return found


def _statement_bindings(node: Node, span: Span) -> list[ModuleBinding]:
    if node.type in (Kind.FUNCTION_DECLARATION, Kind.GENERATOR_FUNCTION_DECLARATION) or (
        node.type in CLASS_TYPES
    ):
        name = node.child_by_field_name(Field.NAME)
        if name is None:
            return []
        kind = BINDING_CLASS if node.type in CLASS_TYPES else BINDING_FUNCTION
        return [ModuleBinding(node_text(name), kind, mutable=False, span=span)]
    if node.type == Kind.IMPORT_STATEMENT:
        return [
            ModuleBinding(local, BINDING_IMPORT, mutable=False, span=span)
            for local in _import_bound_names(node)
        ]
    if node.type in DECLARATION_TYPES:
        return _declaration_bindings(node, span)
    return []


def collect_javascript_bindings(source: SourceText, root: Node) -> tuple[ModuleBinding, ...]:
    bindings: dict[str, ModuleBinding] = {}
    for statement in root.named_children:
        node = statement
        if node.type == Kind.EXPORT_STATEMENT:
            declaration = node.child_by_field_name(Field.DECLARATION)
            if declaration is None:
                continue
            node = declaration
        for binding in _statement_bindings(node, node_span(source, statement)):
            bindings[binding.name] = binding
    return tuple(sorted(bindings.values(), key=lambda b: (b.span, b.name)))
