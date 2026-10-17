"""Python dataflow facts (H6): each unit's value dependencies, read by rules/dataflow.py.

Flow-sensitive in source order, without paths: an assignment at the unit's top level
replaces a variable's origins, one inside a branch, loop or handler adds to them (so a
value validated on one path and not on another keeps both). Nested units are separate:
their bodies are not walked, and their name is a local with no origins. A call's result is
an origin of its own; nothing here knows which call is a source, a sink or a validator.
"""

import ast
from collections.abc import Callable, Iterable

from shockharness.constants import DATAFLOW_MAX_DEPTH, EVIDENCE_MAX_CHARS
from shockharness.ir.model import (
    ORIGIN_CALL,
    ORIGIN_PARAMETER,
    ORIGIN_READ,
    UNIT_METHOD,
    DataflowFacts,
    FlowCall,
    FlowRead,
    FlowReturn,
    FlowStore,
    FlowUnit,
    origin,
)
from shockharness.ir.python_catches import node_span
from shockharness.ir.python_functions import (
    FUNCTION_NODES,
    RECEIVER_NAMES,
    UNIT_NODES,
    UnitInfo,
    discover_units,
)
from shockharness.source import SourceText

Origins = frozenset[str]
EMPTY: Origins = frozenset()
DYNAMIC = "<dynamic>"
DOUBLE_STAR = "**"
STATICMETHOD = "staticmethod"
COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)
# Nodes that can bind a name in their unit (the only ones _local_names looks at).
BINDING_NODES = frozenset(
    {
        ast.Assign,
        ast.AnnAssign,
        ast.AugAssign,
        ast.For,
        ast.AsyncFor,
        ast.NamedExpr,
        ast.comprehension,
        ast.withitem,
        ast.match_case,
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef,
        ast.ExceptHandler,
        ast.Import,
        ast.ImportFrom,
        ast.Global,
        ast.Nonlocal,
    }
)


def _bound_names(target: ast.AST) -> list[str]:
    """Names a binding target introduces (``a``, ``a, (b, *c)``, a match capture)."""
    names: list[str] = []
    stack: list[ast.AST] = [target]
    while len(stack) > 0:
        node = stack.pop()
        if isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, ast.Tuple | ast.List):
            stack.extend(node.elts)
        elif isinstance(node, ast.Starred):
            stack.append(node.value)
        elif isinstance(node, ast.MatchAs | ast.MatchStar) and node.name is not None:
            names.append(node.name)
        if isinstance(node, ast.pattern):
            stack.extend(child for child in ast.iter_child_nodes(node))
    return names


def _own_nodes(unit: ast.AST) -> Iterable[ast.AST]:
    """Every node of the unit's own code: nested units are yielded, not entered."""
    stack: list[ast.AST] = list(ast.iter_child_nodes(unit))
    while len(stack) > 0:
        node = stack.pop()
        yield node
        if not isinstance(node, UNIT_NODES):
            stack.extend(ast.iter_child_nodes(node))


def _binding_targets(node: ast.AST) -> list[ast.AST]:
    if isinstance(node, ast.Assign):
        return list(node.targets)
    if isinstance(node, ast.AnnAssign | ast.AugAssign | ast.For | ast.AsyncFor):
        return [node.target]
    if isinstance(node, ast.NamedExpr | ast.comprehension):
        return [node.target]
    if isinstance(node, ast.withitem) and node.optional_vars is not None:
        return [node.optional_vars]
    if isinstance(node, ast.match_case):
        return [node.pattern]
    return []


def _local_names(unit: ast.AST) -> set[str]:
    """The names the unit binds (Python scoping: assigned anywhere in it)."""
    names: set[str] = set()
    declared: set[str] = set()
    for node in _own_nodes(unit):
        if type(node) not in BINDING_NODES:
            continue
        for target in _binding_targets(node):
            names.update(_bound_names(target))
        if isinstance(node, (*FUNCTION_NODES, ast.ClassDef, ast.ExceptHandler)):
            if node.name is not None:
                names.add(node.name)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            names.update(_import_names(node))
        elif isinstance(node, ast.Global | ast.Nonlocal):
            declared.update(node.names)
    return names - declared


