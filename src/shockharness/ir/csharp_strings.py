"""String, sentinel and disguised-number facts for C# (milestone G3, part two).

* MAGIC002 reads every plain string literal with where it stands: an argument (with its
  callee), a subscript (``d["k"]``), a dictionary initializer key, a comparison (``==``,
  ``!=``, a ``case`` or switch-expression pattern, ``is "x"``), or a value. Interpolated
  strings with holes are not constants.
* MAGIC003 reads numeric literals assigned, returned, passed (``callee`` or
  ``callee=name`` for a named argument) or given as a dictionary entry. A field that is a
  named definition (``const``, ``static readonly``) already has its name.
* MAGIC005 reads numbers written as something else: ``"  ".Length``, ``int.Parse("30")``
  and the other numeric parses and ``Convert.To*``, and numbers inside a literal handed
  to a JSON or Variant parser (``Json.ParseString``, ``JsonSerializer.Deserialize``,
  ``GD.StrToVar``).
"""

from tree_sitter import Node

from shockharness.ir.csharp_functions import dotted_name, scope_for
from shockharness.ir.csharp_nodes import Field, Kind
from shockharness.ir.csharp_numbers import parse_csharp_number
from shockharness.ir.javascript_disguises import converted_number
from shockharness.ir.model import (
    DISGUISE_CONVERSION,
    DISGUISE_LENGTH,
    DISGUISE_PARSED,
    MODULE_SCOPE,
    SENTINEL_ARGUMENT,
    SENTINEL_ASSIGN,
    SENTINEL_ENTRY,
    SENTINEL_RETURN,
    STRING_ARGUMENT,
    STRING_COMPARE,
    STRING_KEY,
    STRING_SUBSCRIPT,
    STRING_VALUE,
    Disguise,
    SentinelUse,
    StringUse,
)
from shockharness.ir.python_disguises import TEXT_LIMIT, numbers_in
from shockharness.ir.tree_sitter_common import node_span, node_text
from shockharness.source import SourceText

PLAIN_STRINGS = frozenset(
    {Kind.STRING_LITERAL, Kind.VERBATIM_STRING_LITERAL, Kind.RAW_STRING_LITERAL}
)
NUMBERS = frozenset({Kind.INTEGER_LITERAL, Kind.REAL_LITERAL})
COMPARISONS = frozenset({"==", "!="})
PATTERN_PARENTS = frozenset(
    {Kind.CONSTANT_PATTERN, Kind.SWITCH_EXPRESSION_ARM, Kind.IS_PATTERN_EXPRESSION}
)
CALLS = frozenset({Kind.INVOCATION_EXPRESSION, Kind.OBJECT_CREATION_EXPRESSION})
LENGTH = "Length"
CONVERSIONS = frozenset(
    {
        "int.Parse",
        "long.Parse",
        "float.Parse",
        "double.Parse",
        "decimal.Parse",
        "short.Parse",
        "Convert.ToInt32",
        "Convert.ToInt64",
        "Convert.ToSingle",
        "Convert.ToDouble",
        "Convert.ToDecimal",
    }
)
PARSERS = frozenset(
    {
        "Json.ParseString",
        "JsonSerializer.Deserialize",
        "GD.StrToVar",
        "JsonConvert.DeserializeObject",
    }
)
NAMED_FIELD = frozenset({"const", "readonly"})
ENTRY_PARTS = 2  # a dictionary initializer entry: { key, value }


def literal_text(node: Node) -> str | None:
    """The text of a plain string literal (``"a"``, ``@"a"``, ``\"\"\"a\"\"\"``), or
    ``None``; an interpolated string with holes is not a constant."""
    if node.type == Kind.INTERPOLATED_STRING_EXPRESSION:
        if any(c.type == "interpolation" for c in node.named_children):
            return None
        return node_text(node).lstrip("$@").strip('"')
    if node.type not in PLAIN_STRINGS:
        return None
    text = node_text(node)
    return text.lstrip("@").strip('"')


def _value(node: Node) -> Node | None:
    values = [c for c in node.named_children if c.type != Kind.COMMENT]
    return values[0] if len(values) == 1 else None


def text_of(node: Node | None) -> str:
    """A node's text; nothing for a missing node (an absent field is not a value)."""
    if node is None:
        return ""
    return node_text(node)


