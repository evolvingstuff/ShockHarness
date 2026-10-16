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

from shockharness.constants import FIRST_LINE
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
from shockharness.source import SourceText

NAMED_SCOPE_TYPES = frozenset(
    {
        "function_declaration",
        "generator_function_declaration",
        "class_declaration",
        "method_definition",
    }
)
ANONYMOUS_FUNCTION_TYPES = frozenset(
    {"arrow_function", "function_expression", "generator_function", "class"}
)
IGNORED_IN_BLOCK = frozenset({"comment", "empty_statement"})
COMPOUND_STATEMENTS = frozenset(
    {
        "if_statement",
        "for_statement",
        "for_in_statement",
        "while_statement",
        "do_statement",
        "try_statement",
        "switch_statement",
        "with_statement",
        "labeled_statement",
        "statement_block",
        "function_declaration",
        "generator_function_declaration",
        "class_declaration",
    }
)
OPERATION_TYPES = frozenset(
    {
        "call_expression",
        "new_expression",
        "arrow_function",
        "function_expression",
        "generator_function",
        "await_expression",
        "yield_expression",
    }
)
LITERAL_TYPES = frozenset({"null", "undefined", "true", "false", "number", "string"})
LOGGING_CALL = re.compile(
    r"^(?:[A-Za-z_$][A-Za-z0-9_$]*\.)*"
    r"(?:console|logger|log|LOGGER|LOG|_logger|_log)"
    r"\.(?:log|debug|info|warn|warning|error|exception|critical|fatal|trace|dir)$"
)
LOGGING_EXACT = frozenset({"process.stderr.write", "process.stdout.write", "log"})
REJECTION_HANDLER_ARGS = {"catch": 0, "then": 1}


def node_span(source: SourceText, node: Node) -> Span:
    start_line = node.start_point.row + FIRST_LINE
    end_line = node.end_point.row + FIRST_LINE
    return Span(
        line=start_line,
        column=source.column_from_byte_offset(start_line, node.start_point.column),
        end_line=end_line,
        end_column=source.column_from_byte_offset(end_line, node.end_point.column),
    )


def node_text(node: Node) -> str:
    if node.text is None:
        return ""
    return node.text.decode("utf-8", errors="replace")


def scope_for(node: Node, scope: str) -> str:
    if node.type in NAMED_SCOPE_TYPES:
        name_node = node.child_by_field_name("name")
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
    if parent.type in ("variable_declarator", "pair", "field_definition", "assignment_expression"):
        field = "left" if parent.type == "assignment_expression" else "name"
        if parent.type == "pair":
            field = "key"
        if parent.type == "field_definition":
            field = "property"
        name_node = parent.child_by_field_name(field)
        if name_node is not None:
            return node_text(name_node)
    return ANONYMOUS_SCOPE


def block_statements(block: Node) -> list[Node]:
    return [child for child in block.named_children if child.type not in IGNORED_IN_BLOCK]


def first_expression(node: Node) -> Node | None:
    for child in node.named_children:
        if child.type != "comment":
            return child
    return None


def unwrap_parens(node: Node) -> Node:
    current = node
    while current.type == "parenthesized_expression":
        inner = first_expression(current)
        if inner is None:
            return current
        current = inner
    return current


def _unwrap_await(node: Node) -> tuple[Node, bool]:
    if node.type == "await_expression":
        inner = first_expression(node)
        if inner is not None:
            return inner, True
    return node, False


def _count_operations(node: Node) -> int:
    count = 0
    stack = [node]
    while len(stack) > 0:
        current = stack.pop()
        if current.type in OPERATION_TYPES:
            count += 1
        stack.extend(current.children)
    return count


def _callee_text(call: Node) -> str:
    if call.type == "new_expression":
        constructor = call.child_by_field_name("constructor")
        assert constructor is not None, "new_expression without a constructor field"
        return "new " + node_text(constructor)
    function = call.child_by_field_name("function")
    assert function is not None, "call_expression without a function field"
    return node_text(function)


ASSIGNMENT_TYPES = frozenset({"assignment_expression", "augmented_assignment_expression"})


def _unwrap_assignment(node: Node) -> Node:
    if node.type in ASSIGNMENT_TYPES:
        right = node.child_by_field_name("right")
        if right is not None:
            return right
    return node


def _attribute_operation(span: Span, statement: Node, value: Node) -> TryStatement:
    inner, awaited = _unwrap_await(unwrap_parens(_unwrap_assignment(value)))
    if inner.type not in ("call_expression", "new_expression"):
        return TryStatement(span, None, f"statement value is not a call ({inner.type})")
    extra = _count_operations(statement) - (1 if awaited else 0)
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
    if kind == "expression_statement":
        value = first_expression(statement)
        if value is None:
            return TryStatement(span, None, "empty statement")
        return _attribute_operation(span, statement, value)
    if kind in ("lexical_declaration", "variable_declaration"):
        declarators = [c for c in statement.named_children if c.type == "variable_declarator"]
        if len(declarators) != 1:
            return TryStatement(span, None, "declaration binds more than one variable")
        value = declarators[0].child_by_field_name("value")
        if value is None:
            return TryStatement(span, None, "declaration has no value")
        return _attribute_operation(span, statement, value)
    if kind == "return_statement":
        value = first_expression(statement)
        if value is None:
            return TryStatement(span, None, "statement (return) does not perform a call")
        return _attribute_operation(span, statement, value)
    return TryStatement(span, None, f"statement ({kind}) does not perform a call")


