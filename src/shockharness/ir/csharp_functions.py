"""Function facts for C#: every unit's control tree, size, calls, locals and writes.

Units are the compilation unit (top-level statements), each type body (class, struct,
record, interface, enum: field and property initializers), each method, constructor,
destructor, operator, local function, lambda and anonymous method, each property or
indexer accessor with a body, and each expression-bodied property or indexer. Namespaces
do not qualify names: a unit is named within its file (``Player._Ready``), as Python and
JavaScript units are. The traversal is iterative and stops at nested units, as the
JavaScript adapter's does, so equivalent code gives the same tree.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from tree_sitter import Node

from shockharness.ir.csharp_nodes import Field, Kind
from shockharness.ir.javascript_catches import node_span, node_text
from shockharness.ir.javascript_functions import Builder, freeze_builders, new_builder
from shockharness.ir.lines import logical_line_count
from shockharness.ir.model import (
    ANONYMOUS_SCOPE,
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
MEMBER_CHAINS = (Kind.MEMBER_ACCESS_EXPRESSION, "element_access_expression")
TYPE_DECLARATIONS = frozenset(
    {
        Kind.CLASS_DECLARATION,
        Kind.STRUCT_DECLARATION,
        Kind.RECORD_DECLARATION,
        Kind.INTERFACE_DECLARATION,
        Kind.ENUM_DECLARATION,
    }
)
MEMBER_FUNCTIONS = frozenset(
    {
        Kind.METHOD_DECLARATION,
        Kind.CONSTRUCTOR_DECLARATION,
        Kind.DESTRUCTOR_DECLARATION,
        Kind.OPERATOR_DECLARATION,
        Kind.CONVERSION_OPERATOR_DECLARATION,
    }
)
EXPRESSION_FUNCTIONS = frozenset({Kind.LAMBDA_EXPRESSION, Kind.ANONYMOUS_METHOD_EXPRESSION})
FUNCTION_TYPES = MEMBER_FUNCTIONS | EXPRESSION_FUNCTIONS | {Kind.LOCAL_FUNCTION_STATEMENT}
PROPERTY_TYPES = frozenset({Kind.PROPERTY_DECLARATION, Kind.INDEXER_DECLARATION})
LOOP_STATEMENTS = frozenset(
    {Kind.FOR_STATEMENT, Kind.FOREACH_STATEMENT, Kind.WHILE_STATEMENT, Kind.DO_STATEMENT}
)
# Statements whose body adds nothing to the control tree and does not nest.
WRAPPING_STATEMENTS = frozenset(
    {
        Kind.USING_STATEMENT,
        Kind.LOCK_STATEMENT,
        Kind.CHECKED_STATEMENT,
        Kind.UNSAFE_STATEMENT,
        Kind.FIXED_STATEMENT,
    }
)
BOOLEAN_OPERATORS = frozenset({"&&", "||", "??"})
PATTERN_COMBINATORS = {Kind.AND_PATTERN: "and", Kind.OR_PATTERN: "or"}
LOGICAL_ASSIGNMENT = "??="
INCREMENTS = frozenset({"++", "--"})
ACCESSOR_KEYWORDS = frozenset({"get", "set", "init", "add", "remove"})
VALUE_ACCESSORS = frozenset({"set", "init", "add", "remove"})
IMPLICIT_VALUE = "value"
ASYNC_MODIFIER = "async"
RECEIVER = "this"
BASE = "base"
INDEXER_NAME = "this[]"
DISCARD = "_"

_T_STATEMENT = "statement"
_T_EXPRESSION = "expression"


@dataclass(frozen=True)
class UnitInfo:
    node: Node
    name: str
    kind: str
    class_name: str | None


def _accessor_keyword(node: Node) -> str:
    for child in node.children:
        if not child.is_named and node_text(child) in ACCESSOR_KEYWORDS:
            return node_text(child)
    return ""


def is_unit(node: Node) -> bool:
    if node.type in TYPE_DECLARATIONS or node.type in FUNCTION_TYPES:
        return True
    if node.type == Kind.ACCESSOR_DECLARATION:
        return node.child_by_field_name(Field.BODY) is not None
    if node.type in PROPERTY_TYPES:
        value = node.child_by_field_name(Field.VALUE)
        return value is not None and value.type == Kind.ARROW_EXPRESSION_CLAUSE
    return False


def _own_name(node: Node) -> str:
    """The name a unit or scope node contributes to qualified names."""
    if node.type == Kind.INDEXER_DECLARATION:
        return INDEXER_NAME
    if node.type == Kind.ACCESSOR_DECLARATION:
        return _accessor_keyword(node)
    if node.type in EXPRESSION_FUNCTIONS:
        return _binding_name(node)
    if node.type == Kind.DESTRUCTOR_DECLARATION:
        return "~" + _declared_name(node)
    if node.type in (Kind.OPERATOR_DECLARATION, Kind.CONVERSION_OPERATOR_DECLARATION):
        return "operator"
    return _declared_name(node)


def _declared_name(node: Node) -> str:
    name = node.child_by_field_name(Field.NAME)
    if name is None:
        return ANONYMOUS_SCOPE
    return node_text(name)


def _binding_name(node: Node) -> str:
    """Best-effort name of a lambda: the variable, member or argument it is bound to."""
    parent = node.parent
    if parent is None:
        return ANONYMOUS_SCOPE
    if parent.type == Kind.VARIABLE_DECLARATOR:
        name = parent.child_by_field_name(Field.NAME)
        if name is not None:
            return node_text(name)
    if parent.type == Kind.ASSIGNMENT_EXPRESSION:
        left = parent.child_by_field_name(Field.LEFT)
        if left is not None:
            _receiver, _dot, member = node_text(left).rpartition(".")
            return member
    return ANONYMOUS_SCOPE


def scope_for(node: Node, scope: str) -> str:
    """The qualified scope inside ``node``: types, functions and accessors add their name
    (``Player.Speed.get``); other nodes, namespaces included, keep ``scope``."""
    if not (
        node.type in TYPE_DECLARATIONS
        or node.type in FUNCTION_TYPES
        or node.type in PROPERTY_TYPES
        or node.type == Kind.ACCESSOR_DECLARATION
    ):
        return scope
    name = _own_name(node)
    if scope == MODULE_SCOPE:
        return name
    return f"{scope}.{name}"


def _unit_kind(node: Node, class_name: str | None) -> str:
    if node.type == Kind.COMPILATION_UNIT:
        return UNIT_MODULE
    if node.type in TYPE_DECLARATIONS:
        return UNIT_CLASS
    if node.type == Kind.LAMBDA_EXPRESSION:
        return UNIT_ARROW
    if node.type in (Kind.LOCAL_FUNCTION_STATEMENT, Kind.ANONYMOUS_METHOD_EXPRESSION):
        return UNIT_FUNCTION
    return UNIT_METHOD if class_name is not None else UNIT_FUNCTION


def discover_units(  # shockharness: ignore[DUP002] reason="C#'s own type and member kinds"
    root: Node,
) -> list[UnitInfo]:
    units: list[UnitInfo] = [UnitInfo(root, MODULE_SCOPE, UNIT_MODULE, None)]
    stack: list[tuple[Node, str, str | None]] = [(root, MODULE_SCOPE, None)]
    while len(stack) > 0:
        node, scope, class_name = stack.pop()
        child_scope = scope_for(node, scope)
        child_class = class_name
        if node.type in TYPE_DECLARATIONS:
            units.append(UnitInfo(node, child_scope, UNIT_CLASS, class_name))
            child_class = child_scope
        elif is_unit(node):
            units.append(UnitInfo(node, child_scope, _unit_kind(node, class_name), class_name))
            child_class = None
        for child in reversed(node.children):
            stack.append((child, child_scope, child_class))
    units.sort(key=lambda u: (u.node.start_byte, -u.node.end_byte))
    return units


def _simple_name(node: Node) -> str | None:
    """``M`` for an identifier, ``M`` for ``M<T>``."""
    if node.type == Kind.IDENTIFIER:
        return node_text(node)
    if node.type == Kind.GENERIC_NAME:
        for child in node.named_children:
            if child.type == Kind.IDENTIFIER:
                return node_text(child)
    return None


def dotted_name(node: Node) -> str | None:
    """``a.b.C`` for a member access chain rooted in a name, ``this``, ``base`` or a
    predefined type (``int.TryParse``); ``None`` when a link is computed."""
    parts: list[str] = []
    current = node
    while current.type == Kind.MEMBER_ACCESS_EXPRESSION:
        name = current.child_by_field_name(Field.NAME)
        expression = current.child_by_field_name(Field.EXPRESSION)
        simple = _simple_name(name) if name is not None else None
        if simple is None or expression is None:
            return None
        parts.append(simple)
        current = expression
    if current.type in (RECEIVER, BASE, Kind.PREDEFINED_TYPE):
        parts.append(node_text(current))
    else:
        root = _simple_name(current)
        if root is None:
            return None
        parts.append(root)
    parts.reverse()
    return ".".join(parts)


def _flatten(root: Node) -> tuple[list[str], list[Node]]:
    """Operators of a ``&&``/``||``/``??`` chain or an ``and``/``or`` pattern chain in
    source order, and its leaves."""
    operators: list[str] = []
    leaves: list[Node] = []
    stack: list[Node | str] = [root]
    while len(stack) > 0:
        item = stack.pop()
        if isinstance(item, str):
            operators.append(item)
            continue
        node = unwrap_parentheses(item)
        operator = _chain_operator(node)
        left = node.child_by_field_name(Field.LEFT)
        right = node.child_by_field_name(Field.RIGHT)
        if operator is not None and left is not None and right is not None:
            stack.append(right)
            stack.append(operator)
            stack.append(left)
            continue
        leaves.append(item)
    return operators, leaves


def _chain_operator(node: Node) -> str | None:
    if node.type in PATTERN_COMBINATORS:
        return PATTERN_COMBINATORS[node.type]
    if node.type != Kind.BINARY_EXPRESSION:
        return None
    operator = node.child_by_field_name(Field.OPERATOR)
    if operator is None or node_text(operator) not in BOOLEAN_OPERATORS:
        return None
    return node_text(operator)


def designated_names(node: Node) -> list[str]:
    """Every name a pattern, declaration expression or tuple designation introduces
    (``is Foo f``, ``out var x``, ``var (a, b)``, ``foreach (var (i, j) in ...)``)."""
    names: list[str] = []
    stack = [node]
    while len(stack) > 0:
        current = stack.pop()
        if current.type in (
            Kind.DECLARATION_PATTERN,
            Kind.RECURSIVE_PATTERN,
            Kind.DECLARATION_EXPRESSION,
        ):
            name = current.child_by_field_name(Field.NAME)
            if name is not None and name.type == Kind.IDENTIFIER:
                names.append(node_text(name))
            elif name is not None:
                stack.append(name)
        elif (
            current.type == Kind.IDENTIFIER
            and current.parent is not None
            and (
                current.parent.type
                in (Kind.VAR_PATTERN, Kind.PARENTHESIZED_VARIABLE_DESIGNATION, Kind.TUPLE_PATTERN)
            )
        ):
            names.append(node_text(current))
        stack.extend(c for c in current.named_children if c.type not in FUNCTION_TYPES)
    return [name for name in names if name != DISCARD]


_Handler = Callable[[list[tuple[str, Node, Builder]], Node, Builder], None]
# Statements that run nothing: namespace names, using directives, attributes.
SKIPPED_STATEMENTS = frozenset(
    {
        Kind.COMMENT,
        Kind.EMPTY_STATEMENT,
        Kind.ATTRIBUTE_LIST,
        Kind.IDENTIFIER,
        Kind.QUALIFIED_NAME,
        Kind.USING_DIRECTIVE,
        Kind.FILE_SCOPED_NAMESPACE_DECLARATION,
    }
)
# Statements whose members are statements of the same unit.
CONTAINERS = frozenset({Kind.BLOCK, Kind.GLOBAL_STATEMENT, Kind.DECLARATION_LIST})


def _members(node: Node) -> list[Node]:
    return [c for c in node.named_children if c.type != Kind.COMMENT]


def _named_of_type(node: Node | None, kind: str) -> list[Node]:
    if node is None:
        return []
    return [c for c in node.named_children if c.type == kind]


def _body_of(node: Node) -> Node | None:
    """A function's or statement's body: its ``body`` field, else its last block."""
    body = node.child_by_field_name(Field.BODY)
    if body is not None:
        return body
    for child in reversed(node.named_children):
        if child.type == Kind.BLOCK:
            return child
    return None


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
        self.yields = False
        self.own_name = _own_name(unit.node) if unit.node.type in FUNCTION_TYPES else None
        self.handlers = self._statement_handlers()

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
        if body.type == Kind.BLOCK:
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

    def _expr_children(
        self, stack: list[tuple[str, Node, Builder]], node: Node, parent: Builder
    ) -> None:
        for child in reversed(node.named_children):
            if child.type != Kind.COMMENT:
                self._expr(stack, child, parent)

    # -- statements -------------------------------------------------------------------

    def _statement(
        self, stack: list[tuple[str, Node, Builder]], node: Node, parent: Builder
    ) -> None:
        kind = node.type
        if kind in SKIPPED_STATEMENTS:
            return
        if kind in CONTAINERS:
            self._push_statements(stack, _members(node), parent)
            return
        self.statements += 1
        if kind in self.handlers:
            self.handlers[kind](stack, node, parent)
        elif kind in TYPE_DECLARATIONS or kind in FUNCTION_TYPES or kind in PROPERTY_TYPES:
            self._member(stack, node, parent)
        else:
            self._expr_children(stack, node, self._new(CK_EXPR, "", parent))

    def _statement_handlers(self) -> dict[str, _Handler]:
        """The statement kinds with their own control shape, each to its handler."""
        handlers: dict[str, _Handler] = {
            Kind.IF_STATEMENT: self._if_statement,
            Kind.TRY_STATEMENT: self._try,
            Kind.SWITCH_STATEMENT: self._switch,
            Kind.LABELED_STATEMENT: self._labeled,
            Kind.GOTO_STATEMENT: self._goto,
            Kind.YIELD_STATEMENT: self._yield,
            Kind.FIELD_DECLARATION: self._declarations,
            Kind.EVENT_FIELD_DECLARATION: self._declarations,
            Kind.LOCAL_DECLARATION_STATEMENT: self._declarations,
            Kind.ENUM_MEMBER_DECLARATION: self._enum_member,
            Kind.DELEGATE_DECLARATION: self._declared,
            Kind.EVENT_DECLARATION: self._declared,
            Kind.NAMESPACE_DECLARATION: self._namespace,
        }
        for loop in LOOP_STATEMENTS:
            handlers[loop] = self._loop
        for wrapping in WRAPPING_STATEMENTS:
            handlers[wrapping] = self._wrapping
        return handlers

    def _if_statement(
        self, stack: list[tuple[str, Node, Builder]], node: Node, parent: Builder
    ) -> None:
        self._if(stack, node, parent, CK_IF)

    def _labeled(self, stack: list[tuple[str, Node, Builder]], node: Node, parent: Builder) -> None:
        """``label: statement``: the label is not a statement of its own."""
        self.statements -= 1
        inner = [c for c in node.named_children if c.type != Kind.IDENTIFIER]
        self._push_statements(stack, inner, parent)

    def _goto(self, _stack: list[tuple[str, Node, Builder]], _node: Node, parent: Builder) -> None:
        jump = self._new(CK_JUMP, "", parent)
        jump.labeled = True

    def _yield(self, stack: list[tuple[str, Node, Builder]], node: Node, parent: Builder) -> None:
        self.yields = True
        self._expr_children(stack, node, self._new(CK_EXPR, "", parent))

    def _declarations(
        self, stack: list[tuple[str, Node, Builder]], node: Node, parent: Builder
    ) -> None:
        for child in node.named_children:
            if child.type == Kind.VARIABLE_DECLARATION:
                self._declaration(stack, child, parent)

    def _enum_member(
        self, stack: list[tuple[str, Node, Builder]], node: Node, parent: Builder
    ) -> None:
        self._expr(stack, node.child_by_field_name(Field.VALUE), self._new(CK_EXPR, "", parent))

    def _declared(
        self, _stack: list[tuple[str, Node, Builder]], node: Node, _parent: Builder
    ) -> None:
        """A delegate or event declaration binds its name and runs nothing."""
        name = node.child_by_field_name(Field.NAME)
        if name is not None:
            self.locals.add(node_text(name))

    def _namespace(
        self, stack: list[tuple[str, Node, Builder]], node: Node, parent: Builder
    ) -> None:
        """``namespace N { ... }``: its members are statements of the enclosing unit."""
        self.statements -= 1
        body = node.child_by_field_name(Field.BODY)
        if body is not None:
            self._push_statements(stack, _members(body), parent)

    def _member(self, stack: list[tuple[str, Node, Builder]], node: Node, parent: Builder) -> None:
        """A nested type, function or property: its name is bound here; a property's
        initializer and the parameter defaults of a nested function are evaluated here."""
        if node.type == Kind.LOCAL_FUNCTION_STATEMENT or node.type in TYPE_DECLARATIONS:
            name = node.child_by_field_name(Field.NAME)
            if name is not None:
                self.locals.add(node_text(name))
        expression = self._new(CK_EXPR, "", parent)
        if node.type in PROPERTY_TYPES:
            value = node.child_by_field_name(Field.VALUE)
            if value is not None and value.type != Kind.ARROW_EXPRESSION_CLAUSE:
                self._expr(stack, value, expression)
            return
        self._parameter_defaults(stack, node, expression)

    def _parameter_defaults(
        self, stack: list[tuple[str, Node, Builder]], node: Node, parent: Builder
    ) -> None:
        parameters = node.child_by_field_name(Field.PARAMETERS)
        if parameters is None or parameters.type != Kind.PARAMETER_LIST:
            return
        for parameter in reversed(parameters.named_children):
            default = _parameter_default(parameter)
            if default is not None:
                self._expr(stack, default, parent)

    def _declaration(
        self, stack: list[tuple[str, Node, Builder]], node: Node, parent: Builder
    ) -> None:
        expression = self._new(CK_EXPR, "", parent)
        for declarator in reversed(node.named_children):
            if declarator.type != Kind.VARIABLE_DECLARATOR:
                continue
            name = declarator.child_by_field_name(Field.NAME)
            if name is not None:
                if name.type == Kind.IDENTIFIER:
                    self.locals.add(node_text(name))
                else:
                    self.locals.update(designated_names(name))
            for child in reversed(declarator.named_children):
                if name is None or child.id != name.id:
                    self._expr(stack, child, expression)

    def _wrapping(
        self, stack: list[tuple[str, Node, Builder]], node: Node, parent: Builder
    ) -> None:
        expression = self._new(CK_EXPR, "", parent)
        body = _body_of(node)
        if body is not None:
            self._push_block(stack, body, parent)
        for child in reversed(node.named_children):
            if body is not None and child.id == body.id:
                continue
            if child.type == Kind.VARIABLE_DECLARATION:
                self._declaration(stack, child, parent)
            elif child.type != Kind.COMMENT:
                self._expr(stack, child, expression)

    def _if(
        self, stack: list[tuple[str, Node, Builder]], node: Node, parent: Builder, kind: str
    ) -> None:
        builder = self._new(kind, "", parent)
        condition = self._new(CK_EXPR, "", builder)
        self._expr(stack, node.child_by_field_name(Field.CONDITION), condition)
        then_block = self._new(CK_BLOCK, "", builder)
        alternative = node.child_by_field_name(Field.ALTERNATIVE)
        if alternative is not None:
            if alternative.type == Kind.IF_STATEMENT:
                self.statements += 1
                self._if(stack, alternative, builder, CK_ELIF)
            else:
                self._push_block(stack, alternative, self._new(CK_BLOCK, "", builder))
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
        if node.type == Kind.FOREACH_STATEMENT:
            left = node.child_by_field_name(Field.LEFT)
            if left is not None:
                if left.type == Kind.IDENTIFIER:
                    self.locals.add(node_text(left))
                else:
                    self.locals.update(designated_names(left))
            self._expr(stack, node.child_by_field_name(Field.RIGHT), condition)
            return
        if node.type == Kind.FOR_STATEMENT:
            initializer = node.child_by_field_name(Field.INITIALIZER)
            if initializer is not None and initializer.type == Kind.VARIABLE_DECLARATION:
                self._declaration(stack, initializer, condition)
            else:
                self._expr(stack, initializer, condition)
            self._expr(stack, node.child_by_field_name(Field.UPDATE), condition)
        self._expr(stack, node.child_by_field_name(Field.CONDITION), condition)

    def _try(self, stack: list[tuple[str, Node, Builder]], node: Node, parent: Builder) -> None:
        builder = self._new(CK_TRY, "", parent)
        body = self._new(CK_BLOCK, "", builder)
        handlers: list[tuple[Node, Builder]] = []
        for clause in node.named_children:
            if clause.type == Kind.CATCH_CLAUSE:
                handlers.append((clause, self._new(CK_HANDLER, "", builder)))
        finalizers = [c for c in node.named_children if c.type == Kind.FINALLY_CLAUSE]
        if len(finalizers) > 0:
            finally_block = self._new(CK_FINALLY, "", builder)
            for child in finalizers[0].named_children:
                if child.type == Kind.BLOCK:
                    self._push_block(stack, child, finally_block)
        for clause, handler in reversed(handlers):
            self._catch(stack, clause, handler)
        try_body = node.child_by_field_name(Field.BODY)
        if try_body is not None:
            self._push_block(stack, try_body, body)

    def _catch(
        self, stack: list[tuple[str, Node, Builder]], clause: Node, handler: Builder
    ) -> None:
        for child in clause.named_children:
            if child.type == Kind.CATCH_DECLARATION:
                name = child.child_by_field_name(Field.NAME)
                if name is not None:
                    self.locals.add(node_text(name))
        body = clause.child_by_field_name(Field.BODY)
        if body is not None:
            self._push_block(stack, body, handler)
        for child in clause.named_children:
            if child.type == Kind.CATCH_FILTER_CLAUSE:
                self._expr_children(stack, child, self._new(CK_EXPR, "", handler))

    def _switch(self, stack: list[tuple[str, Node, Builder]], node: Node, parent: Builder) -> None:
        builder = self._new(CK_SWITCH, "", parent)
        subject = self._new(CK_EXPR, "", builder)
        body = node.child_by_field_name(Field.BODY)
        sections = _named_of_type(body, Kind.SWITCH_SECTION)
        work: list[tuple[list[Node], list[Node], Builder, Builder]] = []
        for section in sections:
            labels, statements = _section_parts(section)
            label = CASE_DEFAULT if _is_default_section(section) else ""
            case = self._new(CK_CASE, label, builder)
            work.append(
                (labels, statements, self._new(CK_EXPR, "", case), self._new(CK_BLOCK, "", case))
            )
        for labels, statements, guard, case_body in reversed(work):
            self._push_statements(stack, statements, case_body)
            for label_node in reversed(labels):
                self._pattern(stack, label_node, guard)
        self._expr(stack, node.child_by_field_name(Field.VALUE), subject)

    def _pattern(self, stack: list[tuple[str, Node, Builder]], node: Node, parent: Builder) -> None:
        self.locals.update(designated_names(node))
        self._expr(stack, node, parent)

    # -- expressions ------------------------------------------------------------------

    def _expression(
        self, stack: list[tuple[str, Node, Builder]], node: Node, parent: Builder
    ) -> None:
        kind = node.type
        if kind == Kind.COMMENT:
            return
        if kind in FUNCTION_TYPES:
            self._parameter_defaults(stack, node, parent)
            return
        if _chain_operator(unwrap_parentheses(node)) is not None:
            operators, leaves = _flatten(node)
            parent.operators += len(operators)
            parent.sequences += count_runs(operators)
            for leaf in reversed(leaves):
                self._expr(stack, leaf, parent)
            return
        if kind == Kind.CONDITIONAL_EXPRESSION:
            self._conditional(stack, node, parent)
            return
        if kind == Kind.SWITCH_EXPRESSION:
            self._switch_expression(stack, node, parent)
            return
        self._record(node, parent)
        self._expr_children(stack, node, parent)

    def _conditional(
        self, stack: list[tuple[str, Node, Builder]], node: Node, parent: Builder
    ) -> None:
        conditional = self._new(CK_CONDITIONAL, "", parent)
        condition = self._new(CK_EXPR, "", conditional)
        then_part = self._new(CK_EXPR, "", conditional)
        else_part = self._new(CK_EXPR, "", conditional)
        self._expr(stack, node.child_by_field_name(Field.ALTERNATIVE), else_part)
        self._expr(stack, node.child_by_field_name(Field.CONSEQUENCE), then_part)
        self._expr(stack, node.child_by_field_name(Field.CONDITION), condition)

    def _record(self, node: Node, parent: Builder) -> None:
        """What an expression adds besides its children: writes, calls, bound names."""
        kind = node.type
        if kind == Kind.ASSIGNMENT_EXPRESSION:
            self._assignment(node, parent)
        elif kind in (Kind.POSTFIX_UNARY_EXPRESSION, Kind.PREFIX_UNARY_EXPRESSION):
            self._increment(node)
        elif kind == Kind.INVOCATION_EXPRESSION:
            self._call(node, parent)
        elif kind in (Kind.OBJECT_CREATION_EXPRESSION, Kind.IMPLICIT_OBJECT_CREATION_EXPRESSION):
            self._new_call(node)
        elif kind in (
            Kind.DECLARATION_EXPRESSION,
            Kind.DECLARATION_PATTERN,
            Kind.RECURSIVE_PATTERN,
        ):
            self.locals.update(designated_names(node))

    def _switch_expression(
        self, stack: list[tuple[str, Node, Builder]], node: Node, parent: Builder
    ) -> None:
        """``x switch { pattern when c => value, _ => other }``: a switch whose arms are
        cases; the discard arm is the default."""
        builder = self._new(CK_SWITCH, "", parent)
        subject = self._new(CK_EXPR, "", builder)
        arms: list[tuple[list[Node], Builder, Builder]] = []
        for arm in _named_of_type(node, Kind.SWITCH_EXPRESSION_ARM):
            parts = [c for c in arm.named_children if c.type != Kind.COMMENT]
            label = CASE_DEFAULT if any(node_text(p) == DISCARD for p in parts[:1]) else ""
            case = self._new(CK_CASE, label, builder)
            arms.append((parts, self._new(CK_EXPR, "", case), self._new(CK_EXPR, "", case)))
        for parts, guard, value in reversed(arms):
            self._arm(stack, parts, guard, value)
        for child in node.named_children:
            if child.type not in (Kind.SWITCH_EXPRESSION_ARM, Kind.COMMENT):
                self._expr(stack, child, subject)

    def _arm(
        self,
        stack: list[tuple[str, Node, Builder]],
        parts: list[Node],
        guard: Builder,
        value: Builder,
    ) -> None:
        """One switch-expression arm: its pattern and ``when`` clause, then its value."""
        if len(parts) == 0:
            return
        *conditions, result = parts
        self._expr(stack, result, value)
        for part in reversed(conditions):
            if part.type == Kind.WHEN_CLAUSE:
                self._expr_children(stack, part, guard)
            else:
                self._pattern(stack, part, guard)

    def _assignment(self, node: Node, parent: Builder) -> None:
        operator = node.child_by_field_name(Field.OPERATOR)
        if operator is not None and node_text(operator) == LOGICAL_ASSIGNMENT:
            parent.operators += 1
            parent.sequences += 1
        self._write(node.child_by_field_name(Field.LEFT), WRITE_ASSIGN)

    def _increment(self, node: Node) -> None:
        tokens = [node_text(c) for c in node.children if not c.is_named]
        operands = node.named_children
        if any(t in INCREMENTS for t in tokens) and len(operands) == 1:
            self._write(operands[0], WRITE_ASSIGN)

    def _write(self, target: Node | None, kind: str) -> None:
        if target is None:
            return
        if target.type == Kind.IDENTIFIER:
            if kind == WRITE_ASSIGN:
                self.assign_candidates.append(node_text(target))
            return
        root = root_identifier(target, MEMBER_CHAINS, Field.EXPRESSION)
        if root is not None:
            self.mutate_candidates.append(root)

    def _call(self, node: Node, parent: Builder) -> None:
        span = node_span(self.source, node)
        function = node.child_by_field_name(Field.FUNCTION)
        if function is not None:
            callee = unwrap_parentheses(function)
            simple = _simple_name(callee)
            if simple is not None:
                self.calls.append(CallSite(span, simple, CALL_NAME, receiver_self=False))
                if simple == self.own_name:
                    self._new(CK_RECURSION, "", parent)
            else:
                self._member_call(callee, span, parent)
        self._arguments(node.child_by_field_name(Field.ARGUMENTS))

    def _member_call(self, callee: Node, span: Span, parent: Builder) -> None:
        dotted = (
            _conditional_dotted(callee)
            if callee.type == Kind.CONDITIONAL_ACCESS_EXPRESSION
            else dotted_name(callee)
        )
        if dotted is None:
            self.calls.append(CallSite(span, first_line(callee), CALL_DYNAMIC, receiver_self=False))
            return
        receiver = dotted.split(".")[0] == RECEIVER
        self.calls.append(CallSite(span, dotted, CALL_ATTRIBUTE, receiver))
        if receiver and dotted == f"{RECEIVER}.{self.own_name}":
            self._new(CK_RECURSION, "", parent)

    def _new_call(self, node: Node) -> None:
        span = node_span(self.source, node)
        constructed = node.child_by_field_name(Field.TYPE)
        name = None if constructed is None else _type_text(constructed)
        if name is None:
            self.calls.append(CallSite(span, first_line(node), CALL_DYNAMIC, receiver_self=False))
        else:
            self.calls.append(CallSite(span, name, CALL_NEW, receiver_self=False))
        self._arguments(node.child_by_field_name(Field.ARGUMENTS))

    def _arguments(self, arguments: Node | None) -> None:
        if arguments is None:
            return
        for argument in arguments.named_children:
            values = [c for c in argument.named_children if c.type != Kind.COMMENT]
            if (
                argument.type == Kind.ARGUMENT
                and len(values) == 1
                and values[0].type == Kind.IDENTIFIER
            ):
                self.calls.append(
                    CallSite(
                        node_span(self.source, values[0]),
                        node_text(values[0]),
                        CALL_ARGUMENT,
                        receiver_self=False,
                    )
                )

    # -- driver -----------------------------------------------------------------------

    def _seed(self, stack: list[tuple[str, Node, Builder]]) -> None:
        """Push the unit's own body: parameters bind locals; a type's body is its members."""
        node = self.unit.node
        if node.type == Kind.ACCESSOR_DECLARATION:
            if _accessor_keyword(node) in VALUE_ACCESSORS:
                self.locals.add(IMPLICIT_VALUE)
            self._body(stack, node.child_by_field_name(Field.BODY))
        elif node.type in PROPERTY_TYPES:
            self._bind_parameters(node)
            self._body(stack, node.child_by_field_name(Field.VALUE))
        elif node.type in FUNCTION_TYPES:
            self._bind_parameters(node)
            self._body(stack, _body_of(node))
        elif node.type in TYPE_DECLARATIONS:
            body = node.child_by_field_name(Field.BODY)
            if body is not None:
                self._push_statements(stack, _members(body), self.root)
        else:
            self._push_statements(stack, _members(node), self.root)

    def _bind_parameters(self, node: Node) -> None:
        parameters = node.child_by_field_name(Field.PARAMETERS)
        if parameters is None:
            parameters_lists = [c for c in node.named_children if c.type == Kind.PARAMETER_LIST]
            parameters = parameters_lists[0] if len(parameters_lists) > 0 else None
        if parameters is None:
            return
        if parameters.type == Kind.IMPLICIT_PARAMETER:
            self.locals.add(node_text(parameters))
            return
        for parameter in parameters.named_children:
            name = parameter.child_by_field_name(Field.NAME)
            if name is not None:
                self.locals.add(node_text(name))

    def _body(self, stack: list[tuple[str, Node, Builder]], body: Node | None) -> None:
        if body is None:
            return
        if body.type == Kind.BLOCK:
            self._push_block(stack, body, self.root)
            return
        expression = body
        if body.type == Kind.ARROW_EXPRESSION_CLAUSE:
            inner = [c for c in body.named_children if c.type != Kind.COMMENT]
            if len(inner) != 1:
                return
            expression = inner[0]
        self.statements += 1
        self._expr(stack, expression, self._new(CK_EXPR, "", self.root))

    def run(self) -> None:
        stack: list[tuple[str, Node, Builder]] = []
        self._seed(stack)
        while len(stack) > 0:
            task, payload, parent = stack.pop()
            if task == _T_STATEMENT:
                self._statement(stack, payload, parent)
            else:
                self._expression(stack, payload, parent)

    def freeze(self) -> ControlNode:
        return freeze_builders(self.builders, self.root)

    def writes(self) -> tuple[tuple[str, str], ...]:
        found: set[tuple[str, str]] = set()
        for name in self.assign_candidates:
            if name not in self.locals:
                found.add((name, WRITE_ASSIGN))
        for name in self.mutate_candidates:
            if name not in self.locals:
                found.add((name, WRITE_MUTATE))
        return tuple(sorted(found))


def _conditional_dotted(node: Node) -> str | None:
    """``o?.M`` as ``o.M``: the condition's dotted name and the bound member."""
    condition = node.child_by_field_name(Field.CONDITION)
    bindings = [c for c in node.named_children if c.type == Kind.MEMBER_BINDING_EXPRESSION]
    if condition is None or len(bindings) != 1:
        return None
    member = bindings[0].child_by_field_name(Field.NAME)
    base = dotted_name(condition)
    simple = _simple_name(member) if member is not None else None
    if base is None or simple is None:
        return None
    return f"{base}.{simple}"


