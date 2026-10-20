"""Default and fallback facts for C# (milestone G2), the shapes DEF001-DEF006 judge.

* DEF001: an optional parameter (``void Hit(int damage = 10)``). A parameter the compiler
  fills (``[CallerMemberName] string name = ""``) is not a fallback and is skipped.
* DEF002: ``GetValueOrDefault(k, v)``, a LINQ ``FirstOrDefault``-family call, Godot's
  ``GetMeta(name, v)``, and the membership ternaries ``m.TryGetValue(k, out var x) ? x : v``
  and ``m.ContainsKey(k) ? m[k] : v``.
* DEF003: ``string.IsNullOrEmpty(s) ? v : s`` (C# has no truthiness otherwise).
* DEF004: ``x ?? v``, ``x ??= v`` and ``x == null ? v : x`` in its four spellings; a
  ``??`` whose right side throws (``x ?? throw new ...``) is a guard, not a fallback.
* DEF006: ``Environment.GetEnvironmentVariable("X") ?? v`` and the variable read alone,
  Godot's ``OS.GetEnvironment("X")``, ``ProjectSettings.GetSetting(name, v)`` and a
  three-argument ``GetValue(section, key, v)`` (``ConfigFile``, settings and save files).

DEF005's literal returns come from the catch facts, as in the other languages.
"""

from tree_sitter import Node

from shockharness.ir.csharp_catches import is_literal_like
from shockharness.ir.csharp_functions import scope_for
from shockharness.ir.csharp_nodes import Field, Kind
from shockharness.ir.javascript_catches import node_span, node_text
from shockharness.ir.model import (
    CONFIDENCE_APPROXIMATE,
    CONFIDENCE_EXACT,
    CONTEXT_ARGUMENT,
    CONTEXT_ASSIGNMENT,
    CONTEXT_DECLARATION,
    CONTEXT_EXPRESSION,
    CONTEXT_RETURN,
    CONTEXT_TEST,
    FAMILY_CONFIGURATION,
    FAMILY_MAPPING,
    FAMILY_NULLISH,
    FAMILY_PARAMETER,
    FAMILY_TRUTHINESS,
    KIND_ENV_GET_IMPLICIT,
    KIND_ENV_NULLISH,
    KIND_MAPPING_GET,
    KIND_MAPPING_GET_IMPLICIT,
    KIND_MEMBER_NULLISH,
    KIND_MEMBERSHIP_TERNARY,
    KIND_NULLISH_ASSIGN,
    KIND_NULLISH_COALESCE,
    KIND_NULLISH_TERNARY,
    KIND_PARAMETER,
    KIND_SETTING_GET,
    KIND_TRUTHINESS_TERNARY,
    MODULE_SCOPE,
    DefaultFact,
)
from shockharness.ir.tree_sitter_common import collapsed_text as _text
from shockharness.ir.tree_sitter_common import unwrap_parentheses as _unwrap
from shockharness.source import SourceText

