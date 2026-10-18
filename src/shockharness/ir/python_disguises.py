"""Python numbers written as something else (MAGIC005); see ``Disguise`` in the model.

Read from the syntax alone: the callee is the name as written (``len``, ``int``,
``json.loads``), so an import alias of a parser is not seen.
"""

import ast
import math
import re
from collections import Counter

from shockharness.ir.model import (
    DISGUISE_CONVERSION,
    DISGUISE_INDENT,
    DISGUISE_LENGTH,
    DISGUISE_PARSED,
    MODULE_SCOPE,
    Disguise,
)
from shockharness.ir.python_catches import SCOPE_NODES, node_span, scope_name
from shockharness.source import SourceText

LENGTH = "len"
CONVERSIONS = frozenset({"int", "float"})
PARSERS = frozenset(
    {"json.loads", "tomllib.loads", "tomli.loads", "ast.literal_eval", "yaml.safe_load"}
)
DUMPERS = frozenset({"json.dumps", "json.dump"})
INDENT = "indent"
SPACE = " "
# A number inside a parsed text: digits not part of a word, an identifier or a version.
NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])")
# The shown expression is cut here (a whole parsed document is not evidence).
TEXT_LIMIT = 60
DISPLAYS = (ast.Tuple, ast.List, ast.Set)


def _shown(node: ast.AST) -> str:
    text = ast.unparse(node)
    if len(text) > TEXT_LIMIT:
        return text[:TEXT_LIMIT] + "..."
    return text


def _string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str | bytes):
        if isinstance(node.value, bytes):
            return node.value.decode("latin-1")
        return node.value
    return None


def _length(argument: ast.expr) -> int | None:
    """The length of a literal written for its length: a string of whitespace only, or a
    display with no starred element. A string whose content means something (a prefix to
    strip, a format such as "YYYY-MM-DD") is not a disguise."""
    text = _string(argument)
    if text is not None:
        if not text.isspace():
            return None
        return len(text)
    if isinstance(argument, DISPLAYS):
        if any(isinstance(e, ast.Starred) for e in argument.elts):
            return None
        return len(argument.elts)
    if isinstance(argument, ast.Dict):
        if any(key is None for key in argument.keys):
            return None
        return len(argument.keys)
    return None


def _converted(callee: str, text: str) -> int | float | None:
    """``int("30")`` -> 30; None when the text is not a plain finite number."""
    stripped = text.strip()
    if NUMBER.fullmatch(stripped) is None:
        return None
    if callee == "int" and "." not in stripped:
        return int(stripped)
    value = float(stripped)
    if not math.isfinite(value):
        return None
    return value


def _number(match: str) -> int | float:
    if "." in match:
        return float(match)
    return int(match)


def numbers_in(text: str) -> tuple[int | float, ...]:
    return tuple(_number(match) for match in NUMBER.findall(text))


def _call_values(
    call: ast.Call, spaces: dict[str, int]
) -> tuple[str, tuple[int | float, ...]] | None:
    """(kind, values) of a call that disguises a number; None for any other call.
    ``spaces``: the module-level names bound to a string of spaces, and its length."""
    callee = ast.unparse(call.func)
    if len(call.args) > 0:
        found = _first_argument(callee, call.args[0], len(call.args))
        if found is not None:
            return found
    if callee in DUMPERS:
        for keyword in call.keywords:
            if keyword.arg == INDENT:
                return _indent(keyword.value, spaces)
    return None


def _indent(value: ast.expr, spaces: dict[str, int]) -> tuple[str, tuple[int, ...]] | None:
    """``indent="  "``, or ``indent=NAME`` for a module-level string of spaces."""
    indent = _string(value)
    if indent is not None and set(indent) == {SPACE}:
        return DISGUISE_INDENT, (len(indent),)
    if isinstance(value, ast.Name) and value.id in spaces:
        return DISGUISE_INDENT, (spaces[value.id],)
    return None


def _bindings(statement: ast.stmt) -> tuple[list[ast.expr], ast.expr | None]:
    if isinstance(statement, ast.Assign):
        return statement.targets, statement.value
    if isinstance(statement, ast.AnnAssign):
        return [statement.target], statement.value
    return [], None


def module_spaces(module: ast.Module) -> dict[str, int]:
    """Module-level names bound once to a string of spaces (``REPORT_INDENT = "  "``)."""
    found: dict[str, int] = {}
    bound: Counter[str] = Counter()
    for statement in module.body:
        targets, value = _bindings(statement)
        names = [target.id for target in targets if isinstance(target, ast.Name)]
        bound.update(names)
        text = None
        if value is not None:
            text = _string(value)
        if text is not None and set(text) == {SPACE}:
            found.update((name, len(text)) for name in names)
    return {name: length for name, length in found.items() if bound[name] == 1}


def _first_argument(
    callee: str, first: ast.expr, count: int
) -> tuple[str, tuple[int | float, ...]] | None:
    """``len(<literal>)``, ``int("30")`` / ``float("2.5")``, a parser of a literal text."""
    if callee == LENGTH and count == 1:
        length = _length(first)
        if length is not None:
            return DISGUISE_LENGTH, (length,)
    text = _string(first)
    if text is None:
        return None
    if callee in CONVERSIONS and count == 1:
        value = _converted(callee, text)
        if value is not None:
            return DISGUISE_CONVERSION, (value,)
    if callee in PARSERS:
        numbers = numbers_in(text)
        if len(numbers) > 0:
            return DISGUISE_PARSED, numbers
    return None


def collect_python_disguises(source: SourceText, module: ast.Module) -> tuple[Disguise, ...]:
    found: list[Disguise] = []
    spaces = module_spaces(module)
    stack: list[tuple[ast.AST, str]] = [(module, MODULE_SCOPE)]
    while len(stack) > 0:
        node, scope = stack.pop()
        if isinstance(node, ast.Call):
            values = _call_values(node, spaces)
            if values is not None:
                kind, numbers = values
                found.append(Disguise(node_span(source, node), kind, numbers, _shown(node), scope))
        child_scope = scope
        if isinstance(node, SCOPE_NODES):
            name = scope_name(node)
            child_scope = name if scope == MODULE_SCOPE else f"{scope}.{name}"
        stack.extend((child, child_scope) for child in ast.iter_child_nodes(node))
    found.sort(key=lambda d: d.span)
    return tuple(found)
