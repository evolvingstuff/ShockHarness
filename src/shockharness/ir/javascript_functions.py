"""Function facts for JavaScript: every unit's control tree, size, calls and writes.

Units are the program, each class body (field initializers and static blocks),
each function declaration or expression, generator, arrow function and method.
The traversal is iterative and stops at nested units, exactly as the Python
adapter does, so the two languages produce the same tree for equivalent code.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from tree_sitter import Node

from shockharness.constants import EVIDENCE_MAX_CHARS, FIRST_COLUMN, FIRST_LINE
from shockharness.ir.javascript_catches import node_span, node_text, scope_for
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
from shockharness.source import SourceText

FUNCTION_TYPES = frozenset(
    {
        "function_declaration",
        "generator_function_declaration",
        "function_expression",
        "generator_function",
        "arrow_function",
        "method_definition",
    }
)
GENERATOR_TYPES = frozenset({"generator_function_declaration", "generator_function"})
CLASS_TYPES = frozenset({"class_declaration", "class"})
# Units that are expressions: their first and last lines usually carry the parent's code too.
EXPRESSION_UNIT_TYPES = frozenset(
    {"arrow_function", "function_expression", "generator_function", "class"}
)
UNIT_TYPES = FUNCTION_TYPES | CLASS_TYPES
STATEMENT_TYPES = frozenset(
    {
        "expression_statement",
        "lexical_declaration",
        "variable_declaration",
        "if_statement",
        "for_statement",
        "for_in_statement",
        "while_statement",
        "do_statement",
        "try_statement",
        "switch_statement",
        "return_statement",
        "throw_statement",
        "break_statement",
        "continue_statement",
        "labeled_statement",
        "with_statement",
        "debugger_statement",
        "export_statement",
        "import_statement",
        "class_declaration",
        "function_declaration",
        "generator_function_declaration",
        "statement_block",
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
DECLARATION_TYPES = frozenset({"lexical_declaration", "variable_declaration"})
PATTERN_SKIP = frozenset({"comment", "property_identifier"})
RECEIVER = "this"
REQUIRE = "require"
OBJECT_ASSIGN = "Object.assign"
IMPORT_CALL = "import"
STRING = "string"
STRING_FRAGMENT = "string_fragment"
DEFAULT_EXPORT = "default"
STAR = "*"

_T_STATEMENTS = "statements"
_T_STATEMENT = "statement"
_T_EXPRESSION = "expression"


@dataclass
class _Builder:
    kind: str
    label: str
    children: list["_Builder"]
    operators: int
    sequences: int
    labeled: bool
    frozen: ControlNode | None


def _builder(kind: str, label: str) -> _Builder:
    return _Builder(kind, label, [], 0, 0, False, None)


@dataclass(frozen=True)
class _UnitInfo:
    node: Node
    name: str
    kind: str
    class_name: str | None


def _is_async(node: Node) -> bool:
    return any(child.type == "async" for child in node.children if not child.is_named)


def _unit_kind(node: Node) -> str:
    if node.type == "program":
        return UNIT_MODULE
    if node.type in CLASS_TYPES:
        return UNIT_CLASS
    if node.type == "arrow_function":
        return UNIT_ARROW
    if node.type == "method_definition":
        return UNIT_METHOD
    return UNIT_FUNCTION


def _discover_units(root: Node) -> list[_UnitInfo]:
    units: list[_UnitInfo] = [_UnitInfo(root, MODULE_SCOPE, UNIT_MODULE, None)]
    stack: list[tuple[Node, str, str | None]] = [(root, MODULE_SCOPE, None)]
    while len(stack) > 0:
        node, scope, class_name = stack.pop()
        child_scope = scope
        child_class = class_name
        if node.is_named and node.type in UNIT_TYPES:
            child_scope = scope_for(node, scope)
            units.append(_UnitInfo(node, child_scope, _unit_kind(node), class_name))
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
    if len(fragments) > 1 or any(c.type == "escape_sequence" for c in node.named_children):
        return "".join(node_text(c) for c in node.named_children if c.type != "comment")
    return node_text(fragments[0])


def _unwrap(node: Node) -> Node:
    current = node
    while current.type == "parenthesized_expression":
        inner = [c for c in current.named_children if c.type != "comment"]
        if len(inner) != 1:
            return current
        current = inner[0]
    return current


def _dotted(node: Node) -> str | None:
    parts: list[str] = []
    current = node
    while current.type == "member_expression":
        prop = current.child_by_field_name("property")
        obj = current.child_by_field_name("object")
        if prop is None or obj is None or prop.type == "private_property_identifier":
            if prop is not None and prop.type == "private_property_identifier" and obj is not None:
                parts.append(node_text(prop))
                current = obj
                continue
            return None
        parts.append(node_text(prop))
        current = obj
    if current.type not in ("identifier", RECEIVER):
        return None
    parts.append(node_text(current))
    parts.reverse()
    return ".".join(parts)


def _root_identifier(node: Node) -> str | None:
    current = node
    while current.type in ("member_expression", "subscript_expression"):
        obj = current.child_by_field_name("object")
        if obj is None:
            return None
        current = obj
    if current.type == "identifier":
        return node_text(current)
    return None


def _excerpt(node: Node) -> str:
    first = node_text(node).split("\n")[0].strip()
    if len(first) > EVIDENCE_MAX_CHARS:
        return first[:EVIDENCE_MAX_CHARS]
    return first


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
        unwrapped = _unwrap(item)
        if unwrapped.type == "binary_expression":
            operator = unwrapped.child_by_field_name("operator")
            left = unwrapped.child_by_field_name("left")
            right = unwrapped.child_by_field_name("right")
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
        if node.type in ("identifier", "shorthand_property_identifier_pattern"):
            names.append(node_text(node))
        elif node.type == "pair_pattern":
            value = node.child_by_field_name("value")
            if value is not None:
                stack.append(value)
        elif node.type == "assignment_pattern":
            left = node.child_by_field_name("left")
            if left is not None:
                stack.append(left)
        elif node.type in ("object_pattern", "array_pattern", "rest_pattern"):
            stack.extend(reversed(node.named_children))
    return names


class _UnitCollector:
    def __init__(self, source: SourceText, unit: _UnitInfo) -> None:
        self.source = source
        self.unit = unit
        self.root = _builder(CK_BLOCK, "")
        self.builders: list[_Builder] = [self.root]
        self.calls: list[CallSite] = []
        self.locals: set[str] = set()
        self.assign_candidates: list[str] = []
        self.mutate_candidates: list[str] = []
        self.statements = 0
        self.own_name = _own_name(unit)

    def _new(self, kind: str, label: str, parent: _Builder) -> _Builder:
        builder = _builder(kind, label)
        parent.children.append(builder)
        self.builders.append(builder)
        return builder

    def _push_statements(
        self, stack: list[tuple[str, Node, _Builder]], statements: Sequence[Node], parent: _Builder
    ) -> None:
        for statement in reversed(statements):
            stack.append((_T_STATEMENT, statement, parent))

    def _push_block(
        self, stack: list[tuple[str, Node, _Builder]], body: Node, parent: _Builder
    ) -> None:
        """A statement body: a block's statements, or the single statement itself."""
        if body.type == "statement_block":
            self._push_statements(
                stack, [c for c in body.named_children if c.type != "comment"], parent
            )
        else:
            stack.append((_T_STATEMENT, body, parent))

    def _expr(
        self, stack: list[tuple[str, Node, _Builder]], node: Node | None, parent: _Builder
    ) -> None:
        if node is not None:
            stack.append((_T_EXPRESSION, node, parent))

    # -- statements ---------------------------------------------------------

    def _statement(
        self, stack: list[tuple[str, Node, _Builder]], node: Node, parent: _Builder
    ) -> None:
        kind = node.type
        if kind in ("comment", "empty_statement"):
            return
        if kind == "statement_block":
            self._push_block(stack, node, parent)
            return
        self.statements += 1
        if kind == "if_statement":
            self._if(stack, node, parent, CK_IF)
        elif kind in ("for_statement", "for_in_statement", "while_statement", "do_statement"):
            self._loop(stack, node, parent)
        elif kind == "try_statement":
            self._try(stack, node, parent)
        elif kind == "switch_statement":
            self._switch(stack, node, parent)
        elif kind == "labeled_statement":
            body = node.child_by_field_name("body")
            if body is not None:
                self.statements -= 1
                stack.append((_T_STATEMENT, body, parent))
        elif kind == "with_statement":
            expression = self._new(CK_EXPR, "", parent)
            body = node.child_by_field_name("body")
            if body is not None:
                self._push_block(stack, body, parent)
            self._expr(stack, node.child_by_field_name("object"), expression)
        elif kind in ("break_statement", "continue_statement"):
            if node.child_by_field_name("label") is not None:
                jump = self._new(CK_JUMP, "", parent)
                jump.labeled = True
        elif kind in (
            "function_declaration",
            "generator_function_declaration",
            "class_declaration",
        ):
            self._nested_declaration(stack, node, parent)
        elif kind == "export_statement":
            declaration = node.child_by_field_name("declaration")
            value = node.child_by_field_name("value")
            if declaration is not None:
                self.statements -= 1
                stack.append((_T_STATEMENT, declaration, parent))
            elif value is not None:
                self._expr(stack, value, self._new(CK_EXPR, "", parent))
        elif kind == "import_statement":
            for name in _import_bound_names(node):
                self.locals.add(name)
        elif kind in DECLARATION_TYPES:
            self._declaration(stack, node, parent)
        elif kind == "class_static_block":
            body = node.child_by_field_name("body")
            if body is not None:
                self._push_block(stack, body, parent)
        elif kind == "field_definition":
            self._expr(stack, node.child_by_field_name("value"), self._new(CK_EXPR, "", parent))
        else:
            expression = self._new(CK_EXPR, "", parent)
            for child in reversed(node.named_children):
                if child.type != "comment":
                    self._expr(stack, child, expression)

    def _declaration(
        self, stack: list[tuple[str, Node, _Builder]], node: Node, parent: _Builder
    ) -> None:
        expression = self._new(CK_EXPR, "", parent)
        for declarator in reversed(node.named_children):
            if declarator.type != "variable_declarator":
                continue
            name = declarator.child_by_field_name("name")
            value = declarator.child_by_field_name("value")
            if name is not None:
                self.locals.update(pattern_names(name))
                self._expr(stack, name, expression)
            self._expr(stack, value, expression)

    def _nested_declaration(
        self, stack: list[tuple[str, Node, _Builder]], node: Node, parent: _Builder
    ) -> None:
        name = node.child_by_field_name("name")
        if name is not None:
            self.locals.add(node_text(name))
        expression = self._new(CK_EXPR, "", parent)
        if node.type == "class_declaration":
            # extends clause is evaluated here; the body is the class unit
            for child in reversed(node.named_children):
                if child.type == "class_heritage":
                    self._expr(stack, child, expression)
        else:
            parameters = node.child_by_field_name("parameters")
            if parameters is not None:
                self._parameter_defaults(stack, parameters, expression)

    def _parameter_defaults(
        self, stack: list[tuple[str, Node, _Builder]], parameters: Node, parent: _Builder
    ) -> None:
        """Default-value expressions of a nested unit's parameters belong to this unit."""
        for child in reversed(parameters.named_children):
            if child.type == "assignment_pattern":
                self._expr(stack, child.child_by_field_name("right"), parent)

    def _if(
        self, stack: list[tuple[str, Node, _Builder]], node: Node, parent: _Builder, kind: str
    ) -> None:
        builder = self._new(kind, "", parent)
        condition = self._new(CK_EXPR, "", builder)
        self._expr(stack, node.child_by_field_name("condition"), condition)
        then_block = self._new(CK_BLOCK, "", builder)
        alternative = node.child_by_field_name("alternative")
        if alternative is not None:
            inner = [c for c in alternative.named_children if c.type != "comment"]
            if len(inner) == 1 and inner[0].type == "if_statement":
                self.statements += 1
                self._if(stack, inner[0], builder, CK_ELIF)
            else:
                else_block = self._new(CK_BLOCK, "", builder)
                for child in inner:
                    self._push_block(stack, child, else_block)
        consequence = node.child_by_field_name("consequence")
        if consequence is not None:
            self._push_block(stack, consequence, then_block)

    def _loop(self, stack: list[tuple[str, Node, _Builder]], node: Node, parent: _Builder) -> None:
        label = LOOP_FOR
        if node.type == "while_statement":
            label = LOOP_WHILE
        elif node.type == "do_statement":
            label = LOOP_DO
        loop = self._new(CK_LOOP, label, parent)
        condition = self._new(CK_EXPR, "", loop)
        body_block = self._new(CK_BLOCK, "", loop)
        body = node.child_by_field_name("body")
        if body is not None:
            self._push_block(stack, body, body_block)
        if node.type == "for_in_statement":
            left = node.child_by_field_name("left")
            if left is not None:
                self.locals.update(pattern_names(left))
            self._expr(stack, node.child_by_field_name("right"), condition)
            self._expr(stack, left, condition)
        elif node.type == "for_statement":
            initializer = node.child_by_field_name("initializer")
            if initializer is not None and initializer.type in DECLARATION_TYPES:
                for declarator in initializer.named_children:
                    name = declarator.child_by_field_name("name")
                    if name is not None:
                        self.locals.update(pattern_names(name))
            self._expr(stack, node.child_by_field_name("increment"), condition)
            self._expr(stack, node.child_by_field_name("condition"), condition)
            self._expr(stack, initializer, condition)
        else:
            self._expr(stack, node.child_by_field_name("condition"), condition)

    def _try(self, stack: list[tuple[str, Node, _Builder]], node: Node, parent: _Builder) -> None:
        builder = self._new(CK_TRY, "", parent)
        body = self._new(CK_BLOCK, "", builder)
        handler = node.child_by_field_name("handler")
        finalizer = node.child_by_field_name("finalizer")
        handler_block: _Builder | None = None
        if handler is not None:
            handler_block = self._new(CK_HANDLER, "", builder)
            parameter = handler.child_by_field_name("parameter")
            if parameter is not None:
                self.locals.update(pattern_names(parameter))
        finally_block: _Builder | None = None
        if finalizer is not None:
            finally_block = self._new(CK_FINALLY, "", builder)
            finally_body = finalizer.child_by_field_name("body")
            if finally_body is not None:
                self._push_block(stack, finally_body, finally_block)
        if handler is not None and handler_block is not None:
            handler_body = handler.child_by_field_name("body")
            if handler_body is not None:
                self._push_block(stack, handler_body, handler_block)
        try_body = node.child_by_field_name("body")
        if try_body is not None:
            self._push_block(stack, try_body, body)

    def _switch(
        self, stack: list[tuple[str, Node, _Builder]], node: Node, parent: _Builder
    ) -> None:
        builder = self._new(CK_SWITCH, "", parent)
        subject = self._new(CK_EXPR, "", builder)
        body = node.child_by_field_name("body")
        cases: list[tuple[Node, _Builder, _Builder]] = []
        if body is not None:
            for case in body.named_children:
                if case.type not in ("switch_case", "switch_default"):
                    continue
                label = CASE_DEFAULT if case.type == "switch_default" else ""
                case_builder = self._new(CK_CASE, label, builder)
                guard = self._new(CK_EXPR, "", case_builder)
                case_body = self._new(CK_BLOCK, "", case_builder)
                cases.append((case, guard, case_body))
        for case, guard, case_body in reversed(cases):
            statements = [c for c in case.named_children if c.type != "comment"]
            value = case.child_by_field_name("value")
            if value is not None:
                statements = [c for c in statements if c.id != value.id]
            self._push_statements(stack, statements, case_body)
            self._expr(stack, value, guard)
        self._expr(stack, node.child_by_field_name("value"), subject)

    # -- expressions --------------------------------------------------------

    def _expression(
        self, stack: list[tuple[str, Node, _Builder]], node: Node, parent: _Builder
    ) -> None:
        kind = node.type
        if kind == "comment":
            return
        if kind in UNIT_TYPES:
            # The body is a separate unit; parameter defaults are evaluated here.
            parameters = node.child_by_field_name("parameters")
            if parameters is not None:
                self._parameter_defaults(stack, parameters, parent)
            return
        if kind == "binary_expression":
            operator = node.child_by_field_name("operator")
            if operator is not None and node_text(operator) in BOOLEAN_OPERATORS:
                operators, leaves = _boolean_operators(node)
                parent.operators += len(operators)
                parent.sequences += count_runs(operators)
                for leaf in reversed(leaves):
                    self._expr(stack, leaf, parent)
                return
        elif kind == "augmented_assignment_expression":
            operator = node.child_by_field_name("operator")
            if operator is not None and node_text(operator) in LOGICAL_ASSIGNMENTS:
                parent.operators += 1
                parent.sequences += 1
            self._write(node.child_by_field_name("left"), WRITE_ASSIGN)
        elif kind == "assignment_expression":
            left = node.child_by_field_name("left")
            self._write(left, WRITE_ASSIGN)
            if left is not None and left.type in ("object_pattern", "array_pattern"):
                for name in pattern_names(left):
                    self._write_name(name)
        elif kind == "update_expression":
            self._write(node.child_by_field_name("argument"), WRITE_ASSIGN)
        elif kind == "unary_expression":
            operator = node.child_by_field_name("operator")
            argument = node.child_by_field_name("argument")
            if operator is not None and node_text(operator) == "delete" and argument is not None:
                self._write(argument, WRITE_MUTATE)
        elif kind == "ternary_expression":
            conditional = self._new(CK_CONDITIONAL, "", parent)
            condition = self._new(CK_EXPR, "", conditional)
            then_part = self._new(CK_EXPR, "", conditional)
            else_part = self._new(CK_EXPR, "", conditional)
            self._expr(stack, node.child_by_field_name("alternative"), else_part)
            self._expr(stack, node.child_by_field_name("consequence"), then_part)
            self._expr(stack, node.child_by_field_name("condition"), condition)
            return
        elif kind in ("call_expression", "new_expression"):
            self._call(node, parent)
        for child in reversed(node.named_children):
            self._expr(stack, child, parent)

    def _write(self, target: Node | None, kind: str) -> None:
        if target is None:
            return
        if target.type == "identifier":
            if kind == WRITE_ASSIGN:
                self._write_name(node_text(target))
            return
        root = _root_identifier(target)
        if root is not None and target.type in ("member_expression", "subscript_expression"):
            self.mutate_candidates.append(root)

    def _write_name(self, name: str) -> None:
        self.assign_candidates.append(name)

    def _call(self, node: Node, parent: _Builder) -> None:
        span = node_span(self.source, node)
        arguments = node.child_by_field_name("arguments")
        if node.type == "new_expression":
            self._new_call(node, span)
            self._arguments(arguments)
            return
        function = node.child_by_field_name("function")
        if function is None:
            return
        callee = _unwrap(function)
        if callee.type == IMPORT_CALL:
            return  # dynamic import: an import fact, not a call
        if callee.type == "identifier":
            name = node_text(callee)
            if name == REQUIRE:
                return  # CommonJS import: an import fact, not a call
            self.calls.append(CallSite(span, name, CALL_NAME, False))
            if name == self.own_name:
                self._new(CK_RECURSION, "", parent)
        elif callee.type == "member_expression":
            self._member_call(callee, span, arguments, parent)
        else:
            self.calls.append(CallSite(span, _excerpt(callee), CALL_DYNAMIC, False))
        self._arguments(arguments)

    def _new_call(self, node: Node, span: Span) -> None:
        constructor = node.child_by_field_name("constructor")
        if constructor is None:
            return
        dotted = _dotted(_unwrap(constructor))
        if dotted is None:
            self.calls.append(CallSite(span, _excerpt(constructor), CALL_DYNAMIC, False))
        else:
            self.calls.append(CallSite(span, dotted, CALL_NEW, False))

    def _member_call(
        self, callee: Node, span: Span, arguments: Node | None, parent: _Builder
    ) -> None:
        dotted = _dotted(callee)
        if dotted is None:
            self.calls.append(CallSite(span, _excerpt(callee), CALL_DYNAMIC, False))
            return
        receiver = dotted.split(".")[0] == RECEIVER
        self.calls.append(CallSite(span, dotted, CALL_ATTRIBUTE, receiver))
        if receiver and self.unit.kind == UNIT_METHOD and dotted == f"{RECEIVER}.{self.own_name}":
            self._new(CK_RECURSION, "", parent)
        self._mutation_through_call(callee, dotted, arguments)

    def _mutation_through_call(self, callee: Node, dotted: str, arguments: Node | None) -> None:
        """``x.push(v)`` and ``Object.assign(x, ...)`` write to ``x``."""
        prop = callee.child_by_field_name("property")
        obj = callee.child_by_field_name("object")
        if prop is not None and obj is not None and obj.type == "identifier":
            if node_text(prop) in MUTATING_METHODS:
                self.mutate_candidates.append(node_text(obj))
        if dotted != OBJECT_ASSIGN or arguments is None:
            return
        first = [a for a in arguments.named_children if a.type != "comment"]
        if len(first) > 0 and first[0].type == "identifier":
            self.mutate_candidates.append(node_text(first[0]))

    def _arguments(self, arguments: Node | None) -> None:
        if arguments is None:
            return
        for argument in arguments.named_children:
            if argument.type == "identifier":
                self.calls.append(
                    CallSite(
                        node_span(self.source, argument), node_text(argument), CALL_ARGUMENT, False
                    )
                )
            elif argument.type == "spread_element":
                inner = [c for c in argument.named_children if c.type != "comment"]
                if len(inner) == 1 and inner[0].type == "identifier":
                    self.calls.append(
                        CallSite(
                            node_span(self.source, inner[0]),
                            node_text(inner[0]),
                            CALL_ARGUMENT,
                            False,
                        )
                    )

    # -- driver -------------------------------------------------------------

    def _seed(self, stack: list[tuple[str, Node, _Builder]]) -> None:
        """Push the unit's own body: parameters bind locals, the body is a block or expression."""
        node = self.unit.node
        if node.type in FUNCTION_TYPES:
            for field_name in ("parameters", "parameter"):
                bound = node.child_by_field_name(field_name)
                if bound is not None:
                    self.locals.update(pattern_names(bound))
            body = node.child_by_field_name("body")
            if body is None:
                return
            if body.type == "statement_block":
                self._push_block(stack, body, self.root)
            else:
                self._expr(stack, body, self._new(CK_EXPR, "", self.root))
            return
        container = node
        if node.type in CLASS_TYPES:
            body = node.child_by_field_name("body")
            if body is None:
                return
            container = body
        members = [c for c in container.named_children if c.type != "comment"]
        self._push_statements(stack, members, self.root)

    def _method_member(
        self, stack: list[tuple[str, Node, _Builder]], node: Node, parent: _Builder
    ) -> None:
        """A method of a class body: one statement of the class unit, its own unit otherwise."""
        self.statements += 1
        self.locals.add(_method_name(node))
        parameters = node.child_by_field_name("parameters")
        if parameters is not None:
            self._parameter_defaults(stack, parameters, self._new(CK_EXPR, "", parent))

    def run(self) -> None:
        stack: list[tuple[str, Node, _Builder]] = []
        self._seed(stack)
        while len(stack) > 0:
            task, payload, parent = stack.pop()
            if task != _T_STATEMENT:
                self._expression(stack, payload, parent)
            elif payload.type == "method_definition":
                self._method_member(stack, payload, parent)
            else:
                self._statement(stack, payload, parent)

    def freeze(self) -> ControlNode:
        for builder in reversed(self.builders):
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
        assert self.root.frozen is not None
        return self.root.frozen

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


