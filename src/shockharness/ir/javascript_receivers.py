"""What a JavaScript method call's receiver is, read from the syntax alone
(docs/proposal-receivers.md, R2). The counterpart of :mod:`.python_receivers`.

Each answer here is exact or absent, never a guess:

* a **module-level object** is ``const name = { ... }`` (or ``Object.freeze({ ... })``)
  at module level, exported or not. Its methods are its method definitions and its
  properties whose value is a function or an arrow. A method the module assigns again
  (``name.m = ...``) is not one, and an object the module writes into some other way
  (``name[k] = ...``, ``Object.assign(name, ...)``) has none;
* a **module-level singleton** is ``const name = new Class(...)`` at module level;
* a **class** is a module-level class declaration: its ``extends`` base as written and
  its instance methods (static methods, getters and setters excluded);
* a **constructed local** is ``const name = new Class(...)`` in a function's own body.

Whether the constructor or the base is a project class is the consumer's question.
"""

from collections.abc import Iterator
from dataclasses import dataclass

from tree_sitter import Node

from shockharness.ir.javascript_catches import node_span, node_text
from shockharness.ir.javascript_functions import UNIT_TYPES, dotted_name
from shockharness.ir.javascript_nodes import Field, Kind
from shockharness.ir.model import ReceiverClass, ReceiverFacts, ReceiverObject
from shockharness.source import SourceText

CONST = "const"
FREEZE = "Object.freeze"
ASSIGN = "Object.assign"
# Keywords before a method's name that make it something other than an instance method.
NOT_INSTANCE = frozenset({"static", "get", "set"})
FUNCTION_VALUES = frozenset({Kind.FUNCTION_EXPRESSION, Kind.ARROW_FUNCTION})
CLASS_DECLARATIONS = frozenset({Kind.CLASS_DECLARATION, Kind.ABSTRACT_CLASS_DECLARATION})


@dataclass(frozen=True)
class JsObject:
    name: str
    methods: dict[str, Node]  # method name -> the unit node (method, function or arrow)


@dataclass(frozen=True)
class JsClass:
    name: str
    node: Node
    base: Node | None  # the expression after extends
    methods: dict[str, Node]  # instance method name -> its method_definition


@dataclass(frozen=True)
class JsReceivers:
    objects: dict[str, JsObject]
    singletons: dict[str, Node]  # name -> the constructor of its new expression
    classes: dict[str, JsClass]


def _statements(root: Node) -> Iterator[Node]:
    """Module-level statements, the declaration of an ``export`` included."""
    for statement in root.named_children:
        if statement.type == Kind.EXPORT_STATEMENT:
            declaration = statement.child_by_field_name(Field.DECLARATION)
            if declaration is not None:
                yield declaration
            continue
        yield statement


def const_declarators(statement: Node) -> Iterator[tuple[str, Node]]:
    """(name, value) of each ``const name = value``."""
    if statement.type != Kind.LEXICAL_DECLARATION:
        return
    kind = statement.child_by_field_name(Field.KIND)
    if kind is None or node_text(kind) != CONST:
        return
    for declarator in statement.named_children:
        if declarator.type != Kind.VARIABLE_DECLARATOR:
            continue
        name = declarator.child_by_field_name(Field.NAME)
        value = declarator.child_by_field_name(Field.VALUE)
        if name is not None and value is not None and name.type == Kind.IDENTIFIER:
            yield node_text(name), value


def _literal(value: Node) -> Node | None:
    """The object literal of ``{ ... }`` or ``Object.freeze({ ... })``."""
    if value.type == Kind.OBJECT:
        return value
    if value.type != Kind.CALL_EXPRESSION:
        return None
    function = value.child_by_field_name(Field.FUNCTION)
    arguments = value.child_by_field_name(Field.ARGUMENTS)
    if function is None or arguments is None or dotted_name(function) != FREEZE:
        return None
    inner = [c for c in arguments.named_children if c.type != Kind.COMMENT]
    if len(inner) == 1 and inner[0].type == Kind.OBJECT:
        return inner[0]
    return None


