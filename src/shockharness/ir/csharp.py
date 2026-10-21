"""C# adapter built on tree-sitter with the pinned C# grammar (milestone G1, Godot .NET).

tree-sitter recovers from syntax errors instead of raising. Any ``ERROR`` or ``MISSING``
node anywhere in the tree is a parse failure (spec section 3), as for JavaScript.

Two rewrites run before parsing. Each replaces characters with spaces and keeps every
newline, so every line and column of the source is unchanged:

* **Conditional compilation.** The grammar parses ``#if``/``#elif``/``#else``/``#endif`` as
  nodes, and fails when a directive splits a declaration (an attribute or a parameter
  list in two versions). The preprocessor keeps one branch, and so does the adapter: the
  ``#if`` branch of each conditional, with its directive lines and the other branches
  blanked. Godot's ``#if TOOLS`` code is therefore analyzed.
* **Lambda parameter modifiers**, only when the first parse fails. The released grammar
  does not accept ``(in T x) =>`` (fixed upstream, unreleased); the ``in``/``ref``/``out``
  modifier of such a parameter is blanked and the file parsed again. The modifier
  changes nothing the rules read.
"""

import re
from importlib import metadata

import tree_sitter_c_sharp
from tree_sitter import Language, Node, Parser

from shockharness.ir.csharp_catches import collect_csharp_catches
from shockharness.ir.csharp_defaults import collect_csharp_defaults
from shockharness.ir.csharp_functions import collect_csharp_functions, scope_for
from shockharness.ir.csharp_guardrails import collect_csharp_guardrails
from shockharness.ir.csharp_nodes import Field, Kind
from shockharness.ir.csharp_numbers import parse_csharp_number
from shockharness.ir.csharp_policy import collect_csharp_policy
from shockharness.ir.csharp_receivers import collect_csharp_receivers
from shockharness.ir.csharp_strings import collect_csharp_strings
from shockharness.ir.csharp_usage import collect_csharp_usage
from shockharness.ir.javascript_catches import node_span, node_text
from shockharness.ir.model import (
    MODULE_SCOPE,
    NO_ANNOTATIONS,
    NO_DATAFLOW,
    NO_DOM,
    NO_STUBS,
    NO_VERIFICATION,
    Comment,
    ConstantDefinition,
    ModuleFacts,
    NumericLiteral,
    failed_facts,
)
from shockharness.ir.tree_sitter_common import first_error, parse_failure
from shockharness.source import SourceText

_PARSER = Parser(Language(tree_sitter_c_sharp.language()))
PARSER_NAME = "tree-sitter-c-sharp " + metadata.version("tree-sitter-c-sharp")
CSHARP_LANGUAGE = "csharp"

LITERALS = frozenset({Kind.INTEGER_LITERAL, Kind.REAL_LITERAL})
SIGN_OPERATORS = frozenset({"-", "+"})
# Literal arithmetic accepted in a named definition: as in Python and JavaScript, plus the
# shift that builds flag values (`A = 1 << 3` in a [Flags] enum).
CONSTANT_OPERATORS = frozenset({"+", "-", "*", "/", "%", "<<"})
CONST_MODIFIER = "const"
STATIC_MODIFIER = "static"
READONLY_MODIFIER = "readonly"
# Godot's built-in value types: a `static readonly` field or an [Export] member built from
# literals of one of these (`new Vector2(64, 32)`, `new(1, 0.5f, 0)`) is a named
# definition, since C# cannot declare them `const` (spec 21.1 decision 40).
VALUE_TYPES = frozenset(
    {
        "Vector2",
        "Vector2I",
        "Vector3",
        "Vector3I",
        "Vector4",
        "Vector4I",
        "Color",
        "Rect2",
        "Rect2I",
        "Quaternion",
        "Plane",
    }
)
EXPORT_ATTRIBUTES = frozenset({"Export", "ExportAttribute", "Godot.Export"})

_DIRECTIVE = re.compile(r"[ \t]*#[ \t]*(?P<keyword>if|elif|else|endif)\b")
# A lambda's explicit parameter list (no nested parentheses) directly followed by `=>`, and
# a parameter modifier at the start of one of its parameters.
_LAMBDA_PARAMETERS = re.compile(r"\((?P<parameters>[^()]*)\)(?=\s*=>)")
_PARAMETER_MODIFIER = re.compile(r"(?:(?<=^)|(?<=,))(?P<space>\s*)(?P<modifier>in|ref|out)(?=\s)")


def _blank(text: str) -> str:
    return re.sub(r"[^\n]", " ", text)


