"""JavaScript and TypeScript dataflow facts (H6), the counterpart of ir/python_dataflow.py.

The same model: flow-sensitive in source order without paths (an assignment inside a
branch, loop or handler adds to a variable's origins), nested units separate, a call's
result an origin of its own. A local is a name the unit declares (``let``/``const``/
``var``, a function or class declaration, a catch or loop binding, an import) or a
parameter; an assignment to any other name, and every binding of the module unit, is a
FlowStore.
"""

from collections.abc import Callable, Iterable

from tree_sitter import Node

from shockharness.constants import DATAFLOW_MAX_DEPTH, EVIDENCE_MAX_CHARS
from shockharness.ir.javascript_catches import (
    FIELD_NAME_FIELDS,
    TYPE_WRAPPERS,
    is_this_parameter,
    node_span,
    node_text,
    parameter_parts,
)
from shockharness.ir.javascript_functions import (
    CLASS_TYPES,
    UNIT_TYPES,
    UnitInfo,
    discover_units,
    dotted_name,
    pattern_names,
    string_value,
)
from shockharness.ir.model import (
    ORIGIN_CALL,
    ORIGIN_PARAMETER,
    ORIGIN_READ,
    DataflowFacts,
    FlowCall,
    FlowGuard,
    FlowRead,
    FlowReturn,
    FlowStore,
    FlowUnit,
    origin,
)
from shockharness.source import SourceText

Origins = frozenset[str]
EMPTY: Origins = frozenset()
DYNAMIC = "<dynamic>"
COMMENT = "comment"
IDENTIFIER = "identifier"
MEMBER = "member_expression"
SUBSCRIPT = "subscript_expression"
DECLARATIONS = frozenset({"lexical_declaration", "variable_declaration"})
NESTED_DECLARATIONS = frozenset(
    {"function_declaration", "generator_function_declaration", "class_declaration"}
) | (CLASS_TYPES - {"class"})
FIELDS = frozenset({"field_definition", "public_field_definition"})
PATTERNS = frozenset({"object_pattern", "array_pattern"})
# The field holding what a declaring node binds.
DECLARED_FIELDS = {
    "variable_declarator": "name",
    "catch_clause": "parameter",
    "for_in_statement": "left",
}
TESTING_OPERATORS = frozenset({"&&", "||", "??"})
LOGICAL_ASSIGNMENTS = frozenset({"&&=", "||=", "??="})
COMPARISONS = frozenset({"===", "!==", "==", "!=", "<", ">", "<=", ">=", "instanceof", "in"})
NOT = "!"
AND = "&&"
JUNCTIONS = frozenset({AND, "||"})
EXITS = frozenset({"return_statement", "throw_statement", "continue_statement", "break_statement"})
TESTING = "testing"
COMPARING = "comparing"
COMBINING = "combining"
BOOLEAN_UNARY = frozenset({"!", "typeof", "void", "delete"})
LITERALS = frozenset(
    {"string", "number", "true", "false", "null", "undefined", "regex", "this", "super"}
)
WRAPPERS = frozenset({"parenthesized_expression", "await_expression", "spread_element"}) | (
    TYPE_WRAPPERS
)


def _named(node: Node) -> list[Node]:
    return [child for child in node.named_children if child.type != COMMENT]


def _excerpt(node: Node) -> str:
    text = " ".join(node_text(node).split("\n")[0].split())
    if len(text) > EVIDENCE_MAX_CHARS:
        return text[:EVIDENCE_MAX_CHARS] + "..."
    return text


def _sorted(origins: Origins) -> tuple[str, ...]:
    return tuple(sorted(origins))


def _own_nodes(unit: Node) -> Iterable[Node]:
    """Every node of the unit's own code: nested units are yielded, not entered."""
    stack: list[Node] = list(unit.named_children)
    while len(stack) > 0:
        node = stack.pop()
        yield node
        if node.type not in UNIT_TYPES:
            stack.extend(node.named_children)


def _field_names(node: Node, field: str) -> list[str]:
    bound = node.child_by_field_name(field)
    if bound is None:
        return []
    return pattern_names(bound)