def _import_names(node: ast.Import | ast.ImportFrom) -> list[str]:
    names: list[str] = []
    for alias in node.names:
        if alias.asname is not None:
            names.append(alias.asname)
        else:
            names.append(alias.name.split(".")[0])
    return names


def _parameters(node: ast.AST) -> list[str]:
    if not isinstance(node, (*FUNCTION_NODES, ast.Lambda)):
        return []
    args = node.args
    names = [a.arg for a in [*args.posonlyargs, *args.args]]
    if args.vararg is not None:
        names.append(args.vararg.arg)
    names.extend(a.arg for a in args.kwonlyargs)
    if args.kwarg is not None:
        names.append(args.kwarg.arg)
    return names


def _bound_receiver(info: UnitInfo, parameters: list[str]) -> bool:
    node = info.node
    if info.kind != UNIT_METHOD or len(parameters) == 0 or parameters[0] not in RECEIVER_NAMES:
        return False
    assert isinstance(node, FUNCTION_NODES)
    return not any(isinstance(d, ast.Name) and d.id == STATICMETHOD for d in node.decorator_list)


def _dotted(node: ast.expr) -> str | None:
    """``a.b.c`` for an attribute chain rooted at a name, the name itself for a name."""
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))


def _chain(node: ast.expr) -> tuple[str, str] | None:
    """(root name, dotted text) of a pure read chain: attributes and string-literal
    subscripts over a name (``os.environ["HOME"]`` -> ``os.environ.HOME``)."""
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute | ast.Subscript):
        if isinstance(current, ast.Attribute):
            parts.append(current.attr)
        elif isinstance(current.slice, ast.Constant) and isinstance(current.slice.value, str):
            parts.append(current.slice.value)
        else:
            return None
        current = current.value
    if not isinstance(current, ast.Name) or len(parts) == 0:
        return None
    parts.append(current.id)
    return current.id, ".".join(reversed(parts))


def _excerpt(source: SourceText, node: ast.expr) -> str:
    """The node's text on its first line (ast offsets are UTF-8 byte offsets)."""
    line = source.line_text(node.lineno).encode("utf-8")
    end = len(line)
    if node.end_lineno == node.lineno and node.end_col_offset is not None:
        end = node.end_col_offset
    segment = line[node.col_offset : end].decode("utf-8")
    first = " ".join(segment.split())
    if len(first) > EVIDENCE_MAX_CHARS:
        return first[:EVIDENCE_MAX_CHARS] + "..."
    return first


def _sorted(origins: Origins) -> tuple[str, ...]:
    return tuple(sorted(origins))


