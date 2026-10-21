"""DOM002 facts (decision 32): elements attached to ``document.body``, and the selector
lists press handlers skip.

A page-level press handler that treats a press as "outside" (it leaves edit mode, it eats
the click that follows) skips the elements that handle their own presses through
``target.closest(<selectors>)``. A control the code attaches to ``document.body``
afterwards (a notice, a banner, an overlay) sits outside everything that list was
written for. Recorded per file:

* floating elements: ``document.body.append(x)`` (``appendChild``, ``prepend``,
  ``insertBefore``, ``insertAdjacentElement``), with the selectors the building function
  gives ``x`` (``x.id``, ``x.className``, ``x.classList.add``, ``setAttribute``), whether
  that function makes something pressable (a ``<button>``, ``role="button"``, a click or
  pointer listener), removes ``x`` again (a download link, a probe) or returns it (a
  container other modules fill);
* container fills: ``container().append(card)``, or through a local assigned from the call;
* selector lists: the ``closest(...)`` / ``matches(...)`` arguments of each function:
  strings, ``[...].join(",")``, and the names of constants used;
* module-level string constants (``const SHELL_SELECTOR = ".meta-shell"``).

Syntax only, vanilla DOM: jQuery (``$("body").append``) and frameworks that render into
portals are not seen.
"""

import re
from collections.abc import Iterator

from tree_sitter import Node

from shockharness.ir.javascript_catches import node_span, node_text
from shockharness.ir.javascript_functions import dotted_name, string_value
from shockharness.ir.javascript_nodes import Field, Kind
from shockharness.ir.javascript_positions import collect_javascript_positions
from shockharness.ir.model import (
    ContainerFill,
    DomFacts,
    FloatingElement,
    SelectorList,
    StringConstant,
)
from shockharness.source import SourceText

FUNCTIONS = frozenset(
    {
        Kind.FUNCTION_DECLARATION,
        Kind.GENERATOR_FUNCTION_DECLARATION,
        Kind.FUNCTION_EXPRESSION,
        Kind.FUNCTION,
        Kind.GENERATOR_FUNCTION,
        Kind.ARROW_FUNCTION,
        Kind.METHOD_DEFINITION,
    }
)
BODY = "document.body"
INSERTS = frozenset({"append", "appendChild", "prepend", "insertBefore", "replaceChildren"})
INSERT_ADJACENT = "insertAdjacentElement"
SELECTOR_METHODS = frozenset({"closest", "matches"})
JOIN = "join"
# Calls on an element that make it a helper the code uses and drops, not a control.
SELF_ACTIONS = frozenset({"remove", "click", "submit"})
# (property, value) assignments that make an element an input nobody sees (an element
# built hidden and shown later, a menu or a modal, is still a control).
HIDING = frozenset({("type", "file"), ("type", "hidden")})
REMOVE_CHILD = "removeChild"
PRESS_EVENTS = frozenset(
    {"click", "dblclick", "mousedown", "mouseup", "pointerdown", "pointerup", "touchstart"}
)
LISTEN = "addEventListener"
PRESS_PROPERTIES = frozenset({"onclick", "onmousedown", "onpointerdown"})
PRESSABLE_TAGS = frozenset({"button", "select", "input"})
CREATE_ELEMENT = "document.createElement"
JQUERY = "$"
# Markup that makes something pressable, in innerHTML / insertAdjacentHTML text.
PRESSABLE_MARKUP = re.compile(r"<button\b|role=[\"']button[\"']|\bonclick=", re.IGNORECASE)
ID_PROPERTY = "id"
CLASS_PROPERTY = "className"
CLASS_LIST_ADD = ("classList", "add")
SET_ATTRIBUTE = "setAttribute"
ATTRIBUTE_NAMES = {"id": "#", "class": "."}
CLASS_PREFIX = "."
ID_PREFIX = "#"
STATIC_TOKEN = re.compile(r"[A-Za-z_][\w-]*")
SUBSTITUTION = "${"


def _named(node: Node) -> list[Node]:
    return [child for child in node.named_children if child.type != Kind.COMMENT]