def _declared(node: Node) -> list[str]:
    """Names one node of the unit declares. Imports are not among them: an imported name
    is read through the file's import aliases."""
    if node.type in DECLARED_FIELDS:
        return _field_names(node, DECLARED_FIELDS[node.type])
    if node.type in NESTED_DECLARATIONS:
        name = node.child_by_field_name("name")
        if name is None:
            return []
        return [node_text(name)]
    return []


def _local_names(unit: Node) -> set[str]:
    names: set[str] = set()
    for node in _own_nodes(unit):
        names.update(_declared(node))
    return names


def _parameter_nodes(node: Node) -> list[Node]:
    if node.type not in UNIT_TYPES or node.type in CLASS_TYPES:
        return []
    single = node.child_by_field_name("parameter")
    if single is not None:
        return [single]
    parameters = node.child_by_field_name("parameters")
    if parameters is None:
        return []
    return [p for p in _named(parameters) if not is_this_parameter(p)]


def _segment(node: Node) -> str | None:
    """The name a property read or string-literal subscript adds to a chain."""
    if node.type == MEMBER:
        prop = node.child_by_field_name("property")
        if prop is None:
            return None
        return node_text(prop)
    index = node.child_by_field_name("index")
    if index is None:
        return None
    return string_value(index)


def _chain(node: Node) -> tuple[Node, str] | None:
    """(root identifier, dotted text) of a pure read chain: properties and string-literal
    subscripts over an identifier (``process.env["HOME"]`` -> ``process.env.HOME``)."""
    parts: list[str] = []
    current = node
    while current.type in (MEMBER, SUBSCRIPT):
        segment = _segment(current)
        obj = current.child_by_field_name("object")
        if segment is None or obj is None:
            return None
        parts.append(segment)
        current = obj
    if current.type != IDENTIFIER or len(parts) == 0:
        return None
    parts.append(node_text(current))
    return current, ".".join(reversed(parts))