ELLIPSIS_TEXT = "..."
COALESCE = "??"
COALESCE_ASSIGN = "??="
EQUALS = "=="
NOT_EQUALS = "!="
CALLER_ATTRIBUTES = frozenset(
    {
        "CallerMemberName",
        "CallerFilePath",
        "CallerLineNumber",
        "CallerArgumentExpression",
    }
)
EMPTINESS_TESTS = frozenset(
    {
        "string.IsNullOrEmpty",
        "string.IsNullOrWhiteSpace",
        "String.IsNullOrEmpty",
        "String.IsNullOrWhiteSpace",
    }
)
OR_DEFAULT_METHODS = frozenset(
    {"FirstOrDefault", "LastOrDefault", "SingleOrDefault", "ElementAtOrDefault", "DefaultIfEmpty"}
)
GET_VALUE_OR_DEFAULT = "GetValueOrDefault"
GET_META = "GetMeta"
TRY_GET_VALUE = "TryGetValue"
CONTAINS_KEY = "ContainsKey"
ENVIRONMENT_READS = frozenset(
    {"Environment.GetEnvironmentVariable", "System.Environment.GetEnvironmentVariable"}
)
GODOT_ENVIRONMENT = "OS.GetEnvironment"
GODOT_SETTING = "ProjectSettings.GetSetting"
GET_VALUE = "GetValue"
# GetSetting(name, default) and ConfigFile.GetValue(section, key, default).
SETTING_ARGUMENTS = 2
CONFIG_VALUE_ARGUMENTS = 3
MEMBER_TYPES = frozenset(
    {
        Kind.MEMBER_ACCESS_EXPRESSION,
        Kind.CONDITIONAL_ACCESS_EXPRESSION,
        Kind.ELEMENT_ACCESS_EXPRESSION,
        Kind.INVOCATION_EXPRESSION,
    }
)
LAMBDAS = frozenset({Kind.LAMBDA_EXPRESSION, Kind.ANONYMOUS_METHOD_EXPRESSION})
CONDITION_PARENTS = frozenset(
    {Kind.IF_STATEMENT, Kind.WHILE_STATEMENT, Kind.DO_STATEMENT, Kind.FOR_STATEMENT}
)
COMPARISONS = frozenset({"==", "!=", "<", ">", "<=", ">=", "&&", "||"})
# Parents through which an expression keeps its context (`return (a ?? b);`).
INHERITING_PARENTS = frozenset({Kind.PARENTHESIZED_EXPRESSION, Kind.AWAIT_EXPRESSION})


def _operator(node: Node) -> str:
    operator = node.child_by_field_name(Field.OPERATOR)
    if operator is None:
        return ""
    return node_text(operator)


def is_constant_shaped(node: Node | None) -> bool:
    """Literal-like, or a static member of a type (``Vector2.Zero``, ``Colors.White``)."""
    if node is None:
        return True
    inner = _unwrap(node)
    if is_literal_like(inner):
        return True
    if inner.type != Kind.MEMBER_ACCESS_EXPRESSION:
        return False
    owner = inner.child_by_field_name(Field.EXPRESSION)
    return owner is not None and owner.type == Kind.IDENTIFIER and node_text(owner)[:1].isupper()


def _callee(call: Node) -> tuple[str, str, Node | None]:
    """(callee as written, method name, receiver) of an invocation."""
    function = call.child_by_field_name(Field.FUNCTION)
    if function is None:
        return "", "", None
    written = node_text(function)
    if function.type == Kind.MEMBER_ACCESS_EXPRESSION:
        name = function.child_by_field_name(Field.NAME)
        receiver = function.child_by_field_name(Field.EXPRESSION)
        if name is None:
            return written, "", receiver
        return written, node_text(name).split("<", 1)[0], receiver
    return written, written.split("<", 1)[0], None


def _arguments(call: Node) -> list[Node]:
    """The argument expressions of an invocation, in order."""
    arguments = call.child_by_field_name(Field.ARGUMENTS)
    if arguments is None:
        return []
    values: list[Node] = []
    for argument in arguments.named_children:
        if argument.type != Kind.ARGUMENT:
            continue
        inner = [c for c in argument.named_children if c.type != Kind.COMMENT]
        if len(inner) > 0:
            values.append(inner[len(inner) - 1])
    return values


def _string_value(node: Node) -> str:
    """``"X"`` -> ``X``; anything else as written."""
    if node.type == Kind.STRING_LITERAL:
        return node_text(node).strip('"')
    return _text(node)


