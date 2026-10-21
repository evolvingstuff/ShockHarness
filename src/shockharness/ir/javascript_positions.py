"""DOM003 facts: what each named function's values may hold, for the cross-file judgment
of a selection or caret saved as text positions and found again through text nodes only.

A value holds a point's text position (``<range>.toString().length``, the range from
``createRange`` / ``getRangeAt`` / ``cloneRange`` / ``getSelection``), the result of a
call, a parameter, or a property; locals, ``+`` / ``-`` and object literals pass what they
hold on. Per function: what it returns, whether it walks text nodes only and which
parameters it counts with there, the calls that pass something on, and the properties it
stores. Which calls are encoders and decoders is decided across files
(``rules/text_positions.py``).
"""

from collections.abc import Iterator

from tree_sitter import Node

from shockharness.ir.javascript_nodes import Field, Kind
from shockharness.ir.model import (
    POSITION_CALL,
    POSITION_DIRECT,
    POSITION_PARAMETER,
    POSITION_PROPERTY,
    PositionCall,
    PositionFunction,
    PositionSource,
    PositionStore,
    TextPositionFacts,
)
from shockharness.ir.tree_sitter_common import (
    call_arguments,
    node_span,
    node_text,
    unwrap_parentheses,
)
from shockharness.source import SourceText

FUNCTIONS = frozenset(
    {
        Kind.FUNCTION_DECLARATION,
        Kind.FUNCTION_EXPRESSION,
        Kind.ARROW_FUNCTION,
        Kind.METHOD_DEFINITION,
        Kind.GENERATOR_FUNCTION_DECLARATION,
        Kind.GENERATOR_FUNCTION,
    }
)
RANGE_MAKERS = frozenset({"createRange", "getRangeAt", "cloneRange", "getSelection"})
RANGE_CLASS = "Range"
TEXT_WALKERS = frozenset({"createTreeWalker", "createNodeIterator"})
WHAT_TO_SHOW = 1  # createTreeWalker(root, whatToShow): the filter's argument position
SHOW_TEXT = "SHOW_TEXT"
SHOW_TEXT_VALUES = frozenset({"4", "0x4"})
NODE_TYPE = "nodeType"
TEXT_NODE_VALUES = frozenset({"3", "Node.TEXT_NODE"})
TO_STRING = "toString"
LENGTH = "length"
EQUALITY = frozenset({"===", "==", "!==", "!="})
SUMMING = frozenset({"+", "-"})
COUNTING = EQUALITY | SUMMING | frozenset({"<", "<=", ">", ">="})
STRINGS = frozenset({Kind.STRING, Kind.TEMPLATE_STRING})
QUOTES = "'\"`"
PARAMETER_WRAPPERS = frozenset({Kind.REQUIRED_PARAMETER, Kind.OPTIONAL_PARAMETER})


def _own(function: Node) -> Iterator[Node]:
    """The function's nodes in source order, nested functions left out."""
    body = function.child_by_field_name(Field.BODY)
    if body is None:
        return
    stack = [body]
    while len(stack) > 0:
        node = stack.pop()
        yield node
        stack.extend(c for c in reversed(node.children) if c.type not in FUNCTIONS)


def _callee(call: Node) -> tuple[str, bool] | None:
    """(name, member) of ``name(...)`` or ``obj.name(...)``."""
    function = call.child_by_field_name(Field.FUNCTION)
    if function is None:
        return None
    if function.type == Kind.IDENTIFIER:
        return node_text(function), False
    if function.type == Kind.MEMBER_EXPRESSION:
        prop = function.child_by_field_name(Field.PROPERTY)
        if prop is not None:
            return node_text(prop), True
    return None


def _parameter_name(node: Node) -> str:
    if node.type == Kind.IDENTIFIER:
        return node_text(node)
    inner = None
    if node.type in PARAMETER_WRAPPERS:
        inner = node.child_by_field_name(Field.PATTERN)
    elif node.type == Kind.ASSIGNMENT_PATTERN:
        inner = node.child_by_field_name(Field.LEFT)
    if inner is not None and inner.type == Kind.IDENTIFIER:
        return node_text(inner)
    return ""


def _parameters(function: Node) -> tuple[str, ...]:
    """``(a, b)``, or the one bare parameter of ``a => ...``."""
    listed = [
        _parameter_name(p)
        for group in function.children_by_field_name(Field.PARAMETERS)
        for p in group.named_children
    ]
    single = [node_text(p) for p in function.children_by_field_name(Field.PARAMETER)]
    return (*listed, *single)


