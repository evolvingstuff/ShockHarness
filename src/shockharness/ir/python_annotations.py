"""How many Python functions carry type annotations (TYPE002, decision 33)."""

import ast

from shockharness.ir.model import AnnotationFacts
from shockharness.ir.python_catches import node_span
from shockharness.source import SourceText

FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
RECEIVERS = frozenset({"self", "cls"})


def _annotated(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """A return annotation, or an annotated parameter other than the receiver."""
    if function.returns is not None:
        return True
    arguments = function.args
    parameters = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
    for extra in (arguments.vararg, arguments.kwarg):
        if extra is not None:
            parameters.append(extra)
    return any(p.annotation is not None for p in parameters if p.arg not in RECEIVERS)


def collect_python_annotations(source: SourceText, module: ast.Module) -> AnnotationFacts:
    functions = sorted(
        (node for node in ast.walk(module) if isinstance(node, FUNCTIONS)),
        key=lambda node: (node.lineno, node.col_offset),
    )
    annotated = [f for f in functions if _annotated(f)]
    first = None
    if len(annotated) > 0:
        first = node_span(source, annotated[0])
    return AnnotationFacts(len(functions), len(annotated), first)