class _Collector:
    def __init__(self, source: SourceText) -> None:
        self.source = source
        self.facts: list[DefaultFact] = []

    def _add(
        self,
        node: Node,
        scope: str,
        family_kind: tuple[str, str],
        subject: str,
        fallback: Node | None,
        context: str,
        confidence: str,
        detail: str,
    ) -> None:
        family, kind = family_kind
        self.facts.append(
            DefaultFact(
                span=node_span(self.source, node),
                scope=scope,
                family=family,
                kind=kind,
                subject=subject,
                fallback=_fallback_text(fallback),
                fallback_constant=is_constant_shaped(fallback),
                context=context,
                confidence=confidence,
                detail=detail,
            )
        )

    def visit(self, node: Node, scope: str, context: str) -> None:
        kind = node.type
        if kind == Kind.PARAMETER:
            self._parameter(node, scope)
        elif kind == Kind.BINARY_EXPRESSION and _operator(node) == COALESCE:
            self._coalesce(node, scope, context)
        elif kind == Kind.ASSIGNMENT_EXPRESSION and _operator(node) == COALESCE_ASSIGN:
            self._coalesce_assign(node, scope)
        elif kind == Kind.CONDITIONAL_EXPRESSION:
            self._ternary(node, scope, context)
        elif kind == Kind.INVOCATION_EXPRESSION and context != CONTEXT_TEST:
            self._call(node, scope, context)

    # -- DEF001 -------------------------------------------------------------------------

    def _parameter(self, parameter: Node, scope: str) -> None:
        name = parameter.child_by_field_name(Field.NAME)
        if name is None:
            return
        after = [
            c
            for c in parameter.named_children
            if c.start_byte > name.end_byte and c.type != Kind.COMMENT
        ]
        if len(after) != 1 or _filled_by_compiler(parameter):
            return
        _owner_scope, _dot, owner = scope.rpartition(".")
        self._add(
            after[0],
            scope,
            (FAMILY_PARAMETER, KIND_PARAMETER),
            node_text(name),
            after[0],
            CONTEXT_DECLARATION,
            CONFIDENCE_EXACT,
            f"parameter {node_text(name)!r} of {owner} has a default value",
        )

    # -- DEF004 and DEF006 through ?? -------------------------------------------------------

    def _coalesce(self, node: Node, scope: str, context: str) -> None:
        left = node.child_by_field_name(Field.LEFT)
        right = node.child_by_field_name(Field.RIGHT)
        if left is None or right is None or _unwrap(right).type == Kind.THROW_EXPRESSION:
            return
        if context == CONTEXT_TEST:
            return
        variable = _environment_variable(_unwrap(left))
        if variable is not None:
            self._add(
                node,
                scope,
                (FAMILY_CONFIGURATION, KIND_ENV_NULLISH),
                variable,
                right,
                context,
                CONFIDENCE_EXACT,
                f"'??' substitutes a fallback when environment variable {variable} is unset",
            )
            return
        family_kind = (FAMILY_NULLISH, KIND_NULLISH_COALESCE)
        detail = "'??' substitutes a fallback when the left operand is null"
        if _unwrap(left).type in MEMBER_TYPES:
            family_kind = (FAMILY_MAPPING, KIND_MEMBER_NULLISH)
            detail = "'??' substitutes a fallback when the member, element or call result is null"
        self._add(node, scope, family_kind, _text(left), right, context, CONFIDENCE_EXACT, detail)

    def _coalesce_assign(self, node: Node, scope: str) -> None:
        left = node.child_by_field_name(Field.LEFT)
        right = node.child_by_field_name(Field.RIGHT)
        if left is None or right is None or _unwrap(right).type == Kind.THROW_EXPRESSION:
            return
        self._add(
            node,
            scope,
            (FAMILY_NULLISH, KIND_NULLISH_ASSIGN),
            _text(left),
            right,
            CONTEXT_ASSIGNMENT,
            CONFIDENCE_EXACT,
            "'??=' assigns a fallback when the target is null",
        )

    # -- ternaries ------------------------------------------------------------------------

    def _ternary(self, node: Node, scope: str, context: str) -> None:
        condition = node.child_by_field_name(Field.CONDITION)
        consequence = node.child_by_field_name(Field.CONSEQUENCE)
        alternative = node.child_by_field_name(Field.ALTERNATIVE)
        if condition is None or consequence is None or alternative is None:
            return
        test = _unwrap(condition)
        null_test = _null_test(test)
        if null_test is not None:
            subject, is_null = null_test
            kept, fallback = (alternative, consequence) if is_null else (consequence, alternative)
            if node_text(_unwrap(kept)) == node_text(subject):
                self._add(
                    node,
                    scope,
                    (FAMILY_NULLISH, KIND_NULLISH_TERNARY),
                    _text(subject),
                    fallback,
                    context,
                    CONFIDENCE_EXACT,
                    "a conditional on null substitutes a fallback when the subject is null",
                )
            return
        self._emptiness_ternary(node, scope, context, (test, consequence, alternative))
        self._membership_ternary(node, scope, context, (test, consequence, alternative))

    def _emptiness_ternary(
        self, node: Node, scope: str, context: str, parts: tuple[Node, Node, Node]
    ) -> None:
        """``string.IsNullOrEmpty(s) ? v : s`` and ``!string.IsNullOrEmpty(s) ? s : v``."""
        test, consequence, alternative = parts
        negated = test.type == Kind.PREFIX_UNARY_EXPRESSION and node_text(test).startswith("!")
        call = _unwrap(test.named_children[0]) if negated and test.named_child_count == 1 else test
        if call.type != Kind.INVOCATION_EXPRESSION or _callee(call)[0] not in EMPTINESS_TESTS:
            return
        arguments = _arguments(call)
        if len(arguments) != 1:
            return
        kept, fallback = (consequence, alternative) if negated else (alternative, consequence)
        if node_text(_unwrap(kept)) != node_text(arguments[0]):
            return
        self._add(
            node,
            scope,
            (FAMILY_TRUTHINESS, KIND_TRUTHINESS_TERNARY),
            _text(arguments[0]),
            fallback,
            context,
            CONFIDENCE_EXACT,
            "a conditional on string.IsNullOrEmpty substitutes a fallback for a null and an "
            "empty string alike",
        )

    def _membership_ternary(
        self, node: Node, scope: str, context: str, parts: tuple[Node, Node, Node]
    ) -> None:
        """``m.TryGetValue(k, out var x) ? x : v`` and ``m.ContainsKey(k) ? m[k] : v``."""
        test, _consequence, alternative = parts
        if test.type != Kind.INVOCATION_EXPRESSION:
            return
        _written, method, receiver = _callee(test)
        arguments = _arguments(test)
        if method not in (TRY_GET_VALUE, CONTAINS_KEY) or receiver is None or len(arguments) == 0:
            return
        self._add(
            node,
            scope,
            (FAMILY_MAPPING, KIND_MEMBERSHIP_TERNARY),
            f"{_text(receiver)}[{_text(arguments[0])}]",
            alternative,
            context,
            CONFIDENCE_EXACT,
            f"a conditional on {method} substitutes a fallback when the key is missing",
        )

    # -- calls ----------------------------------------------------------------------------

    def _call(self, call: Node, scope: str, context: str) -> None:
        written, method, receiver = _callee(call)
        arguments = _arguments(call)
        if written in ENVIRONMENT_READS or written == GODOT_ENVIRONMENT:
            self._environment_read(call, scope, context, written, arguments)
        elif written == GODOT_SETTING or (
            method == GET_VALUE and len(arguments) == CONFIG_VALUE_ARGUMENTS
        ):
            self._setting(call, scope, context, written, arguments)
        elif method in (GET_VALUE_OR_DEFAULT, GET_META) and receiver is not None:
            self._lookup(call, scope, context, (method, receiver), arguments)
        elif method in OR_DEFAULT_METHODS and receiver is not None:
            self._or_default(call, scope, context, (method, receiver), arguments)

    def _environment_read(
        self, call: Node, scope: str, context: str, written: str, arguments: list[Node]
    ) -> None:
        """A variable read on its own: null (or, from Godot, "") when unset. A read that is
        the left of ``??`` or compared is the enclosing expression's."""
        parent = call.parent
        if len(arguments) != 1 or (parent is not None and parent.type == Kind.BINARY_EXPRESSION):
            return
        variable = _string_value(arguments[0])
        missing = '""' if written == GODOT_ENVIRONMENT else "null"
        self._add(
            call,
            scope,
            (FAMILY_CONFIGURATION, KIND_ENV_GET_IMPLICIT),
            variable,
            None,
            context,
            CONFIDENCE_EXACT,
            f"{written}({_text(arguments[0])}) gives {missing} when the variable is unset; "
            "check it and fail loudly, or document why absence is normal",
        )

    def _setting(
        self, call: Node, scope: str, context: str, written: str, arguments: list[Node]
    ) -> None:
        """``ProjectSettings.GetSetting(name, v)`` and ``config.GetValue(section, key, v)``."""
        if written == GODOT_SETTING and len(arguments) != SETTING_ARGUMENTS:
            return
        *keys, fallback = arguments
        exact = written == GODOT_SETTING
        self._add(
            call,
            scope,
            (FAMILY_CONFIGURATION, KIND_SETTING_GET),
            "/".join(_string_value(k) for k in keys),
            fallback,
            context,
            CONFIDENCE_EXACT if exact else CONFIDENCE_APPROXIMATE,
            f"{written} substitutes the fallback when the setting is missing"
            if exact
            else f"{written}(section, key, default) substitutes the fallback when the key is "
            "missing (a ConfigFile, by its shape)",
        )

    def _lookup(
        self,
        call: Node,
        scope: str,
        context: str,
        method_receiver: tuple[str, Node],
        arguments: list[Node],
    ) -> None:
        method, receiver = method_receiver
        if len(arguments) == 0:
            return
        subject = f"{_text(receiver)}[{_text(arguments[0])}]"
        if len(arguments) == 1:
            self._add(
                call,
                scope,
                (FAMILY_MAPPING, KIND_MAPPING_GET_IMPLICIT),
                subject,
                None,
                context,
                CONFIDENCE_EXACT,
                f"{_text(receiver)}.{method}({_text(arguments[0])}) gives default(T) when the "
                "key is missing",
            )
            return
        self._add(
            call,
            scope,
            (FAMILY_MAPPING, KIND_MAPPING_GET),
            subject,
            arguments[1],
            context,
            CONFIDENCE_EXACT,
            f"{method} substitutes the fallback for a missing key",
        )

    def _or_default(
        self,
        call: Node,
        scope: str,
        context: str,
        method_receiver: tuple[str, Node],
        arguments: list[Node],
    ) -> None:
        """LINQ's ``*OrDefault``: default(T) when nothing matches, or the given fallback."""
        method, receiver = method_receiver
        fallbacks = [a for a in arguments if a.type not in LAMBDAS]
        if method == "ElementAtOrDefault" and len(fallbacks) > 0:
            fallbacks = fallbacks[1:]
        subject = f"{_text(receiver)}.{method}"
        if len(fallbacks) == 0:
            self._add(
                call,
                scope,
                (FAMILY_MAPPING, KIND_MAPPING_GET_IMPLICIT),
                subject,
                None,
                context,
                CONFIDENCE_EXACT,
                f"{subject}(...) gives default(T) when no element matches",
            )
            return
        self._add(
            call,
            scope,
            (FAMILY_MAPPING, KIND_MAPPING_GET),
            subject,
            fallbacks[len(fallbacks) - 1],
            context,
            CONFIDENCE_EXACT,
            f"{method} substitutes the fallback when no element matches",
        )


