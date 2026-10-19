"""Property sets through one Python function, in source order (spec §5.2, P1a).

A value's set is what the analysis knows it carries: ``known`` properties, and whether
that is all of them (``exact``). An exact set can prove a requirement missing; an inexact
one (an unresolved callee, an await) can only prove a requirement present, otherwise the
answer is unknown. Assignment copies; ``produces`` adds; ``preserves`` copies the source's
set; ``preserves_except`` removes properties; ``a or b`` and ``a if c else b`` are one of
their operands, so the intersection; every other operation, literal and library call
carries nothing. Branches meet in the intersection, loops reach a fixed point, an except
handler starts from the set at the start of its try, and every await, yield, generator
expression, async for and async with is unknown. What a call does (a project callee's
contract, a sink, a library) is the caller's :class:`Hooks`.
"""

import ast
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Protocol

from shockharness.contracts.catalog import PRESERVES, PRESERVES_EXCEPT, PRODUCES, REQUIRES


@dataclass(frozen=True)
class PropSet:
    known: frozenset[str]
    exact: bool
    why: str  # what made an inexact set inexact (or a note on an exact one); "" otherwise
    # The value may be a generator (a generator expression, a generator function's
    # result): a library call or a comprehension that consumes it is unknown (§5.2c).
    lazy: bool
    # A resolved generator function's result: the set its items carry, which a for or an
    # async for binds (the intersection over its yields).
    items: "PropSet | None"
    # A resolved async function's result (a coroutine or a Promise): what awaiting gives.
    awaited: "PropSet | None"

    def render(self) -> str:
        return "{" + ", ".join(sorted(self.known)) + "}"


def known_set(known: frozenset[str]) -> PropSet:
    """Exactly these properties."""
    return PropSet(known, exact=True, why="", lazy=False, items=None, awaited=None)


EMPTY = known_set(frozenset())
# A local name before its first binding on a path: where paths meet, it gives way to the
# set of the paths that bound it (reading it on the others raises).
UNBOUND = PropSet(
    frozenset(),
    exact=False,
    why="a name read before it is bound",
    lazy=False,
    items=None,
    awaited=None,
)


def unknown(why: str) -> PropSet:
    return PropSet(frozenset(), exact=False, why=why, lazy=False, items=None, awaited=None)


def lazy_unknown(why: str) -> PropSet:
    """A generator whose items are unknown."""
    return PropSet(frozenset(), exact=False, why=why, lazy=True, items=None, awaited=None)


def generator(items: PropSet) -> PropSet:
    """What calling a resolved generator function gives: nothing of its own, and items."""
    return PropSet(frozenset(), exact=True, why="", lazy=True, items=items, awaited=None)


def coroutine(result: PropSet) -> PropSet:
    """What calling a resolved async function gives: nothing until it is awaited."""
    return PropSet(frozenset(), exact=True, why="", lazy=False, items=None, awaited=result)


def _meet_parts(first: PropSet | None, second: PropSet | None) -> PropSet | None:
    if first is None or second is None:
        return None
    return meet(first, second)


def meet(first: PropSet, second: PropSet) -> PropSet:
    reasons = [s.why for s in (first, second) if not s.exact]
    why = ""
    if len(reasons) > 0:
        why = min(reasons)  # deterministic, so the loop fixed point is order-independent
    return PropSet(
        first.known & second.known,
        exact=first.exact and second.exact,
        why=why,
        lazy=first.lazy or second.lazy,
        items=_meet_parts(first.items, second.items),
        awaited=_meet_parts(first.awaited, second.awaited),
    )


def element_of(container: PropSet, what: str) -> PropSet:
    """An element taken out of a value (an unpacked name, a comprehension variable):
    nothing when the container is known, unknown when it is not or is a generator."""
    if container.lazy:
        return unknown(f"{what} of a generator consumed here (only a for loop binds its items)")
    if container.exact:
        return EMPTY
    return unknown(f"{what} of a value the analysis cannot follow ({container.why})")