def _type_text(node: Node) -> str | None:
    simple = _simple_name(node)
    if simple is not None:
        return simple
    if node.type == Kind.QUALIFIED_NAME:
        return node_text(node)
    return None


def _parameter_default(parameter: Node) -> Node | None:
    """The default value of ``int x = 4`` (an unnamed child after the name)."""
    if parameter.type != Kind.PARAMETER:
        return None
    name = parameter.child_by_field_name(Field.NAME)
    if name is None:
        return None
    after = [
        c
        for c in parameter.named_children
        if c.start_byte > name.end_byte and c.type != Kind.COMMENT
    ]
    return after[0] if len(after) == 1 else None


def _section_parts(section: Node) -> tuple[list[Node], list[Node]]:
    """A switch section's labels (patterns and ``when`` clauses) and its statements."""
    labels: list[Node] = []
    statements: list[Node] = []
    for child in section.named_children:
        if child.type == Kind.COMMENT:
            continue
        if child.type.endswith("_statement") or child.type == Kind.BLOCK:
            statements.append(child)
        else:
            labels.append(child)
    return labels, statements


def _is_default_section(section: Node) -> bool:
    # The `default:` label is the keyword the model names its default case after.
    return any(not c.is_named and node_text(c) == CASE_DEFAULT for c in section.children)