def _method_name(node: Node) -> str:
    name = node.child_by_field_name("name")
    if name is None:
        return ""
    return node_text(name)


def _own_name(unit: _UnitInfo) -> str | None:
    node = unit.node
    if node.type == "method_definition":
        return _method_name(node)
    if node.type in FUNCTION_TYPES:
        name = node.child_by_field_name("name")
        if name is not None:
            return node_text(name)
        parent = node.parent
        if parent is not None and parent.type == "variable_declarator":
            bound = parent.child_by_field_name("name")
            if bound is not None and bound.type == "identifier":
                return node_text(bound)
    return None


def _parameter_count(node: Node) -> int:
    if node.type not in FUNCTION_TYPES:
        return 0
    parameters = node.child_by_field_name("parameters")
    if parameters is None:
        # `x => ...`: a single parameter without parentheses
        return 1 if node.child_by_field_name("parameter") is not None else 0
    return sum(1 for c in parameters.named_children if c.type != "comment")


def _unit_span(source: SourceText, node: Node) -> Span:
    if node.type == "program":
        last_line = max(source.line_count, FIRST_LINE)
        return Span(FIRST_LINE, FIRST_COLUMN, last_line, len(source.line_text(last_line)) + 1)
    return node_span(source, node)


def _is_generator(node: Node) -> bool:
    if node.type in GENERATOR_TYPES:
        return True
    if node.type == "method_definition":
        return any(c.type == "*" for c in node.children if not c.is_named)
    return False