class _Unit:
    """Walks one unit's own code, keeping each local's origins."""

    def __init__(self, source: SourceText, info: UnitInfo) -> None:
        self.source = source
        self.info = info
        self.module = info.node.type == "program"
        nodes = _parameter_nodes(info.node)
        self.parameters = [node_text(parameter_parts(p)[0]) for p in nodes]
        self.env: dict[str, Origins] = {}
        self.parameter_names: dict[str, int] = {}
        for index, parameter in enumerate(nodes):
            binding, _default = parameter_parts(parameter)
            for name in pattern_names(binding):
                self.env[name] = frozenset({origin(ORIGIN_PARAMETER, index)})
                self.parameter_names[name] = index
        self.locals = _local_names(info.node) | set(self.parameter_names)
        self.weak = 0
        self.reads: list[FlowRead] = []
        self.calls: list[FlowCall] = []
        self.stores: list[FlowStore] = []
        self.returns: list[FlowReturn] = []
        self.tested: set[str] = set()
        self.mentions: list[set[str]] = []
        self.guards: list[FlowGuard] = []
        self.depth = 0
        self.truncated = False

    # -- driver ---------------------------------------------------------------------

    def run(self) -> FlowUnit:
        node = self.info.node
        if self.module:
            self.statements(_named(node))
        elif node.type in CLASS_TYPES:
            body = node.child_by_field_name("body")
            if body is not None:
                self.class_members(_named(body))
        else:
            self.function_body(node)
        return FlowUnit(
            name=self.info.name,
            parameters=tuple(self.parameters),
            bound_receiver=False,
            reads=tuple(self.reads),
            calls=tuple(self.calls),
            stores=tuple(self.stores),
            returns=tuple(self.returns),
            tested=tuple(sorted(self.tested)),
            asserts=(),
            truncated=self.truncated,
        )

    def function_body(self, node: Node) -> None:
        for parameter in _parameter_nodes(node):
            _binding, default = parameter_parts(parameter)
            self.expr(default)
        body = node.child_by_field_name("body")
        if body is None:
            return
        if body.type == "statement_block":
            self.statements(_named(body))
        else:
            value = self.expr(body)
            self.returns.append(FlowReturn(node_span(self.source, body), _sorted(value)))

    def class_members(self, members: Iterable[Node]) -> None:
        for member in members:
            if member.type in FIELDS:
                value = self.expr(member.child_by_field_name("value"))
                name = member.child_by_field_name(FIELD_NAME_FIELDS[member.type])
                assert name is not None, "class field without a name"
                self.store(member, node_text(name), value)
            elif member.type == "class_static_block":
                body = member.child_by_field_name("body")
                if body is not None:
                    self.statements(_named(body))

    def statements(self, body: Iterable[Node]) -> None:
        """A block; guards established in it (an early exit) end with it."""
        if not self.enter():
            return
        held = len(self.guards)
        for statement in body:
            if statement.type in STATEMENTS:
                STATEMENTS[statement.type](self, statement)
            elif statement.type not in NESTED_DECLARATIONS:
                self.expr(statement)
        del self.guards[held:]
        self.leave()

    def guarded(self, node: Node | None, guards: Iterable[FlowGuard]) -> None:
        """A branch that runs only while ``guards`` hold."""
        held = len(self.guards)
        self.guards.extend(guards)
        self.branch(node)
        del self.guards[held:]

    def holding(self, test: Node | None, when_true: bool) -> list[FlowGuard]:
        """The calls of ``test`` known to be true when ``test`` is ``when_true``."""
        found: list[FlowGuard] = []
        stack: list[tuple[Node, bool]] = []
        if test is not None:
            stack.append((test, when_true))
        while len(stack) > 0:
            node, truth = stack.pop()
            if node.type in WRAPPERS:
                stack.extend((child, truth) for child in _named(node))
            elif node.type == "unary_expression" and _unary_operator(node) == NOT:
                stack.extend((child, not truth) for child in _named(node))
            elif node.type == "binary_expression" and _operator(node) in JUNCTIONS:
                # `a && b` true: both are; `a || b` false: neither is.
                if (_operator(node) == AND) == truth:
                    stack.extend((child, truth) for child in _named(node))
            elif node.type == "call_expression" and truth:
                found.extend(_guard(node))
        return found

    def block(self, node: Node | None) -> None:
        if node is None:
            return
        if node.type in ("statement_block", "else_clause", "finally_clause"):
            self.statements(_named(node))
        else:
            self.statements([node])

    def branch(self, node: Node | None) -> None:
        self.weak += 1
        self.block(node)
        self.weak -= 1

    def test(self, node: Node | None) -> Origins:
        self.mentions.append(set())
        value = self.expr(node)
        mentioned = self.mentions.pop()
        self.tested.update(mentioned)
        if len(self.mentions) > 0:
            self.mentions[len(self.mentions) - 1].update(mentioned)
        return value

    def enter(self) -> bool:
        """One level deeper; False (and the unit truncated) past DATAFLOW_MAX_DEPTH."""
        if self.depth >= DATAFLOW_MAX_DEPTH:
            self.truncated = True
            return False
        self.depth += 1
        return True

    def leave(self) -> None:
        self.depth -= 1

    # -- binding ----------------------------------------------------------------------

    def bind(self, name: str, origins: Origins) -> None:
        if self.weak > 0 and name in self.env:
            self.env[name] = self.env[name] | origins
        else:
            self.env[name] = origins

    def declare(self, pattern: Node, origins: Origins) -> None:
        """``const x = v`` / ``const { a, b = d } = v``: every name the pattern binds."""
        for name in pattern_names(pattern):
            if self.module:
                self.store(pattern, name, origins)
            self.bind(name, origins)
        if pattern.type in PATTERNS:
            self.pattern_defaults(pattern)

    def pattern_defaults(self, pattern: Node) -> None:
        for node in _own_nodes(pattern):
            if node.type in ("assignment_pattern", "object_assignment_pattern"):
                self.expr(node.child_by_field_name("right"))

    def assign(self, target: Node, origins: Origins) -> None:
        if target.type == IDENTIFIER:
            name = node_text(target)
            if self.module or name not in self.locals:
                self.store(target, name, origins)
            self.bind(name, origins)
        elif target.type in (MEMBER, SUBSCRIPT):
            self.expr(target.child_by_field_name("object"))
            if target.type == SUBSCRIPT:
                self.expr(target.child_by_field_name("index"))
            self.store(target, _excerpt(target), origins)
        elif target.type in PATTERNS:
            self.declare(target, origins)
        elif target.type in WRAPPERS:
            inner = _named(target)
            if len(inner) > 0:
                self.assign(inner[0], origins)

    def store(self, target: Node, text: str, origins: Origins) -> None:
        self.stores.append(FlowStore(node_span(self.source, target), text, _sorted(origins)))

    # -- expressions ------------------------------------------------------------------

    def expr(self, node: Node | None) -> Origins:
        if node is None or node.type == COMMENT or not self.enter():
            return EMPTY
        if node.type in EXPRESSIONS:
            value = EXPRESSIONS[node.type](self, node)
        elif node.type in LITERALS or node.type in UNIT_TYPES:
            value = EMPTY
        else:
            value = self.children(node)
        self.leave()
        if len(self.mentions) > 0:
            self.mentions[len(self.mentions) - 1].update(value)
        return value

    def children(self, node: Node) -> Origins:
        found: set[str] = set()
        for child in _named(node):
            found.update(self.expr(child))
        return frozenset(found)

    def name(self, identifier: str) -> Origins:
        if identifier in self.env:
            return self.env[identifier]
        return EMPTY

    def read(self, node: Node, text: str, on_parameter: bool) -> Origins:
        self.reads.append(FlowRead(node_span(self.source, node), text, on_parameter))
        return frozenset({origin(ORIGIN_READ, len(self.reads) - 1)})

    def chained(self, node: Node) -> Origins:
        chain = _chain(node)
        if chain is None:
            if node.type == SUBSCRIPT:
                self.expr(node.child_by_field_name("index"))
            return self.expr(node.child_by_field_name("object"))
        root, text = chain
        name = node_text(root)
        if name not in self.locals:
            return self.read(node, text, on_parameter=False)
        held = self.name(name)
        if name in self.parameter_names:
            marker = origin(ORIGIN_PARAMETER, self.parameter_names[name])
            if marker in held:
                return held | self.read(node, text, on_parameter=True)
        return held

    def call(self, node: Node) -> Origins:
        is_new = node.type == "new_expression"
        function = node.child_by_field_name("constructor" if is_new else "function")
        receiver = EMPTY
        callee = DYNAMIC
        if function is not None:
            unwrapped = function
            while unwrapped.type in WRAPPERS:
                inner = _named(unwrapped)
                if len(inner) == 0:
                    break
                unwrapped = inner[0]
            if unwrapped.type == MEMBER:
                receiver = self.expr(unwrapped.child_by_field_name("object"))
            elif unwrapped.type != IDENTIFIER:
                self.expr(unwrapped)
            dotted = dotted_name(unwrapped)
            if dotted is not None:
                callee = dotted
        arguments = self.arguments(node.child_by_field_name("arguments"))
        self.calls.append(
            FlowCall(
                span=node_span(self.source, node),
                callee=callee,
                text=_excerpt(node),
                receiver=_sorted(receiver),
                arguments=arguments,
                keywords=(),
                first_argument=_first_argument(node),
                guards=tuple(self.guards),
            )
        )
        return frozenset({origin(ORIGIN_CALL, len(self.calls) - 1)})

    def arguments(self, node: Node | None) -> tuple[tuple[str, ...], ...]:
        if node is None:
            return ()
        if node.type == "template_string":
            return (_sorted(self.expr(node)),)
        return tuple(_sorted(self.expr(argument)) for argument in _named(node))


