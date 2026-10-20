"""Catch facts for JavaScript: ``catch`` clauses and promise rejection handlers.

JavaScript has no static exception typing, so a catch is *bare* unless its
handler opens with a recognized guard that re-throws everything except one
named class::

    catch (err) {
      if (!(err instanceof TimeoutError)) throw err;
      ...
    }
    catch (err) {
      if (err instanceof TimeoutError) { ... } else { throw err; }
    }

The guarded class becomes the catch's identity with ``approximate`` confidence
(the class name is taken as written; nothing proves what it refers to). Any
other shape, including ``err.name === "TimeoutError"`` or guards joined with
``||``, leaves the catch untyped. Promise ``.catch(handler)`` and
``.then(onFulfilled, onRejected)`` produce the same fact when the handler is an
inline function or a reference to a function defined at the top level of the
same module (its body is classified); any other reference is *opaque* and
resolves as unresolved. ``.finally(fn)`` is never a catch.
"""

import re

from tree_sitter import Node

from shockharness.ir.javascript_nodes import Field, Kind
from shockharness.ir.model import (
    ANONYMOUS_SCOPE,
    BODY_EMPTY,
    BODY_LOGGING_ONLY,
    BODY_OPAQUE,
    BODY_OTHER,
    BODY_RAISE_CHAINED,
    BODY_RAISE_OTHER,
    BODY_RERAISE,
    BODY_RETURN_FALLBACK,
    CATCH_CLAUSE,
    CATCH_PROMISE,
    CATCH_PROMISE_THEN,
    CONFIDENCE_APPROXIMATE,
    MODULE_SCOPE,
    CatchFact,
    ExceptionIdentity,
    HandlerBody,
    Span,
    TryStatement,
)
from shockharness.ir.tree_sitter_common import count_kinds
from shockharness.ir.tree_sitter_common import node_span as node_span
from shockharness.ir.tree_sitter_common import node_text as node_text
from shockharness.source import SourceText

NAMED_SCOPE_TYPES = frozenset(
    {
        Kind.FUNCTION_DECLARATION,
        Kind.GENERATOR_FUNCTION_DECLARATION,
        Kind.CLASS_DECLARATION,
        Kind.ABSTRACT_CLASS_DECLARATION,
        Kind.METHOD_DEFINITION,
    }
)
ANONYMOUS_FUNCTION_TYPES = frozenset(
    {Kind.ARROW_FUNCTION, Kind.FUNCTION_EXPRESSION, Kind.GENERATOR_FUNCTION, Kind.CLASS}
)
IGNORED_IN_BLOCK = frozenset({Kind.COMMENT, Kind.EMPTY_STATEMENT})
# A class field: `x = v` in JavaScript, `x: T = v` (public_field_definition) in TypeScript,
# whose name is in the `property` and `name` field respectively.
FIELD_DEFINITIONS = frozenset({Kind.FIELD_DEFINITION, Kind.PUBLIC_FIELD_DEFINITION})
FIELD_NAME_FIELDS = {
    Kind.FIELD_DEFINITION: Field.PROPERTY,
    Kind.PUBLIC_FIELD_DEFINITION: Field.NAME,
}
# TypeScript wrappers that change only the static type, never the value: `(x as T)`, `x!`,
# `x satisfies T`, `<T>x`. Code that reads the value looks through them like parentheses.
TYPE_WRAPPERS = frozenset(
    {Kind.AS_EXPRESSION, Kind.NON_NULL_EXPRESSION, Kind.SATISFIES_EXPRESSION, Kind.TYPE_ASSERTION}
)
COMPOUND_STATEMENTS = frozenset(
    {
        Kind.IF_STATEMENT,
        Kind.FOR_STATEMENT,
        Kind.FOR_IN_STATEMENT,
        Kind.WHILE_STATEMENT,
        Kind.DO_STATEMENT,
        Kind.TRY_STATEMENT,
        Kind.SWITCH_STATEMENT,
        Kind.WITH_STATEMENT,
        Kind.LABELED_STATEMENT,
        Kind.STATEMENT_BLOCK,
        Kind.FUNCTION_DECLARATION,
        Kind.GENERATOR_FUNCTION_DECLARATION,
        Kind.CLASS_DECLARATION,
        Kind.ABSTRACT_CLASS_DECLARATION,
    }
)
OPERATION_TYPES = frozenset(
    {
        Kind.CALL_EXPRESSION,
        Kind.NEW_EXPRESSION,
        Kind.ARROW_FUNCTION,
        Kind.FUNCTION_EXPRESSION,
        Kind.GENERATOR_FUNCTION,
        Kind.AWAIT_EXPRESSION,
        Kind.YIELD_EXPRESSION,
    }
)
LITERAL_TYPES = frozenset(
    {Kind.NULL, Kind.UNDEFINED, Kind.TRUE, Kind.FALSE, Kind.NUMBER, Kind.STRING}
)
LOGGING_CALL = re.compile(
    r"^(?:[A-Za-z_$][A-Za-z0-9_$]*\.)*"
    r"(?:console|logger|log|LOGGER|LOG|_logger|_log)"
    r"\.(?:log|debug|info|warn|warning|error|exception|critical|fatal|trace|dir)$"
)
LOGGING_EXACT = frozenset({"process.stderr.write", "process.stdout.write", "log"})
REJECTION_HANDLER_ARGS = {"catch": 0, "then": 1}


