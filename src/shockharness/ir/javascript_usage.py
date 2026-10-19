"""Uses of JavaScript functions the call graph does not record (DEAD001, DEAD002).

The JavaScript side of ``python_usage``: a function named as a value instead of called
(``addEventListener('x', onX)``, ``{ onX }``, ``window.onX = onX``) is a bare reference
from the unit that names it; a property read or written outside a call (``this.h``,
``this.h.bind(this)``, ``obj.value = v`` for a setter, ``obj['h']``) is a member
reference. Import and export lists are not uses. Nothing registers a JavaScript function
without a call: a function only a page or a template calls needs an entry point.
"""

from tree_sitter import Node

from shockharness.constants import FIRST_COLUMN, FIRST_LINE
from shockharness.ir.javascript_catches import FIELD_DEFINITIONS, node_span, node_text
from shockharness.ir.javascript_functions import CLASS_TYPES, UNIT_TYPES, string_value
from shockharness.ir.javascript_nodes import Field, Kind
from shockharness.ir.model import DeclaredFunction, ImportFact, UsageFacts, UsageReference
from shockharness.source import SourceText

DECLARATIONS = frozenset({Kind.FUNCTION_DECLARATION, Kind.GENERATOR_FUNCTION_DECLARATION})
BOUND_FUNCTIONS = frozenset(
    {Kind.FUNCTION_EXPRESSION, Kind.ARROW_FUNCTION, Kind.GENERATOR_FUNCTION}
)
CALLS = {Kind.CALL_EXPRESSION: Field.FUNCTION, Kind.NEW_EXPRESSION: Field.CONSTRUCTOR}

Unit = tuple[int, int]


def _declared(node: Node) -> bool:
    """A function the rules judge: a declaration, a class method or a method of an object
    bound to a name, or a function bound to a declared name or a class field. Methods of
    an object literal passed straight to a call are callbacks of whatever receives them."""
    parent = node.parent
    if node.type in DECLARATIONS:
        return True
    if parent is None:
        return False
    if node.type == Kind.METHOD_DEFINITION:
        holder = parent.parent
        if holder is None:
            return False
        # A class method's parent is the class body, whose parent is the class.
        return holder.type in CLASS_TYPES or (
            parent.type == Kind.OBJECT and holder.type == Kind.VARIABLE_DECLARATOR
        )
    if node.type in BOUND_FUNCTIONS:
        if parent.type == Kind.VARIABLE_DECLARATOR:
            value = parent.child_by_field_name(Field.VALUE)
            return value is not None and value.id == node.id
        return parent.type in FIELD_DEFINITIONS
    return False


def _bindable(root: Node, imports: tuple[ImportFact, ...]) -> frozenset[str]:
    """Names a bare reference may mean a project function by: the file's function
    declarations, names bound to a function, and every name an import binds."""
    names = {local for fact in imports for _imported, local in fact.names if local != ""}
    stack = [root]
    while len(stack) > 0:
        node = stack.pop()
        name: Node | None = None
        if node.type in DECLARATIONS:
            name = node.child_by_field_name(Field.NAME)
        elif node.type == Kind.VARIABLE_DECLARATOR:
            value = node.child_by_field_name(Field.VALUE)
            if value is not None and value.type in BOUND_FUNCTIONS:
                name = node.child_by_field_name(Field.NAME)
        if name is not None and name.type == Kind.IDENTIFIER:
            names.add(node_text(name))
        stack.extend(node.children)
    return frozenset(names)


class _Collector:
    def __init__(self, source: SourceText, root: Node, imports: tuple[ImportFact, ...]) -> None:
        self.source = source
        self.bindable = _bindable(root, imports)
        self.declared: list[DeclaredFunction] = []
        self.references: set[UsageReference] = set()
        self.stack: list[tuple[Node, Unit, bool]] = [(root, (FIRST_LINE, FIRST_COLUMN), False)]

    def _push(self, nodes: list[Node], unit: Unit) -> None:
        for node in reversed(nodes):
            self.stack.append((node, unit, False))

    def _refer(self, unit: Unit, name: str, member: bool) -> None:
        self.references.add(UsageReference(unit[0], unit[1], name, member))

    def _unit(self, node: Node) -> None:
        span = node_span(self.source, node)
        if _declared(node):
            self.declared.append(DeclaredFunction(span.line, span.column, ""))
        name = node.child_by_field_name(Field.NAME)
        children = [c for c in node.named_children if name is None or c.id != name.id]
        self._push(children, (span.line, span.column))

    def _call(self, node: Node, unit: Unit, field: str) -> None:
        function = node.child_by_field_name(field)
        others = [c for c in node.named_children if function is None or c.id != function.id]
        if function is not None:
            self.stack.append((function, unit, True))
        self._push(others, unit)

    def _member(self, node: Node, unit: Unit, callee: bool) -> None:
        member = node.child_by_field_name(Field.PROPERTY)
        if not callee and member is not None:
            self._refer(unit, node_text(member), member=True)
        target = node.child_by_field_name(Field.OBJECT)
        if target is not None:
            self.stack.append((target, unit, False))

    def _subscript(self, node: Node, unit: Unit) -> None:
        index = node.child_by_field_name(Field.INDEX)
        if index is not None:
            named = string_value(index)
            if named is not None:
                self._refer(unit, named, member=True)
        self._push(list(node.named_children), unit)

    def _export(self, node: Node, unit: Unit) -> None:
        """An export list or ``export default name`` is not a use; a declaration or a
        value expression in it is visited."""
        for field in (Field.DECLARATION, Field.VALUE):
            child = node.child_by_field_name(field)
            if child is not None and child.type != Kind.IDENTIFIER:
                self.stack.append((child, unit, False))

    def _visit(self, node: Node, unit: Unit, callee: bool) -> None:
        kind = node.type
        if node.is_named and kind in UNIT_TYPES:
            self._unit(node)
        elif kind in CALLS:
            self._call(node, unit, CALLS[kind])
        elif kind in (Kind.IDENTIFIER, Kind.SHORTHAND_PROPERTY_IDENTIFIER):
            if not callee and node_text(node) in self.bindable:
                self._refer(unit, node_text(node), member=False)
        elif kind == Kind.MEMBER_EXPRESSION:
            self._member(node, unit, callee)
        elif kind == Kind.SUBSCRIPT_EXPRESSION:
            self._subscript(node, unit)
        elif kind == Kind.EXPORT_STATEMENT:
            self._export(node, unit)
        elif kind == Kind.VARIABLE_DECLARATOR:
            value = node.child_by_field_name(Field.VALUE)
            if value is not None:
                self.stack.append((value, unit, False))
        elif kind != Kind.IMPORT_STATEMENT:
            self._push(list(node.named_children), unit)

    def run(self) -> UsageFacts:
        while len(self.stack) > 0:
            node, unit, callee = self.stack.pop()
            self._visit(node, unit, callee)
        references = sorted(self.references, key=lambda r: (r.line, r.column, r.name, r.member))
        return UsageFacts(declared=tuple(self.declared), references=tuple(references))


def collect_javascript_usage(
    source: SourceText, root: Node, imports: tuple[ImportFact, ...]
) -> UsageFacts:
    return _Collector(source, root, imports).run()
