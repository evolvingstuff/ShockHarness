"""Property sets through one JavaScript or TypeScript function (spec §5.2, P1b).

The counterpart of :mod:`.python_flow`, over tree-sitter nodes, with the same transfer
rules:

* assignment copies; ``produces`` adds; ``preserves`` copies the source's set and
  ``preserves_except`` removes properties;
* ``a || b``, ``a ?? b`` and ``c ? a : b`` are the intersection of their operands;
* a string literal carries the ``literal_satisfies`` properties. A template literal, or a
  ``+`` chain with a string or template literal in it, is composed by the catalog's
  rules;
* every other operation, library call and literal carries nothing;
* branches meet in the intersection, loops reach a fixed point, a catch clause starts
  from the set at the start of its try. ``break`` inside a ``switch`` leaves the switch;
* every ``await``, ``yield``, ``for await`` and ``new`` is unknown.

What a call or an assignment to a property does is the caller's :class:`JsHooks`.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Protocol

from tree_sitter import Node

from shockharness.contracts.catalog import PRESERVES, PRESERVES_EXCEPT, PRODUCES, REQUIRES
from shockharness.contracts.python_flow import (
    EMPTY,
    Env,
    Part,
    PropSet,
    awaited,
    element_of,
    intersection,
    loop_element,
    meet,
    merge,
    unknown,
)
from shockharness.ir.javascript_catches import TYPE_WRAPPERS, node_text
from shockharness.ir.javascript_functions import UNIT_TYPES, pattern_names
from shockharness.ir.javascript_nodes import Field, Kind

TEMPLATE_LITERAL = "template_literal"
CONCAT = "concat"
EITHER = frozenset({"||", "??"})
BOTH = "&&"
LOGICAL_ASSIGNMENTS = frozenset({"||=", "??=", "&&="})
PLUS = "+"
OF = "of"
AWAIT = "await"
DELEGATE = "*"
STRINGS = frozenset({Kind.STRING, Kind.TEMPLATE_STRING})
CONSTANTS = frozenset(
    {
        Kind.NUMBER,
        Kind.TRUE,
        Kind.FALSE,
        Kind.NULL,
        Kind.UNDEFINED,
        Kind.REGEX,
        Kind.THIS,
        Kind.SUPER,
    }
)
# A nested function, method or class is its own unit, exactly as the unit's names are
# collected (``own_nodes``): an object literal's method included, so the flow never reads
# a name the entry state does not list.
NESTED_UNITS = UNIT_TYPES
TRANSPARENT = frozenset({Kind.PARENTHESIZED_EXPRESSION}) | TYPE_WRAPPERS
DECLARED_NAMES = frozenset(
    {Kind.FUNCTION_DECLARATION, Kind.GENERATOR_FUNCTION_DECLARATION, Kind.CLASS_DECLARATION}
)
SWITCH = "switch"
LOOP = "loop"


def children(node: Node) -> list[Node]:
    return [child for child in node.named_children if child.type != Kind.COMMENT]


def field(node: Node, name: str) -> Node | None:
    return node.child_by_field_name(name)


def field_nodes(node: Node, name: str) -> list[Node]:
    """The field's node in a list; empty when the grammar leaves the field out (``let x;``
    has no value, ``if`` no ``else``)."""
    found = node.child_by_field_name(name)
    if found is None:
        return []
    return [found]


def inner(node: Node, name: str) -> list[Node]:
    """The children of a field's node (``else { ... }``, ``(a, b)``); empty without it."""
    return [child for found in field_nodes(node, name) for child in children(found)]


def has_token(node: Node, token: str) -> bool:
    return any(not child.is_named and child.type == token for child in node.children)


@dataclass(frozen=True)
class JsDeclaration:
    kind: str
    call: Node
    arguments: tuple[Node, ...]
    properties: frozenset[str]
    valid: bool  # False: PROP006, the call is the identity and contributes nothing


class JsHooks(Protocol):
    def passed(self, name: str) -> PropSet | None: ...

    def literal(self) -> PropSet: ...

    def compose(self, operation: str, parts: Sequence[Part]) -> PropSet: ...

    def assigned(self, target: Node, value: Node, value_set: PropSet, reporting: bool) -> None: ...

    def is_declaration(self, call: Node) -> bool: ...

    def declaration(self, call: Node) -> JsDeclaration: ...

    def checks_requires(self, declaration: JsDeclaration) -> bool: ...

    def requirement(self, declaration: JsDeclaration, value: PropSet, reporting: bool) -> None: ...

    def call(self, call: Node, arguments: Sequence[PropSet], reporting: bool) -> PropSet: ...


