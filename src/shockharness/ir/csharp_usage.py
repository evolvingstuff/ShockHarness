"""Uses of methods and types in C# (milestone G3), for DEAD001 and DEAD002.

* ``declared``: the methods the dead-code rules judge (every method with a body, and
  every local function), with what reaches each one without a call: ``override`` (the
  engine or a base class calls it, while its class is alive), ``constructor``,
  ``finalizer``, ``operator``, ``interface implementation`` (``void IFoo.Bar()``),
  ``[Rpc]`` (a remote peer calls it), a test attribute, and ``entry point`` (a static
  ``Main``). Classes with a base list are declared too: a Godot script nothing uses is
  judged as a whole (``[GlobalClass]`` and ``[Tool]`` register one).
* ``references``: method names used without a call, all by name across the project
  (``partial`` classes span files): a name passed or assigned as a value
  (``Hit += OnHit``, ``Callable.From(OnHit)``, ``nameof(OnHit)``), a member read
  (``MethodName.OnHit``), and a string given to Godot's string-named calls
  (``Call("OnHit")``, ``CallDeferred``, ``Rpc``, ``RpcId``, ``CallGroup``,
  ``new Callable(this, "OnHit")``).
* ``types``: capitalized names used outside a declaration, which covers every type a
  file names (``new Player()``, ``GetNode<Player>``, ``Player p``, ``is Player``); a
  method or member of the same spelling is counted too, which only keeps a class alive.
"""

from tree_sitter import Node

from shockharness.ir.csharp_functions import is_unit
from shockharness.ir.csharp_nodes import Field, Kind
from shockharness.ir.model import DeclaredFunction, UsageFacts, UsageReference
from shockharness.ir.tree_sitter_common import node_span, node_text
from shockharness.source import SourceText

OVERRIDE = "override"
ATTRIBUTE_SUFFIX = "Attribute"
REGISTERED_BY_KIND = {
    Kind.CONSTRUCTOR_DECLARATION: "constructor",
    Kind.DESTRUCTOR_DECLARATION: "finalizer",
    Kind.OPERATOR_DECLARATION: "operator",
    Kind.CONVERSION_OPERATOR_DECLARATION: "operator",
}
REGISTERING_ATTRIBUTES = {
    "Rpc": "[Rpc]",
    "ModuleInitializer": "[ModuleInitializer]",
    "GlobalClass": "[GlobalClass]",
    "Tool": "[Tool]",
    "Test": "test",
    "TestCase": "test",
    "TestMethod": "test",
    "Fact": "test",
    "Theory": "test",
    "Before": "test",
    "After": "test",
    "BeforeTest": "test",
    "AfterTest": "test",
    "Setup": "test",
    "SetUp": "test",
    "TearDown": "test",
    "Cleanup": "test",
}
ENTRY_POINT = "Main"
STATIC = "static"
METHOD_NAME_CALLS = frozenset(
    {
        "Call",
        "CallDeferred",
        "Callv",
        "CallThreadSafe",
        "CallDeferredThreadGroup",
        "Rpc",
        "RpcId",
        "RpcUnreliable",
        "RpcUnreliableId",
        "CallGroup",
        "CallGroupFlags",
        "HasMethod",
        "Callable",
    }
)
# Parents under which a bare name is a value (passed, assigned, returned), not a call.
VALUE_PARENTS = frozenset(
    {
        Kind.ARGUMENT,
        Kind.ASSIGNMENT_EXPRESSION,
        Kind.RETURN_STATEMENT,
        Kind.ARROW_EXPRESSION_CLAUSE,
        Kind.VARIABLE_DECLARATOR,
        "initializer_expression",
        Kind.CONDITIONAL_EXPRESSION,
        Kind.PARENTHESIZED_EXPRESSION,
        Kind.COLLECTION_EXPRESSION,
    }
)
# Fields that hold a declaration's own name: not a use of it.
DECLARATION_PARENTS = frozenset(
    {
        Kind.CLASS_DECLARATION,
        Kind.STRUCT_DECLARATION,
        Kind.RECORD_DECLARATION,
        Kind.INTERFACE_DECLARATION,
        Kind.ENUM_DECLARATION,
        Kind.METHOD_DECLARATION,
        Kind.CONSTRUCTOR_DECLARATION,
        Kind.DESTRUCTOR_DECLARATION,
        Kind.LOCAL_FUNCTION_STATEMENT,
        Kind.DELEGATE_DECLARATION,
        Kind.PROPERTY_DECLARATION,
        Kind.ENUM_MEMBER_DECLARATION,
        Kind.VARIABLE_DECLARATOR,
        Kind.PARAMETER,
        Kind.NAMESPACE_DECLARATION,
        Kind.FILE_SCOPED_NAMESPACE_DECLARATION,
    }
)
JUDGED = frozenset(
    {
        Kind.METHOD_DECLARATION,
        Kind.LOCAL_FUNCTION_STATEMENT,
        *REGISTERED_BY_KIND,
    }
)
CLASSES = frozenset({Kind.CLASS_DECLARATION, Kind.RECORD_DECLARATION, Kind.STRUCT_DECLARATION})


def _modifiers(node: Node) -> frozenset[str]:
    return frozenset(node_text(c) for c in node.children if c.type == Kind.MODIFIER)