def loop_element(container: PropSet, what: str) -> PropSet:
    """A for or async for variable: a resolved generator's item set, else an element."""
    if container.items is not None:
        return container.items
    return element_of(container, what)


def awaited(value: PropSet) -> PropSet:
    """``await x``: a resolved coroutine gives its result; otherwise await is transparent."""
    if value.awaited is not None:
        return value.awaited
    return value


def intersection(results: Sequence[PropSet]) -> PropSet:
    """The intersection of a unit's returns or of its yields (none: nothing)."""
    if len(results) == 0:
        return EMPTY
    found = results[0]
    for value in results[1:]:
        found = meet(found, value)
    return found


Env = dict[str, PropSet]


def _joined(first: PropSet, second: PropSet) -> PropSet:
    if first is UNBOUND:
        return second
    if second is UNBOUND:
        return first
    return meet(first, second)


def merge(states: Iterable[Env | None]) -> Env | None:
    """The state where paths meet; ``None`` (unreachable) when no path arrives. Every
    state of a unit has the same names (its entry state lists them all)."""
    live = [state for state in states if state is not None]
    if len(live) == 0:
        return None
    merged = dict(live[0])
    for state in live[1:]:
        for name, value in state.items():
            merged[name] = _joined(merged[name], value)
    return merged


@dataclass(frozen=True)
class Declaration:
    """A call that resolves to one of the runtime module's four functions."""

    kind: str
    call: ast.Call
    properties: frozenset[str]  # the catalog properties it names
    valid: bool  # False: PROP006, the call is the identity and contributes nothing


@dataclass(frozen=True)
class Part:
    """A non-literal part of a composition: its set, and its text for the note."""

    value: PropSet
    text: str


class Hooks(Protocol):
    def passed(self, name: str) -> PropSet | None:
        """For a parametric parameter (decision 48), the set the caller passed for it;
        None for any other name, or when no caller is in view."""
        ...

    def literal(self) -> PropSet:
        """What a string literal with no interpolation carries (``literal_satisfies``)."""
        ...

    def compose(self, operation: str, parts: Sequence[Part]) -> PropSet:
        """A composition's set, by the catalog's rules for ``operation``."""
        ...

    def assigned(
        self, target: ast.expr, value: ast.expr, value_set: PropSet, reporting: bool
    ) -> None:
        """An assignment to an attribute or subscript: an assignment-target sink."""
        ...

    def is_declaration(self, call: ast.Call) -> bool:
        """Whether the call resolves to one of the runtime module's four functions."""
        ...

    def declaration(self, call: ast.Call) -> Declaration:
        """The declaration a call is (only for one :meth:`is_declaration` accepts)."""
        ...

    def checks_requires(self, declaration: Declaration) -> bool:
        """Whether a requires is a mid-body check (not the function's own header)."""
        ...

    def requirement(self, declaration: Declaration, value: PropSet, reporting: bool) -> None:
        """A mid-body requires: the value must carry the declared properties."""
        ...

    def call(
        self,
        call: ast.Call,
        arguments: Sequence[PropSet],
        keywords: Sequence[tuple[str | None, PropSet]],
        reporting: bool,
    ) -> PropSet:
        """An ordinary call: its checks (when reporting) and its result's set."""
        ...


@dataclass(frozen=True)
class LoopFrame:
    breaks: list[Env]
    continues: list[Env]


def _bound_names(target: ast.expr) -> list[str]:
    return [node.id for node in ast.walk(target) if isinstance(node, ast.Name)]


def _pattern_names(pattern: ast.pattern) -> list[str]:
    found: list[str] = []
    for node in ast.walk(pattern):
        if isinstance(node, ast.MatchAs | ast.MatchStar) and node.name is not None:
            found.append(node.name)
        if isinstance(node, ast.MatchMapping) and node.rest is not None:
            found.append(node.rest)
    return found