def _function_name(node: Node) -> str:
    """A function's name, or the variable, property or key it is assigned to."""
    name = node.child_by_field_name(Field.NAME)
    if name is not None:
        return node_text(name)
    parent = node.parent
    if parent is not None and parent.type == Kind.VARIABLE_DECLARATOR:
        declared = parent.child_by_field_name(Field.NAME)
        if declared is not None:
            return node_text(declared)
    if parent is not None and parent.type == Kind.PAIR:
        key = parent.child_by_field_name(Field.KEY)
        if key is not None:
            return node_text(key)
    return ""


def _scope_nodes(scope: Node) -> Iterator[Node]:
    """Every node of a function, nested functions included (their callbacks build the
    same element: ``button.addEventListener("click", () => ...)``)."""
    stack = list(reversed(_named(scope)))
    while len(stack) > 0:
        node = stack.pop()
        yield node
        stack.extend(reversed(_named(node)))


def _own_nodes(scope: Node) -> Iterator[Node]:
    """The nodes of a function, without its nested functions."""
    stack = list(reversed(_named(scope)))
    while len(stack) > 0:
        node = stack.pop()
        yield node
        if node.type not in FUNCTIONS:
            stack.extend(reversed(_named(node)))


def _member_call(node: Node) -> tuple[Node, str, list[Node]] | None:
    """(object, property, arguments) of ``object.property(...)``."""
    if node.type != Kind.CALL_EXPRESSION:
        return None
    function = node.child_by_field_name(Field.FUNCTION)
    arguments = node.child_by_field_name(Field.ARGUMENTS)
    if function is None or arguments is None or function.type != Kind.MEMBER_EXPRESSION:
        return None
    obj = function.child_by_field_name(Field.OBJECT)
    prop = function.child_by_field_name(Field.PROPERTY)
    if obj is None or prop is None:
        return None
    return obj, node_text(prop), _named(arguments)


def _texts(node: Node | None) -> list[str]:
    """The texts a string expression can have: a literal, a template (its static part
    when it has substitutions), both branches of a ternary."""
    if node is None:
        return []
    if node.type == Kind.TERNARY_EXPRESSION:
        return [
            *_texts(node.child_by_field_name(Field.CONSEQUENCE)),
            *_texts(node.child_by_field_name(Field.ALTERNATIVE)),
        ]
    if node.type == Kind.TEMPLATE_STRING:
        text = node_text(node)
        return [text[1 : len(text) - 1]]
    value = string_value(node)
    if value is None:
        return []
    return [value]


def _tokens(text: str) -> list[str]:
    """The whole words of a class list, without the parts a substitution builds."""
    return [
        word for word in text.split() if SUBSTITUTION not in word and STATIC_TOKEN.fullmatch(word)
    ]


def _assigned_names(node: Node, element: str) -> list[str]:
    """Selectors ``node`` gives ``element``: ``element.id = "a"``, ``element.className``."""
    if node.type != Kind.ASSIGNMENT_EXPRESSION:
        return []
    left = node.child_by_field_name(Field.LEFT)
    right = node.child_by_field_name(Field.RIGHT)
    if left is None or left.type != Kind.MEMBER_EXPRESSION:
        return []
    target = left.child_by_field_name(Field.OBJECT)
    prop = left.child_by_field_name(Field.PROPERTY)
    if target is None or prop is None or node_text(target) != element:
        return []
    if node_text(prop) == ID_PROPERTY:
        return [ID_PREFIX + word for text in _texts(right) for word in _tokens(text)]
    if node_text(prop) == CLASS_PROPERTY:
        return [CLASS_PREFIX + word for text in _texts(right) for word in _tokens(text)]
    return []