# -- statement handlers ---------------------------------------------------------------


def _declaration(unit: _Unit, node: Node) -> None:
    for declarator in _named(node):
        if declarator.type != "variable_declarator":
            continue
        name = declarator.child_by_field_name("name")
        value = unit.expr(declarator.child_by_field_name("value"))
        if name is not None:
            unit.declare(name, value)


def _expression(unit: _Unit, node: Node) -> None:
    unit.children(node)


def _return(unit: _Unit, node: Node) -> None:
    value = unit.children(node)
    unit.returns.append(FlowReturn(node_span(unit.source, node), _sorted(value)))


def _if(unit: _Unit, node: Node) -> None:
    condition = node.child_by_field_name("condition")
    unit.test(condition)
    consequence = node.child_by_field_name("consequence")
    alternative = node.child_by_field_name("alternative")
    unit.guarded(consequence, unit.holding(condition, when_true=True))
    otherwise = unit.holding(condition, when_true=False)
    unit.guarded(alternative, otherwise)
    if alternative is None and _exits(consequence):
        unit.guards.extend(otherwise)  # `if (!has(x)) return;` guards the rest


def _exits(node: Node | None) -> bool:
    """The branch ends by leaving: return, throw, continue or break."""
    if node is None:
        return False
    last = node
    if node.type == "statement_block":
        statements = _named(node)
        if len(statements) == 0:
            return False
        last = statements[len(statements) - 1]
    return last.type in EXITS