def _property_name(member: Node) -> str | None:
    prop = member.child_by_field_name(Field.PROPERTY)
    return None if prop is None else node_text(prop)


def function_name(function: Node) -> str | None:
    """The declared name, or the name a variable, object key or property assignment
    gives the function."""
    name = function.child_by_field_name(Field.NAME)
    if name is not None:
        return node_text(name)
    parent = function.parent
    if parent is None:
        return None
    if parent.type == Kind.VARIABLE_DECLARATOR:
        bound = parent.child_by_field_name(Field.NAME)
        return None if bound is None else node_text(bound)
    if parent.type == Kind.PAIR:
        key = parent.child_by_field_name(Field.KEY)
        return None if key is None else node_text(key).strip(QUOTES)
    if parent.type == Kind.ASSIGNMENT_EXPRESSION:
        left = parent.child_by_field_name(Field.LEFT)
        if left is not None and left.type == Kind.MEMBER_EXPRESSION:
            return _property_name(left)
    return None


def _is_text_node_test(node: Node) -> bool:
    """``x.nodeType === Node.TEXT_NODE`` (or ``3``, ``!==``, ``==``) either way round."""
    operator = node.child_by_field_name(Field.OPERATOR)
    if node.type != Kind.BINARY_EXPRESSION or operator is None:
        return False
    if node_text(operator) not in EQUALITY:
        return False
    sides = [node.child_by_field_name(Field.LEFT), node.child_by_field_name(Field.RIGHT)]
    tested = [s for s in sides if s is not None and s.type == Kind.MEMBER_EXPRESSION]
    values = [s for s in sides if s is not None and node_text(s) in TEXT_NODE_VALUES]
    return any(_property_name(s) == NODE_TYPE for s in tested) and len(values) > 0


def _tested_node(test: Node) -> list[str]:
    """The ``x`` of a ``x.nodeType === Node.TEXT_NODE`` test."""
    sides = [*test.children_by_field_name(Field.LEFT), *test.children_by_field_name(Field.RIGHT)]
    nodes = [s for s in sides if _property_name(s) == NODE_TYPE]
    return [node_text(o) for n in nodes for o in n.children_by_field_name(Field.OBJECT)]


def _tested_points(condition: Node) -> set[str]:
    """The expressions a condition tests to be text nodes (``position.node``)."""
    found: set[str] = set()
    stack = [condition]
    while len(stack) > 0:
        node = stack.pop()
        stack.extend(node.named_children)
        if _is_text_node_test(node):
            found.update(_tested_node(node))
    return found


def _guarded(call: Node, function: Node) -> bool:
    """The call sits in the consequence of an ``if`` that tests one of its arguments to
    be a text node: the point it measures has a text position."""
    arguments = {node_text(a) for a in call_arguments(call)}
    child, parent = call, call.parent
    while parent is not None and parent is not function:
        if parent.type == Kind.IF_STATEMENT and child == parent.child_by_field_name(
            Field.CONSEQUENCE
        ):
            condition = parent.child_by_field_name(Field.CONDITION)
            if condition is not None and len(_tested_points(condition) & arguments) > 0:
                return True
        child, parent = parent, parent.parent
    return False


def _parts(node: Node) -> list[Node]:
    """The parts that pass on what they hold: an object's values, a sum's sides."""
    if node.type == Kind.OBJECT:
        pairs = [p for p in node.named_children if p.type == Kind.PAIR]
        return [v for p in pairs for v in p.children_by_field_name(Field.VALUE)]
    operators = [node_text(o) for o in node.children_by_field_name(Field.OPERATOR)]
    if node.type != Kind.BINARY_EXPRESSION or not any(o in SUMMING for o in operators):
        return []
    return [*node.children_by_field_name(Field.LEFT), *node.children_by_field_name(Field.RIGHT)]


def _source(kind: str, name: str, index: int) -> PositionSource:
    return PositionSource(kind=kind, name=name, index=index, member=False, guarded=False)


def _add(target: list[PositionSource], sources: list[PositionSource]) -> bool:
    added = False
    for source in sources:
        if source not in target:
            target.append(source)
            added = True
    return added