class _Unit:
    """Walks one unit's own code, keeping each local's origins."""

    def __init__(self, source: SourceText, info: UnitInfo) -> None:
        self.source = source
        self.info = info
        self.module = isinstance(info.node, ast.Module)
        self.parameters = _parameters(info.node)
        self.locals = _local_names(info.node) | set(self.parameters)
        self.env: dict[str, Origins] = {
            name: frozenset({origin(ORIGIN_PARAMETER, index)})
            for index, name in enumerate(self.parameters)
        }
        self.weak = 0
        self.reads: list[FlowRead] = []
        self.calls: list[FlowCall] = []
        self.stores: list[FlowStore] = []
        self.returns: list[FlowReturn] = []
        self.tested: set[str] = set()
        self.mentions: list[set[str]] = []
        self.depth = 0
        self.truncated = False

    # -- driver ---------------------------------------------------------------------

    def run(self) -> FlowUnit:
        node = self.info.node
        if isinstance(node, ast.Lambda):
            body = self.expr(node.body)
            self.returns.append(FlowReturn(node_span(self.source, node.body), _sorted(body)))
        elif isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            self.statements(node.body)
        return FlowUnit(
            name=self.info.name,
            parameters=tuple(self.parameters),
            bound_receiver=_bound_receiver(self.info, self.parameters),
            reads=tuple(self.reads),
            calls=tuple(self.calls),
            stores=tuple(self.stores),
            returns=tuple(self.returns),
            tested=tuple(sorted(self.tested)),
            truncated=self.truncated,
        )

    def statements(self, body: Iterable[ast.stmt]) -> None:
        if not self.enter():
            return
        for statement in body:
            if type(statement) in STATEMENTS:
                STATEMENTS[type(statement)](self, statement)
        self.leave()

    def branch(self, body: Iterable[ast.stmt]) -> None:
        """Code that may not run: its assignments add to a variable's origins."""
        self.weak += 1
        self.statements(body)
        self.weak -= 1

    def test(self, node: ast.expr) -> Origins:
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

    def assign(self, target: ast.expr, origins: Origins) -> None:
        if isinstance(target, ast.Name):
            if self.module:
                self.store(target, target.id, origins)
            self.bind(target.id, origins)
        elif isinstance(target, ast.Tuple | ast.List):
            for element in target.elts:
                self.assign(element, origins)
        elif isinstance(target, ast.Starred):
            self.assign(target.value, origins)
        elif isinstance(target, ast.Attribute):
            self.expr(target.value)
            self.store(target, _excerpt(self.source, target), origins)
        elif isinstance(target, ast.Subscript):
            self.expr(target.value)
            self.expr(target.slice)
            self.store(target, _excerpt(self.source, target), origins)
            if isinstance(target.value, ast.Name) and target.value.id in self.locals:
                self.env[target.value.id] = self.name(target.value.id) | origins

    def store(self, target: ast.expr, text: str, origins: Origins) -> None:
        self.stores.append(FlowStore(node_span(self.source, target), text, _sorted(origins)))

    # -- expressions ------------------------------------------------------------------

    def expr(self, node: ast.expr | None) -> Origins:
        if node is None or not self.enter():
            return EMPTY
        if type(node) in EXPRESSIONS:
            value = EXPRESSIONS[type(node)](self, node)
        else:
            value = self.children(node)
        self.leave()
        if len(self.mentions) > 0:
            self.mentions[len(self.mentions) - 1].update(value)
        return value

    def children(self, node: ast.AST) -> Origins:
        found: set[str] = set()
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.expr):
                found.update(self.expr(child))
        return frozenset(found)

    def name(self, identifier: str) -> Origins:
        if identifier in self.env:
            return self.env[identifier]
        return EMPTY

    def read(self, node: ast.expr, text: str, on_parameter: bool) -> Origins:
        self.reads.append(FlowRead(node_span(self.source, node), text, on_parameter))
        return frozenset({origin(ORIGIN_READ, len(self.reads) - 1)})

    def chained(self, node: ast.Attribute | ast.Subscript) -> Origins:
        chain = _chain(node)
        if chain is None:
            if isinstance(node, ast.Subscript):
                self.expr(node.slice)
            return self.expr(node.value)
        root, text = chain
        if root not in self.locals:
            return self.read(node, text, on_parameter=False)
        held = self.name(root)
        if root in self.parameters:
            marker = origin(ORIGIN_PARAMETER, self.parameters.index(root))
            if marker in held:
                return held | self.read(node, text, on_parameter=True)
        return held

    def call(self, node: ast.Call) -> Origins:
        receiver = EMPTY
        if isinstance(node.func, ast.Attribute):
            receiver = self.expr(node.func.value)
        elif not isinstance(node.func, ast.Name):
            self.expr(node.func)
        callee = DYNAMIC
        dotted = _dotted(node.func)
        if dotted is not None:
            callee = dotted
        arguments = tuple(_sorted(self.expr(argument)) for argument in node.args)
        keywords = tuple(self.keyword(keyword) for keyword in node.keywords)
        self.calls.append(
            FlowCall(
                span=node_span(self.source, node),
                callee=callee,
                text=_excerpt(self.source, node),
                receiver=_sorted(receiver),
                arguments=arguments,
                keywords=keywords,
            )
        )
        return frozenset({origin(ORIGIN_CALL, len(self.calls) - 1)})

    def keyword(self, keyword: ast.keyword) -> tuple[str, tuple[str, ...]]:
        name = DOUBLE_STAR
        if keyword.arg is not None:
            name = keyword.arg
        return name, _sorted(self.expr(keyword.value))

    def comprehension(self, node: ast.expr) -> Origins:
        assert isinstance(node, COMPREHENSIONS)
        self.weak += 1
        for generator in node.generators:
            self.assign(generator.target, self.expr(generator.iter))
            for condition in generator.ifs:
                self.test(condition)
        if isinstance(node, ast.DictComp):
            value = self.expr(node.key) | self.expr(node.value)
        else:
            value = self.expr(node.elt)
        self.weak -= 1
        return value