def _called_names(node: Node, element: str) -> list[str]:
    """``element.classList.add("a", "b")``, ``element.setAttribute("id", "a")``."""
    call = _member_call(node)
    if call is None:
        return []
    obj, prop, arguments = call
    if obj.type == Kind.MEMBER_EXPRESSION and (dotted_name(obj), prop) == (
        f"{element}.{CLASS_LIST_ADD[0]}",
        CLASS_LIST_ADD[1],
    ):
        return [CLASS_PREFIX + word for a in arguments for t in _texts(a) for word in _tokens(t)]
    if node_text(obj) != element or prop != SET_ATTRIBUTE or len(arguments) == 0:
        return []
    attribute = string_value(arguments[0])
    if attribute not in ATTRIBUTE_NAMES:
        return []
    prefix = ATTRIBUTE_NAMES[attribute]
    return [prefix + word for a in arguments[1:] for t in _texts(a) for word in _tokens(t)]


def _creation_tag(node: Node) -> str | None:
    """``document.createElement("tag")``: the tag."""
    if node.type != Kind.CALL_EXPRESSION:
        return None
    function = node.child_by_field_name(Field.FUNCTION)
    arguments = node.child_by_field_name(Field.ARGUMENTS)
    if function is None or arguments is None or dotted_name(function) != CREATE_ELEMENT:
        return None
    named = _named(arguments)
    if len(named) == 0:
        return None
    return string_value(named[0])


def _created_tag(node: Node, element: str) -> str | None:
    """``const element = document.createElement("tag")``: the tag."""
    if node.type != Kind.VARIABLE_DECLARATOR:
        return None
    name = node.child_by_field_name(Field.NAME)
    value = node.child_by_field_name(Field.VALUE)
    if name is None or value is None or node_text(name) != element:
        return None
    return _creation_tag(value)


def _assigned_property(node: Node) -> str | None:
    """``onclick`` of ``x.onclick = ...``."""
    if node.type != Kind.ASSIGNMENT_EXPRESSION:
        return None
    left = node.child_by_field_name(Field.LEFT)
    if left is None or left.type != Kind.MEMBER_EXPRESSION:
        return None
    prop = left.child_by_field_name(Field.PROPERTY)
    if prop is None:
        return None
    return node_text(prop)


def _pressable(node: Node) -> bool:
    """A node that makes something pressable: a click listener, ``onclick``, a created
    button, markup with a button."""
    call = _member_call(node)
    if call is not None:
        _obj, prop, arguments = call
        if prop == LISTEN and len(arguments) > 0 and string_value(arguments[0]) in PRESS_EVENTS:
            return True
    tag = _creation_tag(node)
    if tag is not None:
        return tag in PRESSABLE_TAGS
    if _assigned_property(node) in PRESS_PROPERTIES:
        return True
    if node.type in (Kind.STRING, Kind.TEMPLATE_STRING):
        return PRESSABLE_MARKUP.search(node_text(node)) is not None
    return False


def _helper(node: Node, element: str) -> bool:
    """``element`` is a helper, not a control: removed again (``element.remove()``,
    ``removeChild(element)``), activated by the code itself (``element.click()``,
    ``element.submit()``), or an input nobody sees (``type = "file"`` / ``"hidden"``)."""
    call = _member_call(node)
    if call is not None:
        obj, prop, arguments = call
        if node_text(obj) == element and prop in SELF_ACTIONS:
            return True
        return prop == REMOVE_CHILD and len(arguments) > 0 and node_text(arguments[0]) == element
    if node.type != Kind.ASSIGNMENT_EXPRESSION:
        return False
    left = node.child_by_field_name(Field.LEFT)
    right = node.child_by_field_name(Field.RIGHT)
    if left is None or right is None:
        return False
    return (node_text(left), node_text(right).strip("'\"`")) in {
        (f"{element}.{prop}", value) for prop, value in HIDING
    }


def _returns(node: Node, element: str) -> bool:
    if node.type != Kind.RETURN_STATEMENT:
        return False
    values = _named(node)
    return len(values) == 1 and node_text(values[0]) == element


class _Element:
    """What a function does to one local element."""

    def __init__(self, scope: Node, element: str) -> None:
        self.names: list[str] = []
        self.interactive = False
        self.transient = False
        self.returned = False
        for node in _scope_nodes(scope):
            self.names.extend(_assigned_names(node, element))
            self.names.extend(_called_names(node, element))
            tag = _created_tag(node, element)
            if tag is not None:
                self.names.append(tag)
            if _pressable(node) or tag in PRESSABLE_TAGS:
                self.interactive = True
            if _helper(node, element):
                self.transient = True
            if _returns(node, element):
                self.returned = True

    def selectors(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.names)))