def _callee(call: Node) -> str:
    if call.type == Kind.OBJECT_CREATION_EXPRESSION:
        return text_of(call.child_by_field_name(Field.TYPE))
    function = call.child_by_field_name(Field.FUNCTION)
    if function is None:
        return ""
    dotted = dotted_name(function)
    if dotted is None:
        return ""
    return dotted


def _argument_callee(argument: Node) -> str:
    """The callee of the call an argument belongs to (an attribute's name for an
    attribute argument)."""
    holder = argument.parent.parent if argument.parent is not None else None
    if holder is None:
        return ""
    if holder.type in CALLS:
        return _callee(holder)
    if holder.type == Kind.ATTRIBUTE:
        return text_of(holder.child_by_field_name(Field.NAME))
    return ""


def _string_position(node: Node) -> tuple[str, str]:
    """(kind, callee) of a string literal's place."""
    parent = node.parent
    if parent is None:
        return STRING_VALUE, ""
    if parent.type in (Kind.ARGUMENT, "attribute_argument"):
        grand = parent.parent
        if grand is not None and grand.type == "bracketed_argument_list":
            return STRING_SUBSCRIPT, ""
        return STRING_ARGUMENT, _argument_callee(parent)
    if _is_comparison(parent):
        return STRING_COMPARE, ""
    if _is_key(node, parent):
        return STRING_KEY, ""
    return STRING_VALUE, ""


def _is_comparison(parent: Node) -> bool:
    """``s == "x"``, ``case "x":``, ``"x" => ...``, ``s is "x"``."""
    if parent.type == Kind.BINARY_EXPRESSION:
        return text_of(parent.child_by_field_name(Field.OPERATOR)) in COMPARISONS
    return parent.type in PATTERN_PARENTS or parent.type == Kind.SWITCH_SECTION


def _is_key(node: Node, parent: Node) -> bool:
    """The key of ``{ "key", value }`` in a dictionary initializer."""
    if parent.type != "initializer_expression" or parent.parent is None:
        return False
    return parent.parent.type == "initializer_expression" and parent.named_children[0].id == node.id


def _folded_number(node: Node) -> tuple[float, Node] | None:
    """A numeric literal, a unary sign chain folded in: its value and the outer node."""
    negative = False
    current = node
    while current.type == Kind.PREFIX_UNARY_EXPRESSION and current.child_count > 0:
        sign = node_text(current.children[0])
        inner = _value(current)
        if sign not in ("-", "+") or inner is None:
            return None
        negative = negative != (sign == "-")
        current = inner
    if current.type not in NUMBERS:
        return None
    value = float(parse_csharp_number(node_text(current)))
    return (-value if negative else value), node


