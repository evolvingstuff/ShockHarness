"""Function facts for Python: every unit's control tree, size, calls and writes.

Units are the module body, each class body, each ``def``/``async def`` and each
``lambda``. Traversal is iterative: a unit's body is reduced to a control tree
with an explicit work stack, and nested units are stopped at (they are their
own facts), so a unit's tree, statement count, logical lines and calls never
include a nested body. Comprehensions are part of the unit that contains them.
"""

import ast
from collections.abc import Sequence
from dataclasses import dataclass

from shockharness.constants import EVIDENCE_MAX_CHARS, FIRST_COLUMN, FIRST_LINE
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
    CASE_DEFAULT,
    CK_BLOCK,
    CK_CASE,
    CK_CONDITIONAL,
    CK_ELIF,
    CK_EXPR,
    CK_FINALLY,
    CK_HANDLER,
    CK_IF,
    CK_LOOP,
    CK_RECURSION,
    CK_SWITCH,
    CK_TRY,
    CK_TRY_ELSE,
    IMPORT_MODULE,
    IMPORT_NAMES,
    LOOP_COMPREHENSION,
    LOOP_FOR,
    LOOP_WHILE,
    MODULE_SCOPE,
    UNIT_CLASS,
    UNIT_FUNCTION,
    UNIT_LAMBDA,
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
from shockharness.ir.python_catches import SCOPE_NODES, bound_name, node_span, scope_name
from shockharness.source import SourceText

UNIT_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
COMPREHENSION_NODES = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
RECEIVER_NAMES = frozenset({"self", "cls"})
# Method names that mutate a list/dict/set/deque in place; a call of one on a
# module-level container counts as a write to that container.
MUTATING_METHODS = frozenset(
    {
        "append",
        "extend",
        "insert",
        "remove",
        "pop",
        "clear",
        "sort",
        "reverse",
        "update",
        "setdefault",
        "popitem",
        "add",
        "discard",
        "appendleft",
        "extendleft",
        "popleft",
        "rotate",
    }
)
ELIF_KEYWORD = b"elif"

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
    frozen: ControlNode | None


def _builder(kind: str, label: str) -> _Builder:
    return _Builder(kind, label, [], 0, 0, None)


@dataclass(frozen=True)
class _UnitInfo:
    node: ast.AST
    name: str
    kind: str
    class_name: str | None


def import_binding(alias: ast.alias) -> str:
    """The local name ``import a.b.c [as d]`` binds: ``d`` when aliased, else the root ``a``."""
    if alias.asname is not None:
        return alias.asname
    return alias.name.split(".")[0]


def _unit_kind(node: ast.AST, parent: ast.AST | None) -> str:
    if isinstance(node, ast.Module):
        return UNIT_MODULE
    if isinstance(node, ast.ClassDef):
        return UNIT_CLASS
    if isinstance(node, ast.Lambda):
        return UNIT_LAMBDA
    if isinstance(parent, ast.ClassDef):
        return UNIT_METHOD
    return UNIT_FUNCTION


def _discover_units(module: ast.Module) -> list[_UnitInfo]:
    """Every unit in source order with its qualified name and enclosing class."""
    units: list[_UnitInfo] = [_UnitInfo(module, MODULE_SCOPE, UNIT_MODULE, None)]
    stack: list[tuple[ast.AST, str, ast.AST | None, str | None]] = [
        (module, MODULE_SCOPE, None, None)
    ]
    while len(stack) > 0:
        node, scope, parent, class_name = stack.pop()
        child_scope = scope
        child_class = class_name
        if isinstance(node, UNIT_NODES) and node is not module:
            name = scope_name(node)
            child_scope = name if scope == MODULE_SCOPE else f"{scope}.{name}"
            units.append(_UnitInfo(node, child_scope, _unit_kind(node, parent), class_name))
            child_class = child_scope if isinstance(node, ast.ClassDef) else None
        children = list(ast.iter_child_nodes(node))
        for child in reversed(children):
            stack.append((child, child_scope, node, child_class))
    units.sort(key=lambda u: _unit_span_key(u.node))
    return units


def _unit_span_key(node: ast.AST) -> tuple[int, int]:
    if isinstance(node, ast.Module):
        return (0, 0)
    assert isinstance(node, ast.expr | ast.stmt)
    return (node.lineno, node.col_offset)