def _enclosing(node: Node) -> Node | None:
    current = node.parent
    while current is not None and current.type not in FUNCTIONS:
        current = current.parent
    return current


def _declares(scope: Node, element: str) -> bool:
    return any(
        child.type == Kind.VARIABLE_DECLARATOR and _declared_name(child) == element
        for child in _own_nodes(scope)
    )


def _declared_name(declarator: Node) -> str | None:
    name = declarator.child_by_field_name(Field.NAME)
    if name is None:
        return None
    return node_text(name)


def _building_scope(node: Node, element: str) -> Node | None:
    """The innermost function that declares ``element`` (a callback may attach what its
    enclosing function built); the innermost function when none does."""
    innermost = _enclosing(node)
    current = innermost
    while current is not None:
        if _declares(current, element):
            return current
        current = _enclosing(current)
    return innermost


def _inserted(node: Node) -> tuple[Node, Node] | None:
    """(the container expression, the inserted element) of an insertion call."""
    call = _member_call(node)
    if call is None:
        return None
    obj, prop, arguments = call
    if prop in INSERTS and len(arguments) > 0:
        return obj, arguments[0]
    if prop == INSERT_ADJACENT and len(arguments) > 1:
        return obj, arguments[1]
    return None


def _container_callee(container: Node, scope: Node | None) -> str | None:
    """The plain function whose result ``container`` is: ``stack()`` or a local assigned
    from it (methods and lookups such as ``$(...)`` or ``.find(...)`` are not followed)."""
    if container.type == Kind.CALL_EXPRESSION:
        return _plain_callee(container)
    if container.type != Kind.IDENTIFIER or scope is None:
        return None
    for child in _own_nodes(scope):
        value = _declared_value(child, node_text(container))
        if value is not None and value.type == Kind.CALL_EXPRESSION:
            return _plain_callee(value)
    return None


def _declared_value(node: Node, name: str) -> Node | None:
    """The value of ``const name = <value>``."""
    if node.type != Kind.VARIABLE_DECLARATOR:
        return None
    declared = node.child_by_field_name(Field.NAME)
    if declared is None or node_text(declared) != name:
        return None
    return node.child_by_field_name(Field.VALUE)


def _insertion_fact(source: SourceText, node: Node) -> FloatingElement | ContainerFill | None:
    inserted = _inserted(node)
    if inserted is None:
        return None
    container, element = inserted
    if element.type != Kind.IDENTIFIER:
        return None
    name = node_text(element)
    scope = _building_scope(node, name)
    if scope is None:
        return None
    built = _Element(scope, name)
    if dotted_name(container) == BODY:
        return FloatingElement(
            span=node_span(source, node),
            function=_function_name(scope),
            names=built.selectors(),
            interactive=built.interactive,
            transient=built.transient,
            returned=built.returned,
        )
    callee = _container_callee(container, scope)
    if callee is None or not built.interactive:
        return None
    return ContainerFill(
        span=node_span(source, node), callee=callee, names=built.selectors(), interactive=True
    )


def _joined_array(node: Node) -> Node | None:
    """The array of ``[...].join(",")``."""
    call = _member_call(node)
    if call is None:
        return None
    array, method, _arguments = call
    if method != JOIN or array.type != Kind.ARRAY:
        return None
    return array


def _substituted(node: Node) -> list[str]:
    """The constants a template substitutes (`${SHELL_SELECTOR}, .note`)."""
    if node.type != Kind.TEMPLATE_STRING:
        return []
    return [
        node_text(inner)
        for child in _named(node)
        if child.type == Kind.TEMPLATE_SUBSTITUTION
        for inner in _named(child)
        if inner.type == Kind.IDENTIFIER
    ]