def _fallback_text(fallback: Node | None) -> str:
    """The fallback as written; nothing for an implicit default (``FirstOrDefault()``)."""
    if fallback is None:
        return ""
    return _text(fallback)


def _filled_by_compiler(parameter: Node) -> bool:
    for attribute_list in parameter.named_children:
        if attribute_list.type != Kind.ATTRIBUTE_LIST:
            continue
        for attribute in attribute_list.named_children:
            name = attribute.child_by_field_name(Field.NAME)
            if name is None:
                continue
            _namespace, _dot, last = node_text(name).rpartition(".")
            if last.removesuffix("Attribute") in CALLER_ATTRIBUTES:
                return True
    return False


def _environment_variable(node: Node) -> str | None:
    """The variable name of ``Environment.GetEnvironmentVariable("X")`` / ``OS.GetEnvironment``."""
    if node.type != Kind.INVOCATION_EXPRESSION:
        return None
    written, _method, _receiver = _callee(node)
    arguments = _arguments(node)
    if (written in ENVIRONMENT_READS or written == GODOT_ENVIRONMENT) and len(arguments) == 1:
        return _string_value(arguments[0])
    return None


def _null_test(test: Node) -> tuple[Node, bool] | None:
    """``x == null`` / ``x is null`` -> (x, True); ``x != null`` / ``x is not null`` ->
    (x, False); anything else ``None``."""
    if test.type == Kind.BINARY_EXPRESSION and _operator(test) in (EQUALS, NOT_EQUALS):
        return _null_comparison(test)
    if test.type != Kind.IS_PATTERN_EXPRESSION:
        return None
    subject = test.child_by_field_name(Field.EXPRESSION)
    pattern = test.child_by_field_name(Field.PATTERN)
    if subject is None or pattern is None:
        return None
    spelled = node_text(pattern).split()
    if spelled == ["null"] or spelled == ["not", "null"]:
        return subject, spelled == ["null"]
    return None