# TypeScript wraps each parameter (`x: T = v`, `x?: T`, `private x = v`) in one of these,
# with the binding in `pattern` and the default in `value`.
TYPED_PARAMETERS = frozenset({Kind.REQUIRED_PARAMETER, Kind.OPTIONAL_PARAMETER})
THIS_PARAMETER = Kind.THIS


def parameter_parts(parameter: Node) -> tuple[Node, Node | None]:
    """A formal parameter's binding (identifier or pattern) and its default value, the
    same for ``x = v`` in JavaScript and ``x: T = v`` in TypeScript."""
    if parameter.type in TYPED_PARAMETERS:
        pattern = parameter.child_by_field_name(Field.PATTERN)
        assert pattern is not None, "TypeScript parameter without a pattern"
        return pattern, parameter.child_by_field_name(Field.VALUE)
    if parameter.type == Kind.ASSIGNMENT_PATTERN:
        left = parameter.child_by_field_name(Field.LEFT)
        assert left is not None, "assignment pattern without a left side"
        return left, parameter.child_by_field_name(Field.RIGHT)
    return parameter, None


def is_this_parameter(parameter: Node) -> bool:
    """TypeScript's ``this: T`` declares the receiver's type; it is not a parameter."""
    binding, _default = parameter_parts(parameter)
    return binding.type == THIS_PARAMETER


def scope_for(node: Node, scope: str) -> str:
    if node.type in NAMED_SCOPE_TYPES:
        name_node = node.child_by_field_name(Field.NAME)
        assert name_node is not None, f"{node.type} without a name field"
        name = node_text(name_node)
    elif node.type in ANONYMOUS_FUNCTION_TYPES:
        name = binding_name(node)
    else:
        return scope
    if scope == MODULE_SCOPE:
        return name
    return f"{scope}.{name}"


def binding_name(node: Node) -> str:
    """Best-effort name for an anonymous function: the declarator or property it is bound to."""
    parent = node.parent
    if parent is None:
        return ANONYMOUS_SCOPE
    if parent.type in (Kind.VARIABLE_DECLARATOR, Kind.PAIR, Kind.ASSIGNMENT_EXPRESSION) or (
        parent.type in FIELD_DEFINITIONS
    ):
        field = Field.LEFT if parent.type == Kind.ASSIGNMENT_EXPRESSION else Field.NAME
        if parent.type == Kind.PAIR:
            field = Field.KEY
        if parent.type in FIELD_DEFINITIONS:
            field = FIELD_NAME_FIELDS[parent.type]
        name_node = parent.child_by_field_name(field)
        if name_node is not None:
            return node_text(name_node)
    return ANONYMOUS_SCOPE


