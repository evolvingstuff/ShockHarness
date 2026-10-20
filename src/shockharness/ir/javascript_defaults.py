"""Default and fallback facts for JavaScript (consumed by DEF001-DEF006).

Syntactic, like the Python extractor. Recognized shapes:

* parameter defaults (``function f(a = v)``, arrow and method parameters) and
  destructuring defaults inside parameters (``function f({a = v}, [b = w])``);
  rest parameters are not defaults;
* destructuring defaults in declarations (``const {a = v} = o``,
  ``const [a = v] = arr``), member fallbacks (``o?.a ?? v``, ``o.a ?? v``,
  ``m.get(k) ?? v``, ``o[k] ?? v``), and membership ternaries
  (``k in o ? o[k] : v``, ``o.hasOwnProperty(k) ? o[k] : v``,
  ``Object.hasOwn(o, k) ? o[k] : v``);
* truthiness fallbacks: ``x || v`` outside a boolean test, ``x ||= v``,
  ``x ? x : v``;
* nullish fallbacks: ``x ?? v``, ``x ??= v``, and ternaries guarded by
  ``x === undefined``, ``x == null``, ``typeof x === "undefined"`` (and their
  negations);
* configuration fallbacks: ``process.env.X || v``, ``process.env.X ?? v``,
  ``process.env.X ||= v``, ``const { X = v } = process.env``;
* exception-to-default traces for DEF005: a ``catch`` block whose one statement
  returns a module-level constant or calls a module-level helper that returns a
  literal (literal returns are already classified on the ``CatchFact``).

A bare ``process.env.X`` read and a bare ``map.get(k)`` are not facts: every
property read of an absent key yields ``undefined`` in JavaScript, so nothing in
the syntax singles these out (see docs/limitations.md).
"""

import re

from tree_sitter import Node

from shockharness.constants import LOOKUP_WITH_FALLBACK_ARITY
from shockharness.ir.javascript_catches import (
    FIELD_DEFINITIONS,
    TYPE_WRAPPERS,
    block_statements,
    first_expression,
    is_literal_like,
    is_logging_statement,
    node_span,
    node_text,
    parameter_parts,
    scope_for,
    unwrap_parens,
)
from shockharness.ir.javascript_nodes import Field, Kind
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
    FAMILY_EXCEPTION,
    FAMILY_MAPPING,
    FAMILY_NULLISH,
    FAMILY_PARAMETER,
    FAMILY_TRUTHINESS,
    KIND_DESTRUCTURING,
    KIND_ENV_DESTRUCTURING,
    KIND_ENV_NULLISH,
    KIND_ENV_TRUTHINESS,
    KIND_EXCEPTION_CONSTANT,
    KIND_EXCEPTION_HELPER,
    KIND_MEMBER_NULLISH,
    KIND_MEMBERSHIP_TERNARY,
    KIND_NULLISH_ASSIGN,
    KIND_NULLISH_COALESCE,
    KIND_NULLISH_TERNARY,
    KIND_PARAMETER,
    KIND_PARAMETER_DESTRUCTURING,
    KIND_TRUTHINESS_ASSIGN,
    KIND_TRUTHINESS_OR,
    KIND_TRUTHINESS_TERNARY,
    MODULE_SCOPE,
    DefaultFact,
)
from shockharness.ir.tree_sitter_common import collapsed_text as _text
from shockharness.source import SourceText

UPPER_CASE_NAME = re.compile(r"_*[A-Z][A-Z0-9_]*")
EMPTY_CONSTRUCTORS = frozenset({"Map", "Set", "Array", "Object", "WeakMap", "WeakSet"})
ENV_OBJECT = "process.env"
ELLIPSIS_TEXT = "..."