def _first_argument(call: Node) -> str:
    arguments = call.child_by_field_name("arguments")
    if arguments is None or arguments.type != "arguments":
        return ""
    given = _named(arguments)
    if len(given) == 0:
        return ""
    return _excerpt(given[0])


def _guard(call: Node) -> list[FlowGuard]:
    function = call.child_by_field_name("function")
    argument = _first_argument(call)
    if function is None or argument == "":
        return []
    dotted = dotted_name(function)
    if dotted is None:
        return []
    return [FlowGuard(dotted, argument)]


def _unary_operator(node: Node) -> str:
    operator = node.child_by_field_name("operator")
    if operator is None:
        return ""
    return node_text(operator)


def _loop(unit: _Unit, node: Node) -> None:
    unit.expr(node.child_by_field_name("initializer"))
    unit.test(node.child_by_field_name("condition"))
    unit.weak += 1
    unit.expr(node.child_by_field_name("increment"))
    unit.weak -= 1
    unit.branch(node.child_by_field_name("body"))


def _for_in(unit: _Unit, node: Node) -> None:
    iterated = unit.expr(node.child_by_field_name("right"))
    left = node.child_by_field_name("left")
    unit.weak += 1
    if left is not None:
        unit.assign(left, iterated)
    unit.weak -= 1
    unit.branch(node.child_by_field_name("body"))


def _try(unit: _Unit, node: Node) -> None:
    unit.block(node.child_by_field_name("body"))
    handler = node.child_by_field_name("handler")
    if handler is not None:
        parameter = handler.child_by_field_name("parameter")
        if parameter is not None:
            for name in pattern_names(parameter):
                unit.bind(name, EMPTY)
        unit.branch(handler.child_by_field_name("body"))
    unit.block(node.child_by_field_name("finalizer"))


def _switch(unit: _Unit, node: Node) -> None:
    unit.test(node.child_by_field_name("value"))
    body = node.child_by_field_name("body")
    if body is None:
        return
    unit.weak += 1
    for case in _named(body):
        unit.test(case.child_by_field_name("value"))
        unit.statements(c for c in _named(case) if c != case.child_by_field_name("value"))
    unit.weak -= 1


def _block(unit: _Unit, node: Node) -> None:
    unit.statements(_named(node))


def _labeled(unit: _Unit, node: Node) -> None:
    unit.block(node.child_by_field_name("body"))


def _export(unit: _Unit, node: Node) -> None:
    declaration = node.child_by_field_name("declaration")
    if declaration is not None:
        unit.statements([declaration])
    unit.expr(node.child_by_field_name("value"))


def _ignored(unit: _Unit, node: Node) -> None:
    return None


StatementHandler = Callable[[_Unit, Node], None]
STATEMENTS: dict[str, StatementHandler] = {
    "lexical_declaration": _declaration,
    "variable_declaration": _declaration,
    "expression_statement": _expression,
    "throw_statement": _expression,
    "return_statement": _return,
    "if_statement": _if,
    "for_statement": _loop,
    "while_statement": _loop,
    "do_statement": _loop,
    "for_in_statement": _for_in,
    "try_statement": _try,
    "switch_statement": _switch,
    "statement_block": _block,
    "labeled_statement": _labeled,
    "export_statement": _export,
    "import_statement": _ignored,
    "empty_statement": _ignored,
    "break_statement": _ignored,
    "continue_statement": _ignored,
    "debugger_statement": _ignored,
}


# -- expression handlers --------------------------------------------------------------