def block_statements(block: Node) -> list[Node]:
    return [child for child in block.named_children if child.type not in IGNORED_IN_BLOCK]


def first_expression(node: Node) -> Node | None:
    for child in node.named_children:
        if child.type != Kind.COMMENT:
            return child
    return None


def unwrap_parens(node: Node) -> Node:
    """The value inside any parentheses and TypeScript type wrappers around it."""
    current = node
    while current.type == Kind.PARENTHESIZED_EXPRESSION or current.type in TYPE_WRAPPERS:
        inner = _wrapped_value(current)
        if inner is None:
            return current
        current = inner
    return current


def _wrapped_value(node: Node) -> Node | None:
    if node.type == Kind.TYPE_ASSERTION:
        # `<T>x`: the type arguments come first, the value last.
        values = [
            c for c in node.named_children if c.type not in (Kind.COMMENT, Kind.TYPE_ARGUMENTS)
        ]
        return values[0] if len(values) == 1 else None
    return first_expression(node)


def _unwrap_await(node: Node) -> tuple[Node, bool]:
    if node.type == Kind.AWAIT_EXPRESSION:
        inner = first_expression(node)
        if inner is not None:
            return inner, True
    return node, False


def _callee_text(call: Node) -> str:
    if call.type == Kind.NEW_EXPRESSION:
        constructor = call.child_by_field_name(Field.CONSTRUCTOR)
        assert constructor is not None, "new_expression without a constructor field"
        return "new " + node_text(constructor)
    function = call.child_by_field_name(Field.FUNCTION)
    assert function is not None, "call_expression without a function field"
    return node_text(function)


ASSIGNMENT_TYPES = frozenset({Kind.ASSIGNMENT_EXPRESSION, Kind.AUGMENTED_ASSIGNMENT_EXPRESSION})


def _unwrap_assignment(node: Node) -> Node:
    if node.type in ASSIGNMENT_TYPES:
        right = node.child_by_field_name(Field.RIGHT)
        if right is not None:
            return right
    return node


def _attribute_operation(span: Span, statement: Node, value: Node) -> TryStatement:
    inner, awaited = _unwrap_await(unwrap_parens(_unwrap_assignment(value)))
    if inner.type not in (Kind.CALL_EXPRESSION, Kind.NEW_EXPRESSION):
        return TryStatement(span, None, f"statement value is not a call ({inner.type})")
    extra = count_kinds(statement, OPERATION_TYPES) - (1 if awaited else 0)
    if extra != 1:
        return TryStatement(
            span,
            None,
            f"statement performs {extra} operations; only one can be attributed to the boundary",
        )
    return TryStatement(span, _callee_text(inner), None)


def try_statement(source: SourceText, statement: Node) -> TryStatement:
    span = node_span(source, statement)
    kind = statement.type
    if kind in COMPOUND_STATEMENTS:
        return TryStatement(
            span, None, f"compound statement ({kind}) wraps more than one operation"
        )
    if kind == Kind.EXPRESSION_STATEMENT:
        value = first_expression(statement)
        if value is None:
            return TryStatement(span, None, "empty statement")
        return _attribute_operation(span, statement, value)
    if kind in (Kind.LEXICAL_DECLARATION, Kind.VARIABLE_DECLARATION):
        declarators = [c for c in statement.named_children if c.type == Kind.VARIABLE_DECLARATOR]
        if len(declarators) != 1:
            return TryStatement(span, None, "declaration binds more than one variable")
        value = declarators[0].child_by_field_name(Field.VALUE)
        if value is None:
            return TryStatement(span, None, "declaration has no value")
        return _attribute_operation(span, statement, value)
    if kind == Kind.RETURN_STATEMENT:
        value = first_expression(statement)
        if value is None:
            return TryStatement(span, None, "statement (return) does not perform a call")
        return _attribute_operation(span, statement, value)
    return TryStatement(span, None, f"statement ({kind}) does not perform a call")