def _always_true(test: ast.expr) -> bool:
    return isinstance(test, ast.Constant) and bool(test.value)


class Flow:
    """One walk of one unit's statements; ``returns`` collects each return's set."""

    def __init__(self, hooks: Hooks) -> None:
        self.hooks = hooks
        self.reporting = True
        self.loops: list[LoopFrame] = []
        # The set at each return and yield, from the last walk past it (a loop's final pass).
        self.returns: dict[ast.AST, PropSet] = {}
        self.yields: dict[ast.AST, PropSet] = {}

    # -- statements -------------------------------------------------------------------

    def block(self, statements: Sequence[ast.stmt], state: Env | None) -> Env | None:
        for statement in statements:
            if state is None:
                return None
            state = self.statement(statement, state)
        return state

    def statement(self, node: ast.stmt, env: Env) -> Env | None:
        kind = type(node)
        if kind in STATEMENTS:
            return STATEMENTS[kind](self, node, env)
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.expr):
                self.expression(child, env)
        return env

    def assign(self, node: ast.Assign, env: Env) -> Env:
        for target in node.targets:
            if not self._pairwise(target, node.value, env):
                value = self.expression(node.value, env)
                self._assigned(target, node.value, value)
                self.bind(target, value, env)
        return env

    def _assigned(self, target: ast.expr, value: ast.expr, value_set: PropSet) -> None:
        if isinstance(target, ast.Attribute | ast.Subscript):
            self.hooks.assigned(target, value, value_set, self.reporting)

    def _pairwise(self, target: ast.expr, value: ast.expr, env: Env) -> bool:
        """``a, b = x, y``: each name takes its own element's set."""
        if not isinstance(target, ast.Tuple | ast.List) or not isinstance(
            value, ast.Tuple | ast.List
        ):
            return False
        if len(target.elts) != len(value.elts):
            return False
        if any(isinstance(e, ast.Starred) for e in [*target.elts, *value.elts]):
            return False
        sets = [self.expression(element, env) for element in value.elts]
        for element, value_set in zip(target.elts, sets, strict=True):
            self.bind(element, value_set, env)
        return True

    def annotated(self, node: ast.AnnAssign, env: Env) -> Env:
        if node.value is not None:
            value = self.expression(node.value, env)
            self._assigned(node.target, node.value, value)
            self.bind(node.target, value, env)
        return env

    def augmented(self, node: ast.AugAssign, env: Env) -> Env:
        value = self.expression(node.value, env)
        self._assigned(node.target, node.value, value)  # el.html += part: the part reaches it
        self.bind(node.target, EMPTY, env)  # x += 1 is an operation
        return env

    def bind(self, target: ast.expr, value: PropSet, env: Env) -> None:
        if isinstance(target, ast.Name):
            env[target.id] = value
            return
        if isinstance(target, ast.Tuple | ast.List | ast.Starred):
            element = element_of(value, "an unpacked element")
            for name in _bound_names(target):
                env[name] = element
            return
        for child in ast.iter_child_nodes(target):  # obj.attr = v, m[k] = v
            if isinstance(child, ast.expr):
                self.expression(child, env)

    def return_(self, node: ast.Return, env: Env) -> None:
        value = EMPTY
        if node.value is not None:
            value = self.expression(node.value, env)
        self.returns[node] = value
        return None

    def raise_(self, node: ast.Raise, env: Env) -> None:
        for child in (node.exc, node.cause):
            if child is not None:
                self.expression(child, env)
        return None

    def break_(self, node: ast.Break, env: Env) -> None:
        self.loops[len(self.loops) - 1].breaks.append(env)
        return None

    def continue_(self, node: ast.Continue, env: Env) -> None:
        self.loops[len(self.loops) - 1].continues.append(env)
        return None

    def if_(self, node: ast.If, env: Env) -> Env | None:
        self.expression(node.test, env)
        return merge([self.block(node.body, dict(env)), self.block(node.orelse, dict(env))])

    def definition(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, env: Env
    ) -> Env:
        env[node.name] = EMPTY  # a nested definition is its own unit
        return env

    def with_(self, node: ast.With | ast.AsyncWith, env: Env) -> Env | None:
        for item in node.items:
            value = self.expression(item.context_expr, env)
            if item.optional_vars is not None:
                bound = element_of(value, "the value a with statement binds")
                if isinstance(node, ast.AsyncWith):
                    bound = unknown(
                        "an async with binding (what __aenter__ returns is not followed)"
                    )
                for name in _bound_names(item.optional_vars):
                    env[name] = bound
        return self.block(node.body, env)

    def try_(self, node: ast.Try | ast.TryStar, env: Env) -> Env | None:
        start = dict(env)
        body = self.block(node.body, dict(env))
        outcomes: list[Env | None] = [None]
        if body is not None:
            outcomes = [self.block(node.orelse, body)]
        for handler in node.handlers:
            state = dict(start)  # what the try produced may not have happened
            if handler.type is not None:
                self.expression(handler.type, state)
            if handler.name is not None:
                state[handler.name] = EMPTY
            outcomes.append(self.block(handler.body, state))
        merged = merge(outcomes)
        if len(node.finalbody) == 0:
            return merged
        # The finally block is checked from what every path may bring to it.
        checked = merge([start, merged])
        assert checked is not None, "the start of the try is a live state"
        self.block(node.finalbody, checked)
        if merged is None:
            return None
        return self._quietly(node.finalbody, merged)

    def _quietly(self, statements: Sequence[ast.stmt], env: Env) -> Env | None:
        saved = self.reporting
        self.reporting = False
        out = self.block(statements, env)
        self.reporting = saved
        return out

    def match(self, node: ast.Match, env: Env) -> Env | None:
        subject = self.expression(node.subject, env)
        captured = element_of(subject, "a match capture")
        outcomes: list[Env | None] = [env]  # no case matched
        for case in node.cases:
            state = dict(env)
            for name in _pattern_names(case.pattern):
                state[name] = captured
            if case.guard is not None:
                self.expression(case.guard, state)
            outcomes.append(self.block(case.body, state))
        return merge(outcomes)

    # -- loops ------------------------------------------------------------------------

    def for_(self, node: ast.For | ast.AsyncFor, env: Env) -> Env | None:
        iterated = self.expression(node.iter, env)
        element = loop_element(iterated, "an item")
        if isinstance(node, ast.AsyncFor) and iterated.items is None:
            element = unknown("an async for item of a value that is not a resolved async generator")
        return self._loop(node, env, element, exits=True)

    def while_(self, node: ast.While, env: Env) -> Env | None:
        return self._loop(node, env, EMPTY, exits=not _always_true(node.test))

    def _loop(
        self, node: ast.For | ast.AsyncFor | ast.While, entry: Env, element: PropSet, exits: bool
    ) -> Env | None:
        """Iterate to a fixed point without reporting, then walk once more reporting."""
        saved = self.reporting
        self.reporting = False
        head = dict(entry)
        stable = False
        while not stable:
            out, frame = self._pass(node, head, element)
            widened = merge([entry, out, *frame.continues])
            assert widened is not None, "the loop entry is a live state"
            stable = widened == head
            head = widened
        self.reporting = saved
        _out, frame = self._pass(node, head, element)
        normal: Env | None = None
        if exits:
            normal = self.block(node.orelse, dict(head))
        return merge([normal, *frame.breaks])

    def _pass(
        self, node: ast.For | ast.AsyncFor | ast.While, head: Env, element: PropSet
    ) -> tuple[Env | None, LoopFrame]:
        frame = LoopFrame([], [])
        self.loops.append(frame)
        state = dict(head)
        if isinstance(node, ast.While):
            self.expression(node.test, state)
        else:
            self.bind(node.target, element, state)
        out = self.block(node.body, state)
        self.loops.pop()
        return out, frame

    # -- expressions ------------------------------------------------------------------

    def expression(self, node: ast.expr, env: Env) -> PropSet:
        kind = type(node)
        if kind in EXPRESSIONS:
            return EXPRESSIONS[kind](self, node, env)
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.expr):
                self.expression(child, env)
        return EMPTY  # an undeclared operation destroys every property

    def name(self, node: ast.Name, env: Env) -> PropSet:
        return env[node.id]  # the entry state lists every name the unit reads

    def constant(self, node: ast.Constant, env: Env) -> PropSet:
        if isinstance(node.value, str):
            return self.hooks.literal()
        return EMPTY

    def _parts(self, nodes: Sequence[ast.expr], env: Env) -> list[Part]:
        return [Part(self.expression(node, env), ast.unparse(node)) for node in nodes]

    def fstring(self, node: ast.JoinedStr, env: Env) -> PropSet:
        values = [v.value for v in node.values if isinstance(v, ast.FormattedValue)]
        if len(values) == 0:
            return self.hooks.literal()
        return self.hooks.compose(FSTRING, self._parts(values, env))

    def binary(self, node: ast.BinOp, env: Env) -> PropSet:
        """``"a" + b + "c"`` is a concatenation and ``"%s" % x`` a format when a string
        literal is part of it; any other arithmetic is an undeclared operation."""
        if isinstance(node.op, ast.Mod) and _is_text(node.left):
            values = node.right.elts if isinstance(node.right, ast.Tuple) else [node.right]
            return self.hooks.compose(FORMAT, self._parts(values, env))
        leaves = _concatenated(node)
        if isinstance(node.op, ast.Add) and any(_is_text(leaf) for leaf in leaves):
            others = [leaf for leaf in leaves if not _is_literal(leaf)]
            return self.hooks.compose(CONCAT, self._parts(others, env))
        self.expression(node.left, env)
        self.expression(node.right, env)
        return EMPTY

    def lambda_(self, node: ast.Lambda, env: Env) -> PropSet:
        return EMPTY

    def await_(self, node: ast.Await, env: Env) -> PropSet:
        return awaited(self.expression(node.value, env))

    def yield_(self, node: ast.Yield, env: Env) -> PropSet:
        value = EMPTY  # a bare yield yields None
        if node.value is not None:
            value = self.expression(node.value, env)
        self.yields[node] = value
        return unknown("the value sent into a generator")

    def yield_from(self, node: ast.YieldFrom, env: Env) -> PropSet:
        delegated = self.expression(node.value, env)
        items = unknown("yield from a generator the analysis cannot follow")
        if delegated.items is not None:
            items = delegated.items
        self.yields[node] = items
        return unknown("the value a delegated generator returns")

    def named(self, node: ast.NamedExpr, env: Env) -> PropSet:
        value = self.expression(node.value, env)
        env[node.target.id] = value
        return value

    def either(self, node: ast.BoolOp, env: Env) -> PropSet:
        sets = [self.expression(value, env) for value in node.values]
        result = sets[0]
        for value in sets[1:]:
            result = meet(result, value)
        return result

    def conditional(self, node: ast.IfExp, env: Env) -> PropSet:
        self.expression(node.test, env)
        body, orelse = dict(env), dict(env)
        result = meet(self.expression(node.body, body), self.expression(node.orelse, orelse))
        merged = merge([body, orelse])
        assert merged is not None, "both operands are live"
        env.clear()
        env.update(merged)
        return result

    def _scope(
        self, node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp, env: Env
    ) -> tuple[Env, bool]:
        """A comprehension's names bound to their items, and whether it is async."""
        inner = dict(env)
        asynchronous = False
        for generator in node.generators:
            iterated = self.expression(generator.iter, inner)
            for name in _bound_names(generator.target):
                inner[name] = element_of(iterated, "an item")
            for condition in generator.ifs:
                self.expression(condition, inner)
            asynchronous = asynchronous or bool(generator.is_async)
        return inner, asynchronous

    def comprehension(
        self, node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp, env: Env
    ) -> PropSet:
        inner, asynchronous = self._scope(node, env)
        elements = [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]
        for element in elements:
            self.expression(element, inner)
        if isinstance(node, ast.GeneratorExp):
            return lazy_unknown("a generator expression (its items are not followed)")
        if asynchronous:
            return unknown("an async comprehension (its items are not followed)")
        return EMPTY

    def call(self, node: ast.Call, env: Env) -> PropSet:
        if self.hooks.is_declaration(node):
            return self.declared(self.hooks.declaration(node), env)
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == FORMAT and _is_literal(func.value):
            values = [*node.args, *(kw.value for kw in node.keywords)]
            return self.hooks.compose(FORMAT, self._parts(values, env))
        if _is_join(node):
            return self._join(node, env)
        self.expression(node.func, env)
        arguments = [self.expression(argument, env) for argument in node.args]
        keywords = [(kw.arg, self.expression(kw.value, env)) for kw in node.keywords]
        return self.hooks.call(node, arguments, keywords, self.reporting)

    def _join(self, node: ast.Call, env: Env) -> PropSet:
        """``"sep".join(items)``: a composition of the separator (unless it is a literal)
        and each item, when the items are written out (a list, tuple or set display) or
        built by a comprehension or generator expression; else the items' sets are not
        followed."""
        assert isinstance(node.func, ast.Attribute), "a join is a method call"
        parts: list[Part] = []
        if not _is_literal(node.func.value):
            parts.append(Part(self.expression(node.func.value, env), ast.unparse(node.func.value)))
        items = node.args[0]
        if isinstance(items, ast.List | ast.Tuple | ast.Set):
            parts.extend(self._item(element, env) for element in items.elts)
        elif isinstance(items, ast.ListComp | ast.SetComp | ast.GeneratorExp):
            inner, asynchronous = self._scope(items, env)
            value = self.expression(items.elt, inner)
            if asynchronous:
                value = unknown("an async comprehension (its items are not followed)")
            parts.append(Part(value, ast.unparse(items.elt)))
        else:
            value = self.expression(items, env)
            why = f"the items of {ast.unparse(items)} (a joined value's items are not followed)"
            parts.append(Part(_items(value, why), ast.unparse(items)))
        return self.hooks.compose(JOIN, parts)

    def _item(self, element: ast.expr, env: Env) -> Part:
        if isinstance(element, ast.Starred):
            self.expression(element.value, env)
            why = "a starred item (its items are not followed)"
            return Part(unknown(why), ast.unparse(element))
        return Part(self.expression(element, env), ast.unparse(element))

    def declared(self, declaration: Declaration, env: Env) -> PropSet:
        arguments = declaration.call.args
        sets = [self.expression(argument, env) for argument in arguments]
        for keyword in declaration.call.keywords:
            self.expression(keyword.value, env)
        if not declaration.valid:
            return sets[0] if len(sets) > 0 else EMPTY  # the identity, contributing nothing
        value = sets[0]
        if declaration.kind == REQUIRES:
            if self.hooks.checks_requires(declaration):
                self.hooks.requirement(declaration, value, self.reporting)
            return value
        result = self._declared_result(declaration, arguments, sets)
        target = arguments[0]
        if isinstance(target, ast.Name):
            env[target.id] = result  # from this point on, the value carries it
        return result

    def _declared_result(
        self, declaration: Declaration, arguments: Sequence[ast.expr], sets: Sequence[PropSet]
    ) -> PropSet:
        if declaration.kind == PRODUCES:
            value = sets[0]
            return replace(value, known=value.known | declaration.properties)
        source = sets[1]
        if not isinstance(arguments[1], ast.Name):
            return unknown("preserves names a source that is not a local value")
        caller = self.hooks.passed(arguments[1].id)
        if caller is not None:
            source = caller  # a generic pass-through: what this call site passed
        if declaration.kind == PRESERVES_EXCEPT:
            return replace(source, known=source.known - declaration.properties)
        assert declaration.kind == PRESERVES, f"unexpected declaration {declaration.kind}"
        return source