def _is_elif(source: SourceText, node: ast.If) -> bool:
    line = source.line_text(node.lineno).encode("utf-8")
    return line[node.col_offset :].startswith(ELIF_KEYWORD)


def _dotted(expr: ast.expr) -> str | None:
    parts: list[str] = []
    current = expr
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    parts.reverse()
    return ".".join(parts)


def _root_name(expr: ast.expr) -> str | None:
    current = expr
    while isinstance(current, ast.Attribute | ast.Subscript):
        current = current.value
    if isinstance(current, ast.Name):
        return current.id
    return None


def _excerpt(source: SourceText, node: ast.expr) -> str:
    segment = ast.get_source_segment(source.text, node)
    if segment is None:
        return type(node).__name__
    first = segment.split("\n")[0].strip()
    if len(first) > EVIDENCE_MAX_CHARS:
        return first[:EVIDENCE_MAX_CHARS]
    return first


def _boolean_operators(root: ast.BoolOp) -> tuple[list[str], list[ast.expr]]:
    """Operators of a boolean chain in source order, and the non-boolean leaves.

    A ``BoolOp`` nested directly as a value continues the chain (``a and b or c``);
    anything else is a leaf whose own boolean expressions are separate chains.
    """
    operators: list[str] = []
    leaves: list[ast.expr] = []
    stack: list[ast.expr | str] = [root]
    while len(stack) > 0:
        item = stack.pop()
        if isinstance(item, str):
            operators.append(item)
            continue
        if isinstance(item, ast.BoolOp):
            operator = type(item.op).__name__
            tokens: list[ast.expr | str] = []
            for index, value in enumerate(item.values):
                if index > 0:
                    tokens.append(operator)
                tokens.append(value)
            for token in reversed(tokens):
                stack.append(token)
            continue
        leaves.append(item)
    return operators, leaves


def count_runs(operators: Sequence[str]) -> int:
    runs = 0
    previous: str | None = None
    for operator in operators:
        if operator != previous:
            runs += 1
        previous = operator
    return runs


def _assigned_names(target: ast.expr) -> list[str]:
    names: list[str] = []
    stack = [target]
    while len(stack) > 0:
        node = stack.pop()
        if isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, ast.Tuple | ast.List):
            stack.extend(node.elts)
        elif isinstance(node, ast.Starred):
            stack.append(node.value)
    return names