def _keywords(method: Node) -> set[str]:
    return {node_text(child) for child in method.children if not child.is_named}


def _method_name(method: Node) -> str | None:
    """The name of an instance method definition (not static, a getter or a setter)."""
    if method.type != Kind.METHOD_DEFINITION or len(_keywords(method) & NOT_INSTANCE) > 0:
        return None
    name = method.child_by_field_name(Field.NAME)
    if name is None or name.type != Kind.PROPERTY_IDENTIFIER:
        return None
    return node_text(name)


def _function_pair(member: Node) -> tuple[str, Node] | None:
    """(key, value) of ``key: function () {...}`` or ``key: () => ...``."""
    if member.type != Kind.PAIR:
        return None
    key = member.child_by_field_name(Field.KEY)
    value = member.child_by_field_name(Field.VALUE)
    if key is None or value is None or value.type not in FUNCTION_VALUES:
        return None
    if key.type != Kind.PROPERTY_IDENTIFIER:
        return None
    return node_text(key), value


def _literal_methods(literal: Node) -> dict[str, Node]:
    found: dict[str, Node] = {}
    for member in literal.named_children:
        name = _method_name(member)
        if name is not None:
            found[name] = member
        pair = _function_pair(member)
        if pair is not None:
            found[pair[0]] = pair[1]
    return found


def _new_constructor(value: Node) -> Node | None:
    if value.type != Kind.NEW_EXPRESSION:
        return None
    constructor = value.child_by_field_name(Field.CONSTRUCTOR)
    if constructor is None or dotted_name(constructor) is None:
        return None
    return constructor


def _class(node: Node) -> JsClass | None:
    name = node.child_by_field_name(Field.NAME)
    body = node.child_by_field_name(Field.BODY)
    if name is None or body is None:
        return None
    methods: dict[str, Node] = {}
    for member in body.named_children:
        method = _method_name(member)
        if method is not None:
            methods[method] = member
    return JsClass(node_text(name), node, _heritage(node), methods)


def _heritage(node: Node) -> Node | None:
    """The one expression after ``extends``."""
    for child in node.named_children:
        if child.type == Kind.CLASS_HERITAGE:
            inner = [c for c in child.named_children if c.type != Kind.COMMENT]
            if len(inner) == 1:
                return inner[0]
    return None


def _written(root: Node) -> tuple[set[tuple[str, str]], set[str]]:
    """(name, member) pairs the module assigns (``name.m = ...``), and the names it writes
    into otherwise (``name[k] = ...``, ``Object.assign(name, ...)``)."""
    members: set[tuple[str, str]] = set()
    whole: set[str] = set()
    pending = [root]
    while len(pending) > 0:
        node = pending.pop()
        pending.extend(node.named_children)
        if node.type in (Kind.ASSIGNMENT_EXPRESSION, Kind.AUGMENTED_ASSIGNMENT_EXPRESSION):
            _assigned_member(node, members, whole)
        elif node.type == Kind.CALL_EXPRESSION:
            assigned = _assign_target(node)
            if assigned is not None:
                whole.add(assigned)
    return members, whole


def _assigned_member(node: Node, members: set[tuple[str, str]], whole: set[str]) -> None:
    """``name.m = ...`` adds (name, m); ``name[k] = ...`` adds name to ``whole``."""
    left = node.child_by_field_name(Field.LEFT)
    if left is None:
        return
    target = left.child_by_field_name(Field.OBJECT)
    if target is None or target.type != Kind.IDENTIFIER:
        return
    if left.type == Kind.MEMBER_EXPRESSION:
        prop = left.child_by_field_name(Field.PROPERTY)
        if prop is not None:
            members.add((node_text(target), node_text(prop)))
    elif left.type == Kind.SUBSCRIPT_EXPRESSION:
        whole.add(node_text(target))