class _Collector:
    def __init__(self, source: SourceText) -> None:
        self.source = source
        self.strings: list[StringUse] = []
        self.sentinels: list[SentinelUse] = []
        self.disguises: list[Disguise] = []

    def visit(self, node: Node, scope: str) -> None:
        text = literal_text(node)
        if text is not None:
            kind, callee = _string_position(node)
            self.strings.append(StringUse(node_span(self.source, node), text, kind, callee))
        if node.type == Kind.RETURN_STATEMENT or node.type == Kind.ARROW_EXPRESSION_CLAUSE:
            self._sentinel(_value(node), SENTINEL_RETURN, "")
        elif node.type == Kind.ASSIGNMENT_EXPRESSION:
            target = text_of(node.child_by_field_name(Field.LEFT))
            self._sentinel(node.child_by_field_name(Field.RIGHT), SENTINEL_ASSIGN, target)
        elif node.type == Kind.VARIABLE_DECLARATOR and not _named_field(node):
            self._declarator(node)
        elif node.type == Kind.ARGUMENT:
            self._argument(node)
        elif node.type == "initializer_expression":
            self._entry(node)
        self._disguise(node, scope)

    def _declarator(self, declarator: Node) -> None:
        name = declarator.child_by_field_name(Field.NAME)
        values = [c for c in declarator.named_children if name is None or c.id != name.id]
        value = values[0] if len(values) == 1 else None
        self._sentinel(value, SENTINEL_ASSIGN, text_of(name))

    def _sentinel(self, node: Node | None, kind: str, target: str) -> None:
        if node is None:
            return
        folded = _folded_number(node)
        if folded is None:
            return
        value, outer = folded
        raw = node_text(outer)[:TEXT_LIMIT]
        self.sentinels.append(SentinelUse(node_span(self.source, outer), value, raw, kind, target))

    def _argument(self, argument: Node) -> None:
        holder = argument.parent.parent if argument.parent is not None else None
        if holder is None or holder.type not in CALLS:
            return
        callee = _callee(holder)
        named = argument.child_by_field_name(Field.NAME)
        target = callee
        if named is not None:
            target = f"{callee}={node_text(named)}"
        values = [c for c in argument.named_children if named is None or c.id != named.id]
        self._sentinel(
            values[len(values) - 1] if len(values) > 0 else None, SENTINEL_ARGUMENT, target
        )

    def _entry(self, node: Node) -> None:
        """``{ "key", -1 }`` inside a dictionary initializer."""
        parts = [c for c in node.named_children if c.type != Kind.COMMENT]
        parent = node.parent
        pair = len(parts) == ENTRY_PARTS
        if pair and parent is not None and parent.type == "initializer_expression":
            key, value = parts
            self._sentinel(value, SENTINEL_ENTRY, node_text(key))

    def _disguise(self, node: Node, scope: str) -> None:
        found: tuple[str, tuple[int | float, ...]] | None = None
        if node.type == Kind.MEMBER_ACCESS_EXPRESSION:
            found = _length(node)
        elif node.type == Kind.INVOCATION_EXPRESSION:
            found = _parsed(node)
        if found is not None:
            kind, values = found
            shown = node_text(node).replace("\n", " ")[:TEXT_LIMIT]
            self.disguises.append(
                Disguise(node_span(self.source, node), kind, values, shown, scope)
            )


def _named_field(declarator: Node) -> bool:
    """A declarator of a ``const`` or ``readonly`` field: a named definition."""
    declaration = declarator.parent
    field = declaration.parent if declaration is not None else None
    if field is None or field.type != Kind.FIELD_DECLARATION:
        return False
    modifiers = {node_text(c) for c in field.children if c.type == Kind.MODIFIER}
    return len(modifiers & NAMED_FIELD) > 0


def _length(member: Node) -> tuple[str, tuple[int | float, ...]] | None:
    """``"  ".Length`` of a whitespace literal."""
    name = member.child_by_field_name(Field.NAME)
    receiver = member.child_by_field_name(Field.EXPRESSION)
    if name is None or receiver is None or node_text(name) != LENGTH:
        return None
    text = literal_text(receiver)
    if text is None or text == "" or not text.isspace():
        return None
    return DISGUISE_LENGTH, (len(text),)


def _parsed(call: Node) -> tuple[str, tuple[int | float, ...]] | None:
    """``int.Parse("30")``, ``Convert.ToInt32("30")``, ``Json.ParseString("[2, 3]")``."""
    callee = _callee(call).split("<", 1)[0]
    arguments = call.child_by_field_name(Field.ARGUMENTS)
    first = (
        None
        if arguments is None or arguments.named_child_count == 0
        else _value(arguments.named_children[0])
    )
    text = None if first is None else literal_text(first)
    if text is None:
        return None
    if callee in CONVERSIONS:
        value = converted_number(text)
        return None if value is None else (DISGUISE_CONVERSION, (value,))
    if callee in PARSERS:
        numbers = numbers_in(text)
        return None if len(numbers) == 0 else (DISGUISE_PARSED, numbers)
    return None


def collect_csharp_strings(
    source: SourceText, root: Node
) -> tuple[tuple[StringUse, ...], tuple[SentinelUse, ...], tuple[Disguise, ...]]:
    collector = _Collector(source)
    stack: list[tuple[Node, str]] = [(root, MODULE_SCOPE)]
    while len(stack) > 0:
        node, scope = stack.pop()
        collector.visit(node, scope)
        inner = scope_for(node, scope)
        stack.extend((child, inner) for child in reversed(node.children))
    return (
        tuple(sorted(collector.strings, key=lambda s: s.span)),
        tuple(sorted(collector.sentinels, key=lambda s: s.span)),
        tuple(sorted(collector.disguises, key=lambda d: d.span)),
    )