def is_literal_like(node: Node) -> bool:
    kind = node.type
    if kind in LITERAL_TYPES:
        return True
    if kind == "parenthesized_expression":
        inner = first_expression(node)
        return inner is not None and is_literal_like(inner)
    if kind == "unary_expression":
        argument = node.child_by_field_name("argument")
        return argument is not None and argument.type == "number"
    if kind == "template_string":
        return all(child.type != "template_substitution" for child in node.named_children)
    if kind == "array":
        return all(
            is_literal_like(child) for child in node.named_children if child.type != "comment"
        )
    if kind == "object":
        for child in node.named_children:
            if child.type == "comment":
                continue
            if child.type != "pair":
                return False
            value = child.child_by_field_name("value")
            if value is None or not is_literal_like(value):
                return False
        return True
    return False


def _callee_name(statement: Node) -> str | None:
    expression = statement if statement.type == "call_expression" else first_expression(statement)
    if expression is None or expression.type != "call_expression":
        return None
    function = expression.child_by_field_name("function")
    if function is None:
        return None
    return node_text(function)


def is_logging_statement(statement: Node) -> bool:
    if statement.type != "expression_statement":
        return False
    return is_logging_expression(statement)


def is_logging_expression(node: Node) -> bool:
    """``console.error(e)``, ``logger.warn(e)``, ``log(e)``: a call that only records."""
    name = _callee_name(node)
    if name is None:
        return False
    return name in LOGGING_EXACT or LOGGING_CALL.match(name) is not None


def _is_throw_of(statement: Node, name: str | None) -> bool:
    if statement.type != "throw_statement" or name is None:
        return False
    thrown = first_expression(statement)
    return thrown is not None and thrown.type == "identifier" and node_text(thrown) == name


def _single_statement(node: Node) -> Node | None:
    """The one statement in a block (or the statement itself when not a block)."""
    if node.type != "statement_block":
        return node
    statements = block_statements(node)
    if len(statements) != 1:
        return None
    return statements[0]


def _instanceof_class(expression: Node, name: str | None) -> str | None:
    """``name instanceof C`` -> ``"C"``."""
    if expression.type != "binary_expression" or name is None:
        return None
    operator = expression.child_by_field_name("operator")
    left = expression.child_by_field_name("left")
    right = expression.child_by_field_name("right")
    if operator is None or left is None or right is None or node_text(operator) != "instanceof":
        return None
    if left.type != "identifier" or node_text(left) != name:
        return None
    if right.type not in ("identifier", "member_expression"):
        return None
    return node_text(right)


def _guard(statements: list[Node], name: str | None) -> tuple[str | None, list[Node]]:
    """Recognize a leading instanceof guard. Returns (class name, remaining statements)."""
    if len(statements) == 0 or statements[0].type != "if_statement":
        return None, statements
    guard = statements[0]
    condition = guard.child_by_field_name("condition")
    consequence = guard.child_by_field_name("consequence")
    alternative = guard.child_by_field_name("alternative")
    if condition is None or consequence is None:
        return None, statements
    test = unwrap_parens(condition)
    rest = statements[1:]
    if test.type == "unary_expression":
        operator = test.child_by_field_name("operator")
        argument = test.child_by_field_name("argument")
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
    if consequence.type == "statement_block":
        return klass, block_statements(consequence) + rest
    return klass, [consequence, *rest]


def _classify_throw(statement: Node, name: str | None) -> HandlerBody:
    thrown = first_expression(statement)
    described = node_text(statement).split("\n")[0].strip()
    if thrown is None:
        return HandlerBody(BODY_RAISE_OTHER, described)
    if thrown.type == "identifier" and name is not None and node_text(thrown) == name:
        return HandlerBody(BODY_RERAISE, described)
    if thrown.type == "new_expression" and _preserves_cause(thrown, name):
        return HandlerBody(BODY_RAISE_CHAINED, described)
    return HandlerBody(BODY_RAISE_OTHER, f"{described} (cause is not preserved)")


def _preserves_cause(new_expression: Node, name: str | None) -> bool:
    arguments = new_expression.child_by_field_name("arguments")
    if arguments is None or name is None:
        return False
    for argument in arguments.named_children:
        if argument.type != "object":
            continue
        for member in argument.named_children:
            if member.type == "shorthand_property_identifier" and node_text(member) == "cause":
                return name == "cause"
            if member.type != "pair":
                continue
            key = member.child_by_field_name("key")
            value = member.child_by_field_name("value")
            if key is None or value is None or node_text(key) != "cause":
                continue
            return value.type == "identifier" and node_text(value) == name
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
    if statement.type == "return_statement":
        value = first_expression(statement)
        if value is None or is_literal_like(value):
            return HandlerBody(BODY_RETURN_FALLBACK, node_text(statement).strip())
        return HandlerBody(BODY_OTHER, "handler body is not classified")
    if statement.type == "throw_statement":
        return _classify_throw(statement, name)
    return HandlerBody(BODY_OTHER, "handler body is not classified")