def _attributes(node: Node) -> list[str]:
    names: list[str] = []
    for attribute_list in node.named_children:
        if attribute_list.type != Kind.ATTRIBUTE_LIST:
            continue
        for attribute in attribute_list.named_children:
            name = attribute.child_by_field_name(Field.NAME)
            if name is not None:
                _qualifier, _dot, last = node_text(name).rpartition(".")
                names.append(last.removesuffix(ATTRIBUTE_SUFFIX))
    return names


def _registered(node: Node) -> str:
    """What reaches a declared method or class without a call ("" for nothing)."""
    if node.type in REGISTERED_BY_KIND:
        return REGISTERED_BY_KIND[node.type]
    for attribute in _attributes(node):
        if attribute in REGISTERING_ATTRIBUTES:
            return REGISTERING_ATTRIBUTES[attribute]
    if any(c.type == "explicit_interface_specifier" for c in node.named_children):
        return "interface implementation"
    modifiers = _modifiers(node)
    if OVERRIDE in modifiers:
        return OVERRIDE
    name = node.child_by_field_name(Field.NAME)
    if name is not None and node_text(name) == ENTRY_POINT and STATIC in modifiers:
        return "entry point"
    return ""


def _has_body(node: Node) -> bool:
    if node.type in CLASSES:
        return any(c.type == "base_list" for c in node.named_children)
    return node.child_by_field_name(Field.BODY) is not None or any(
        c.type in (Kind.BLOCK, Kind.ARROW_EXPRESSION_CLAUSE) for c in node.named_children
    )


def _is_callee(node: Node) -> bool:
    """``node`` is what an invocation calls (``M`` of ``M()``, ``x.M`` of ``x.M()``)."""
    parent = node.parent
    if parent is None or parent.type != Kind.INVOCATION_EXPRESSION:
        return False
    function = parent.child_by_field_name(Field.FUNCTION)
    return function is not None and function.id == node.id


def _declares(node: Node) -> bool:
    parent = node.parent
    if parent is None or parent.type not in DECLARATION_PARENTS:
        return False
    name = parent.child_by_field_name(Field.NAME)
    return name is not None and name.id == node.id


def _called_name(call: Node) -> str:
    """The simple name an invocation calls or a creation constructs (``Call``,
    ``Callable``); "" when the callee is not written as a name."""
    field = Field.TYPE if call.type == Kind.OBJECT_CREATION_EXPRESSION else Field.FUNCTION
    callee = call.child_by_field_name(field)
    if callee is None:
        return ""
    _receiver, _dot, last = node_text(callee).rpartition(".")
    return last.split("<", 1)[0]


class _Collector:
    def __init__(self, source: SourceText) -> None:
        self.source = source
        self.declared: list[DeclaredFunction] = []
        self.references: list[UsageReference] = []
        self.types: set[str] = set()

    def visit(self, node: Node, unit: tuple[int, int]) -> None:
        """``unit``: where the unit holding ``node`` starts."""
        if (node.type in JUDGED or node.type in CLASSES) and _has_body(node):
            span = node_span(self.source, node)
            self.declared.append(DeclaredFunction(span.line, span.column, _registered(node)))
        elif node.type == Kind.IDENTIFIER:
            self._identifier(node, unit)
        elif node.type == Kind.MEMBER_ACCESS_EXPRESSION and not _is_callee(node):
            name = node.child_by_field_name(Field.NAME)
            if name is not None:
                self._reference(unit, node_text(name).split("<", 1)[0], member=True)
        elif node.type in (Kind.INVOCATION_EXPRESSION, Kind.OBJECT_CREATION_EXPRESSION):
            self._string_names(node, unit)

    def _identifier(self, node: Node, unit: tuple[int, int]) -> None:
        text = node_text(node)
        if _declares(node):
            return
        parent = node.parent
        if text[:1].isupper():
            self.types.add(text)
            if parent is not None and parent.type == Kind.ATTRIBUTE:
                self.types.add(text + ATTRIBUTE_SUFFIX)  # [Preserve] names PreserveAttribute
        if parent is not None and parent.type in VALUE_PARENTS and not _is_callee(node):
            self._reference(unit, text, member=True)

    def _string_names(self, call: Node, unit: tuple[int, int]) -> None:
        """``Call("OnHit")``, ``new Callable(this, "OnHit")``: a string names a method."""
        if _called_name(call) not in METHOD_NAME_CALLS:
            return
        arguments = call.child_by_field_name(Field.ARGUMENTS)
        if arguments is None:
            return
        for argument in arguments.named_children:
            for value in argument.named_children:
                if value.type == Kind.STRING_LITERAL:
                    self._reference(unit, node_text(value).strip('"'), member=True)

    def _reference(self, unit: tuple[int, int], name: str, *, member: bool) -> None:
        line, column = unit
        self.references.append(UsageReference(line, column, name, member))


def collect_csharp_usage(source: SourceText, root: Node) -> UsageFacts:
    """References are recorded against the unit they are in, by where it starts."""
    collector = _Collector(source)
    stack: list[tuple[Node, tuple[int, int]]] = [(root, (1, 1))]
    while len(stack) > 0:
        node, unit = stack.pop()
        collector.visit(node, unit)
        holder = unit
        if is_unit(node):
            span = node_span(source, node)
            holder = (span.line, span.column)
        stack.extend((child, holder) for child in reversed(node.children))
    references = sorted(set(collector.references), key=lambda r: (r.line, r.column, r.name))
    return UsageFacts(
        declared=tuple(sorted(set(collector.declared), key=lambda d: (d.line, d.column))),
        references=tuple(references),
        handed=(),
        types=tuple(sorted(collector.types)),
    )