def keep_first_branches(text: str) -> str:
    """The source with every conditional-compilation directive line blanked, and the lines
    of every ``#elif``/``#else`` branch blanked: what the compiler sees when each ``#if``
    condition holds. Unbalanced directives are left to the parser."""
    lines = text.split("\n")
    skipping: list[bool] = []
    for index, line in enumerate(lines):
        match = _DIRECTIVE.match(line)
        if match is None:
            if any(skipping):
                lines[index] = _blank(line)
            continue
        keyword = match.group("keyword")
        if keyword == "if":
            skipping.append(False)
        elif len(skipping) == 0:
            continue
        elif keyword == "endif":
            skipping.pop()
        else:
            skipping[len(skipping) - 1] = True
        lines[index] = _blank(line)
    return "\n".join(lines)


def _blank_modifiers(parameters: re.Match[str]) -> str:
    inner = _PARAMETER_MODIFIER.sub(
        lambda m: m.group("space") + _blank(m.group("modifier")), parameters.group("parameters")
    )
    return "(" + inner + ")"


def blank_lambda_modifiers(text: str) -> str:
    """``(in T x, ref U y) => ...`` with the modifiers blanked; calls are untouched."""
    return _LAMBDA_PARAMETERS.sub(_blank_modifiers, text)


def _parse(text: str) -> Node:
    return _PARSER.parse(text.encode("utf-8")).root_node


def parse_csharp(text: str) -> tuple[Node, Node | None]:
    """The tree of a C# source after the two rewrites, and its first error node."""
    prepared = keep_first_branches(text)
    root = _parse(prepared)
    error = first_error(root)
    if error is None:
        return root, None
    retried = _parse(blank_lambda_modifiers(prepared))
    retried_error = first_error(retried)
    if retried_error is None:
        return retried, None
    return root, error


def extract_csharp_facts(source: SourceText, filename: str) -> ModuleFacts:
    """The facts of a C# file: numbers and named definitions, comments, function facts
    (G1); catches, defaults, discarded calls, Boolean arguments and placeholders (G2). The
    other families have no C# facts yet; their rules do not list C# among their languages,
    so they never run on these files (the report lists them as not applicable)."""
    root, error = parse_csharp(source.text)
    if error is not None:
        return failed_facts(CSHARP_LANGUAGE, PARSER_NAME, parse_failure(source, filename, error))
    literals, constants, comments = _number_facts(source, root)
    booleans, asynchrony = collect_csharp_guardrails(source, root)
    bindings, guardrails, catalog, imports = collect_csharp_policy(source, root, booleans)
    strings, sentinels, disguises = collect_csharp_strings(source, root)
    return ModuleFacts(
        language=CSHARP_LANGUAGE,
        parser=PARSER_NAME,
        numeric_literals=literals,
        constants=constants,
        comments=comments,
        catches=collect_csharp_catches(source, root),
        managers=(),  # C# has no exception-capturing using idiom
        defaults=collect_csharp_defaults(source, root),
        functions=collect_csharp_functions(source, root, comments),
        imports=imports,
        bindings=bindings,
        verification=NO_VERIFICATION,
        guardrails=guardrails,
        asynchrony=asynchrony,
        catalog=catalog,
        dataflow=NO_DATAFLOW,
        sentinels=sentinels,
        strings=strings,
        dom=NO_DOM,
        receivers=collect_csharp_receivers(root),
        disguises=disguises,
        annotations=NO_ANNOTATIONS,
        usage=collect_csharp_usage(source, root),
        shapes=(),
        stubs=NO_STUBS,
        parse_failure=None,
    )


def _number_facts(
    source: SourceText, root: Node
) -> tuple[tuple[NumericLiteral, ...], tuple[ConstantDefinition, ...], tuple[Comment, ...]]:
    """The numeric literals (marked when a named definition holds them), the named
    definitions, and the comments."""
    definitions = _definitions(root)
    literals, comments = _literals_and_comments(source, root, _definition_literals(definitions))
    constants = tuple(
        ConstantDefinition(name=node_text(name), span=node_span(source, name))
        for name, _value in definitions
    )
    return literals, constants, comments


# -- literals ---------------------------------------------------------------------------


def _unary_operator(node: Node) -> str | None:
    if node.type != Kind.PREFIX_UNARY_EXPRESSION or node.child_count == 0:
        return None
    return node_text(node.children[0])


def _fold_unary(node: Node) -> tuple[Node, bool] | None:
    """A chain of unary ``+``/``-`` over a numeric literal: the literal and its sign."""
    negative = False
    current = node
    while current.type == Kind.PREFIX_UNARY_EXPRESSION:
        operator = _unary_operator(current)
        operands = current.named_children
        if operator not in SIGN_OPERATORS or len(operands) != 1:
            return None
        if operator == "-":
            negative = not negative
        current = operands[0]
    if current is node or current.type not in LITERALS:
        return None
    return current, negative