def collect_javascript_functions(
    source: SourceText, root: Node, comments: Sequence[Comment]
) -> tuple[FunctionFact, ...]:
    units = _discover_units(root)
    spans = [_unit_span(source, unit.node) for unit in units]
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
                    in ("arrow_function", "function_expression", "generator_function", "class"),
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


def _specifier_names(clause: Node, specifier_type: str) -> list[tuple[str, str]]:
    """``{a, b as c}`` of an import or export clause as (name, local) pairs."""
    names: list[tuple[str, str]] = []
    for specifier in clause.named_children:
        if specifier.type != specifier_type:
            continue
        name = specifier.child_by_field_name("name")
        if name is None:
            continue
        names.append((node_text(name), _local_name(name, specifier.child_by_field_name("alias"))))
    return names


def _namespace_name(node: Node) -> str | None:
    inner = [c for c in node.named_children if c.type == "identifier"]
    if len(inner) == 1:
        return node_text(inner[0])
    return None


def _import_clause(span: Span, module: str, clause: Node) -> list[ImportFact]:
    facts: list[ImportFact] = []
    names: list[tuple[str, str]] = []
    for child in clause.named_children:
        if child.type == "identifier":
            names.append((DEFAULT_EXPORT, node_text(child)))
        elif child.type == "namespace_import":
            namespace = _namespace_name(child)
            if namespace is not None:
                facts.append(ImportFact(span, IMPORT_MODULE, module, 0, (("", namespace),)))
        elif child.type == "named_imports":
            names.extend(_specifier_names(child, "import_specifier"))
    if len(names) > 0 or len(facts) == 0:
        facts.append(ImportFact(span, IMPORT_NAMES, module, 0, tuple(names)))
    return facts