def _assign_target(call: Node) -> str | None:
    """The name ``Object.assign(name, ...)`` writes into."""
    function = call.child_by_field_name(Field.FUNCTION)
    arguments = call.child_by_field_name(Field.ARGUMENTS)
    if function is None or arguments is None or dotted_name(function) != ASSIGN:
        return None
    first = [c for c in arguments.named_children if c.type != Kind.COMMENT]
    if len(first) == 0 or first[0].type != Kind.IDENTIFIER:
        return None
    return node_text(first[0])


def module_receivers(root: Node) -> JsReceivers:
    objects: dict[str, JsObject] = {}
    singletons: dict[str, Node] = {}
    classes: dict[str, JsClass] = {}
    members, whole = _written(root)
    for statement in _statements(root):
        if statement.type in CLASS_DECLARATIONS:
            found = _class(statement)
            if found is not None:
                classes[found.name] = found
            continue
        for name, value in const_declarators(statement):
            literal = _literal(value)
            constructor = _new_constructor(value)
            if literal is not None and name not in whole:
                objects[name] = _object(name, literal, members)
            elif constructor is not None:
                singletons[name] = constructor
    return JsReceivers(objects, singletons, classes)


def _object(name: str, literal: Node, members: set[tuple[str, str]]) -> JsObject:
    """The object ``name`` with the methods its module never assigns again."""
    methods = {
        method: node
        for method, node in _literal_methods(literal).items()
        if (name, method) not in members
    }
    return JsObject(name, methods)


def constructed_locals(function: Node) -> dict[str, Node]:
    """``const name = new Class(...)`` in a function's own body: name -> the constructor.
    Nested functions are their own units; a ``const`` is never rebound."""
    found: dict[str, Node] = {}
    body = function.child_by_field_name(Field.BODY)
    if body is None:
        return found
    pending = list(body.named_children)
    while len(pending) > 0:
        node = pending.pop()
        if node.type in UNIT_TYPES:
            continue
        pending.extend(node.named_children)
        for name, value in const_declarators(node):
            constructor = _new_constructor(value)
            if constructor is not None:
                found[name] = constructor
    return found


def _start(source: SourceText, node: Node) -> tuple[int, int]:
    span = node_span(source, node)
    return span.line, span.column


def _units(root: Node) -> Iterator[Node]:
    pending = [root]
    while len(pending) > 0:
        node = pending.pop()
        if node.is_named and node.type in UNIT_TYPES:
            yield node
        pending.extend(node.named_children)


def collect_javascript_receivers(source: SourceText, root: Node) -> ReceiverFacts:
    found = module_receivers(root)
    objects = tuple(
        ReceiverObject(
            o.name,
            tuple(sorted((m, *_start(source, node)) for m, node in o.methods.items())),
        )
        for o in sorted(found.objects.values(), key=lambda o: o.name)
    )
    classes = tuple(
        ReceiverClass(c.name, _bases(c), tuple(sorted(c.methods)))
        for c in sorted(found.classes.values(), key=lambda c: c.name)
    )
    singletons = tuple(
        sorted((name, node_text(constructor)) for name, constructor in found.singletons.items())
    )
    constructed = tuple(
        sorted(
            (f"{line}:{column}", name, node_text(constructor))
            for unit in _units(root)
            for line, column in [_start(source, unit)]
            for name, constructor in constructed_locals(unit).items()
        )
    )
    return ReceiverFacts(singletons, constructed, classes, objects)


def _bases(found: JsClass) -> tuple[str, ...]:
    """The base as written when it is a plain or dotted name, ``""`` for any other
    expression; no base for a class without ``extends``."""
    base = found.base
    if base is None:
        return ()
    if dotted_name(base) is None:
        return ("",)
    return (node_text(base),)