def is_literal_like(node: Node) -> bool:
    kind = node.type
    if kind in LITERAL_TYPES:
        return True
    if kind == Kind.PARENTHESIZED_EXPRESSION:
        inner = first_expression(node)
        return inner is not None and is_literal_like(inner)
    if kind == Kind.UNARY_EXPRESSION:
        argument = node.child_by_field_name(Field.ARGUMENT)
        return argument is not None and argument.type == Kind.NUMBER
    if kind == Kind.TEMPLATE_STRING:
        return all(child.type != Kind.TEMPLATE_SUBSTITUTION for child in node.named_children)
    if kind == Kind.ARRAY:
        return all(
            is_literal_like(child) for child in node.named_children if child.type != Kind.COMMENT
        )
    if kind == Kind.OBJECT:
        for child in node.named_children:
            if child.type == Kind.COMMENT:
                continue
            if child.type != Kind.PAIR:
                return False
            value = child.child_by_field_name(Field.VALUE)
            if value is None or not is_literal_like(value):
                return False
        return True
    return False


def _callee_name(statement: Node) -> str | None:
    expression = (
        statement if statement.type == Kind.CALL_EXPRESSION else first_expression(statement)
    )
    if expression is None or expression.type != Kind.CALL_EXPRESSION:
        return None
    function = expression.child_by_field_name(Field.FUNCTION)
    if function is None:
        return None
    return node_text(function)


def is_logging_statement(statement: Node) -> bool:
    if statement.type != Kind.EXPRESSION_STATEMENT:
        return False
    return is_logging_expression(statement)


def is_logging_expression(node: Node) -> bool:
    """``console.error(e)``, ``logger.warn(e)``, ``log(e)``: a call that only records."""
    name = _callee_name(node)
    if name is None:
        return False
    return name in LOGGING_EXACT or LOGGING_CALL.match(name) is not None


def _is_throw_of(statement: Node, name: str | None) -> bool:
    if statement.type != Kind.THROW_STATEMENT or name is None:
        return False
    thrown = first_expression(statement)
    return thrown is not None and thrown.type == Kind.IDENTIFIER and node_text(thrown) == name


def _single_statement(node: Node) -> Node | None:
    """The one statement in a block (or the statement itself when not a block)."""
    if node.type != Kind.STATEMENT_BLOCK:
        return node
    statements = block_statements(node)
    if len(statements) != 1:
        return None
    return statements[0]


def _instanceof_class(expression: Node, name: str | None) -> str | None:
    """``name instanceof C`` -> ``"C"``."""
    if expression.type != Kind.BINARY_EXPRESSION or name is None:
        return None
    operator = expression.child_by_field_name(Field.OPERATOR)
    left = expression.child_by_field_name(Field.LEFT)
    right = expression.child_by_field_name(Field.RIGHT)
    if operator is None or left is None or right is None or node_text(operator) != Kind.INSTANCEOF:
        return None
    if left.type != Kind.IDENTIFIER or node_text(left) != name:
        return None
    if right.type not in (Kind.IDENTIFIER, Kind.MEMBER_EXPRESSION):
        return None
    return node_text(right)


def _guard(statements: list[Node], name: str | None) -> tuple[str | None, list[Node]]:
    """Recognize a leading instanceof guard. Returns (class name, remaining statements)."""
    if len(statements) == 0 or statements[0].type != Kind.IF_STATEMENT:
        return None, statements
    guard = statements[0]
    condition = guard.child_by_field_name(Field.CONDITION)
    consequence = guard.child_by_field_name(Field.CONSEQUENCE)
    alternative = guard.child_by_field_name(Field.ALTERNATIVE)
    if condition is None or consequence is None:
        return None, statements
    test = unwrap_parens(condition)
    rest = statements[1:]
    if test.type == Kind.UNARY_EXPRESSION:
        operator = test.child_by_field_name(Field.OPERATOR)
        argument = test.child_by_field_name(Field.ARGUMENT)
        if operator is None or argument is None or node_text(operator) != "!":
            return None, statements
        klass = _instanceof_class(unwrap_parens(argument), name)
        single = _single_statement(consequence)
        if klass is None or alternative is not None or single is None:
            return None, statements
        if not _is_throw_of(single, name):
            return None, statements
        return klass, rest
    klass = _instanceof_class(test, name)
    if klass is None or alternative is None:
        return None, statements
    else_body = first_expression(alternative)
    if else_body is None:
        return None, statements
    single = _single_statement(else_body)
    if single is None or not _is_throw_of(single, name):
        return None, statements
    if consequence.type == Kind.STATEMENT_BLOCK:
        return klass, block_statements(consequence) + rest
    return klass, [consequence, *rest]