def _is_literal(node: ast.expr) -> bool:
    """A string literal with no interpolation."""
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _is_join(node: ast.Call) -> bool:
    """``"sep".join(items)`` (or an f-string separator): one positional argument."""
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == JOIN
        and _is_text(func.value)
        and len(node.args) == 1
        and not isinstance(node.args[0], ast.Starred)
        and len(node.keywords) == 0
    )


def _items(value: PropSet, why: str) -> PropSet:
    """What a joined value's items carry: a resolved generator function's items, else not
    followed (a container's elements are not tracked)."""
    if value.items is not None:
        return value.items
    return unknown(why)


def _is_text(node: ast.expr) -> bool:
    """A string literal or an f-string: what makes ``+`` a concatenation."""
    return _is_literal(node) or isinstance(node, ast.JoinedStr)


def _concatenated(node: ast.BinOp) -> list[ast.expr]:
    """The operands of a left-nested chain of ``+`` (``a + b + c``)."""
    leaves: list[ast.expr] = [node.right]
    current: ast.expr = node.left
    while isinstance(current, ast.BinOp) and isinstance(current.op, ast.Add):
        leaves.append(current.right)
        current = current.left
    leaves.append(current)
    leaves.reverse()
    return leaves


FSTRING = "fstring"
CONCAT = "concat"
JOIN = "join"
FORMAT = "format"

