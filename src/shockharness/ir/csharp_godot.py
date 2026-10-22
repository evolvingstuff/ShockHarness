"""Godot names in C# (milestone G4): the input actions, node paths, groups and signal names
a script writes as strings, and the signals it declares. GODOT001-GODOT005
(rules/godot_names.py) check them against the project's files.

Only string literals are names here: a name built at run time is not checkable, and is
not recorded. A call's receiver matters for node paths and signals: ``GetNode("A")`` and
``this.EmitSignal("Hit")`` are about the script's own node; ``other.GetNode("A")`` is not
recorded as a node path, and ``other.EmitSignal("Hit")`` not as a signal.
"""

from tree_sitter import Node

from shockharness.ir.csharp_functions import TYPE_DECLARATIONS, scope_for
from shockharness.ir.csharp_nodes import Field, Kind
from shockharness.ir.csharp_strings import literal_text
from shockharness.ir.model import (
    GODOT_ACTION,
    GODOT_ACTION_ADDED,
    GODOT_GROUP_ADDED,
    GODOT_GROUP_READ,
    GODOT_NODE_PATH,
    GODOT_SIGNAL_DECLARED,
    GODOT_SIGNAL_USE,
    MODULE_SCOPE,
    GodotNameUse,
)
from shockharness.ir.tree_sitter_common import node_span, node_text
from shockharness.source import SourceText

# Method name -> what its string arguments are, and which of them (None: every one).
ACTION_READS = frozenset(
    {
        "IsActionPressed",
        "IsActionJustPressed",
        "IsActionJustReleased",
        "IsActionReleased",
        "GetActionStrength",
        "GetActionRawStrength",
        "ActionPress",
        "ActionRelease",
        "IsAction",
        "GetAxis",
        "GetVector",
    }
)
CALLS: dict[str, tuple[str, int | None]] = {
    **{name: (GODOT_ACTION, None) for name in ACTION_READS},
    "AddAction": (GODOT_ACTION_ADDED, 0),
    "GetNode": (GODOT_NODE_PATH, 0),
    "GetNodesInGroup": (GODOT_GROUP_READ, 0),
    "GetFirstNodeInGroup": (GODOT_GROUP_READ, 0),
    "IsInGroup": (GODOT_GROUP_READ, 0),
    "CallGroup": (GODOT_GROUP_READ, 0),
    "CallGroupFlags": (GODOT_GROUP_READ, 1),
    "NotifyGroup": (GODOT_GROUP_READ, 0),
    "SetGroup": (GODOT_GROUP_READ, 0),
    "AddToGroup": (GODOT_GROUP_ADDED, 0),
    "EmitSignal": (GODOT_SIGNAL_USE, 0),
    "Connect": (GODOT_SIGNAL_USE, 0),
    "Disconnect": (GODOT_SIGNAL_USE, 0),
    "IsConnected": (GODOT_SIGNAL_USE, 0),
}
# Kinds that are about the script's own node: recorded only for a call on it.
ON_SELF_ONLY = frozenset({GODOT_NODE_PATH, GODOT_SIGNAL_USE})
SELF = "this"
SIGNAL_ATTRIBUTES = frozenset({"Signal", "SignalAttribute"})
EVENT_HANDLER = "EventHandler"


def _method_and_receiver(call: Node) -> tuple[str, Node | None, bool]:
    """(method name without type arguments, receiver, whether it is the object itself)."""
    function = call.child_by_field_name(Field.FUNCTION)
    if function is None:
        return "", None, False
    if function.type == Kind.MEMBER_ACCESS_EXPRESSION:
        name = function.child_by_field_name(Field.NAME)
        receiver = function.child_by_field_name(Field.EXPRESSION)
        on_self = receiver is not None and receiver.type == SELF
        if name is None:
            return "", receiver, on_self
        return node_text(name).split("<", 1)[0], receiver, on_self
    return node_text(function).split("<", 1)[0], None, True


def _string_arguments(call: Node) -> list[tuple[int, Node, str]]:
    """(position, node, text) of each plain string literal argument."""
    arguments = call.child_by_field_name(Field.ARGUMENTS)
    if arguments is None:
        return []
    found: list[tuple[int, Node, str]] = []
    position = 0
    for argument in arguments.named_children:
        if argument.type != Kind.ARGUMENT:
            continue
        values = [c for c in argument.named_children if c.type != Kind.COMMENT]
        if len(values) > 0:
            text = literal_text(values[len(values) - 1])
            if text is not None:
                found.append((position, values[len(values) - 1], text))
        position += 1
    return found


def _last(dotted: str) -> str:
    _head, _dot, last = dotted.rpartition(".")
    return last


def _signal_declared(delegate: Node) -> str | None:
    """``[Signal] public delegate void HitEventHandler(...)`` -> ``Hit``."""
    attributes = [
        node_text(name)
        for attribute_list in delegate.named_children
        if attribute_list.type == Kind.ATTRIBUTE_LIST
        for attribute in attribute_list.named_children
        for name in [attribute.child_by_field_name(Field.NAME)]
        if name is not None
    ]
    if not any(_last(a) in SIGNAL_ATTRIBUTES for a in attributes):
        return None
    name = delegate.child_by_field_name(Field.NAME)
    if name is None:
        return None
    return node_text(name).removesuffix(EVENT_HANDLER)


class _Collector:
    def __init__(self, source: SourceText) -> None:
        self.source = source
        self.found: list[GodotNameUse] = []

    def visit(self, node: Node, owner: str | None) -> None:
        if node.type == Kind.INVOCATION_EXPRESSION:
            self._call(node, owner)
        elif node.type == Kind.DELEGATE_DECLARATION:
            signal = _signal_declared(node)
            if signal is not None:
                span = node_span(self.source, node)
                self.found.append(
                    GodotNameUse(GODOT_SIGNAL_DECLARED, signal, owner, on_self=True, span=span)
                )

    def _call(self, call: Node, owner: str | None) -> None:
        method, _receiver, on_self = _method_and_receiver(call)
        if method not in CALLS:
            return
        kind, position = CALLS[method]
        if kind in ON_SELF_ONLY and not on_self:
            return
        for index, value, text in _string_arguments(call):
            if position is None or index == position:
                span = node_span(self.source, value)
                self.found.append(GodotNameUse(kind, text, owner, on_self, span))


def collect_csharp_godot(source: SourceText, root: Node) -> tuple[GodotNameUse, ...]:
    collector = _Collector(source)
    stack: list[tuple[Node, str, str | None]] = [(root, MODULE_SCOPE, None)]
    while len(stack) > 0:
        node, scope, owner = stack.pop()
        collector.visit(node, owner)
        inner = scope_for(node, scope)
        held = inner if node.type in TYPE_DECLARATIONS else owner
        stack.extend((child, inner, held) for child in reversed(node.children))
    return tuple(sorted(collector.found, key=lambda use: use.span))
