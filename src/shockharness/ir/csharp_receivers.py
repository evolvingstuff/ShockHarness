"""Receiver facts for C# (milestone G3): the classes a file declares and the types its
names hold, for the C# call graph (complexity/csharp_calls.py).

* ``classes``: each class, struct, record and interface, named like its unit
  (``Player``, ``Outer.Inner``), with its bases as simple names (``CharacterBody2D``,
  ``IDamageable``) and the methods its body declares. ``partial`` declarations of one
  class are separate entries here; the call graph merges them by name.
* ``constructed``: (unit name, name, type) for every name whose type the syntax states:
  a typed parameter or local (``Player p``), ``var p = new Player()``,
  ``var p = GetNode<Player>("P")`` (any generic call with one type argument whose name
  starts with ``Get`` or ``Instantiate``), a cast (``(Player)x``, ``x as Player``), and,
  under the class unit's name, a field or property (``private Hud _hud;``).

Types are simple names (``Godot.Node2D`` gives ``Node2D``, ``Player?`` gives ``Player``);
predefined types, arrays and tuples are not recorded: no project method is called on them.
"""

from tree_sitter import Node

from shockharness.ir.csharp_functions import TYPE_DECLARATIONS, scope_for
from shockharness.ir.csharp_nodes import Field, Kind
from shockharness.ir.model import MODULE_SCOPE, ReceiverClass, ReceiverFacts
from shockharness.ir.tree_sitter_common import node_text

TYPED_GETTERS = ("Get", "Instantiate")
CAST_EXPRESSION = "cast_expression"
AS_EXPRESSION = "as_expression"
NULLABLE_TYPE = "nullable_type"
IMPLICIT_TYPE = "implicit_type"
TYPE_ARGUMENT_LIST = "type_argument_list"
BASE_LIST = "base_list"
PRIMARY_CONSTRUCTOR_BASE = "primary_constructor_base_type"
# Statements and members whose variable declarations name typed fields or locals.
DECLARATION_HOLDERS = frozenset(
    {Kind.FIELD_DECLARATION, Kind.EVENT_FIELD_DECLARATION, Kind.LOCAL_DECLARATION_STATEMENT}
)


def simple_type(node: Node | None) -> str | None:
    """The simple name of a named type (``Player``, ``List<int>`` -> ``List``,
    ``Godot.Node`` -> ``Node``, ``Player?`` -> ``Player``); ``None`` for anything else."""
    if node is None:
        return None
    if node.type == NULLABLE_TYPE:
        inner = [c for c in node.named_children if c.type != Kind.COMMENT]
        return simple_type(inner[0]) if len(inner) == 1 else None
    if node.type == Kind.IDENTIFIER:
        return node_text(node)
    if node.type == Kind.GENERIC_NAME:
        return node_text(node).split("<", 1)[0]
    if node.type == Kind.QUALIFIED_NAME:
        _qualifier, _dot, last = node_text(node).rpartition(".")
        return last.split("<", 1)[0]
    return None


def _value_type(value: Node | None) -> str | None:
    """The type a ``var`` initializer states: ``new T()``, ``GetNode<T>()``, a cast."""
    if value is None:
        return None
    if value.type == Kind.OBJECT_CREATION_EXPRESSION:
        return simple_type(value.child_by_field_name(Field.TYPE))
    if value.type == CAST_EXPRESSION:
        return simple_type(value.child_by_field_name(Field.TYPE))
    if value.type == AS_EXPRESSION:
        return simple_type(value.child_by_field_name(Field.RIGHT))
    if value.type == Kind.INVOCATION_EXPRESSION:
        return _getter_type(value.child_by_field_name(Field.FUNCTION))
    return None


def _getter_type(function: Node | None) -> str | None:
    """``GetNode<T>`` / ``x.Instantiate<T>`` -> ``T``."""
    name = _called_name(function)
    if name is None or name.type != Kind.GENERIC_NAME:
        return None
    if not node_text(name).startswith(TYPED_GETTERS):
        return None
    arguments = [c for c in name.named_children if c.type == TYPE_ARGUMENT_LIST]
    types = (
        []
        if len(arguments) != 1
        else [c for c in arguments[0].named_children if c.type != Kind.COMMENT]
    )
    return simple_type(types[0]) if len(types) == 1 else None