class _Scope:
    """One function: its parameters, its range variables and what its locals hold."""

    def __init__(self, source: SourceText, function: Node) -> None:
        self.source = source
        self.function = function
        self.nodes = list(_own(function))
        self.parameters = _parameters(function)
        self.ranges = self._ranges()
        self.locals: dict[str, list[PositionSource]] = {}
        self._fill_locals()

    def _assignments(self) -> Iterator[tuple[Node, Node]]:
        for node in self.nodes:
            if node.type == Kind.VARIABLE_DECLARATOR:
                target, value = (
                    node.child_by_field_name(Field.NAME),
                    node.child_by_field_name(Field.VALUE),
                )
            elif node.type == Kind.ASSIGNMENT_EXPRESSION:
                target, value = (
                    node.child_by_field_name(Field.LEFT),
                    node.child_by_field_name(Field.RIGHT),
                )
            else:
                continue
            if target is not None and value is not None:
                yield target, value

    def _ranges(self) -> frozenset[str]:
        found: set[str] = set()
        for target, value in self._assignments():
            if target.type == Kind.IDENTIFIER and self._makes_range(value):
                found.add(node_text(target))
        return frozenset(found)

    def _makes_range(self, value: Node) -> bool:
        value = unwrap_parentheses(value)
        if value.type == Kind.NEW_EXPRESSION:
            constructor = value.child_by_field_name(Field.CONSTRUCTOR)
            return constructor is not None and node_text(constructor) == RANGE_CLASS
        callee = _callee(value) if value.type == Kind.CALL_EXPRESSION else None
        return callee is not None and callee[0] in RANGE_MAKERS

    def _fill_locals(self) -> None:
        pairs = [(node_text(t), v) for t, v in self._assignments() if t.type == Kind.IDENTIFIER]
        changed = True
        while changed:
            changed = False
            for name, value in pairs:
                if name not in self.locals:
                    self.locals[name] = []
                if _add(self.locals[name], self.held(value)):
                    changed = True

    def _range_length(self, member: Node) -> bool:
        """``<range>.toString().length``."""
        call = member.child_by_field_name(Field.OBJECT)
        if _property_name(member) != LENGTH or call is None or call.type != Kind.CALL_EXPRESSION:
            return False
        function = call.child_by_field_name(Field.FUNCTION)
        if function is None or function.type != Kind.MEMBER_EXPRESSION:
            return False
        receiver = function.child_by_field_name(Field.OBJECT)
        if _property_name(function) != TO_STRING or receiver is None:
            return False
        return node_text(receiver) in self.ranges or self._makes_range(receiver)

    def _identifier(self, name: str) -> list[PositionSource]:
        found = [s for key, sources in self.locals.items() if key == name for s in sources]
        for index, parameter in enumerate(self.parameters):
            if parameter == name:
                found.append(_source(POSITION_PARAMETER, "", index))
        return found

    def _call(self, call: Node) -> list[PositionSource]:
        callee = _callee(call)
        if callee is None:
            return []
        name, member = callee
        guarded = _guarded(call, self.function)
        return [
            PositionSource(kind=POSITION_CALL, name=name, index=0, member=member, guarded=guarded)
        ]

    def held(self, node: Node) -> list[PositionSource]:
        """What the expression may hold (an explicit stack: sums can nest deep)."""
        found: list[PositionSource] = []
        stack = [node]
        while len(stack) > 0:
            current = unwrap_parentheses(stack.pop())
            found.extend(self._leaf(current))
            stack.extend(_parts(current))
        return found

    def _leaf(self, node: Node) -> list[PositionSource]:
        if node.type == Kind.IDENTIFIER:
            return self._identifier(node_text(node))
        if node.type == Kind.CALL_EXPRESSION:
            return self._call(node)
        if node.type != Kind.MEMBER_EXPRESSION:
            return []
        if self._range_length(node):
            return [_source(POSITION_DIRECT, "", 0)]
        names = [node_text(p) for p in node.children_by_field_name(Field.PROPERTY)]
        return [_source(POSITION_PROPERTY, name, 0) for name in names]

    def returns(self) -> tuple[PositionSource, ...]:
        found: list[PositionSource] = []
        body = self.function.child_by_field_name(Field.BODY)
        if body is not None and body.type != Kind.STATEMENT_BLOCK:
            _add(found, self.held(body))
        for node in self.nodes:
            if node.type == Kind.RETURN_STATEMENT and node.named_child_count > 0:
                _add(found, self.held(node.named_children[0]))
        return tuple(found)

    def walks_text(self) -> bool:
        """A SHOW_TEXT walker or iterator, or a hand-written walk that tests nodes to be
        text and reads lengths."""
        tests_text = False
        reads_length = False
        for node in self.nodes:
            if node.type == Kind.CALL_EXPRESSION and self._text_walker(node):
                return True
            if _is_text_node_test(node):
                tests_text = True
            if node.type == Kind.MEMBER_EXPRESSION and _property_name(node) == LENGTH:
                reads_length = True
        return tests_text and reads_length

    def _text_walker(self, call: Node) -> bool:
        callee = _callee(call)
        arguments = call_arguments(call)
        if callee is None or callee[0] not in TEXT_WALKERS or len(arguments) <= WHAT_TO_SHOW:
            return False
        shown = node_text(arguments[WHAT_TO_SHOW])
        return SHOW_TEXT in shown or shown in SHOW_TEXT_VALUES

    def _counted(self, side: Node) -> int | None:
        """The parameter a side of a comparison or sum counts with: ``p`` or ``p.x``."""
        if side.type == Kind.MEMBER_EXPRESSION:
            inner = side.child_by_field_name(Field.OBJECT)
            if inner is None:
                return None
            side = inner
        if side.type != Kind.IDENTIFIER or node_text(side) not in self.parameters:
            return None
        return self.parameters.index(node_text(side))

    def _counted_in(self, node: Node) -> list[int]:
        """The parameters a comparison or sum counts with, against anything but a string."""
        operators = [node_text(o) for o in node.children_by_field_name(Field.OPERATOR)]
        if node.type != Kind.BINARY_EXPRESSION or not any(o in COUNTING for o in operators):
            return []
        left, right = node.child_by_field_name(Field.LEFT), node.child_by_field_name(Field.RIGHT)
        found: list[int] = []
        for side, other in ((left, right), (right, left)):
            if side is None or other is None or other.type in STRINGS:
                continue
            index = self._counted(side)
            if index is not None:
                found.append(index)
        return found

    def counted_parameters(self) -> tuple[int, ...]:
        found: list[int] = []
        for node in self.nodes:
            for index in self._counted_in(node):
                if index not in found:
                    found.append(index)
        return tuple(found)

    def calls(self) -> tuple[PositionCall, ...]:
        found: list[PositionCall] = []
        for node in self.nodes:
            callee = _callee(node) if node.type == Kind.CALL_EXPRESSION else None
            if callee is None:
                continue
            arguments = tuple(tuple(self.held(a)) for a in call_arguments(node))
            if any(len(a) > 0 for a in arguments):
                span = node_span(self.source, node)
                found.append(PositionCall(span, callee[0], callee[1], arguments))
        return tuple(found)

    def stores(self) -> list[PositionStore]:
        found: list[PositionStore] = []
        for node in self.nodes:
            name, value = self._stored(node)
            if name is None or value is None:
                continue
            held = tuple(self.held(value))
            if len(held) > 0:
                found.append(PositionStore(name, held))
        return found

    def _stored(self, node: Node) -> tuple[str | None, Node | None]:
        if node.type == Kind.PAIR:
            key = node.child_by_field_name(Field.KEY)
            name = None if key is None else node_text(key).strip(QUOTES)
            return name, node.child_by_field_name(Field.VALUE)
        if node.type == Kind.ASSIGNMENT_EXPRESSION:
            left = node.child_by_field_name(Field.LEFT)
            if left is not None and left.type == Kind.MEMBER_EXPRESSION:
                return _property_name(left), node.child_by_field_name(Field.RIGHT)
        return None, None

    def summary(self, name: str) -> PositionFunction:
        walks = self.walks_text()
        return PositionFunction(
            name=name,
            span=node_span(self.source, self.function),
            returns=self.returns(),
            walks_text=walks,
            counted_parameters=self.counted_parameters() if walks else (),
            calls=self.calls(),
        )


def _interesting(function: PositionFunction) -> bool:
    return len(function.returns) > 0 or function.walks_text or len(function.calls) > 0


def collect_javascript_positions(source: SourceText, root: Node) -> TextPositionFacts:
    functions: list[PositionFunction] = []
    stores: list[PositionStore] = []
    stack = [root]
    while len(stack) > 0:
        node = stack.pop()
        stack.extend(node.named_children)
        name = function_name(node) if node.type in FUNCTIONS else None
        if name is None:
            continue
        scope = _Scope(source, node)
        summary = scope.summary(name)
        if _interesting(summary):
            functions.append(summary)
        stores.extend(scope.stores())
    functions.sort(key=lambda f: f.span)
    return TextPositionFacts(functions=tuple(functions), stores=tuple(stores))