@dataclass(frozen=True)
class Frame:
    kind: str  # LOOP or SWITCH
    breaks: list[Env]
    continues: list[Env]


def _concatenated(node: Node) -> list[Node]:
    """The operands of a left-nested chain of ``+``."""
    leaves: list[Node] = []
    current = node
    while current.type == Kind.BINARY_EXPRESSION and _operator(current) == PLUS:
        right = field(current, Field.RIGHT)
        left = field(current, Field.LEFT)
        assert right is not None and left is not None, "a binary expression has operands"
        leaves.append(right)
        current = left
    leaves.append(current)
    leaves.reverse()
    return leaves


def _operator(node: Node) -> str:
    return "".join(node_text(found) for found in field_nodes(node, Field.OPERATOR))


def _substitutions(template: Node) -> list[Node]:
    found: list[Node] = []
    for child in children(template):
        if child.type == Kind.TEMPLATE_SUBSTITUTION:
            found.extend(children(child))
    return found


def _bound(target: Node) -> list[str]:
    if target.type == Kind.IDENTIFIER:
        return [node_text(target)]
    return pattern_names(target)


class JsFlow:
    def __init__(self, hooks: JsHooks) -> None:
        self.hooks = hooks
        self.reporting = True
        self.frames: list[Frame] = []
        # The set at each return and yield (by node id), from the last walk past it.
        self.returns: dict[int, PropSet] = {}
        self.return_nodes: dict[int, Node] = {}
        self.yields: dict[int, PropSet] = {}

    # -- statements -------------------------------------------------------------------

    def block(self, statements: Sequence[Node], state: Env | None) -> Env | None:
        for statement in statements:
            if state is None:
                return None
            state = self.statement(statement, state)
        return state

    def statement(self, node: Node, env: Env) -> Env | None:
        if node.type in STATEMENTS:
            return STATEMENTS[node.type](self, node, env)
        if node.type in DECLARED_NAMES:
            name = field(node, Field.NAME)
            if name is not None:
                env[node_text(name)] = EMPTY  # a nested definition is its own unit
            return env
        if node.type in SKIPPED:
            return env
        self.expression(node, env)
        return env

    def statements(self, node: Node, env: Env) -> Env | None:
        return self.block(children(node), env)

    def expression_statement(self, node: Node, env: Env) -> Env:
        for child in children(node):
            self.expression(child, env)
        return env

    def declaration(self, node: Node, env: Env) -> Env:
        for declarator in children(node):
            if declarator.type != Kind.VARIABLE_DECLARATOR:
                continue
            name = field(declarator, Field.NAME)
            value_set = EMPTY  # let x; is undefined
            for found in field_nodes(declarator, Field.VALUE):
                value_set = self.expression(found, env)
            if name is not None:
                self.bind(name, value_set, env)
        return env

    def bind(self, target: Node, value: PropSet, env: Env) -> None:
        if target.type == Kind.IDENTIFIER:
            env[node_text(target)] = value
            return
        element = element_of(value, "a destructured element")
        for name in pattern_names(target):
            env[name] = element

    def export(self, node: Node, env: Env) -> Env | None:
        declaration = field(node, Field.DECLARATION)
        if declaration is not None:
            return self.statement(declaration, env)
        value = field(node, Field.VALUE)
        if value is not None:
            self.expression(value, env)
        return env

    def if_(self, node: Node, env: Env) -> Env | None:
        condition = field(node, Field.CONDITION)
        if condition is not None:
            self.expression(condition, env)
        taken = self.block(field_nodes(node, Field.CONSEQUENCE), dict(env))
        other = self.block(inner(node, Field.ALTERNATIVE), dict(env))
        return merge([taken, other])

    def return_(self, node: Node, env: Env) -> None:
        value = EMPTY  # return; returns undefined
        for returned in children(node)[:1]:
            value = self.expression(returned, env)
        self.returns[node.id] = value
        self.return_nodes[node.id] = node
        return None

    def throw(self, node: Node, env: Env) -> None:
        for child in children(node):
            self.expression(child, env)
        return None

    def break_(self, node: Node, env: Env) -> None:
        self.frames[len(self.frames) - 1].breaks.append(env)
        return None

    def continue_(self, node: Node, env: Env) -> None:
        loops = [frame for frame in self.frames if frame.kind == LOOP]
        loops[len(loops) - 1].continues.append(env)
        return None

    def try_(self, node: Node, env: Env) -> Env | None:
        start = dict(env)
        handler = field(node, Field.HANDLER)
        finalizer = field(node, Field.FINALIZER)
        outcomes = [self.block(field_nodes(node, Field.BODY), dict(env))]
        if handler is not None:
            state = dict(start)  # what the try produced may not have happened
            parameter = field(handler, Field.PARAMETER)
            if parameter is not None:
                for name in _bound(parameter):
                    state[name] = EMPTY
            outcomes.append(self.block(field_nodes(handler, Field.BODY), state))
        merged = merge(outcomes)
        if finalizer is None:
            return merged
        final = children(finalizer)
        checked = merge([start, merged])
        assert checked is not None, "the start of the try is a live state"
        self.block(final, checked)
        if merged is None:
            return None
        return self._quietly(final, merged)

    def _quietly(self, statements: Sequence[Node], env: Env) -> Env | None:
        saved = self.reporting
        self.reporting = False
        out = self.block(statements, env)
        self.reporting = saved
        return out

    def switch(self, node: Node, env: Env) -> Env | None:
        value = field(node, Field.VALUE)
        if value is not None:
            self.expression(value, env)
        frame = Frame(SWITCH, [], [])
        self.frames.append(frame)
        outcomes: list[Env | None] = [env]  # no case matched
        for case in inner(node, Field.BODY):
            state = dict(env)
            tested = field(case, Field.VALUE)
            if tested is not None:
                self.expression(tested, state)
            statements = [c for c in children(case) if tested is None or c != tested]
            outcomes.append(self.block(statements, state))
        self.frames.pop()
        return merge([*outcomes, *frame.breaks])

    # -- loops ------------------------------------------------------------------------

    def for_(self, node: Node, env: Env) -> Env | None:
        initializer = field(node, Field.INITIALIZER)
        state: Env | None = env
        if initializer is not None:
            state = self.statement(initializer, env)
        assert state is not None, "an initializer does not leave the function"
        condition = field(node, Field.CONDITION)
        increment = field(node, Field.INCREMENT)

        def one(head: Env) -> Env | None:
            if condition is not None:
                self.statement(condition, head)
            out = self.block(field_nodes(node, Field.BODY), head)
            if out is not None and increment is not None:
                self.expression(increment, out)
            return out

        return self._loop(state, one, exits=True)

    def for_in(self, node: Node, env: Env) -> Env | None:
        right = field(node, Field.RIGHT)
        left = field(node, Field.LEFT)
        assert right is not None, "for ... in/of has a right side"
        iterated = self.expression(right, env)
        element = EMPTY  # for...in: property names
        if has_token(node, OF):
            element = loop_element(iterated, "an item")
        if has_token(node, AWAIT) and iterated.items is None:
            element = unknown("a for await item of a value that is not a resolved generator")

        def one(head: Env) -> Env | None:
            if left is not None:
                for name in _loop_names(left):
                    head[name] = element
            return self.block(field_nodes(node, Field.BODY), head)

        return self._loop(env, one, exits=True)

    def while_(self, node: Node, env: Env) -> Env | None:
        condition = field(node, Field.CONDITION)

        def one(head: Env) -> Env | None:
            if condition is not None:
                self.expression(condition, head)
            return self.block(field_nodes(node, Field.BODY), head)

        return self._loop(env, one, exits=True)

    def do(self, node: Node, env: Env) -> Env | None:
        condition = field(node, Field.CONDITION)

        def one(head: Env) -> Env | None:
            out = self.block(field_nodes(node, Field.BODY), head)
            if out is not None and condition is not None:
                self.expression(condition, out)
            return out

        # The body runs at least once; the loop is entered with what may hold after it.
        first = self._quietly(field_nodes(node, Field.BODY), dict(env))
        entry = merge([env, first])
        assert entry is not None, "the loop entry is a live state"
        return self._loop(entry, one, exits=True)

    def _loop(self, entry: Env, one: Callable[[Env], Env | None], exits: bool) -> Env | None:
        """Iterate to a fixed point without reporting, then walk once more reporting."""
        saved = self.reporting
        self.reporting = False
        head = dict(entry)
        stable = False
        while not stable:
            out, frame = self._pass(one, head)
            widened = merge([entry, out, *frame.continues])
            assert widened is not None, "the loop entry is a live state"
            stable = widened == head
            head = widened
        self.reporting = saved
        _out, frame = self._pass(one, head)
        normal = dict(head) if exits else None
        return merge([normal, *frame.breaks])

    def _pass(self, one: Callable[[Env], Env | None], head: Env) -> tuple[Env | None, Frame]:
        frame = Frame(LOOP, [], [])
        self.frames.append(frame)
        out = one(dict(head))
        self.frames.pop()
        return out, frame

    # -- expressions ------------------------------------------------------------------

    def expression(self, node: Node, env: Env) -> PropSet:
        if node.type in EXPRESSIONS:
            return EXPRESSIONS[node.type](self, node, env)
        if node.type in CONSTANTS or node.type in NESTED_UNITS:
            return EMPTY
        for child in children(node):
            self.expression(child, env)
        return EMPTY  # an undeclared operation destroys every property

    def identifier(self, node: Node, env: Env) -> PropSet:
        return env[node_text(node)]  # the entry state lists every name the unit reads

    def transparent(self, node: Node, env: Env) -> PropSet:
        inner = children(node)
        if len(inner) == 0:
            return EMPTY
        result = self.expression(inner[0], env)
        for other in inner[1:]:
            self.expression(other, env)  # a TypeScript type, which reads no value
        return result

    def string(self, node: Node, env: Env) -> PropSet:
        return self.hooks.literal()

    def template(self, node: Node, env: Env) -> PropSet:
        parts = _substitutions(node)
        if len(parts) == 0:
            return self.hooks.literal()
        return self.hooks.compose(TEMPLATE_LITERAL, self._parts(parts, env))

    def _parts(self, nodes: Sequence[Node], env: Env) -> list[Part]:
        return [Part(self.expression(n, env), " ".join(node_text(n).split())) for n in nodes]

    def binary(self, node: Node, env: Env) -> PropSet:
        operator = _operator(node)
        left = field(node, Field.LEFT)
        right = field(node, Field.RIGHT)
        assert left is not None and right is not None, "a binary expression has operands"
        if operator == PLUS:
            leaves = _concatenated(node)
            if any(leaf.type in STRINGS for leaf in leaves):
                others = [leaf for leaf in leaves if leaf.type != Kind.STRING]
                return self.hooks.compose(CONCAT, self._parts(others, env))
        first = self.expression(left, env)
        second = self.expression(right, env)
        if operator in EITHER:
            return meet(first, second)  # the result is one of the operands
        if operator == BOTH:
            return meet(first, second)
        return EMPTY

    def ternary(self, node: Node, env: Env) -> PropSet:
        condition = field(node, Field.CONDITION)
        if condition is not None:
            self.expression(condition, env)
        consequence = field(node, Field.CONSEQUENCE)
        alternative = field(node, Field.ALTERNATIVE)
        taken, other = dict(env), dict(env)
        assert consequence is not None and alternative is not None, "a ternary has two branches"
        first = self.expression(consequence, taken)
        second = self.expression(alternative, other)
        merged = merge([taken, other])
        assert merged is not None, "both operands are live"
        env.clear()
        env.update(merged)
        return meet(first, second)

    def assignment(self, node: Node, env: Env) -> PropSet:
        left = field(node, Field.LEFT)
        right = field(node, Field.RIGHT)
        assert left is not None and right is not None, "an assignment has two sides"
        value = self.expression(right, env)
        if left.type in (Kind.MEMBER_EXPRESSION, Kind.SUBSCRIPT_EXPRESSION):
            self._evaluate_target(left, env)
            self.hooks.assigned(left, right, value, self.reporting)
        else:
            self.bind(left, value, env)
        return value

    def _evaluate_target(self, target: Node, env: Env) -> None:
        for child in children(target):
            if child.type not in (Kind.PROPERTY_IDENTIFIER, Kind.PRIVATE_PROPERTY_IDENTIFIER):
                self.expression(child, env)

    def augmented(self, node: Node, env: Env) -> PropSet:
        left = field(node, Field.LEFT)
        right = field(node, Field.RIGHT)
        assert left is not None and right is not None, "an assignment has two sides"
        value = self.expression(right, env)
        if left.type in (Kind.MEMBER_EXPRESSION, Kind.SUBSCRIPT_EXPRESSION):
            self._evaluate_target(left, env)
            self.hooks.assigned(left, right, value, self.reporting)  # el.html += part
            return EMPTY
        if left.type != Kind.IDENTIFIER:
            return EMPTY
        name = node_text(left)
        result = EMPTY  # x += 1 is an operation
        if _operator(node) in LOGICAL_ASSIGNMENTS:
            result = meet(env[name], value)  # x ??= y: x or y
        env[name] = result
        return result

    def await_(self, node: Node, env: Env) -> PropSet:
        value = EMPTY
        for child in children(node):
            value = self.expression(child, env)
        return awaited(value)

    def yield_(self, node: Node, env: Env) -> PropSet:
        """``yield x`` adds to the item set; ``yield* g`` adds a resolved generator's items."""
        value = EMPTY  # a bare yield yields undefined
        for child in children(node):
            value = self.expression(child, env)
        if has_token(node, DELEGATE):
            delegated = value.items
            value = unknown("yield* of a generator the analysis cannot follow")
            if delegated is not None:
                value = delegated
        self.yields[node.id] = value
        return unknown("the value sent into a generator")

    def constructed(self, node: Node, env: Env) -> PropSet:
        for child in children(node):
            self.expression(child, env)
        return unknown("a new expression (a constructor is not resolved)")

    def sequence(self, node: Node, env: Env) -> PropSet:
        result = EMPTY
        for child in children(node):
            result = self.expression(child, env)
        return result

    def call(self, node: Node, env: Env) -> PropSet:
        if self.hooks.is_declaration(node):
            return self.declared(self.hooks.declaration(node), env)
        function = field(node, Field.FUNCTION)
        arguments = field(node, Field.ARGUMENTS)
        if function is not None and function.type == Kind.IMPORT:
            return unknown("a dynamic import (the module it loads is not followed)")
        if function is not None:
            self.expression(function, env)
        passed = inner(node, Field.ARGUMENTS)
        sets = [self.expression(argument, env) for argument in passed]
        if arguments is not None and arguments.type == Kind.TEMPLATE_STRING:
            sets = []  # a tagged template: the tag is the call, the template its argument
        return self.hooks.call(node, sets, self.reporting)

    def _with_caller(self, declaration: JsDeclaration, sets: Sequence[PropSet]) -> list[PropSet]:
        """A preserves whose source is a parametric parameter takes the caller's set."""
        found = list(sets)
        source = declaration.arguments[1]
        if source.type == Kind.IDENTIFIER:
            caller = self.hooks.passed(node_text(source))
            if caller is not None:
                found[1] = caller
        return found

    def declared(self, declaration: JsDeclaration, env: Env) -> PropSet:
        sets = [self.expression(argument, env) for argument in declaration.arguments]
        if not declaration.valid:
            return sets[0] if len(sets) > 0 else EMPTY  # the identity, contributing nothing
        value = sets[0]
        if declaration.kind == REQUIRES:
            if self.hooks.checks_requires(declaration):
                self.hooks.requirement(declaration, value, self.reporting)
            return value
        if declaration.kind in (PRESERVES, PRESERVES_EXCEPT):
            sets = self._with_caller(declaration, sets)
        result = _declared_result(declaration, sets)
        target = declaration.arguments[0]
        if target.type == Kind.IDENTIFIER:
            env[node_text(target)] = result  # from this point on, the value carries it
        return result


