"""Async lifecycle facts for Python (H4; consumed by ASYNC001-ASYNC003 in
rules/async_lifecycle.py).

Syntax only, per function scope (nested functions, lambdas and classes are their own
scopes):

* **discarded calls**: every call that is a whole expression statement (``f()``, not
  ``await f()``), with whether the enclosing function is ``async`` and, for
  ``name.method(...)``, the callee of the ``with``/``async with`` that bound ``name`` in
  the same function (``async with asyncio.TaskGroup() as group:`` makes
  ``group.create_task(...)`` owned);
* **settled batches**: ``asyncio.gather(..., return_exceptions=True)`` (any callee whose
  last segment is ``gather``), with whether its result is thrown away (an expression
  statement, awaited or not) and whether the enclosing function inspects results for
  failure: an ``isinstance`` check against a type whose name contains ``Exception`` or
  ``Error``, or returning the batch to the caller.
"""

import ast

from shockharness.constants import EVIDENCE_MAX_CHARS, ISINSTANCE_ARGUMENTS
from shockharness.ir.model import AsyncFacts, DiscardedCall, SettledBatch
from shockharness.ir.python_catches import dotted_name, node_span
from shockharness.source import SourceText

SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
GATHER = "gather"
RETURN_EXCEPTIONS = "return_exceptions"
ISINSTANCE = "isinstance"
FAILURE_TYPE_MARKERS = ("Exception", "Error")
DYNAMIC = "<dynamic>"


def _excerpt(node: ast.AST) -> str:
    text = " ".join(ast.unparse(node).split())
    if len(text) > EVIDENCE_MAX_CHARS:
        return text[:EVIDENCE_MAX_CHARS] + "..."
    return text


def scope_nodes(scope: ast.AST) -> list[tuple[ast.AST, ast.AST]]:
    """(node, parent) for every node in ``scope``, not descending into nested scopes."""
    found: list[tuple[ast.AST, ast.AST]] = []
    stack: list[tuple[ast.AST, ast.AST]] = [(child, scope) for child in ast.iter_child_nodes(scope)]
    while len(stack) > 0:
        node, parent = stack.pop()
        found.append((node, parent))
        if isinstance(node, SCOPES):
            continue
        stack.extend((child, node) for child in ast.iter_child_nodes(node))
    return found


def _with_bindings(nodes: list[tuple[ast.AST, ast.AST]]) -> dict[str, str]:
    """``name`` -> dotted callee for ``with X(...) as name`` / ``async with``."""
    bound: dict[str, str] = {}
    for node, _parent in nodes:
        if not isinstance(node, ast.With | ast.AsyncWith):
            continue
        for item in node.items:
            target = item.optional_vars
            context = item.context_expr
            manager = context.func if isinstance(context, ast.Call) else context
            dotted = dotted_name(manager)
            if isinstance(target, ast.Name) and dotted is not None:
                bound[target.id] = dotted
    return bound


def _inspects_failures(nodes: list[tuple[ast.AST, ast.AST]]) -> bool:
    for node, _parent in nodes:
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != ISINSTANCE or len(node.args) != ISINSTANCE_ARGUMENTS:
            continue
        types = ast.unparse(node.args[1])
        if any(marker in types for marker in FAILURE_TYPE_MARKERS):
            return True
    return False


def _returns_exceptions(call: ast.Call) -> bool:
    return any(
        keyword.arg == RETURN_EXCEPTIONS
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is True
        for keyword in call.keywords
    )


class _Scope:
    def __init__(self, source: SourceText, scope: ast.AST) -> None:
        self.source = source
        self.nodes = scope_nodes(scope)
        self.parents = {id(node): parent for node, parent in self.nodes}
        self.in_async = isinstance(scope, ast.AsyncFunctionDef)
        self.bound = _with_bindings(self.nodes)
        self.inspects = _inspects_failures(self.nodes)

    def _usage(self, call: ast.Call) -> ast.AST:
        """The node that consumes ``call``, looking through an ``await``."""
        parent = self.parents[id(call)]
        if isinstance(parent, ast.Await):
            return self.parents[id(parent)]
        return parent

    def discarded(self) -> list[DiscardedCall]:
        found: list[DiscardedCall] = []
        for node, parent in self.nodes:
            if not isinstance(node, ast.Call) or not isinstance(parent, ast.Expr):
                continue
            callee = dotted_name(node.func)
            bound_by: str | None = None
            if callee is None:
                callee = DYNAMIC
            elif "." in callee:
                root, _dot, _rest = callee.partition(".")
                if root in self.bound:
                    bound_by = self.bound[root]
            found.append(
                DiscardedCall(
                    callee=callee,
                    text=_excerpt(node),
                    void=False,
                    in_async=self.in_async,
                    bound_by=bound_by,
                    span=node_span(self.source, node),
                )
            )
        return found

    def settled(self) -> list[SettledBatch]:
        found: list[SettledBatch] = []
        for node, _parent in self.nodes:
            if not isinstance(node, ast.Call) or not _returns_exceptions(node):
                continue
            callee = dotted_name(node.func)
            if callee is None:
                continue
            _receiver, _dot, last = callee.rpartition(".")
            if last != GATHER:
                continue
            usage = self._usage(node)
            inspected = self.inspects
            if isinstance(usage, ast.Return):
                inspected = True  # the caller receives the batch
            found.append(
                SettledBatch(
                    callee=callee,
                    text=_excerpt(node),
                    discarded=isinstance(usage, ast.Expr),
                    inspected=inspected,
                    span=node_span(self.source, node),
                )
            )
        return found


def collect_python_async(source: SourceText, module: ast.Module) -> AsyncFacts:
    discarded: list[DiscardedCall] = []
    settled: list[SettledBatch] = []
    scopes: list[ast.AST] = [module]
    scopes.extend(node for node in ast.walk(module) if isinstance(node, SCOPES))
    for scope in scopes:
        facts = _Scope(source, scope)
        discarded.extend(facts.discarded())
        settled.extend(facts.settled())
    return AsyncFacts(
        discarded_calls=tuple(sorted(discarded, key=lambda d: (d.span, d.callee))),
        settled_batches=tuple(sorted(settled, key=lambda s: (s.span, s.callee))),
    )