PATTERN_TYPES = frozenset({Kind.OBJECT_PATTERN, Kind.ARRAY_PATTERN})
MEMBER_TYPES = frozenset({Kind.MEMBER_EXPRESSION, Kind.SUBSCRIPT_EXPRESSION, Kind.CALL_EXPRESSION})
NULLISH_LITERALS = frozenset({Kind.NULL, Kind.UNDEFINED})
EQUALITY = frozenset({"===", "=="})
INEQUALITY = frozenset({"!==", "!="})
COMPARISONS = frozenset({"===", "!==", "==", "!=", "<", ">", "<=", ">=", Kind.INSTANCEOF, "in"})
CONDITION_PARENTS = frozenset(
    {Kind.IF_STATEMENT, Kind.WHILE_STATEMENT, Kind.DO_STATEMENT, Kind.FOR_STATEMENT}
)
HAS_OWN_METHODS = frozenset({"hasOwnProperty", "hasOwn"})
VALUE_TYPES = frozenset(
    {Kind.IDENTIFIER, Kind.MEMBER_EXPRESSION, Kind.SUBSCRIPT_EXPRESSION, Kind.CALL_EXPRESSION}
)


def _same(a: Node, b: Node) -> bool:
    return node_text(unwrap_parens(a)) == node_text(unwrap_parens(b))


def _mentions(container: Node, target: Node) -> bool:
    wanted = node_text(unwrap_parens(target))
    stack = [container]
    while len(stack) > 0:
        current = stack.pop()
        if node_text(current) == wanted:
            return True
        stack.extend(current.children)
    return False


def is_constant_shaped(node: Node | None) -> bool:
    """Literal-like, an UPPER_CASE identifier or property, or an empty ``new Map()``-style call."""
    if node is None:
        return True
    inner = unwrap_parens(node)
    if is_literal_like(inner):
        return True
    if inner.type == Kind.IDENTIFIER:
        return UPPER_CASE_NAME.fullmatch(node_text(inner)) is not None
    if inner.type == Kind.MEMBER_EXPRESSION:
        prop = inner.child_by_field_name(Field.PROPERTY)
        return prop is not None and UPPER_CASE_NAME.fullmatch(node_text(prop)) is not None
    if inner.type == Kind.NEW_EXPRESSION:
        constructor = inner.child_by_field_name(Field.CONSTRUCTOR)
        arguments = inner.child_by_field_name(Field.ARGUMENTS)
        return (
            constructor is not None
            and node_text(constructor) in EMPTY_CONSTRUCTORS
            and (arguments is None or len(arguments.named_children) == 0)
        )
    return False


BOOLEAN_LITERALS = frozenset({Kind.TRUE, Kind.FALSE})
BOOLEAN_OPERATORS = COMPARISONS | frozenset({"&&"})


def _is_boolean_expression(node: Node) -> bool:
    """A comparison, ``&&``, ``!x``, ``typeof``-free Boolean literal: logic, not a value."""
    inner = unwrap_parens(node)
    if inner.type in BOOLEAN_LITERALS:
        return True
    if inner.type == Kind.BINARY_EXPRESSION:
        return _operator(inner) in BOOLEAN_OPERATORS
    return inner.type == Kind.UNARY_EXPRESSION and _operator(inner) == "!"


def _is_nullish_literal(node: Node | None) -> bool:
    return node is not None and unwrap_parens(node).type in NULLISH_LITERALS


def _operator(node: Node) -> str:
    operator = node.child_by_field_name(Field.OPERATOR)
    assert operator is not None, f"{node.type} without an operator field"
    return node_text(operator)


def _env_variable(node: Node) -> str | None:
    """``"X"`` when ``node`` reads ``process.env.X`` / ``process.env["X"]``, else ``None``."""
    inner = unwrap_parens(node)
    if inner.type not in (Kind.MEMBER_EXPRESSION, Kind.SUBSCRIPT_EXPRESSION):
        return None
    receiver = inner.child_by_field_name(Field.OBJECT)
    if receiver is None or node_text(receiver) != ENV_OBJECT:
        return None
    key = inner.child_by_field_name(Field.PROPERTY)
    if key is None:
        key = inner.child_by_field_name(Field.INDEX)
    return None if key is None else _text(key)


def _is_env_object(node: Node | None) -> bool:
    return node is not None and node_text(unwrap_parens(node)) == ENV_OBJECT