def _declared_result(declaration: JsDeclaration, sets: Sequence[PropSet]) -> PropSet:
    """produces adds; preserves copies the source's set; preserves_except removes."""
    if declaration.kind == PRODUCES:
        value = sets[0]
        return replace(value, known=value.known | declaration.properties)
    if declaration.arguments[1].type != Kind.IDENTIFIER:
        return unknown("preserves names a source that is not a local value")
    source = sets[1]
    if declaration.kind == PRESERVES_EXCEPT:
        return replace(source, known=source.known - declaration.properties)
    assert declaration.kind == PRESERVES, f"unexpected declaration {declaration.kind}"
    return source


def _loop_names(left: Node) -> list[str]:
    """``for (const x of xs)``, ``for (x of xs)``, ``for (const [a, b] of xs)``."""
    if left.type in (Kind.LEXICAL_DECLARATION, Kind.VARIABLE_DECLARATION):
        names: list[str] = []
        for declarator in children(left):
            name = field(declarator, Field.NAME)
            if name is not None:
                names.extend(_bound(name))
        return names
    if left.type in (Kind.MEMBER_EXPRESSION, Kind.SUBSCRIPT_EXPRESSION):
        return []
    return _bound(left)


SKIPPED = frozenset(
    {
        Kind.IMPORT_STATEMENT,
        Kind.EMPTY_STATEMENT,
        Kind.DEBUGGER_STATEMENT,
        Kind.COMMENT,
    }
)