def _statement_module(statement: Node) -> str | None:
    """The literal specifier of an import/export statement, if it has one."""
    source_node = statement.child_by_field_name("source")
    if source_node is None:
        return None
    return string_value(source_node)


def _import_statement(source: SourceText, statement: Node) -> list[ImportFact]:
    module = _statement_module(statement)
    if module is None:
        return []
    span = Span(FIRST_LINE, FIRST_COLUMN, FIRST_LINE, FIRST_COLUMN)
    if source.text != "":
        span = node_span(source, statement)
    clauses = [c for c in statement.named_children if c.type == "import_clause"]
    if len(clauses) == 0:
        return [ImportFact(span, IMPORT_MODULE, module, 0, ())]
    return _import_clause(span, module, clauses[0])


def _export_statement(source: SourceText, statement: Node) -> list[ImportFact]:
    module = _statement_module(statement)
    if module is None:
        return []
    names: list[tuple[str, str]] = []
    for child in statement.named_children:
        if child.type == "export_clause":
            names.extend(_specifier_names(child, "export_specifier"))
        elif child.type == "namespace_export":
            namespace = _namespace_name(child)
            if namespace is not None:
                names.append((STAR, namespace))
    if len(names) == 0:
        names.append((STAR, STAR))
    return [ImportFact(node_span(source, statement), IMPORT_REEXPORT, module, 0, tuple(names))]