def _classify_throw(statement: Node, name: str | None) -> HandlerBody:
    thrown = first_expression(statement)
    described = node_text(statement).split("\n")[0].strip()
    if thrown is None:
        return HandlerBody(BODY_RAISE_OTHER, described)
    if thrown.type == Kind.IDENTIFIER and name is not None and node_text(thrown) == name:
        return HandlerBody(BODY_RERAISE, described)
    if thrown.type == Kind.NEW_EXPRESSION and _preserves_cause(thrown, name):
        return HandlerBody(BODY_RAISE_CHAINED, described)
    return HandlerBody(BODY_RAISE_OTHER, f"{described} (cause is not preserved)")


def _preserves_cause(new_expression: Node, name: str | None) -> bool:
    arguments = new_expression.child_by_field_name(Field.ARGUMENTS)
    if arguments is None or name is None:
        return False
    for argument in arguments.named_children:
        if argument.type != Kind.OBJECT:
            continue
        for member in argument.named_children:
            if member.type == Kind.SHORTHAND_PROPERTY_IDENTIFIER and node_text(member) == "cause":
                return name == "cause"
            if member.type != Kind.PAIR:
                continue
            key = member.child_by_field_name(Field.KEY)
            value = member.child_by_field_name(Field.VALUE)
            if key is None or value is None or node_text(key) != "cause":
                continue
            return value.type == Kind.IDENTIFIER and node_text(value) == name
    return False


def classify_statements(statements: list[Node], name: str | None) -> HandlerBody:
    if len(statements) == 0:
        return HandlerBody(BODY_EMPTY, "handler body is empty; the failure vanishes")
    remaining = [s for s in statements if not is_logging_statement(s)]
    if len(remaining) == 0:
        return HandlerBody(
            BODY_LOGGING_ONLY, "handler only logs; the failure is recorded, not handled"
        )
    if len(remaining) != 1:
        return HandlerBody(BODY_OTHER, "handler body is not classified")
    statement = remaining[0]
    if statement.type == Kind.RETURN_STATEMENT:
        value = first_expression(statement)
        if value is None or is_literal_like(value):
            return HandlerBody(BODY_RETURN_FALLBACK, node_text(statement).strip())
        return HandlerBody(BODY_OTHER, "handler body is not classified")
    if statement.type == Kind.THROW_STATEMENT:
        return _classify_throw(statement, name)
    return HandlerBody(BODY_OTHER, "handler body is not classified")


def guard_call(statements: list[Node], name: str | None) -> str | None:
    """The callee, as written, when the first statement is ``callee(<caught>)``."""
    if name is None or len(statements) == 0:
        return None
    first = statements[0]
    if first.type != Kind.EXPRESSION_STATEMENT:
        return None
    call = first_expression(first)
    if call is None or call.type != Kind.CALL_EXPRESSION:
        return None
    function = call.child_by_field_name(Field.FUNCTION)
    arguments = call.child_by_field_name(Field.ARGUMENTS)
    if function is None or arguments is None:
        return None
    if function.type not in (Kind.IDENTIFIER, Kind.MEMBER_EXPRESSION):
        return None
    actual = [a for a in arguments.named_children if a.type != Kind.COMMENT]
    if len(actual) != 1 or actual[0].type != Kind.IDENTIFIER or node_text(actual[0]) != name:
        return None
    return node_text(function)


def _guard_body(statements: list[Node], name: str | None) -> HandlerBody | None:
    if guard_call(statements, name) is None:
        return None
    return classify_statements(statements[1:], name)