class _UnitCollector:
    """Builds one unit's control tree and gathers its calls, locals and writes."""

    def __init__(self, source: SourceText, unit: _UnitInfo) -> None:
        self.source = source
        self.unit = unit
        self.root = _builder(CK_BLOCK, "")
        self.builders: list[_Builder] = [self.root]
        self.calls: list[CallSite] = []
        self.locals: set[str] = set()
        self.globals_declared: set[str] = set()
        self.assign_candidates: list[str] = []
        self.mutate_candidates: list[str] = []
        self.statements = 0
        self.generator = False
        self.own_name: str | None = None
        if isinstance(unit.node, FUNCTION_NODES):
            self.own_name = unit.node.name

    def _new(self, kind: str, label: str, parent: _Builder) -> _Builder:
        builder = _builder(kind, label)
        parent.children.append(builder)
        self.builders.append(builder)
        return builder

    # -- statements ---------------------------------------------------------

    def _push_statements(
        self, stack: list[tuple[str, object, _Builder]], body: Sequence[ast.stmt], parent: _Builder
    ) -> None:
        for statement in reversed(body):
            stack.append((_T_STATEMENT, statement, parent))

    def _statement(
        self, stack: list[tuple[str, object, _Builder]], node: ast.stmt, parent: _Builder
    ) -> None:
        self.statements += 1
        if isinstance(node, ast.If):
            self._if(stack, node, parent, CK_IF)
        elif isinstance(node, ast.For | ast.AsyncFor):
            loop = self._new(CK_LOOP, LOOP_FOR, parent)
            self.locals.update(_assigned_names(node.target))
            condition = self._new(CK_EXPR, "", loop)
            stack.append((_T_EXPRESSION, node.iter, condition))
            stack.append((_T_EXPRESSION, node.target, condition))
            self._loop_bodies(stack, node.body, node.orelse, loop)
        elif isinstance(node, ast.While):
            loop = self._new(CK_LOOP, LOOP_WHILE, parent)
            condition = self._new(CK_EXPR, "", loop)
            stack.append((_T_EXPRESSION, node.test, condition))
            self._loop_bodies(stack, node.body, node.orelse, loop)
        elif isinstance(node, ast.Try | ast.TryStar):
            self._try(stack, node, parent)
        elif isinstance(node, ast.With | ast.AsyncWith):
            # A context manager is a syntactic wrapper: its body stays at this level.
            expression = self._new(CK_EXPR, "", parent)
            for item in node.items:
                if item.optional_vars is not None:
                    self.locals.update(_assigned_names(item.optional_vars))
                    stack.append((_T_EXPRESSION, item.optional_vars, expression))
                stack.append((_T_EXPRESSION, item.context_expr, expression))
            self._push_statements(stack, node.body, parent)
        elif isinstance(node, ast.Match):
            self._match(stack, node, parent)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            self._nested_unit(stack, node, parent)
        elif isinstance(node, ast.Global):
            self.globals_declared.update(node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                self.locals.add(import_binding(alias))
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                self.locals.add(bound_name(alias))
        elif isinstance(node, ast.Nonlocal | ast.Pass | ast.Break | ast.Continue):
            return
        else:
            self._simple_statement(stack, node, parent)

    def _simple_statement(
        self, stack: list[tuple[str, object, _Builder]], node: ast.stmt, parent: _Builder
    ) -> None:
        expression = self._new(CK_EXPR, "", parent)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                self._write_target(target)
        elif isinstance(node, ast.AugAssign | ast.AnnAssign):
            self._write_target(node.target)
            if isinstance(node, ast.AugAssign):
                root = _root_name(node.target)
                if root is not None and not isinstance(node.target, ast.Name):
                    self.mutate_candidates.append(root)
        elif isinstance(node, ast.Delete):
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    root = _root_name(target)
                    if root is not None:
                        self.mutate_candidates.append(root)
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            self._mutating_call(node.value)
        for child in reversed(list(ast.iter_child_nodes(node))):
            if isinstance(child, ast.expr):
                stack.append((_T_EXPRESSION, child, expression))

    def _write_target(self, target: ast.expr) -> None:
        if isinstance(target, ast.Name):
            self.locals.add(target.id)
            self.assign_candidates.append(target.id)
            return
        if isinstance(target, ast.Tuple | ast.List | ast.Starred):
            for name in _assigned_names(target):
                self.locals.add(name)
                self.assign_candidates.append(name)
            return
        root = _root_name(target)
        if root is not None:
            self.mutate_candidates.append(root)

    def _mutating_call(self, call: ast.Call) -> None:
        func = call.func
        if not isinstance(func, ast.Attribute) or func.attr not in MUTATING_METHODS:
            return
        if isinstance(func.value, ast.Name):
            self.mutate_candidates.append(func.value.id)

    def _if(
        self,
        stack: list[tuple[str, object, _Builder]],
        node: ast.If,
        parent: _Builder,
        kind: str,
    ) -> None:
        builder = self._new(kind, "", parent)
        condition = self._new(CK_EXPR, "", builder)
        stack.append((_T_EXPRESSION, node.test, condition))
        then_block = self._new(CK_BLOCK, "", builder)
        if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
            chained = node.orelse[0]
            if _is_elif(self.source, chained):
                self.statements += 1
                self._if(stack, chained, builder, CK_ELIF)
                self._push_statements(stack, node.body, then_block)
                return
        if len(node.orelse) > 0:
            else_block = self._new(CK_BLOCK, "", builder)
            self._push_statements(stack, node.orelse, else_block)
        self._push_statements(stack, node.body, then_block)

    def _loop_bodies(
        self,
        stack: list[tuple[str, object, _Builder]],
        body: Sequence[ast.stmt],
        orelse: Sequence[ast.stmt],
        loop: _Builder,
    ) -> None:
        body_block = self._new(CK_BLOCK, "", loop)
        if len(orelse) > 0:
            else_block = self._new(CK_BLOCK, "", loop)
            self._push_statements(stack, orelse, else_block)
        self._push_statements(stack, body, body_block)

    def _try(
        self,
        stack: list[tuple[str, object, _Builder]],
        node: ast.Try | ast.TryStar,
        parent: _Builder,
    ) -> None:
        builder = self._new(CK_TRY, "", parent)
        body = self._new(CK_BLOCK, "", builder)
        handlers: list[tuple[ast.ExceptHandler, _Builder]] = []
        for handler in node.handlers:
            if handler.name is not None:
                self.locals.add(handler.name)
            handlers.append((handler, self._new(CK_HANDLER, "", builder)))
        tail: list[tuple[Sequence[ast.stmt], _Builder]] = []
        if len(node.orelse) > 0:
            tail.append((node.orelse, self._new(CK_TRY_ELSE, "", builder)))
        if len(node.finalbody) > 0:
            tail.append((node.finalbody, self._new(CK_FINALLY, "", builder)))
        for statements, block in reversed(tail):
            self._push_statements(stack, statements, block)
        for handler, block in reversed(handlers):
            self._push_statements(stack, handler.body, block)
            if handler.type is not None:
                expression = self._new(CK_EXPR, "", block)
                stack.append((_T_EXPRESSION, handler.type, expression))
        self._push_statements(stack, node.body, body)

    def _match(
        self, stack: list[tuple[str, object, _Builder]], node: ast.Match, parent: _Builder
    ) -> None:
        builder = self._new(CK_SWITCH, "", parent)
        subject = self._new(CK_EXPR, "", builder)
        stack.append((_T_EXPRESSION, node.subject, subject))
        cases: list[tuple[ast.match_case, _Builder, _Builder]] = []
        for case in node.cases:
            label = ""
            if isinstance(case.pattern, ast.MatchAs) and case.pattern.pattern is None:
                label = CASE_DEFAULT
            case_builder = self._new(CK_CASE, label, builder)
            guard = self._new(CK_EXPR, "", case_builder)
            body = self._new(CK_BLOCK, "", case_builder)
            for pattern_node in ast.walk(case.pattern):
                if isinstance(pattern_node, ast.MatchAs | ast.MatchStar):
                    if pattern_node.name is not None:
                        self.locals.add(pattern_node.name)
                elif isinstance(pattern_node, ast.MatchMapping) and pattern_node.rest is not None:
                    self.locals.add(pattern_node.rest)
            cases.append((case, guard, body))
        for case, guard, body in reversed(cases):
            self._push_statements(stack, case.body, body)
            if case.guard is not None:
                stack.append((_T_EXPRESSION, case.guard, guard))

    def _nested_unit(
        self,
        stack: list[tuple[str, object, _Builder]],
        node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
        parent: _Builder,
    ) -> None:
        self.locals.add(node.name)
        expression = self._new(CK_EXPR, "", parent)
        outer: list[ast.expr] = list(node.decorator_list)
        if isinstance(node, ast.ClassDef):
            outer.extend(node.bases)
            outer.extend(keyword.value for keyword in node.keywords)
        else:
            outer.extend(node.args.defaults)
            outer.extend(d for d in node.args.kw_defaults if d is not None)
        for decorator in node.decorator_list:
            self._decorator_call(decorator)
        for child in reversed(outer):
            stack.append((_T_EXPRESSION, child, expression))

    def _decorator_call(self, decorator: ast.expr) -> None:
        if isinstance(decorator, ast.Call):
            return  # the call itself is collected as an ordinary call
        self._record_call(decorator, decorator)

    # -- expressions --------------------------------------------------------

    def _expression(
        self, stack: list[tuple[str, object, _Builder]], node: ast.expr, parent: _Builder
    ) -> None:
        if isinstance(node, ast.Lambda):
            # Its body is a unit of its own; defaults are evaluated here.
            for default in reversed(list(node.args.defaults)):
                stack.append((_T_EXPRESSION, default, parent))
            for default in reversed(list(node.args.kw_defaults)):
                if default is not None:
                    stack.append((_T_EXPRESSION, default, parent))
            return
        if isinstance(node, ast.BoolOp):
            operators, leaves = _boolean_operators(node)
            parent.operators += len(operators)
            parent.sequences += count_runs(operators)
            for leaf in reversed(leaves):
                stack.append((_T_EXPRESSION, leaf, parent))
            return
        if isinstance(node, ast.IfExp):
            conditional = self._new(CK_CONDITIONAL, "", parent)
            condition = self._new(CK_EXPR, "", conditional)
            then_part = self._new(CK_EXPR, "", conditional)
            else_part = self._new(CK_EXPR, "", conditional)
            stack.append((_T_EXPRESSION, node.orelse, else_part))
            stack.append((_T_EXPRESSION, node.body, then_part))
            stack.append((_T_EXPRESSION, node.test, condition))
            return
        if isinstance(node, COMPREHENSION_NODES):
            self._comprehension(stack, node, parent)
            return
        if isinstance(node, ast.Yield | ast.YieldFrom):
            self.generator = True
        if isinstance(node, ast.NamedExpr):
            self.locals.add(node.target.id)
        if isinstance(node, ast.Call):
            self._call(node, parent)
        for child in reversed(list(ast.iter_child_nodes(node))):
            if isinstance(child, ast.expr):
                stack.append((_T_EXPRESSION, child, parent))
            elif isinstance(child, ast.keyword):
                stack.append((_T_EXPRESSION, child.value, parent))

    def _comprehension(
        self,
        stack: list[tuple[str, object, _Builder]],
        node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
        parent: _Builder,
    ) -> None:
        """``[elt for a in xs if p for b in a if q]``: nested loops, each ``if`` an IF inside."""
        elements: list[ast.expr] = []
        if isinstance(node, ast.DictComp):
            elements = [node.key, node.value]
        else:
            elements = [node.elt]
        innermost = parent
        loops: list[tuple[ast.expr, _Builder]] = []
        for generator in node.generators:
            self.locals.update(_assigned_names(generator.target))
            loop = self._new(CK_LOOP, LOOP_COMPREHENSION, innermost)
            condition = self._new(CK_EXPR, "", loop)
            body = self._new(CK_BLOCK, "", loop)
            loops.append((generator.iter, condition))
            innermost = body
            for test in generator.ifs:
                branch = self._new(CK_IF, "", innermost)
                branch_condition = self._new(CK_EXPR, "", branch)
                branch_body = self._new(CK_BLOCK, "", branch)
                stack.append((_T_EXPRESSION, test, branch_condition))
                innermost = branch_body
        element = self._new(CK_EXPR, "", innermost)
        for expression in reversed(elements):
            stack.append((_T_EXPRESSION, expression, element))
        for iterable, condition in reversed(loops):
            stack.append((_T_EXPRESSION, iterable, condition))

    def _call(self, node: ast.Call, parent: _Builder) -> None:
        self._record_call(node.func, node)
        for argument in node.args:
            if isinstance(argument, ast.Name):
                self.calls.append(
                    CallSite(node_span(self.source, argument), argument.id, CALL_ARGUMENT, False)
                )
            elif isinstance(argument, ast.Starred) and isinstance(argument.value, ast.Name):
                self.calls.append(
                    CallSite(
                        node_span(self.source, argument), argument.value.id, CALL_ARGUMENT, False
                    )
                )
        for keyword in node.keywords:
            if isinstance(keyword.value, ast.Name):
                self.calls.append(
                    CallSite(
                        node_span(self.source, keyword.value),
                        keyword.value.id,
                        CALL_ARGUMENT,
                        False,
                    )
                )
        if self.own_name is None:
            return
        if (isinstance(node.func, ast.Name) and node.func.id == self.own_name) or (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == self.own_name
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in RECEIVER_NAMES
            and self.unit.kind == UNIT_METHOD
        ):
            self._new(CK_RECURSION, "", parent)

    def _record_call(self, func: ast.expr, whole: ast.expr) -> None:
        span = node_span(self.source, whole)
        if isinstance(func, ast.Name):
            self.calls.append(CallSite(span, func.id, CALL_NAME, False))
            return
        dotted = _dotted(func)
        if dotted is not None:
            root = dotted.split(".")[0]
            receiver = root in RECEIVER_NAMES and self.unit.kind == UNIT_METHOD
            self.calls.append(CallSite(span, dotted, CALL_ATTRIBUTE, receiver))
            return
        self.calls.append(CallSite(span, _excerpt(self.source, func), CALL_DYNAMIC, False))

    # -- driver -------------------------------------------------------------

    def run(self) -> None:
        node = self.unit.node
        stack: list[tuple[str, object, _Builder]] = []
        if isinstance(node, ast.Lambda):
            self._parameters(node.args)
            stack.append((_T_EXPRESSION, node.body, self._new(CK_EXPR, "", self.root)))
        elif isinstance(node, FUNCTION_NODES):
            self._parameters(node.args)
            self._push_statements(stack, node.body, self.root)
        elif isinstance(node, ast.ClassDef):
            self._push_statements(stack, node.body, self.root)
        else:
            assert isinstance(node, ast.Module)
            self._push_statements(stack, node.body, self.root)
        while len(stack) > 0:
            task, payload, parent = stack.pop()
            if task == _T_STATEMENT:
                assert isinstance(payload, ast.stmt)
                self._statement(stack, payload, parent)
            else:
                assert isinstance(payload, ast.expr)
                self._expression(stack, payload, parent)

    def _parameters(self, args: ast.arguments) -> None:
        for parameter in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
            self.locals.add(parameter.arg)
        if args.vararg is not None:
            self.locals.add(args.vararg.arg)
        if args.kwarg is not None:
            self.locals.add(args.kwarg.arg)

    def freeze(self) -> ControlNode:
        """Freeze bottom-up: builders are created parent-first, so reverse order works."""
        for builder in reversed(self.builders):
            children = tuple(child.frozen for child in builder.children if child.frozen is not None)
            if builder.kind == CK_BLOCK or builder.kind in _STATEMENT_BLOCKS:
                children = tuple(c for c in children if not _trivial_expr(c))
            builder.frozen = ControlNode(
                builder.kind, children, builder.operators, builder.sequences, builder.label, False
            )
        assert self.root.frozen is not None
        return self.root.frozen

    def writes(self) -> tuple[tuple[str, str], ...]:
        found: list[tuple[str, str]] = []
        for name in self.assign_candidates:
            if name in self.globals_declared:
                found.append((name, WRITE_ASSIGN))
        for name in self.mutate_candidates:
            if name in self.globals_declared or name not in self.locals:
                found.append((name, WRITE_MUTATE))
        return tuple(sorted(set(found)))


_STATEMENT_BLOCKS = frozenset({CK_HANDLER, CK_TRY_ELSE, CK_FINALLY})


def _trivial_expr(node: ControlNode) -> bool:
    return node.kind == CK_EXPR and node.operators == 0 and len(node.children) == 0


def _parameter_count(node: ast.AST) -> int:
    if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
        return 0
    args = node.args
    count = len(args.posonlyargs) + len(args.args) + len(args.kwonlyargs)
    if args.vararg is not None:
        count += 1
    if args.kwarg is not None:
        count += 1
    return count


def _unit_span(source: SourceText, node: ast.AST) -> Span:
    if isinstance(node, ast.Module):
        last_line = max(source.line_count, FIRST_LINE)
        return Span(FIRST_LINE, FIRST_COLUMN, last_line, len(source.line_text(last_line)) + 1)
    assert isinstance(node, ast.expr | ast.stmt)
    return node_span(source, node)


def collect_python_functions(
    source: SourceText, module: ast.Module, comments: Sequence[Comment]
) -> tuple[FunctionFact, ...]:
    units = _discover_units(module)
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
                (other, isinstance(units[other_index].node, ast.Lambda))
                for other_index, other in enumerate(spans)
                if other_index != index
            ],
        )
        is_async = isinstance(unit.node, ast.AsyncFunctionDef)
        facts.append(
            FunctionFact(
                name=unit.name,
                kind=unit.kind,
                is_async=is_async,
                is_generator=collector.generator,
                span=span,
                parameters=_parameter_count(unit.node),
                statements=collector.statements,
                logical_lines=logical_line_count(source, comments, span, nested),
                control=tree,
                calls=tuple(sorted(collector.calls, key=lambda c: c.span)),
                class_name=unit.class_name,
                locals=frozenset(collector.locals),
                globals_declared=frozenset(collector.globals_declared),
                writes=collector.writes(),
            )
        )
    return tuple(facts)