def _require_target(call: Node) -> tuple[str | None, bool]:
    """(module specifier, is_require) for ``require(...)`` and ``import(...)`` calls."""
    function = call.child_by_field_name("function")
    arguments = call.child_by_field_name("arguments")
    if function is None or arguments is None:
        return None, False
    callee = _unwrap(function)
    if (callee.type == "identifier" and node_text(callee) == REQUIRE) or callee.type == IMPORT_CALL:
        pass
    else:
        return None, False
    actual = [a for a in arguments.named_children if a.type != "comment"]
    if len(actual) == 0:
        return None, True
    return string_value(actual[0]), True


def collect_javascript_imports(source: SourceText, root: Node) -> tuple[ImportFact, ...]:
    imports: list[ImportFact] = []
    stack = [root]
    while len(stack) > 0:
        node = stack.pop()
        if node.type == "import_statement":
            imports.extend(_import_statement(source, node))
            continue
        if node.type == "export_statement":
            imports.extend(_export_statement(source, node))
        if node.type == "call_expression":
            module, is_import = _require_target(node)
            if is_import:
                span = node_span(source, node)
                if module is None:
                    imports.append(ImportFact(span, IMPORT_DYNAMIC, _excerpt(node), 0, ()))
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
    if parent is not None and parent.type == "variable_declarator":
        name = parent.child_by_field_name("name")
        if name is not None and name.type == "object_pattern":
            return IMPORT_NAMES
    return IMPORT_MODULE