STATEMENTS: dict[type[ast.stmt], Callable[..., Env | None]] = {
    ast.Assign: Flow.assign,
    ast.AnnAssign: Flow.annotated,
    ast.AugAssign: Flow.augmented,
    ast.Return: Flow.return_,
    ast.Raise: Flow.raise_,
    ast.Break: Flow.break_,
    ast.Continue: Flow.continue_,
    ast.If: Flow.if_,
    ast.For: Flow.for_,
    ast.AsyncFor: Flow.for_,
    ast.While: Flow.while_,
    ast.With: Flow.with_,
    ast.AsyncWith: Flow.with_,
    ast.Try: Flow.try_,
    ast.TryStar: Flow.try_,
    ast.Match: Flow.match,
    ast.FunctionDef: Flow.definition,
    ast.AsyncFunctionDef: Flow.definition,
    ast.ClassDef: Flow.definition,
}

EXPRESSIONS: dict[type[ast.expr], Callable[..., PropSet]] = {
    ast.Name: Flow.name,
    ast.Constant: Flow.constant,
    ast.Lambda: Flow.lambda_,
    ast.Await: Flow.await_,
    ast.Yield: Flow.yield_,
    ast.YieldFrom: Flow.yield_from,
    ast.NamedExpr: Flow.named,
    ast.BoolOp: Flow.either,
    ast.IfExp: Flow.conditional,
    ast.ListComp: Flow.comprehension,
    ast.SetComp: Flow.comprehension,
    ast.DictComp: Flow.comprehension,
    ast.GeneratorExp: Flow.comprehension,
    ast.Call: Flow.call,
    ast.JoinedStr: Flow.fstring,
    ast.BinOp: Flow.binary,
}


@dataclass(frozen=True)
class Summary:
    """One unit walked: its result set (the intersection over its returns, and falling
    off the end, which returns None), its item set (over its yields) and each return."""

    result: PropSet
    items: PropSet
    returns: Mapping[ast.AST, PropSet]


def run_unit(hooks: Hooks, body: Sequence[ast.stmt], entry: Env) -> Summary:
    flow = Flow(hooks)
    out = flow.block(body, entry)
    results = list(flow.returns.values())
    if out is not None or len(results) == 0:
        results.append(EMPTY)
    return Summary(
        intersection(results), intersection(list(flow.yields.values())), dict(flow.returns)
    )