def _parameter_name(parameter: Node | None) -> str | None:
    if parameter is None:
        return None
    if parameter.type == Kind.IDENTIFIER:
        return node_text(parameter)
    if parameter.type == Kind.FORMAL_PARAMETERS:
        first = first_expression(parameter)
        if first is None:
            return None
        binding, _default = parameter_parts(first)
        if binding.type == Kind.IDENTIFIER:
            return node_text(binding)
    return None


def _identities(klass: str | None) -> tuple[ExceptionIdentity, ...]:
    if klass is None:
        return ()
    return (ExceptionIdentity(klass, klass, CONFIDENCE_APPROXIMATE, broad=False),)


def _catch_clause(source: SourceText, scope: str, try_node: Node, clause: Node) -> CatchFact:
    body = clause.child_by_field_name(Field.BODY)
    try_body = try_node.child_by_field_name(Field.BODY)
    assert body is not None and try_body is not None, "try/catch without a body field"
    statements = block_statements(body)
    name = _parameter_name(clause.child_by_field_name(Field.PARAMETER))
    klass, remaining = _guard(statements, name)
    protected = block_statements(try_body)
    return CatchFact(
        span=node_span(source, clause),
        kind=CATCH_CLAUSE,
        scope=scope,
        identities=_identities(klass),
        bare=klass is None,
        bound_name=name,
        body=classify_statements(remaining, name),
        try_statements=tuple(try_statement(source, s) for s in protected),
        narrowed_from=None,
        guard_call=guard_call(remaining, name),
        guard_body=_guard_body(remaining, name),
    )


def _receiver_statement(source: SourceText, receiver: Node) -> TryStatement:
    span = node_span(source, receiver)
    inner, _awaited = _unwrap_await(unwrap_parens(receiver))
    if inner.type not in (Kind.CALL_EXPRESSION, Kind.NEW_EXPRESSION):
        return TryStatement(
            span, None, f"rejection source ({inner.type}) is not a call; it cannot be attributed"
        )
    count = count_kinds(inner, OPERATION_TYPES)
    if count != 1:
        return TryStatement(
            span, None, f"promise chain performs {count} operations before the rejection handler"
        )
    return TryStatement(span, _callee_text(inner), None)


def _rejection_handler(
    source: SourceText,
    scope: str,
    call: Node,
    member: Node,
    handler: Node,
    kind: str,
    functions: dict[str, Node],
) -> CatchFact:
    receiver = member.child_by_field_name(Field.OBJECT)
    property_node = member.child_by_field_name(Field.PROPERTY)
    assert receiver is not None and property_node is not None, "member_expression without fields"
    start_span = node_span(source, property_node)
    end_span = node_span(source, call)
    span = Span(start_span.line, start_span.column, end_span.end_line, end_span.end_column)
    protected = (_receiver_statement(source, receiver),)
    if handler.type == Kind.IDENTIFIER and node_text(handler) in functions:
        handler = functions[node_text(handler)]  # a reference to a module-level function
    if handler.type not in FUNCTION_NODE_TYPES:
        return CatchFact(
            span=span,
            kind=kind,
            scope=scope,
            identities=(),
            bare=True,
            bound_name=None,
            body=HandlerBody(
                BODY_OPAQUE,
                f"rejection handler {node_text(handler)!r} is not an inline function or a "
                "function defined at the top level of this module; its behaviour cannot be "
                "inspected",
            ),
            try_statements=protected,
            narrowed_from=None,
            guard_call=None,
            guard_body=None,
        )
    parameter = handler.child_by_field_name(Field.PARAMETER)
    if parameter is None:
        parameter = handler.child_by_field_name(Field.PARAMETERS)
    name = _parameter_name(parameter)
    body = handler.child_by_field_name(Field.BODY)
    if body is None:
        statements: list[Node] = []
        classified = HandlerBody(BODY_OTHER, "handler body is not classified")
        klass = None
    elif body.type == Kind.STATEMENT_BLOCK:
        klass, statements = _guard(block_statements(body), name)
        classified = classify_statements(statements, name)
    else:
        klass = None
        statements = []  # an expression body has no statements and cannot open with a guard
        if is_literal_like(body):
            classified = HandlerBody(BODY_RETURN_FALLBACK, "=> " + node_text(body).strip())
        elif is_logging_expression(unwrap_parens(body)):
            classified = HandlerBody(
                BODY_LOGGING_ONLY, "handler only logs; the failure is recorded, not handled"
            )
        else:
            classified = HandlerBody(BODY_OTHER, "handler body is not classified")
    return CatchFact(
        span=span,
        kind=kind,
        scope=scope,
        identities=_identities(klass),
        bare=klass is None,
        bound_name=name,
        body=classified,
        try_statements=protected,
        narrowed_from=None,
        guard_call=guard_call(statements, name),
        guard_body=_guard_body(statements, name),
    )