def _literals_and_comments(
    source: SourceText, root: Node, definitions: set[int]
) -> tuple[tuple[NumericLiteral, ...], tuple[Comment, ...]]:
    """Every numeric literal (a unary sign chain folded into one) and every comment."""
    literals: list[NumericLiteral] = []
    comments: list[Comment] = []
    stack: list[tuple[Node, str]] = [(root, MODULE_SCOPE)]
    while len(stack) > 0:
        node, scope = stack.pop()
        if node.type == Kind.COMMENT:
            comments.append(Comment(span=node_span(source, node), text=node_text(node)))
            continue
        literal = _literal(source, node, scope, definition=node.id in definitions)
        if literal is not None:
            literals.append(literal)
            continue
        child_scope = scope_for(node, scope)
        for child in reversed(node.children):
            stack.append((child, child_scope))
    literals.sort(key=lambda lit: lit.span)
    comments.sort(key=lambda comment: comment.span)
    return tuple(literals), tuple(comments)


def _literal(
    source: SourceText, node: Node, scope: str, *, definition: bool
) -> NumericLiteral | None:
    """The literal ``node`` is: a numeric literal, or a unary sign chain over one."""
    folded = _fold_unary(node)
    if folded is not None:
        number, negated = folded
    elif node.type in LITERALS:
        number, negated = node, False
    else:
        return None
    value = parse_csharp_number(node_text(number))
    return NumericLiteral(
        span=node_span(source, node),
        raw=node_text(node),
        value=-value if negated else value,
        negated=negated,
        in_annotation=False,
        scope=scope,
        constant_definition=definition,
    )


# -- named definitions ---------------------------------------------------------------------


def _modifiers(node: Node) -> frozenset[str]:
    return frozenset(node_text(c) for c in node.children if c.type == Kind.MODIFIER)


def _attribute_names(node: Node) -> frozenset[str]:
    names: set[str] = set()
    for attribute_list in node.children:
        if attribute_list.type != Kind.ATTRIBUTE_LIST:
            continue
        for attribute in attribute_list.named_children:
            name = attribute.child_by_field_name(Field.NAME)
            if attribute.type == Kind.ATTRIBUTE and name is not None:
                names.add(node_text(name))
    return frozenset(names)


def _type_name(node: Node | None) -> str | None:
    if node is None:
        return None
    if node.type == Kind.IDENTIFIER:
        return node_text(node)
    if node.type == Kind.QUALIFIED_NAME:
        _qualifier, _dot, last = node_text(node).rpartition(".")
        return last
    return None


def _arithmetic_operands(node: Node) -> list[Node] | None:
    """The operands of a node accepted in literal arithmetic (none for a literal), or
    ``None`` when the node disqualifies the expression."""
    if node.type in LITERALS:
        return []
    operands = [c for c in node.named_children if c.type != Kind.COMMENT]
    if node.type == Kind.PREFIX_UNARY_EXPRESSION:
        accepted = _unary_operator(node) in SIGN_OPERATORS
    elif node.type == Kind.PARENTHESIZED_EXPRESSION:
        accepted = len(operands) == 1
    elif node.type == Kind.BINARY_EXPRESSION:
        operator = node.child_by_field_name(Field.OPERATOR)
        accepted = operator is not None and node_text(operator) in CONSTANT_OPERATORS
    else:
        accepted = False
    return operands if accepted else None


def _is_literal_arithmetic(value: Node) -> bool:
    """The whole expression is numeric literals, unary ``+``/``-``, parentheses and the
    binary operators of :data:`CONSTANT_OPERATORS`."""
    stack = [value]
    while len(stack) > 0:
        operands = _arithmetic_operands(stack.pop())
        if operands is None:
            return False
        stack.extend(operands)
    return True


def _constructed_type(value: Node, declared_type: str | None) -> str | None:
    """The type ``new T(...)`` builds, or the declared type for a target-typed ``new(...)``."""
    if value.type == Kind.OBJECT_CREATION_EXPRESSION:
        return _type_name(value.child_by_field_name(Field.TYPE))
    if value.type == Kind.IMPLICIT_OBJECT_CREATION_EXPRESSION:
        return declared_type
    return None