def _is_async(node: Node) -> bool:
    return any(
        node_text(c) == ASYNC_MODIFIER
        for c in node.children
        if c.type == Kind.MODIFIER or not c.is_named
    )


def _parameter_count(node: Node) -> int:
    if node.type not in FUNCTION_TYPES and node.type != Kind.INDEXER_DECLARATION:
        return 0
    parameters = node.child_by_field_name(Field.PARAMETERS)
    if parameters is None:
        lists = [
            c
            for c in node.named_children
            if c.type in (Kind.PARAMETER_LIST, "bracketed_parameter_list")
        ]
        parameters = lists[0] if len(lists) > 0 else None
    if parameters is None:
        return 0
    if parameters.type == Kind.IMPLICIT_PARAMETER:
        return 1
    return sum(1 for c in parameters.named_children if c.type == Kind.PARAMETER)


def collect_csharp_functions(
    source: SourceText, root: Node, comments: Sequence[Comment]
) -> tuple[FunctionFact, ...]:
    units = discover_units(root)
    spans = [unit_span(source, unit.node, Kind.COMPILATION_UNIT) for unit in units]
    facts: list[FunctionFact] = []
    for index, unit in enumerate(units):
        collector = _UnitCollector(source, unit)
        collector.run()
        tree = collector.freeze()
        span = spans[index]
        nested = nested_line_exclusions(
            span,
            [
                (other, units[other_index].node.type in EXPRESSION_FUNCTIONS)
                for other_index, other in enumerate(spans)
                if other_index != index
            ],
        )
        facts.append(
            FunctionFact(
                name=unit.name,
                kind=unit.kind,
                is_async=_is_async(unit.node),
                is_generator=collector.yields,
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