def _null_comparison(test: Node) -> tuple[Node, bool] | None:
    """``x == null``, ``null != x``: the compared side and whether the test is for null."""
    left = test.child_by_field_name(Field.LEFT)
    right = test.child_by_field_name(Field.RIGHT)
    if left is None or right is None:
        return None
    is_null = _operator(test) == EQUALS
    if _unwrap(right).type == Kind.NULL_LITERAL:
        return left, is_null
    if _unwrap(left).type == Kind.NULL_LITERAL:
        return right, is_null
    return None


# How a child's context follows from its parent's kind (field-independent cases).
FIXED_CONTEXTS = {
    Kind.RETURN_STATEMENT: CONTEXT_RETURN,
    Kind.ARROW_EXPRESSION_CLAUSE: CONTEXT_RETURN,
    Kind.ARGUMENT: CONTEXT_ARGUMENT,
}


# Field-dependent cases: (fields, context of a child in one of them, context otherwise).
INHERITED = "inherited"
FIELD_CONTEXTS: dict[str, tuple[frozenset[str], str, str]] = {
    Kind.VARIABLE_DECLARATOR: (
        frozenset({Field.LEFT, Field.NAME}),
        CONTEXT_EXPRESSION,
        CONTEXT_ASSIGNMENT,
    ),
    Kind.ASSIGNMENT_EXPRESSION: (
        frozenset({Field.LEFT, Field.NAME}),
        CONTEXT_EXPRESSION,
        CONTEXT_ASSIGNMENT,
    ),
    Kind.CONDITIONAL_EXPRESSION: (frozenset({Field.CONDITION}), CONTEXT_TEST, INHERITED),
    **{
        parent: (frozenset({Field.CONDITION}), CONTEXT_TEST, CONTEXT_EXPRESSION)
        for parent in CONDITION_PARENTS
    },
}