def _is_value_construction(value: Node, declared_type: str | None) -> bool:
    """``new Vector2(64, 32)`` or ``new(64, 32)`` of a Godot value type, every argument
    literal arithmetic, and no object initializer."""
    if _constructed_type(value, declared_type) not in VALUE_TYPES:
        return False
    if any(c.type == Kind.INITIALIZER_EXPRESSION for c in value.named_children):
        return False
    arguments = [c for c in value.named_children if c.type == Kind.ARGUMENT_LIST]
    if len(arguments) != 1:
        return False
    return all(_is_literal_argument(argument) for argument in arguments[0].named_children)


def _is_literal_argument(argument: Node) -> bool:
    operands = [c for c in argument.named_children if c.type != Kind.COMMENT]
    return (
        argument.type == Kind.ARGUMENT
        and len(operands) == 1
        and _is_literal_arithmetic(operands[0])
    )


def _declarator_value(declarator: Node) -> Node | None:
    """The initializer of ``Name = value`` in a variable declarator (an unnamed child)."""
    name = declarator.child_by_field_name(Field.NAME)
    values = [
        c
        for c in declarator.named_children
        if c.type != Kind.COMMENT and (name is None or c.id != name.id)
    ]
    return values[0] if len(values) == 1 else None


def _field_definitions(field: Node) -> list[tuple[Node, Node]]:
    """``const`` fields (literal arithmetic), and ``static readonly`` or ``[Export]`` fields
    whose value is literal arithmetic or a Godot value type built from it."""
    modifiers = _modifiers(field)
    constant = CONST_MODIFIER in modifiers
    named = constant or {STATIC_MODIFIER, READONLY_MODIFIER} <= modifiers
    if not named and len(_attribute_names(field) & EXPORT_ATTRIBUTES) == 0:
        return []
    found: list[tuple[Node, Node]] = []
    for declaration in field.named_children:
        if declaration.type == Kind.VARIABLE_DECLARATION:
            found.extend(_declaration_definitions(declaration, constant))
    return found


def _declaration_definitions(declaration: Node, constant: bool) -> list[tuple[Node, Node]]:
    declared = _type_name(declaration.child_by_field_name(Field.TYPE))
    found: list[tuple[Node, Node]] = []
    for declarator in declaration.named_children:
        if declarator.type != Kind.VARIABLE_DECLARATOR:
            continue
        name = declarator.child_by_field_name(Field.NAME)
        value = _declarator_value(declarator)
        if name is None or value is None:
            continue
        if _is_literal_arithmetic(value) or (
            not constant and _is_value_construction(value, declared)
        ):
            found.append((name, value))
    return found


def _property_definition(prop: Node) -> list[tuple[Node, Node]]:
    """The initializer of an ``[Export]`` auto-property (``= 300f;``): the editor is
    where the value is configured (spec 21.1 decision 40)."""
    if len(_attribute_names(prop) & EXPORT_ATTRIBUTES) == 0:
        return []
    name = prop.child_by_field_name(Field.NAME)
    value = prop.child_by_field_name(Field.VALUE)
    if name is None or value is None or value.type == Kind.ARROW_EXPRESSION_CLAUSE:
        return []
    declared = _type_name(prop.child_by_field_name(Field.TYPE))
    if _is_literal_arithmetic(value) or _is_value_construction(value, declared):
        return [(name, value)]
    return []


def _enum_definition(member: Node) -> list[tuple[Node, Node]]:
    name = member.child_by_field_name(Field.NAME)
    value = member.child_by_field_name(Field.VALUE)
    if name is None or value is None or not _is_literal_arithmetic(value):
        return []
    return [(name, value)]


def _definitions(root: Node) -> list[tuple[Node, Node]]:
    """(name, value) of every named definition in the file, in source order."""
    found: list[tuple[Node, Node]] = []
    stack = [root]
    while len(stack) > 0:
        node = stack.pop()
        if node.type == Kind.FIELD_DECLARATION:
            found.extend(_field_definitions(node))
        elif node.type == Kind.PROPERTY_DECLARATION:
            found.extend(_property_definition(node))
        elif node.type == Kind.ENUM_MEMBER_DECLARATION:
            found.extend(_enum_definition(node))
        stack.extend(reversed(node.named_children))
    found.sort(key=lambda pair: pair[0].start_byte)
    return found


def _definition_literals(definitions: list[tuple[Node, Node]]) -> set[int]:
    """Ids of every literal node of the definitions' values, as the literal collector
    records them: a unary sign chain over a literal is one node."""
    ids: set[int] = set()
    stack = [value for _name, value in definitions]
    while len(stack) > 0:
        node = stack.pop()
        if node.type in LITERALS or _fold_unary(node) is not None:
            ids.add(node.id)
            continue
        stack.extend(c for c in node.named_children if c.type != Kind.COMMENT)
    return ids
