"""The shapes of JavaScript and TypeScript functions (DUP001, DUP002), as ``python_shapes``
does for Python: the body's tokens in source order with comments and layout dropped,
parameters and declared locals renamed by first appearance, and a string's mention of the
file's own path or the function's own name replaced.

A function is recorded when it has a name: a declaration, a method, or a function or arrow
bound to a declared name, a class field or an object key; and a block body.
"""

from tree_sitter import Node

from shockharness.ir.javascript_catches import FIELD_NAME_FIELDS, node_span, node_text
from shockharness.ir.javascript_functions import CLASS_TYPES
from shockharness.ir.javascript_nodes import Field, Kind
from shockharness.ir.model import SHAPE_FILE, SHAPE_MIN_STATEMENTS, SHAPE_NAME, FunctionShape
from shockharness.source import SourceText

NAMED = frozenset(
    {Kind.FUNCTION_DECLARATION, Kind.GENERATOR_FUNCTION_DECLARATION, Kind.METHOD_DEFINITION}
)
BOUND = frozenset({Kind.FUNCTION_EXPRESSION, Kind.ARROW_FUNCTION, Kind.GENERATOR_FUNCTION})
# Where a bound function's name is: the declarator's name, the object key, the field name.
BINDERS = {Kind.VARIABLE_DECLARATOR: Field.NAME, Kind.PAIR: Field.KEY, **FIELD_NAME_FIELDS}
LOCAL_NAMES = frozenset({Kind.IDENTIFIER, Kind.SHORTHAND_PROPERTY_IDENTIFIER_PATTERN})
STATEMENT_SUFFIX = "statement"
DECLARATIONS = frozenset({Kind.LEXICAL_DECLARATION, Kind.VARIABLE_DECLARATION})
UNDERSCORE = "_"


def _walk(node: Node) -> list[Node]:
    found: list[Node] = []
    stack = [node]
    while len(stack) > 0:
        current = stack.pop()
        found.append(current)
        stack.extend(reversed(current.children))
    return found


def _name(node: Node) -> str | None:
    """The function's own name, or None when it has none the file gives it."""
    if node.type in NAMED:
        name = node.child_by_field_name(Field.NAME)
        return None if name is None else node_text(name)
    parent = node.parent
    if node.type not in BOUND or parent is None or parent.type not in BINDERS:
        return None
    name = parent.child_by_field_name(BINDERS[parent.type])
    if name is None or name.type not in (Kind.IDENTIFIER, Kind.PROPERTY_IDENTIFIER):
        return None
    return node_text(name)


def _owner(node: Node) -> str:
    """The class a method is defined in (its name, or the name a class expression is bound
    to); "" for anything else."""
    body = node.parent
    if node.type != Kind.METHOD_DEFINITION or body is None:
        return ""
    declaration = body.parent  # a class method's parent is the class body
    if declaration is None or declaration.type not in CLASS_TYPES:
        return ""
    name = declaration.child_by_field_name(Field.NAME)
    holder = declaration.parent
    if name is None and holder is not None and holder.type == Kind.VARIABLE_DECLARATOR:
        name = holder.child_by_field_name(Field.NAME)
    if name is None:
        return ""
    return node_text(name)


def _parameters(node: Node) -> set[str]:
    names: set[str] = set()
    parameters = node.child_by_field_name(Field.PARAMETERS)
    if parameters is not None:
        names.update(node_text(n) for n in _walk(parameters) if n.type in LOCAL_NAMES)
    single = node.child_by_field_name(Field.PARAMETER)
    if single is not None:
        names.add(node_text(single))
    return names


def _declared_names(declarator: Node) -> list[str]:
    bound = declarator.child_by_field_name(Field.NAME)
    if bound is None:
        return []
    return [node_text(x) for x in _walk(bound) if x.type in LOCAL_NAMES]


TYPE_FIELD = "type"  # TypeScript: a parameter's type annotation
RETURN_TYPE_FIELD = "return_type"
RETURNS = "->"


def _signature(node: Node) -> tuple[str, ...]:
    """TypeScript's parameter and return annotations; empty for JavaScript."""
    found: list[str] = []
    parameters = node.child_by_field_name(Field.PARAMETERS)
    if parameters is not None:
        for parameter in parameters.named_children:
            annotation = parameter.child_by_field_name(TYPE_FIELD)
            if annotation is not None:
                found.append(node_text(annotation))
    returned = node.child_by_field_name(RETURN_TYPE_FIELD)
    if returned is not None:
        found.extend((RETURNS, node_text(returned)))
    return tuple(found)


def _locals_and_statements(node: Node, nodes: list[Node]) -> tuple[set[str], int]:
    """The parameters and declared locals, and the statement count, in one pass over the
    body's nodes."""
    names = _parameters(node)
    statements = 0
    for n in nodes:
        if n.type.endswith(STATEMENT_SUFFIX) or n.type in DECLARATIONS:
            statements += 1
        if n.type == Kind.VARIABLE_DECLARATOR:
            names.update(_declared_names(n))
    return names, statements


def _set_aside(text: str, path: str, own: str) -> str:
    """A string's mention of its own file and of its function's own name, replaced."""
    if path != "":
        text = text.replace(path, SHAPE_FILE)
    if own != "":
        text = text.replace(own, SHAPE_NAME)
    return text


def _rename(renamed: dict[str, str], name: str) -> str:
    """A local's name by its order of first appearance (``v0``, ``v1``...)."""
    if name not in renamed:
        renamed[name] = f"v{len(renamed)}"
    return renamed[name]


def _tokens(nodes: list[Node], local: set[str], path: str, own: str) -> tuple[str, ...]:
    renamed: dict[str, str] = {}
    tokens: list[str] = []
    for n in nodes:
        if n.type == Kind.COMMENT or n.child_count > 0:
            continue
        text = node_text(n)
        if n.type == Kind.STRING_FRAGMENT:
            text = _set_aside(text, path, own)
        elif n.type == Kind.IDENTIFIER and text in local:
            text = _rename(renamed, text)
        tokens.append(text)
    return tuple(tokens)


def collect_javascript_shapes(
    source: SourceText, root: Node, path: str
) -> tuple[FunctionShape, ...]:
    shapes: list[FunctionShape] = []
    for node in _walk(root):
        name = _name(node)
        body = node.child_by_field_name(Field.BODY)
        if name is None or body is None or body.type != Kind.STATEMENT_BLOCK:
            continue
        nodes = _walk(body)
        local, statements = _locals_and_statements(node, nodes)
        if statements < SHAPE_MIN_STATEMENTS:
            continue
        tokens = _tokens(nodes, local, path, name.lstrip(UNDERSCORE))
        span = node_span(source, node)
        shapes.append(
            FunctionShape(
                span.line,
                span.column,
                span.end_line,
                name,
                _owner(node),
                statements,
                tokens,
                _signature(node),
            )
        )
    shapes.sort(key=lambda s: (s.line, s.column))
    return tuple(shapes)