def _require_names(call: Node) -> tuple[tuple[str, str], ...]:
    parent = call.parent
    if parent is None or parent.type != "variable_declarator":
        return ()
    name = parent.child_by_field_name("name")
    if name is None:
        return ()
    if name.type == "identifier":
        return (("", node_text(name)),)
    if name.type == "object_pattern":
        names: list[tuple[str, str]] = []
        for child in name.named_children:
            if child.type == "shorthand_property_identifier_pattern":
                names.append((node_text(child), node_text(child)))
            elif child.type == "pair_pattern":
                key = child.child_by_field_name("key")
                value = child.child_by_field_name("value")
                if key is not None and value is not None and value.type == "identifier":
                    names.append((node_text(key), node_text(value)))
        return tuple(names)
    return ()


def _is_mutable_value(value: Node | None) -> bool:
    if value is None:
        return False
    unwrapped = _unwrap(value)
    if unwrapped.type in ("object", "array"):
        return True
    if unwrapped.type == "new_expression":
        constructor = unwrapped.child_by_field_name("constructor")
        return constructor is not None and node_text(constructor) in MUTABLE_CONSTRUCTORS
    return False


def _declarator_bindings(declarator: Node, reassignable: bool, span: Span) -> list[ModuleBinding]:
    name = declarator.child_by_field_name("name")
    value = declarator.child_by_field_name("value")
    if name is None:
        return []
    if value is not None and value.type == "call_expression":
        _module, is_import = _require_target(value)
        if is_import:
            return [
                ModuleBinding(local, BINDING_IMPORT, False, span)
                for _imported, local in _require_names(value)
            ]
    if name.type == "identifier" and value is not None:
        if value.type in FUNCTION_TYPES:
            return [ModuleBinding(node_text(name), BINDING_FUNCTION, False, span)]
        if value.type in CLASS_TYPES:
            return [ModuleBinding(node_text(name), BINDING_CLASS, False, span)]
    mutable = reassignable or _is_mutable_value(value)
    return [ModuleBinding(bound, BINDING_VARIABLE, mutable, span) for bound in pattern_names(name)]