# -- statement handlers ---------------------------------------------------------------


def _assign(unit: _Unit, node: ast.stmt) -> None:
    assert isinstance(node, ast.Assign)
    value = unit.expr(node.value)
    for target in node.targets:
        unit.assign(target, value)


def _ann_assign(unit: _Unit, node: ast.stmt) -> None:
    assert isinstance(node, ast.AnnAssign)
    if node.value is not None:
        unit.assign(node.target, unit.expr(node.value))


def _aug_assign(unit: _Unit, node: ast.stmt) -> None:
    assert isinstance(node, ast.AugAssign)
    unit.assign(node.target, unit.expr(node.value) | unit.expr(node.target))


def _expression(unit: _Unit, node: ast.stmt) -> None:
    assert isinstance(node, ast.Expr)
    unit.expr(node.value)


def _return(unit: _Unit, node: ast.stmt) -> None:
    assert isinstance(node, ast.Return)
    value = unit.expr(node.value)
    unit.returns.append(FlowReturn(node_span(unit.source, node), _sorted(value)))


def _if(unit: _Unit, node: ast.stmt) -> None:
    assert isinstance(node, ast.If | ast.While)
    unit.test(node.test)
    unit.branch(node.body)
    unit.branch(node.orelse)


def _for(unit: _Unit, node: ast.stmt) -> None:
    assert isinstance(node, ast.For | ast.AsyncFor)
    iterated = unit.expr(node.iter)
    unit.weak += 1
    unit.assign(node.target, iterated)
    unit.weak -= 1
    unit.branch(node.body)
    unit.branch(node.orelse)


def _with(unit: _Unit, node: ast.stmt) -> None:
    assert isinstance(node, ast.With | ast.AsyncWith)
    for item in node.items:
        value = unit.expr(item.context_expr)
        if item.optional_vars is not None:
            unit.assign(item.optional_vars, value)
    unit.statements(node.body)


def _try(unit: _Unit, node: ast.stmt) -> None:
    assert isinstance(node, ast.Try | ast.TryStar)
    unit.statements(node.body)
    for handler in node.handlers:
        unit.expr(handler.type)
        if handler.name is not None:
            unit.bind(handler.name, EMPTY)
        unit.branch(handler.body)
    unit.branch(node.orelse)
    unit.statements(node.finalbody)


def _match(unit: _Unit, node: ast.stmt) -> None:
    assert isinstance(node, ast.Match)
    subject = unit.test(node.subject)
    unit.weak += 1
    for case in node.cases:
        for name in _bound_names(case.pattern):
            unit.bind(name, subject)
        if case.guard is not None:
            unit.test(case.guard)
        unit.statements(case.body)
    unit.weak -= 1


def _raise(unit: _Unit, node: ast.stmt) -> None:
    assert isinstance(node, ast.Raise)
    unit.expr(node.exc)
    unit.expr(node.cause)


def _assert(unit: _Unit, node: ast.stmt) -> None:
    assert isinstance(node, ast.Assert)
    unit.test(node.test)
    unit.expr(node.msg)


def _definition(unit: _Unit, node: ast.stmt) -> None:
    """A nested function or class: what the enclosing unit evaluates, and its name."""
    assert isinstance(node, (*FUNCTION_NODES, ast.ClassDef))
    for decorator in node.decorator_list:
        unit.expr(decorator)
    if isinstance(node, ast.ClassDef):
        for base in [*node.bases, *(k.value for k in node.keywords)]:
            unit.expr(base)
    else:
        for default in [*node.args.defaults, *node.args.kw_defaults]:
            unit.expr(default)
    unit.bind(node.name, EMPTY)


def _import(unit: _Unit, node: ast.stmt) -> None:
    assert isinstance(node, ast.Import | ast.ImportFrom)
    for name in _import_names(node):
        unit.bind(name, EMPTY)


StatementHandler = Callable[[_Unit, ast.stmt], None]
STATEMENTS: dict[type, StatementHandler] = {
    ast.Assign: _assign,
    ast.AnnAssign: _ann_assign,
    ast.AugAssign: _aug_assign,
    ast.Expr: _expression,
    ast.Return: _return,
    ast.If: _if,
    ast.While: _if,
    ast.For: _for,
    ast.AsyncFor: _for,
    ast.With: _with,
    ast.AsyncWith: _with,
    ast.Try: _try,
    ast.TryStar: _try,
    ast.Match: _match,
    ast.Raise: _raise,
    ast.Assert: _assert,
    ast.FunctionDef: _definition,
    ast.AsyncFunctionDef: _definition,
    ast.ClassDef: _definition,
    ast.Import: _import,
    ast.ImportFrom: _import,
}