def guard_call(statements: list[Node], name: str | None) -> str | None:
    """The callee, as written, when the first statement is ``callee(<caught>)``."""
    if name is None or len(statements) == 0:
        return None
    first = statements[0]
    if first.type != "expression_statement":
        return None
    call = first_expression(first)
    if call is None or call.type != "call_expression":
        return None
    function = call.child_by_field_name("function")
    arguments = call.child_by_field_name("arguments")
    if function is None or arguments is None:
        return None
    if function.type not in ("identifier", "member_expression"):
        return None
    actual = [a for a in arguments.named_children if a.type != "comment"]
    if len(actual) != 1 or actual[0].type != "identifier" or node_text(actual[0]) != name:
        return None
    return node_text(function)


def _guard_body(statements: list[Node], name: str | None) -> HandlerBody | None:
    if guard_call(statements, name) is None:
        return None
    return classify_statements(statements[1:], name)


def _parameter_name(parameter: Node | None) -> str | None:
    if parameter is None:
        return None
    if parameter.type == "identifier":
        return node_text(parameter)
    if parameter.type == "formal_parameters":
        first = first_expression(parameter)
        if first is not None and first.type == "identifier":
            return node_text(first)
    return None


def _identities(klass: str | None) -> tuple[ExceptionIdentity, ...]:
    if klass is None:
        return ()
    return (ExceptionIdentity(klass, klass, CONFIDENCE_APPROXIMATE, broad=False),)


def _catch_clause(source: SourceText, scope: str, try_node: Node, clause: Node) -> CatchFact:
    body = clause.child_by_field_name("body")
    try_body = try_node.child_by_field_name("body")
    assert body is not None and try_body is not None, "try/catch without a body field"
    statements = block_statements(body)
    name = _parameter_name(clause.child_by_field_name("parameter"))
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
    if inner.type not in ("call_expression", "new_expression"):
        return TryStatement(
            span, None, f"rejection source ({inner.type}) is not a call; it cannot be attributed"
        )
    count = _count_operations(inner)
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
    receiver = member.child_by_field_name("object")
    property_node = member.child_by_field_name("property")
    assert receiver is not None and property_node is not None, "member_expression without fields"
    start_span = node_span(source, property_node)
    end_span = node_span(source, call)
    span = Span(start_span.line, start_span.column, end_span.end_line, end_span.end_column)
    protected = (_receiver_statement(source, receiver),)
    if handler.type == "identifier" and node_text(handler) in functions:
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
    parameter = handler.child_by_field_name("parameter")
    if parameter is None:
        parameter = handler.child_by_field_name("parameters")
    name = _parameter_name(parameter)
    body = handler.child_by_field_name("body")
    if body is None:
        statements: list[Node] = []
        classified = HandlerBody(BODY_OTHER, "handler body is not classified")
        klass = None
    elif body.type == "statement_block":
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


FUNCTION_NODE_TYPES = frozenset({"function_declaration", "arrow_function", "function_expression"})


def module_functions(root: Node) -> dict[str, Node]:
    """Top-level functions by name: declarations (exported or not) and ``const``/``let``
    bindings to an arrow or function expression."""
    found: dict[str, Node] = {}
    for statement in root.named_children:
        node = statement
        if node.type == "export_statement":
            exported = node.child_by_field_name("declaration")
            if exported is None:
                continue
            node = exported
        if node.type == "function_declaration":
            name = node.child_by_field_name("name")
            if name is not None:
                found[node_text(name)] = node
        elif node.type in ("lexical_declaration", "variable_declaration"):
            for declarator in node.named_children:
                if declarator.type != "variable_declarator":
                    continue
                name = declarator.child_by_field_name("name")
                value = declarator.child_by_field_name("value")
                if name is None or value is None or name.type != "identifier":
                    continue
                if value.type in FUNCTION_NODE_TYPES:
                    found[node_text(name)] = value
    return found


def _promise_handler(call: Node) -> tuple[Node, Node, str] | None:
    """``x.catch(h)`` / ``x.then(ok, h)`` -> (member_expression, handler node, kind)."""
    function = call.child_by_field_name("function")
    arguments = call.child_by_field_name("arguments")
    if function is None or arguments is None or function.type != "member_expression":
        return None
    property_node = function.child_by_field_name("property")
    if property_node is None:
        return None
    method = node_text(property_node)
    if method not in REJECTION_HANDLER_ARGS:
        return None
    actual = [a for a in arguments.named_children if a.type != "comment"]
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
        if node.type == "try_statement":
            handler = node.child_by_field_name("handler")
            if handler is not None:
                catches.append(_catch_clause(source, scope, node, handler))
        elif node.type == "call_expression":
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