FUNCTION_NODE_TYPES = frozenset(
    {Kind.FUNCTION_DECLARATION, Kind.ARROW_FUNCTION, Kind.FUNCTION_EXPRESSION}
)


def module_functions(root: Node) -> dict[str, Node]:
    """Top-level functions by name: declarations (exported or not) and ``const``/``let``
    bindings to an arrow or function expression."""
    found: dict[str, Node] = {}
    for statement in root.named_children:
        node = statement
        if node.type == Kind.EXPORT_STATEMENT:
            exported = node.child_by_field_name(Field.DECLARATION)
            if exported is None:
                continue
            node = exported
        if node.type == Kind.FUNCTION_DECLARATION:
            name = node.child_by_field_name(Field.NAME)
            if name is not None:
                found[node_text(name)] = node
        elif node.type in (Kind.LEXICAL_DECLARATION, Kind.VARIABLE_DECLARATION):
            for declarator in node.named_children:
                if declarator.type != Kind.VARIABLE_DECLARATOR:
                    continue
                name = declarator.child_by_field_name(Field.NAME)
                value = declarator.child_by_field_name(Field.VALUE)
                if name is None or value is None or name.type != Kind.IDENTIFIER:
                    continue
                if value.type in FUNCTION_NODE_TYPES:
                    found[node_text(name)] = value
    return found


def _promise_handler(call: Node) -> tuple[Node, Node, str] | None:
    """``x.catch(h)`` / ``x.then(ok, h)`` -> (member_expression, handler node, kind)."""
    function = call.child_by_field_name(Field.FUNCTION)
    arguments = call.child_by_field_name(Field.ARGUMENTS)
    if function is None or arguments is None or function.type != Kind.MEMBER_EXPRESSION:
        return None
    property_node = function.child_by_field_name(Field.PROPERTY)
    if property_node is None:
        return None
    method = node_text(property_node)
    if method not in REJECTION_HANDLER_ARGS:
        return None
    actual = [a for a in arguments.named_children if a.type != Kind.COMMENT]
    index = REJECTION_HANDLER_ARGS[method]
    if len(actual) <= index:
        return None
    kind = CATCH_PROMISE if method == "catch" else CATCH_PROMISE_THEN
    return function, actual[index], kind


def collect_javascript_catches(source: SourceText, root: Node) -> tuple[CatchFact, ...]:
    catches: list[CatchFact] = []
    functions = module_functions(root)
    stack: list[tuple[Node, str]] = [(root, MODULE_SCOPE)]
    while len(stack) > 0:
        node, scope = stack.pop()
        if node.type == Kind.TRY_STATEMENT:
            handler = node.child_by_field_name(Field.HANDLER)
            if handler is not None:
                catches.append(_catch_clause(source, scope, node, handler))
        elif node.type == Kind.CALL_EXPRESSION:
            promise = _promise_handler(node)
            if promise is not None:
                member, handler, kind = promise
                catches.append(
                    _rejection_handler(source, scope, node, member, handler, kind, functions)
                )
        child_scope = scope_for(node, scope)
        for child in reversed(node.children):
            stack.append((child, child_scope))
    catches.sort(key=lambda catch: catch.span)
    return tuple(catches)