def _declaration_bindings(node: Node, span: Span) -> list[ModuleBinding]:
    kind_node = node.child_by_field_name("kind")
    reassignable = node.type == "variable_declaration" or (
        kind_node is not None and node_text(kind_node) != "const"
    )
    found: list[ModuleBinding] = []
    for declarator in node.named_children:
        if declarator.type == "variable_declarator":
            found.extend(_declarator_bindings(declarator, reassignable, span))
    return found


def _statement_bindings(node: Node, span: Span) -> list[ModuleBinding]:
    if node.type in ("function_declaration", "generator_function_declaration", "class_declaration"):
        name = node.child_by_field_name("name")
        if name is None:
            return []
        kind = BINDING_CLASS if node.type == "class_declaration" else BINDING_FUNCTION
        return [ModuleBinding(node_text(name), kind, False, span)]
    if node.type == "import_statement":
        return [
            ModuleBinding(local, BINDING_IMPORT, False, span) for local in _import_bound_names(node)
        ]
    if node.type in DECLARATION_TYPES:
        return _declaration_bindings(node, span)
    return []


def collect_javascript_bindings(source: SourceText, root: Node) -> tuple[ModuleBinding, ...]:
    bindings: dict[str, ModuleBinding] = {}
    for statement in root.named_children:
        node = statement
        if node.type == "export_statement":
            declaration = node.child_by_field_name("declaration")
            if declaration is None:
                continue
            node = declaration
        for binding in _statement_bindings(node, node_span(source, statement)):
            bindings[binding.name] = binding
    return tuple(sorted(bindings.values(), key=lambda b: (b.span, b.name)))