def nested_line_exclusions(span: Span, others: Sequence[tuple[Span, bool]]) -> list[Span]:
    """Spans of units nested in ``span`` whose lines the unit does not own.

    A statement unit (``def``, ``class``) gives up its whole span; an expression
    unit (lambda, arrow) gives up only its interior lines, because its first and
    last lines usually carry the enclosing unit's code too.
    """
    excluded: list[Span] = []
    for other, is_expression in others:
        if other.line < span.line or other.end_line > span.end_line:
            continue
        if other.line == span.line and other.end_line == span.end_line:
            continue
        if not is_expression:
            excluded.append(other)
        elif other.end_line > other.line + 1:
            excluded.append(Span(other.line + 1, FIRST_COLUMN, other.end_line - 1, FIRST_COLUMN))
    return excluded


__all__ = [
    "SCOPE_NODES",
    "collect_python_bindings",
    "collect_python_functions",
    "collect_python_imports",
    "count_runs",
    "nested_line_exclusions",
]


MUTABLE_CONSTRUCTORS = frozenset(
    {
        "list",
        "dict",
        "set",
        "bytearray",
        "defaultdict",
        "deque",
        "OrderedDict",
        "Counter",
        "ChainMap",
        "collections.defaultdict",
        "collections.deque",
        "collections.OrderedDict",
        "collections.Counter",
        "collections.ChainMap",
    }
)
MUTABLE_DISPLAYS = (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)