class _ModuleIndex:
    """Module-level constants and one-statement helpers, for DEF005 traces."""

    def __init__(self, root: Node) -> None:
        self.constants: dict[str, Node] = {}
        self.helpers: dict[str, Node] = {}
        for statement in root.named_children:
            if statement.type in (Kind.LEXICAL_DECLARATION, Kind.VARIABLE_DECLARATION):
                for declarator in statement.named_children:
                    if declarator.type != Kind.VARIABLE_DECLARATOR:
                        continue
                    name = declarator.child_by_field_name(Field.NAME)
                    value = declarator.child_by_field_name(Field.VALUE)
                    if name is None or value is None or name.type != Kind.IDENTIFIER:
                        continue
                    if value.type in (Kind.ARROW_FUNCTION, Kind.FUNCTION_EXPRESSION):
                        self.helpers[node_text(name)] = value
                    elif is_constant_shaped(value):
                        self.constants[node_text(name)] = value
            elif statement.type == Kind.FUNCTION_DECLARATION:
                name = statement.child_by_field_name(Field.NAME)
                if name is not None:
                    self.helpers[node_text(name)] = statement

    def helper_returns(self, name: str) -> Node | None:
        """The constant the helper returns, or ``None`` when it is not a one-return helper."""
        if name not in self.helpers:
            return None
        body = self.helpers[name].child_by_field_name(Field.BODY)
        if body is None:
            return None
        if body.type != Kind.STATEMENT_BLOCK:
            return body if is_constant_shaped(body) else None
        statements = block_statements(body)
        if len(statements) != 1 or statements[0].type != Kind.RETURN_STATEMENT:
            return None
        value = first_expression(statements[0])
        if value is None:
            return statements[0]
        return value if is_constant_shaped(value) else None