STATEMENTS: dict[str, Callable[[JsFlow, Node, Env], Env | None]] = {
    Kind.PROGRAM: JsFlow.statements,
    Kind.STATEMENT_BLOCK: JsFlow.statements,
    Kind.EXPRESSION_STATEMENT: JsFlow.expression_statement,
    Kind.LEXICAL_DECLARATION: JsFlow.declaration,
    Kind.VARIABLE_DECLARATION: JsFlow.declaration,
    Kind.EXPORT_STATEMENT: JsFlow.export,
    Kind.IF_STATEMENT: JsFlow.if_,
    Kind.RETURN_STATEMENT: JsFlow.return_,
    Kind.THROW_STATEMENT: JsFlow.throw,
    Kind.BREAK_STATEMENT: JsFlow.break_,
    Kind.CONTINUE_STATEMENT: JsFlow.continue_,
    Kind.TRY_STATEMENT: JsFlow.try_,
    Kind.SWITCH_STATEMENT: JsFlow.switch,
    Kind.FOR_STATEMENT: JsFlow.for_,
    Kind.FOR_IN_STATEMENT: JsFlow.for_in,
    Kind.WHILE_STATEMENT: JsFlow.while_,
    Kind.DO_STATEMENT: JsFlow.do,
    Kind.LABELED_STATEMENT: JsFlow.statements,
}