def _is_mutable_value(value: ast.expr | None) -> bool:
    if value is None:
        return False
    if isinstance(value, MUTABLE_DISPLAYS):
        return True
    if isinstance(value, ast.Call):
        dotted = _dotted(value.func)
        return dotted is not None and dotted in MUTABLE_CONSTRUCTORS
    return False


def collect_python_imports(source: SourceText, module: ast.Module) -> tuple[ImportFact, ...]:
    """Every ``import``/``from ... import`` in the module, at any depth, in source order."""
    imports: list[ImportFact] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(
                    ImportFact(
                        node_span(source, node),
                        IMPORT_MODULE,
                        alias.name,
                        0,
                        (("", import_binding(alias)),),
                    )
                )
        elif isinstance(node, ast.ImportFrom):
            module_name = ""
            if node.module is not None:
                module_name = node.module
            names = tuple((alias.name, bound_name(alias)) for alias in node.names)
            imports.append(
                ImportFact(node_span(source, node), IMPORT_NAMES, module_name, node.level, names)
            )
    imports.sort(key=lambda i: i.span)
    return tuple(imports)


def collect_python_bindings(source: SourceText, module: ast.Module) -> tuple[ModuleBinding, ...]:
    """Names bound at module level (module-level ``if``/``try`` bodies included)."""
    bindings: dict[str, ModuleBinding] = {}
    stack: list[ast.stmt] = list(reversed(module.body))
    while len(stack) > 0:
        statement = stack.pop()
        span = node_span(source, statement)
        if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef):
            bindings[statement.name] = ModuleBinding(statement.name, BINDING_FUNCTION, False, span)
        elif isinstance(statement, ast.ClassDef):
            bindings[statement.name] = ModuleBinding(statement.name, BINDING_CLASS, False, span)
        elif isinstance(statement, ast.Import | ast.ImportFrom):
            for alias in statement.names:
                if alias.name == "*":
                    continue
                bound = import_binding(alias)
                if isinstance(statement, ast.ImportFrom):
                    bound = bound_name(alias)
                bindings[bound] = ModuleBinding(bound, BINDING_IMPORT, False, span)
        elif isinstance(statement, ast.Assign | ast.AnnAssign):
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            mutable = _is_mutable_value(statement.value)
            for target in targets:
                for name in _assigned_names(target):
                    if name in bindings and bindings[name].kind == BINDING_VARIABLE:
                        mutable = mutable or bindings[name].mutable
                    bindings[name] = ModuleBinding(name, BINDING_VARIABLE, mutable, span)
        elif isinstance(statement, ast.If | ast.Try | ast.TryStar | ast.With | ast.For | ast.While):
            for child in reversed(list(ast.iter_child_nodes(statement))):
                if isinstance(child, ast.stmt):
                    stack.append(child)
                elif isinstance(child, ast.ExceptHandler):
                    stack.extend(reversed(child.body))
    return tuple(sorted(bindings.values(), key=lambda b: (b.span, b.name)))