def _identifier(unit: _Unit, node: Node) -> Origins:
    return unit.name(node_text(node))


def _shorthand(unit: _Unit, node: Node) -> Origins:
    return unit.name(node_text(node))


def _chained(unit: _Unit, node: Node) -> Origins:
    return unit.chained(node)


def _call(unit: _Unit, node: Node) -> Origins:
    return unit.call(node)


def _operator(node: Node) -> str:
    operator = node.child_by_field_name("operator")
    assert operator is not None, "binary expression without an operator"
    return node_text(operator)


def _kind(operator: str) -> str:
    if operator in TESTING_OPERATORS:
        return TESTING
    if operator in COMPARISONS:
        return COMPARING
    return COMBINING


def _operands(node: Node, kind: str) -> list[Node]:
    """The operands of a chain of one kind of binary operator, in source order."""
    leaves: list[Node] = []
    stack: list[Node] = [node]
    while len(stack) > 0:
        current = stack.pop()
        if current.type != "binary_expression" or _kind(_operator(current)) != kind:
            leaves.append(current)
            continue
        for field in ("right", "left"):
            child = current.child_by_field_name(field)
            if child is not None:
                stack.append(child)
    return leaves


def _binary(unit: _Unit, node: Node) -> Origins:
    """A chain of one kind of operator (``a + b + c``, ``a && b && c``), flattened so that
    its length is not depth: every operand of a testing chain but the last is a test."""
    kind = _kind(_operator(node))
    leaves = _operands(node, kind)
    found: set[str] = set()
    last = len(leaves) - 1
    for index, leaf in enumerate(leaves):
        if kind == TESTING and index < last:
            found.update(unit.test(leaf))
        else:
            found.update(unit.expr(leaf))
    if kind == COMPARING:
        return EMPTY
    return frozenset(found)


def _unary(unit: _Unit, node: Node) -> Origins:
    operator = node.child_by_field_name("operator")
    value = unit.expr(node.child_by_field_name("argument"))
    if operator is not None and node_text(operator) in BOOLEAN_UNARY:
        return EMPTY
    return value


def _ternary(unit: _Unit, node: Node) -> Origins:
    unit.test(node.child_by_field_name("condition"))
    return unit.expr(node.child_by_field_name("consequence")) | unit.expr(
        node.child_by_field_name("alternative")
    )


def _assignment(unit: _Unit, node: Node) -> Origins:
    value = unit.expr(node.child_by_field_name("right"))
    left = node.child_by_field_name("left")
    if left is None:
        return value
    if node.type == "augmented_assignment_expression":
        # `x ||= v`, `x ??= v`, `x &&= v` test x; `x += v` combines it.
        if _operator(node) in LOGICAL_ASSIGNMENTS:
            value = value | unit.test(left)
        else:
            value = value | unit.expr(left)
    unit.assign(left, value)
    return value


def _sequence(unit: _Unit, node: Node) -> Origins:
    value = EMPTY
    for child in _named(node):
        value = unit.expr(child)
    return value


def _pair(unit: _Unit, node: Node) -> Origins:
    unit.expr(node.child_by_field_name("key"))
    return unit.expr(node.child_by_field_name("value"))


def _yield(unit: _Unit, node: Node) -> Origins:
    value = unit.children(node)
    unit.returns.append(FlowReturn(node_span(unit.source, node), _sorted(value)))
    return EMPTY


ExpressionHandler = Callable[[_Unit, Node], Origins]
EXPRESSIONS: dict[str, ExpressionHandler] = {
    IDENTIFIER: _identifier,
    "shorthand_property_identifier": _shorthand,
    MEMBER: _chained,
    SUBSCRIPT: _chained,
    "call_expression": _call,
    "new_expression": _call,
    "binary_expression": _binary,
    "unary_expression": _unary,
    "ternary_expression": _ternary,
    "assignment_expression": _assignment,
    "augmented_assignment_expression": _assignment,
    "sequence_expression": _sequence,
    "pair": _pair,
    "yield_expression": _yield,
}


def collect_javascript_dataflow(source: SourceText, root: Node) -> DataflowFacts:
    return DataflowFacts(units=tuple(_Unit(source, info).run() for info in discover_units(root)))