def _called_name(function: Node | None) -> Node | None:
    """The name node of a callee: itself, or the member of ``x.Name``."""
    if function is not None and function.type == Kind.MEMBER_ACCESS_EXPRESSION:
        return function.child_by_field_name(Field.NAME)
    return function


def _declarators(declaration: Node) -> list[tuple[str, Node | None]]:
    """(name, initializer) of each declarator of a variable declaration."""
    found: list[tuple[str, Node | None]] = []
    for declarator in declaration.named_children:
        if declarator.type != Kind.VARIABLE_DECLARATOR:
            continue
        name = declarator.child_by_field_name(Field.NAME)
        if name is None or name.type != Kind.IDENTIFIER:
            continue
        values = [
            c for c in declarator.named_children if c.id != name.id and c.type != Kind.COMMENT
        ]
        found.append((node_text(name), values[0] if len(values) == 1 else None))
    return found


def _declared(declaration: Node) -> list[tuple[str, str]]:
    """(name, type) of a variable declaration: its stated type, or for ``var`` the type
    each initializer states."""
    stated = declaration.child_by_field_name(Field.TYPE)
    found: list[tuple[str, str]] = []
    for name, value in _declarators(declaration):
        typed = _value_type(value)
        if stated is not None and stated.type != IMPLICIT_TYPE:
            typed = simple_type(stated)
        if typed is not None:
            found.append((name, typed))
    return found


def _base_names(declaration: Node) -> tuple[str, ...]:
    names: list[str] = []
    for child in declaration.named_children:
        if child.type == BASE_LIST:
            names.extend(
                n for n in (_base_name(base) for base in child.named_children) if n is not None
            )
    return tuple(names)


def _base_name(base: Node) -> str | None:
    """A base list entry's simple name; ``Base(x)`` of a primary constructor too."""
    if base.type == PRIMARY_CONSTRUCTOR_BASE and base.named_child_count > 0:
        return simple_type(base.named_children[0])
    return simple_type(base)


def _methods(declaration: Node) -> tuple[str, ...]:
    body = declaration.child_by_field_name(Field.BODY)
    if body is None:
        return ()
    names: list[str] = []
    for member in body.named_children:
        if member.type == Kind.METHOD_DECLARATION:
            name = member.child_by_field_name(Field.NAME)
            if name is not None:
                names.append(node_text(name))
    return tuple(names)


def _named_type(node: Node) -> list[tuple[str, str]]:
    """(name, type) of a property or parameter whose type is a named type."""
    name = node.child_by_field_name(Field.NAME)
    typed = simple_type(node.child_by_field_name(Field.TYPE))
    if name is None or typed is None:
        return []
    return [(node_text(name), typed)]


class _Collector:
    def __init__(self) -> None:
        self.classes: list[ReceiverClass] = []
        self.constructed: list[tuple[str, str, str]] = []

    def visit(self, node: Node, scope: str) -> None:
        """``scope`` is the qualified name of the unit ``node`` is in."""
        kind = node.type
        if kind in TYPE_DECLARATIONS and kind != Kind.ENUM_DECLARATION:
            name = scope_for(node, scope)
            self.classes.append(ReceiverClass(name, _base_names(node), _methods(node)))
        elif kind in DECLARATION_HOLDERS:
            for declaration in node.named_children:
                if declaration.type == Kind.VARIABLE_DECLARATION:
                    self._add(scope, _declared(declaration))
        elif kind in (Kind.PROPERTY_DECLARATION, Kind.PARAMETER):
            self._add(scope, _named_type(node))

    def _add(self, unit: str, pairs: list[tuple[str, str]]) -> None:
        self.constructed.extend((unit, name, typed) for name, typed in pairs)


def collect_csharp_receivers(root: Node) -> ReceiverFacts:
    collector = _Collector()
    stack: list[tuple[Node, str]] = [(root, MODULE_SCOPE)]
    while len(stack) > 0:
        node, scope = stack.pop()
        collector.visit(node, scope)
        # Children are in the node's scope: a parameter or local in its function's, a
        # field in its class's (units are named the same way).
        inner = scope_for(node, scope)
        stack.extend((child, inner) for child in reversed(node.children))
    return ReceiverFacts(
        singletons=(),
        constructed=tuple(sorted(set(collector.constructed))),
        classes=tuple(collector.classes),
        objects=(),
    )