class _Collector:
    def __init__(self, source: SourceText, root: Node) -> None:
        self.source = source
        self.index = _ModuleIndex(root)
        self.facts: list[DefaultFact] = []

    def _add(
        self,
        node: Node,
        scope: str,
        family: str,
        kind: str,
        subject: str,
        fallback: Node | None,
        context: str,
        confidence: str,
        detail: str,
    ) -> None:
        fallback_text = "undefined"
        if fallback is not None:
            fallback_text = _text(fallback)
        self.facts.append(
            DefaultFact(
                span=node_span(self.source, node),
                scope=scope,
                family=family,
                kind=kind,
                subject=subject,
                fallback=fallback_text,
                fallback_constant=is_constant_shaped(fallback),
                context=context,
                confidence=confidence,
                detail=detail,
            )
        )

    @staticmethod
    def _confidence_for(fallback: Node | None) -> str:
        return CONFIDENCE_EXACT if is_constant_shaped(fallback) else CONFIDENCE_APPROXIMATE

    # -- patterns ----------------------------------------------------------------------------

    def _pattern_defaults(
        self, pattern: Node, scope: str, kind: str, family: str, where: str
    ) -> None:
        """Every ``name = value`` inside an object/array pattern, recursively."""
        stack = [pattern]
        while len(stack) > 0:
            current = stack.pop()
            if current.type == Kind.OBJECT_ASSIGNMENT_PATTERN:
                left = current.child_by_field_name(Field.LEFT)
                right = current.child_by_field_name(Field.RIGHT)
                if left is not None and right is not None:
                    self._add(
                        right,
                        scope,
                        family,
                        kind,
                        node_text(left),
                        right,
                        CONTEXT_DECLARATION,
                        CONFIDENCE_EXACT,
                        f"destructuring default for {node_text(left)!r} in {where}",
                    )
                continue
            if current.type == Kind.ASSIGNMENT_PATTERN:
                left = current.child_by_field_name(Field.LEFT)
                right = current.child_by_field_name(Field.RIGHT)
                if left is not None and right is not None:
                    self._add(
                        right,
                        scope,
                        family,
                        kind,
                        _text(left),
                        right,
                        CONTEXT_DECLARATION,
                        CONFIDENCE_EXACT,
                        f"destructuring default for {_text(left)!r} in {where}",
                    )
                    if left.type in PATTERN_TYPES:
                        stack.append(left)
                continue
            if current.type == Kind.REST_PATTERN:
                continue
            if current.type == Kind.PAIR_PATTERN:
                value = current.child_by_field_name(Field.VALUE)
                if value is not None:
                    stack.append(value)
                continue
            if current.type in PATTERN_TYPES:
                stack.extend(reversed(current.named_children))

    def _formal_parameters(self, parameters: Node, scope: str) -> None:
        parts = scope.rsplit(".", 1)
        owner = parts[len(parts) - 1]
        for parameter in parameters.named_children:
            left, right = parameter_parts(parameter)
            if right is not None:
                self._add(
                    right,
                    scope,
                    FAMILY_PARAMETER,
                    KIND_PARAMETER,
                    _text(left),
                    right,
                    CONTEXT_DECLARATION,
                    CONFIDENCE_EXACT,
                    f"parameter {_text(left)!r} of {owner} has a default value",
                )
                if left.type in PATTERN_TYPES:
                    self._pattern_defaults(
                        left, scope, KIND_PARAMETER_DESTRUCTURING, FAMILY_PARAMETER, "parameters"
                    )
            elif left.type in PATTERN_TYPES:
                self._pattern_defaults(
                    left, scope, KIND_PARAMETER_DESTRUCTURING, FAMILY_PARAMETER, "parameters"
                )

    def _declarator(self, declarator: Node, scope: str) -> None:
        name = declarator.child_by_field_name(Field.NAME)
        value = declarator.child_by_field_name(Field.VALUE)
        if name is None or name.type not in PATTERN_TYPES:
            return
        if _is_env_object(value):
            self._pattern_defaults(
                name,
                scope,
                KIND_ENV_DESTRUCTURING,
                FAMILY_CONFIGURATION,
                "a destructuring of process.env",
            )
            return
        assert value is not None, "destructuring declarator without an initializer"
        source = f"a destructuring of {_text(value)}"
        self._pattern_defaults(name, scope, KIND_DESTRUCTURING, FAMILY_MAPPING, source)

    def _loop_pattern(self, loop: Node, scope: str) -> None:
        """``for (const {x = v} of rows)``: destructuring defaults on the loop variable."""
        left = loop.child_by_field_name(Field.LEFT)
        right = loop.child_by_field_name(Field.RIGHT)
        if left is None or left.type not in PATTERN_TYPES:
            return
        assert right is not None, "for-in/for-of statement without an iterable"
        source = f"a loop over {_text(right)}"
        self._pattern_defaults(left, scope, KIND_DESTRUCTURING, FAMILY_MAPPING, source)

    def _assignment_pattern(self, assignment: Node, scope: str) -> None:
        """``({x = v} = o)``: destructuring defaults in an assignment expression."""
        left = assignment.child_by_field_name(Field.LEFT)
        right = assignment.child_by_field_name(Field.RIGHT)
        if left is None or right is None or left.type not in PATTERN_TYPES:
            return
        if _is_env_object(right):
            self._pattern_defaults(
                left,
                scope,
                KIND_ENV_DESTRUCTURING,
                FAMILY_CONFIGURATION,
                "a destructuring of process.env",
            )
            return
        self._pattern_defaults(
            left, scope, KIND_DESTRUCTURING, FAMILY_MAPPING, f"a destructuring of {_text(right)}"
        )

    # -- binary and assignment operators -----------------------------------------------------

    def _binary(self, node: Node, parent: Node | None, scope: str, context: str) -> None:
        operator = _operator(node)
        if operator not in ("||", "??") or context == CONTEXT_TEST:
            return
        left = node.child_by_field_name(Field.LEFT)
        right = node.child_by_field_name(Field.RIGHT)
        if left is None or right is None:
            return
        if (
            parent is not None
            and parent.type == Kind.BINARY_EXPRESSION
            and _operator(parent) == operator
        ):
            return  # ``a || b || c``: the outermost node reports the chain once
        subject = _text(left)
        if operator == "||":
            self._truthiness(node, left, right, subject, scope, context, "'||'")
        else:
            self._nullish(node, left, right, subject, scope, context, "'??'")

    def _augmented(self, node: Node, scope: str) -> None:
        operator = _operator(node)
        left = node.child_by_field_name(Field.LEFT)
        right = node.child_by_field_name(Field.RIGHT)
        if left is None or right is None:
            return
        subject = _text(left)
        if operator == "||=":
            variable = _env_variable(left)
            if variable is not None:
                self._add(
                    node,
                    scope,
                    FAMILY_CONFIGURATION,
                    KIND_ENV_TRUTHINESS,
                    variable,
                    right,
                    CONTEXT_ASSIGNMENT,
                    self._confidence_for(right),
                    f"'||=' assigns a fallback when environment variable {variable} is unset "
                    "or empty",
                )
                return
            self._add(
                node,
                scope,
                FAMILY_TRUTHINESS,
                KIND_TRUTHINESS_ASSIGN,
                subject,
                right,
                CONTEXT_ASSIGNMENT,
                self._confidence_for(right),
                "'||=' assigns the fallback for every falsy value of the target "
                "(undefined, null, 0, '', NaN, false alike)",
            )
        elif operator == "??=":
            self._nullish(node, left, right, subject, scope, CONTEXT_ASSIGNMENT, "'??='")

    def _truthiness(
        self,
        node: Node,
        left: Node,
        right: Node,
        subject: str,
        scope: str,
        context: str,
        spelled: str,
    ) -> None:
        variable = _env_variable(left)
        if variable is not None:
            self._add(
                node,
                scope,
                FAMILY_CONFIGURATION,
                KIND_ENV_TRUTHINESS,
                variable,
                right,
                context,
                self._confidence_for(right),
                f"{spelled} replaces an unset or empty environment variable {variable} with a "
                "fallback",
            )
            return
        if _is_boolean_expression(left) or _is_boolean_expression(right):
            return  # ``a < b || c === d``: Boolean logic, not a value substitution
        constant = is_constant_shaped(right)
        if not constant and context not in (CONTEXT_ASSIGNMENT, CONTEXT_RETURN):
            return
        detail = (
            f"{spelled} substitutes a constant for every falsy value of the left operand "
            "(undefined, null, 0, '', NaN, false alike)"
            if constant
            else f"{spelled} in {context} position may be a fallback or a legitimate alternative; "
            "the right operand is not a constant, so this is approximate"
        )
        self._add(
            node,
            scope,
            FAMILY_TRUTHINESS,
            KIND_TRUTHINESS_OR if spelled == "'||'" else KIND_TRUTHINESS_TERNARY,
            subject,
            right,
            context,
            CONFIDENCE_EXACT if constant else CONFIDENCE_APPROXIMATE,
            detail,
        )

    def _nullish(
        self,
        node: Node,
        left: Node,
        right: Node,
        subject: str,
        scope: str,
        context: str,
        spelled: str,
    ) -> None:
        variable = _env_variable(left)
        if variable is not None:
            self._add(
                node,
                scope,
                FAMILY_CONFIGURATION,
                KIND_ENV_NULLISH,
                variable,
                right,
                context,
                self._confidence_for(right),
                f"{spelled} substitutes a fallback when environment variable {variable} is unset",
            )
            return
        inner = unwrap_parens(left)
        if inner.type in MEMBER_TYPES:
            self._add(
                node,
                scope,
                FAMILY_MAPPING,
                KIND_MEMBER_NULLISH,
                subject,
                right,
                context,
                self._confidence_for(right),
                f"{spelled} substitutes a fallback when the property or lookup result is "
                "null or undefined",
            )
            return
        kind = KIND_NULLISH_ASSIGN if spelled == "'??='" else KIND_NULLISH_COALESCE
        self._add(
            node,
            scope,
            FAMILY_NULLISH,
            kind,
            subject,
            right,
            context,
            self._confidence_for(right),
            f"{spelled} substitutes a fallback when the left operand is null or undefined",
        )

    # -- ternaries ---------------------------------------------------------------------------

    def _ternary(self, node: Node, scope: str, context: str) -> None:
        condition = node.child_by_field_name(Field.CONDITION)
        consequence = node.child_by_field_name(Field.CONSEQUENCE)
        alternative = node.child_by_field_name(Field.ALTERNATIVE)
        if condition is None or consequence is None or alternative is None:
            return
        test = unwrap_parens(condition)
        negated = False
        if test.type == Kind.UNARY_EXPRESSION and _operator(test) == "!":
            argument = test.child_by_field_name(Field.ARGUMENT)
            if argument is None:
                return
            test = unwrap_parens(argument)
            negated = True
        if test.type == Kind.BINARY_EXPRESSION:
            operator = _operator(test)
            left = test.child_by_field_name(Field.LEFT)
            right = test.child_by_field_name(Field.RIGHT)
            if left is None or right is None:
                return
            if operator in EQUALITY or operator in INEQUALITY:
                missing_when_true = (operator in EQUALITY) != negated
                self._nullish_ternary(
                    node, left, right, missing_when_true, consequence, alternative, scope, context
                )
                return
            if operator == "in":
                present, missing = (
                    (alternative, consequence) if negated else (consequence, alternative)
                )
                self._membership_ternary(node, right, left, present, missing, scope, context)
            return
        if test.type == Kind.CALL_EXPRESSION:
            owner_key = _has_own_call(test)
            if owner_key is not None:
                owner, key = owner_key
                present, missing = (
                    (alternative, consequence) if negated else (consequence, alternative)
                )
                self._membership_ternary(node, owner, key, present, missing, scope, context)
            return
        if test.type in VALUE_TYPES:
            present, missing = (alternative, consequence) if negated else (consequence, alternative)
            if _same(test, present):
                self._truthiness(node, test, missing, _text(test), scope, context, "'x ? x : v'")

    def _nullish_ternary(
        self,
        node: Node,
        left: Node,
        right: Node,
        missing_when_true: bool,
        consequence: Node,
        alternative: Node,
        scope: str,
        context: str,
    ) -> None:
        subject = _nullish_subject(left, right)
        if subject is None:
            return
        missing, present = (
            (consequence, alternative) if missing_when_true else (alternative, consequence)
        )
        if _is_nullish_literal(missing):
            return  # ``x == null ? null : x.y`` propagates absence; it substitutes nothing
        if not _mentions(present, subject):
            return  # a choice between two values, not a fallback for the subject
        variable = _env_variable(subject)
        if variable is not None:
            self._add(
                node,
                scope,
                FAMILY_CONFIGURATION,
                KIND_ENV_NULLISH,
                variable,
                missing,
                context,
                self._confidence_for(missing),
                f"ternary substitutes a fallback when environment variable {variable} is unset",
            )
            return
        if unwrap_parens(subject).type in MEMBER_TYPES:
            self._add(
                node,
                scope,
                FAMILY_MAPPING,
                KIND_MEMBER_NULLISH,
                _text(subject),
                missing,
                context,
                self._confidence_for(missing),
                "ternary on a null/undefined check substitutes a fallback for a missing property",
            )
            return
        self._add(
            node,
            scope,
            FAMILY_NULLISH,
            KIND_NULLISH_TERNARY,
            _text(subject),
            missing,
            context,
            self._confidence_for(missing),
            "ternary on a null/undefined check substitutes a value when the subject is missing",
        )

    def _membership_ternary(
        self,
        node: Node,
        owner: Node,
        key: Node,
        present: Node,
        missing: Node,
        scope: str,
        context: str,
    ) -> None:
        inner = unwrap_parens(present)
        if inner.type not in (Kind.MEMBER_EXPRESSION, Kind.SUBSCRIPT_EXPRESSION):
            return
        receiver = inner.child_by_field_name(Field.OBJECT)
        if receiver is None or not _same(receiver, owner):
            return
        looked_up = inner.child_by_field_name(Field.INDEX)
        if looked_up is None:
            looked_up = inner.child_by_field_name(Field.PROPERTY)
        if looked_up is None:
            return
        key_text = node_text(unwrap_parens(key))
        if key_text.strip("'\"`") != node_text(looked_up).strip("'\"`"):
            return
        self._add(
            node,
            scope,
            FAMILY_MAPPING,
            KIND_MEMBERSHIP_TERNARY,
            _text(present),
            missing,
            context,
            self._confidence_for(missing),
            "membership test followed by a lookup substitutes a value for a missing property",
        )

    # -- exception-to-default traces ---------------------------------------------------------

    def _catch_trace(self, clause: Node, scope: str) -> None:
        body = clause.child_by_field_name(Field.BODY)
        if body is None:
            return
        statements = [s for s in block_statements(body) if not is_logging_statement(s)]
        if len(statements) != 1 or statements[0].type != Kind.RETURN_STATEMENT:
            return
        value = first_expression(statements[0])
        if value is None or is_literal_like(value):
            return  # classified on the CatchFact as return_fallback
        value = unwrap_parens(value)
        if value.type == Kind.NEW_EXPRESSION and is_constant_shaped(value):
            self._add(
                clause,
                scope,
                FAMILY_EXCEPTION,
                KIND_EXCEPTION_CONSTANT,
                _text(value),
                value,
                CONTEXT_RETURN,
                CONFIDENCE_EXACT,
                f"handler fabricates an empty value in place: return {_text(value)}",
            )
            return
        if value.type == Kind.IDENTIFIER:
            name = node_text(value)
            if name in self.index.constants:
                constant = self.index.constants[name]
                self._add(
                    clause,
                    scope,
                    FAMILY_EXCEPTION,
                    KIND_EXCEPTION_CONSTANT,
                    name,
                    constant,
                    CONTEXT_RETURN,
                    CONFIDENCE_APPROXIMATE,
                    f"handler returns {name}, bound at module level to {_text(constant)} "
                    "(static trace; reassignment is not followed)",
                )
            return
        if value.type == Kind.CALL_EXPRESSION:
            function = value.child_by_field_name(Field.FUNCTION)
            if function is None or function.type != Kind.IDENTIFIER:
                return
            returned = self.index.helper_returns(node_text(function))
            if returned is None:
                return
            text = "undefined" if returned.type == Kind.RETURN_STATEMENT else _text(returned)
            self._add(
                clause,
                scope,
                FAMILY_EXCEPTION,
                KIND_EXCEPTION_HELPER,
                _text(value),
                None if returned.type == Kind.RETURN_STATEMENT else returned,
                CONTEXT_RETURN,
                CONFIDENCE_APPROXIMATE,
                f"handler delegates to {node_text(function)}(), a module-level helper that "
                f"returns {text} (static trace)",
            )

    # -- traversal ---------------------------------------------------------------------------

    def visit(self, node: Node, parent: Node | None, scope: str, context: str) -> None:
        kind = node.type
        if kind == Kind.FORMAL_PARAMETERS:
            self._formal_parameters(node, scope)
        elif kind == Kind.VARIABLE_DECLARATOR:
            self._declarator(node, scope)
        elif kind == Kind.FOR_IN_STATEMENT:
            self._loop_pattern(node, scope)
        elif kind == Kind.ASSIGNMENT_EXPRESSION:
            self._assignment_pattern(node, scope)
        elif kind == Kind.BINARY_EXPRESSION:
            self._binary(node, parent, scope, context)
        elif kind == Kind.AUGMENTED_ASSIGNMENT_EXPRESSION:
            self._augmented(node, scope)
        elif kind == Kind.TERNARY_EXPRESSION:
            self._ternary(node, scope, context)
        elif kind == Kind.CATCH_CLAUSE:
            self._catch_trace(node, scope)