EXPRESSIONS: dict[str, Callable[[JsFlow, Node, Env], PropSet]] = {
    Kind.IDENTIFIER: JsFlow.identifier,
    Kind.STRING: JsFlow.string,
    Kind.TEMPLATE_STRING: JsFlow.template,
    Kind.BINARY_EXPRESSION: JsFlow.binary,
    Kind.TERNARY_EXPRESSION: JsFlow.ternary,
    Kind.ASSIGNMENT_EXPRESSION: JsFlow.assignment,
    Kind.AUGMENTED_ASSIGNMENT_EXPRESSION: JsFlow.augmented,
    Kind.AWAIT_EXPRESSION: JsFlow.await_,
    Kind.YIELD_EXPRESSION: JsFlow.yield_,
    Kind.NEW_EXPRESSION: JsFlow.constructed,
    Kind.SEQUENCE_EXPRESSION: JsFlow.sequence,
    Kind.CALL_EXPRESSION: JsFlow.call,
    **{kind: JsFlow.transparent for kind in TRANSPARENT},
}


@dataclass(frozen=True)
class JsSummary:
    """One unit walked: its result set, its item set (over its yields), each return."""

    result: PropSet
    items: PropSet
    returns: Mapping[int, PropSet]
    return_nodes: Mapping[int, Node]


def summarize(flow: JsFlow, out: Env | None) -> JsSummary:
    results = list(flow.returns.values())
    if out is not None or len(results) == 0:
        results.append(EMPTY)  # falling off the end returns undefined
    items = intersection(list(flow.yields.values()))
    return JsSummary(intersection(results), items, dict(flow.returns), dict(flow.return_nodes))


def run_js_unit(hooks: JsHooks, body: Sequence[Node], entry: Env) -> JsSummary:
    flow = JsFlow(hooks)
    return summarize(flow, flow.block(body, entry))