def _selector_parts(argument: Node) -> tuple[list[str], list[str]]:
    """(selector strings, constant names) of a closest / matches argument."""
    texts = _texts(argument)
    if len(texts) > 0:
        return texts, _substituted(argument)
    if argument.type == Kind.IDENTIFIER:
        return [], [node_text(argument)]
    joined = _joined_array(argument)
    if joined is None:
        return [], []
    selectors: list[str] = []
    constants: list[str] = []
    for element in _named(joined):
        if element.type == Kind.IDENTIFIER:
            constants.append(node_text(element))
        else:
            selectors.extend(_texts(element))
    return selectors, constants


def _plain_callee(node: Node) -> str | None:
    """The name of a plain function call (``isMenuTarget(target)``); jQuery's ``$`` is a
    lookup, not a function the project wrote."""
    if node.type != Kind.CALL_EXPRESSION:
        return None
    function = node.child_by_field_name(Field.FUNCTION)
    if function is None or function.type != Kind.IDENTIFIER or node_text(function) == JQUERY:
        return None
    return node_text(function)


def _selector_list(source: SourceText, scope: Node) -> SelectorList | None:
    selectors: list[str] = []
    constants: list[str] = []
    calls: list[str] = []
    for node in _own_nodes(scope):
        helper = _plain_callee(node)
        if helper is not None:
            calls.append(helper)
        call = _member_call(node)
        if call is None:
            continue
        _obj, method, arguments = call
        if method not in SELECTOR_METHODS or len(arguments) == 0:
            continue
        found, names = _selector_parts(arguments[0])
        selectors.extend(found)
        constants.extend(names)
    if len(selectors) == 0 and len(constants) == 0:
        return None
    return SelectorList(
        function=_function_name(scope),
        span=node_span(source, scope),
        selectors=tuple(selectors),
        constants=tuple(constants),
        calls=tuple(sorted(set(calls))),
    )


def _constant(declarator: Node) -> StringConstant | None:
    name = declarator.child_by_field_name(Field.NAME)
    value = declarator.child_by_field_name(Field.VALUE)
    if name is None or value is None or name.type != Kind.IDENTIFIER:
        return None
    texts = _texts(value)
    if len(texts) == 0 and value.type == Kind.ARRAY:
        texts = [text for element in _named(value) for text in _texts(element)]
    joined = _joined_array(value)
    if len(texts) == 0 and joined is not None:
        texts = [text for element in _named(joined) for text in _texts(element)]
    if len(texts) == 0:
        return None
    return StringConstant(node_text(name), tuple(texts))


def _constants(root: Node) -> list[StringConstant]:
    """``const NAME = "..."`` (or an array of strings) at the top of the module."""
    found: list[StringConstant] = []
    for statement in _named(root):
        declaration = statement
        if statement.type == Kind.EXPORT_STATEMENT:
            inner = statement.child_by_field_name(Field.DECLARATION)
            if inner is None:
                continue
            declaration = inner
        if declaration.type not in (Kind.LEXICAL_DECLARATION, Kind.VARIABLE_DECLARATION):
            continue
        for declarator in _named(declaration):
            constant = _constant(declarator)
            if constant is not None:
                found.append(constant)
    return found


def collect_javascript_floating(source: SourceText, root: Node) -> DomFacts:
    floating: list[FloatingElement] = []
    fills: list[ContainerFill] = []
    lists: list[SelectorList] = []
    stack: list[Node] = [root]
    while len(stack) > 0:
        node = stack.pop()
        stack.extend(node.named_children)
        fact = _insertion_fact(source, node)
        if isinstance(fact, FloatingElement):
            floating.append(fact)
        elif isinstance(fact, ContainerFill):
            fills.append(fact)
        if node.type in FUNCTIONS:
            selector_list = _selector_list(source, node)
            if selector_list is not None:
                lists.append(selector_list)
    return DomFacts(
        floating=tuple(sorted(floating, key=lambda f: f.span)),
        fills=tuple(sorted(fills, key=lambda f: f.span)),
        selector_lists=tuple(sorted(lists, key=lambda s: s.span)),
        constants=tuple(_constants(root)),
        positions=collect_javascript_positions(source, root),
    )