def _nullish_subject(left: Node, right: Node) -> Node | None:
    """The operand compared against null/undefined, unwrapping ``typeof x``."""
    if _is_nullish_literal(right):
        candidate = left
    elif _is_nullish_literal(left):
        candidate = right
    elif right.type == Kind.STRING and node_text(right).strip("'\"`") == Kind.UNDEFINED:
        candidate = left
    elif left.type == Kind.STRING and node_text(left).strip("'\"`") == Kind.UNDEFINED:
        candidate = right
    else:
        return None
    candidate = unwrap_parens(candidate)
    if candidate.type == Kind.UNARY_EXPRESSION and _operator(candidate) == "typeof":
        argument = candidate.child_by_field_name(Field.ARGUMENT)
        return None if argument is None else unwrap_parens(argument)
    if candidate.type in VALUE_TYPES:
        return candidate
    return None


def _has_own_call(call: Node) -> tuple[Node, Node] | None:
    """``o.hasOwnProperty(k)`` / ``Object.hasOwn(o, k)`` -> (owner, key)."""
    function = call.child_by_field_name(Field.FUNCTION)
    arguments = call.child_by_field_name(Field.ARGUMENTS)
    if function is None or arguments is None or function.type != Kind.MEMBER_EXPRESSION:
        return None
    method = function.child_by_field_name(Field.PROPERTY)
    receiver = function.child_by_field_name(Field.OBJECT)
    if method is None or receiver is None or node_text(method) not in HAS_OWN_METHODS:
        return None
    actual = [a for a in arguments.named_children if a.type != Kind.COMMENT]
    if node_text(method) == "hasOwn":
        if node_text(receiver) != "Object" or len(actual) != LOOKUP_WITH_FALLBACK_ARITY:
            return None
        return actual[0], actual[1]
    if len(actual) != 1:
        return None
    return receiver, actual[0]