def _child_context(parent: Node, index: int, inherited: str) -> str:
    kind = parent.type
    if kind in FIXED_CONTEXTS:
        return FIXED_CONTEXTS[kind]
    if kind in INHERITING_PARENTS:
        return inherited
    if kind == Kind.BINARY_EXPRESSION:
        return CONTEXT_TEST if _operator(parent) in COMPARISONS else inherited
    if kind not in FIELD_CONTEXTS:
        return CONTEXT_EXPRESSION
    fields, matched, other = FIELD_CONTEXTS[kind]
    chosen = matched if parent.field_name_for_child(index) in fields else other
    return inherited if chosen == INHERITED else chosen


def collect_csharp_defaults(source: SourceText, root: Node) -> tuple[DefaultFact, ...]:
    collector = _Collector(source)
    stack: list[tuple[Node, str, str]] = [(root, MODULE_SCOPE, CONTEXT_EXPRESSION)]
    while len(stack) > 0:
        node, scope, context = stack.pop()
        collector.visit(node, scope, context)
        child_scope = scope_for(node, scope)
        for index in reversed(range(node.child_count)):
            child = node.children[index]
            stack.append((child, child_scope, _child_context(node, index, context)))
    facts = collector.facts
    facts.sort(key=lambda fact: (fact.span, fact.family, fact.kind))
    return tuple(facts)