# -- expression handlers --------------------------------------------------------------


def _name(unit: _Unit, node: ast.expr) -> Origins:
    assert isinstance(node, ast.Name)
    return unit.name(node.id)


def _chained(unit: _Unit, node: ast.expr) -> Origins:
    assert isinstance(node, ast.Attribute | ast.Subscript)
    return unit.chained(node)


def _call(unit: _Unit, node: ast.expr) -> Origins:
    assert isinstance(node, ast.Call)
    return unit.call(node)


def _constant(unit: _Unit, node: ast.expr) -> Origins:
    return EMPTY


def _boolean(unit: _Unit, node: ast.expr) -> Origins:
    """``a or b``: every operand but the last is a truth test."""
    assert isinstance(node, ast.BoolOp)
    found: set[str] = set()
    last = len(node.values) - 1
    for index, value in enumerate(node.values):
        if index < last:
            found.update(unit.test(value))
        else:
            found.update(unit.expr(value))
    return frozenset(found)


def _arithmetic(unit: _Unit, node: ast.expr) -> Origins:
    """``a + b + c ...``: a left-deep chain, flattened so that its length is not depth."""
    found: set[str] = set()
    stack: list[ast.expr] = [node]
    while len(stack) > 0:
        current = stack.pop()
        if isinstance(current, ast.BinOp):
            stack.extend((current.right, current.left))
        else:
            found.update(unit.expr(current))
    return frozenset(found)


def _unary(unit: _Unit, node: ast.expr) -> Origins:
    assert isinstance(node, ast.UnaryOp)
    operand = unit.expr(node.operand)
    if isinstance(node.op, ast.Not):
        return EMPTY
    return operand


def _compare(unit: _Unit, node: ast.expr) -> Origins:
    """A comparison is a Boolean: its operands are looked at, not passed on."""
    unit.children(node)
    return EMPTY


def _conditional(unit: _Unit, node: ast.expr) -> Origins:
    assert isinstance(node, ast.IfExp)
    unit.test(node.test)
    return unit.expr(node.body) | unit.expr(node.orelse)


def _comprehension(unit: _Unit, node: ast.expr) -> Origins:
    return unit.comprehension(node)


def _lambda(unit: _Unit, node: ast.expr) -> Origins:
    assert isinstance(node, ast.Lambda)
    for default in [*node.args.defaults, *node.args.kw_defaults]:
        unit.expr(default)
    return EMPTY


def _walrus(unit: _Unit, node: ast.expr) -> Origins:
    assert isinstance(node, ast.NamedExpr)
    value = unit.expr(node.value)
    unit.assign(node.target, value)
    return value


def _yield(unit: _Unit, node: ast.expr) -> Origins:
    assert isinstance(node, ast.Yield | ast.YieldFrom)
    value = unit.expr(node.value)
    unit.returns.append(FlowReturn(node_span(unit.source, node), _sorted(value)))
    return EMPTY


ExpressionHandler = Callable[[_Unit, ast.expr], Origins]
EXPRESSIONS: dict[type, ExpressionHandler] = {
    ast.Name: _name,
    ast.Attribute: _chained,
    ast.Subscript: _chained,
    ast.Call: _call,
    ast.Constant: _constant,
    ast.BoolOp: _boolean,
    ast.BinOp: _arithmetic,
    ast.UnaryOp: _unary,
    ast.Compare: _compare,
    ast.IfExp: _conditional,
    ast.ListComp: _comprehension,
    ast.SetComp: _comprehension,
    ast.GeneratorExp: _comprehension,
    ast.DictComp: _comprehension,
    ast.Lambda: _lambda,
    ast.NamedExpr: _walrus,
    ast.Yield: _yield,
    ast.YieldFrom: _yield,
}


def collect_python_dataflow(source: SourceText, module: ast.Module) -> DataflowFacts:
    return DataflowFacts(units=tuple(_Unit(source, info).run() for info in discover_units(module)))