# Parents whose `value` child is assigned; parents that pass their context through (with
# TypeScript's `as`/`!`/`satisfies`/`<T>` wrappers, which change no value).
ASSIGNING_PARENTS = frozenset({Kind.VARIABLE_DECLARATOR, Kind.PAIR}) | FIELD_DEFINITIONS
INHERITING_PARENTS = (
    frozenset({Kind.PARENTHESIZED_EXPRESSION, Kind.AWAIT_EXPRESSION, Kind.SPREAD_ELEMENT})
    | TYPE_WRAPPERS
)


def _child_context(parent: Node, child: Node, index: int, inherited: str) -> str:
    kind = parent.type
    field = parent.field_name_for_child(index)
    if kind in ASSIGNING_PARENTS:
        return CONTEXT_ASSIGNMENT if field == Field.VALUE else CONTEXT_EXPRESSION
    if kind in (Kind.ASSIGNMENT_EXPRESSION, Kind.AUGMENTED_ASSIGNMENT_EXPRESSION):
        return CONTEXT_ASSIGNMENT if field == Field.RIGHT else CONTEXT_EXPRESSION
    if kind == Kind.RETURN_STATEMENT:
        return CONTEXT_RETURN
    if kind == Kind.ARROW_FUNCTION:
        return (
            CONTEXT_RETURN
            if field == Field.BODY and child.type != Kind.STATEMENT_BLOCK
            else CONTEXT_EXPRESSION
        )
    if kind in CONDITION_PARENTS:
        return CONTEXT_TEST if field == Field.CONDITION else CONTEXT_EXPRESSION
    if kind == Kind.TERNARY_EXPRESSION:
        return CONTEXT_TEST if field == Field.CONDITION else inherited
    if kind == Kind.BINARY_EXPRESSION:
        operator = _operator(parent)
        if operator == "&&" or operator in COMPARISONS:
            return CONTEXT_TEST
        return inherited
    if kind == Kind.UNARY_EXPRESSION:
        return CONTEXT_TEST if _operator(parent) == "!" else inherited
    if kind == Kind.ARGUMENTS:
        return CONTEXT_ARGUMENT
    if kind in INHERITING_PARENTS:
        return inherited
    return CONTEXT_EXPRESSION


def collect_javascript_defaults(source: SourceText, root: Node) -> tuple[DefaultFact, ...]:
    collector = _Collector(source, root)
    stack: list[tuple[Node, Node | None, str, str]] = [
        (root, None, MODULE_SCOPE, CONTEXT_EXPRESSION)
    ]
    while len(stack) > 0:
        node, parent, scope, context = stack.pop()
        collector.visit(node, parent, scope, context)
        child_scope = scope_for(node, scope)
        for index, child in reversed(list(enumerate(node.children))):
            stack.append((child, node, child_scope, _child_context(node, child, index, context)))
    facts = collector.facts
    facts.sort(key=lambda fact: (fact.span, fact.family, fact.kind))
    return tuple(facts)
