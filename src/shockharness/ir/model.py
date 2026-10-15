"""IR data model shared by the Python and JavaScript adapters.

Rules consume these facts and never touch parser-specific nodes. Every fact keeps
its source span and enclosing scope so findings can be explained and sorted.
"""

from dataclasses import dataclass
from typing import Any

MODULE_SCOPE = "<module>"
ANONYMOUS_SCOPE = "<anonymous>"


@dataclass(frozen=True, order=True)
class Span:
    """1-based line and character column; ``end_column`` is exclusive."""

    line: int
    column: int
    end_line: int
    end_column: int

    def to_json_dict(self) -> dict[str, int]:
        return {
            "line": self.line,
            "column": self.column,
            "end_line": self.end_line,
            "end_column": self.end_column,
        }


@dataclass(frozen=True)
class NumericLiteral:
    """A numeric literal, with any chain of unary ``+``/``-`` folded into it.

    ``value`` is the folded value; ``negated`` is true when the folded sign is
    negative (so ``-0`` is negated with value ``0``). ``raw`` is the exact source
    text including the sign operators. ``constant_definition`` is true when the
    literal is the whole value of a module-level named constant definition
    (``MAX_PAGES = 8``, ``_WAIT: Final = 10.0``, ``const SETTLE_MS = 400``,
    ``export const N = -3``); ``rules.magic_numbers.named_constant_definitions``
    decides whether MAGIC001 reports it.
    """

    span: Span
    raw: str
    value: int | float | complex
    negated: bool
    in_annotation: bool
    scope: str
    constant_definition: bool


@dataclass(frozen=True)
class Comment:
    span: Span
    text: str


@dataclass(frozen=True)
class ParseFailure:
    span: Span | None
    message: str

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "span": None if self.span is None else self.span.to_json_dict(),
            "message": self.message,
        }


# Resolution confidence of an exception identity (shared with findings.py).
CONFIDENCE_EXACT = "exact"
CONFIDENCE_APPROXIMATE = "approximate"
CONFIDENCE_UNRESOLVED = "unresolved"

# Kinds of catch construct.
CATCH_EXCEPT = "except"  # Python ``except`` handler of ``try``
CATCH_EXCEPT_STAR = "except*"  # Python ``except*`` handler of ``try``
CATCH_CLAUSE = "catch"  # JavaScript ``catch`` clause of ``try``
CATCH_PROMISE = "promise.catch"  # JavaScript ``promise.catch(handler)``
CATCH_PROMISE_THEN = "promise.then"  # JavaScript ``promise.then(onFulfilled, onRejected)``
CATCH_MANAGER = "context manager"  # Python ``with suppress(T):`` / a configured capture manager

# Handler body classifications.
BODY_EMPTY = "empty"  # ``pass`` / ``...`` / ``{}``: the failure vanishes
BODY_LOGGING_ONLY = "logging_only"  # only logging/printing statements
BODY_RETURN_FALLBACK = "return_fallback"  # returns a literal / None / null / undefined / false / 0
BODY_RERAISE = "reraise"  # bare ``raise`` / ``raise err`` / ``throw err``: transparent
BODY_RAISE_CHAINED = "raise_chained"  # ``raise X from err`` / ``throw new E(.., {cause: err})``
BODY_RAISE_OTHER = "raise_other"  # raises a different exception without preserving the cause
BODY_OTHER = "other"  # anything else; not classified
BODY_OPAQUE = "opaque"  # handler is a reference, not inline code; cannot be inspected

BROAD_IDENTITIES = frozenset({"Exception", "BaseException"})


@dataclass(frozen=True)
class ExceptionIdentity:
    """One exception type named by a handler, resolved as far as static analysis allows.

    ``qualified`` is the best-effort dotted name (``"OSError"`` for a builtin,
    ``"requests.exceptions.Timeout"`` through imports, ``".errors.MyError"`` for
    a relative import, ``"pkg.mod.MyError"`` for a class defined in the module)
    or ``None`` when the identity could not be resolved. ``confidence`` says how
    much the name can be trusted. ``broad`` is true for ``Exception`` and
    ``BaseException`` (and for an untyped JavaScript catch).
    """

    source: str
    qualified: str | None
    confidence: str
    broad: bool


@dataclass(frozen=True)
class HandlerBody:
    classification: str
    detail: str


@dataclass(frozen=True)
class TryStatement:
    """One statement of a ``try`` body, attributed to a single operation when possible.

    ``operation`` is the text of the one call (or import) the statement performs;
    ``reason`` explains why no single operation could be attributed.
    """

    span: Span
    operation: str | None
    reason: str | None

    @property
    def attributable(self) -> bool:
        return self.operation is not None


@dataclass(frozen=True)
class CatchFact:
    """A catch construct: ``except``/``except*`` handler, ``catch`` clause, or rejection handler.

    ``identities`` is empty for a bare Python ``except`` and for a JavaScript
    catch with no recognized ``instanceof`` guard (``bare`` is true in both
    cases). ``bound_name`` is the variable the exception is bound to, if any.
    ``try_statements`` are the statements the handler protects; for a promise
    rejection handler it is the receiver expression of ``.catch``/``.then`` as a
    single pseudo-statement.

    Guards (0.2.0). ``narrowed_from`` is the type written on the handler when a
    leading ``if not isinstance(<caught>, T): raise`` (Python) narrowed
    ``identities`` to ``T``; ``body`` then classifies the statements after the
    guard, as it already does after a JavaScript ``instanceof`` guard (for which
    ``narrowed_from`` is ``None``: an untyped catch has nothing to narrow from).
    ``guard_call`` is the callee, as written, when the handler's first statement
    is a call with the caught exception as its only argument
    (``rethrowUnexpectedError(error)``); ``guard_body`` classifies the statements
    after that call. Whether the call counts as a guard is the rule's decision
    (``rules.exceptions.transparent_guards``), not the adapter's.
    """

    span: Span
    kind: str
    scope: str
    identities: tuple[ExceptionIdentity, ...]
    bare: bool
    bound_name: str | None
    body: HandlerBody
    try_statements: tuple[TryStatement, ...]
    narrowed_from: str | None
    guard_call: str | None
    guard_body: HandlerBody | None


@dataclass(frozen=True)
class ManagerFact:
    """A ``with`` item whose context expression is a call: a candidate exception capture.

    The adapter records every such item (``with open(p) as f:`` included) because it
    does not know which managers catch; ``rules.exceptions`` turns the ones that do
    (``contextlib.suppress`` and the configured ``capture_managers``) into
    :class:`CatchFact` entries of kind ``context manager``. ``qualified`` and
    ``confidence`` are the callee resolved through the module's symbol table;
    ``identities`` are the positional arguments that resolve as exception types;
    ``unreadable_arguments`` counts positional arguments that are not names (a
    string, a call); keyword arguments are ignored. ``body_statements`` are the
    ``with`` body, attributed like a ``try`` body.
    """

    span: Span
    scope: str
    callee: str
    qualified: str | None
    confidence: str
    identities: tuple[ExceptionIdentity, ...]
    unreadable_arguments: int
    bound_name: str | None
    body_statements: tuple[TryStatement, ...]


# Default/fallback fact families (one rule each; see rules/defaults.py).
FAMILY_PARAMETER = "parameter"  # DEF001: parameter and dataclass field defaults
FAMILY_MAPPING = "mapping"  # DEF002: mapping / attribute / property fallbacks
FAMILY_TRUTHINESS = "truthiness"  # DEF003: ``x or v`` / ``x || v``
FAMILY_NULLISH = "nullish"  # DEF004: ``x ?? v`` / ``x if x is not None else v``
FAMILY_EXCEPTION = (
    "exception"  # DEF005: handler returns a traced default (literal returns come from CatchFact)
)
FAMILY_CONFIGURATION = "configuration"  # DEF006: environment-variable fallbacks

# Default/fallback fact kinds (the concrete shape within a family).
KIND_PARAMETER = "parameter"  # def f(x=v) / function f(x = v) / lambda x=v
KIND_PARAMETER_DESTRUCTURING = "parameter_destructuring"  # function f({x = v}) / f([x = v])
KIND_DATACLASS_FIELD = "dataclass_field"  # x: int = v inside a @dataclass body
KIND_DATACLASS_FACTORY = "dataclass_default_factory"  # x: list = field(default_factory=list)
KIND_NEXT_DEFAULT = "next_default"  # next(iterator, v): v when the iterator is exhausted
KIND_DEFAULTDICT = (
    "defaultdict"  # collections.defaultdict(factory): every missing key gets factory()
)
KIND_MAPPING_GET = "mapping_get"  # m.get(k, v) / m.setdefault(k, v) / m.pop(k, v)
KIND_MAPPING_GET_IMPLICIT = "mapping_get_implicit"  # m.get(k): None when the key is missing
KIND_GETATTR = "getattr"  # getattr(o, name, v)
KIND_MEMBERSHIP_TERNARY = "membership_ternary"  # m[k] if k in m else v / k in o ? o[k] : v
KIND_DESTRUCTURING = "destructuring"  # const {x = v} = o / const [x = v] = a
KIND_MEMBER_NULLISH = "member_nullish"  # obj?.x ?? v / obj.x ?? v / m.get(k) ?? v
KIND_TRUTHINESS_OR = "or"  # x or v / x || v (and chains ending in v)
KIND_TRUTHINESS_ASSIGN = "or_assign"  # x ||= v
KIND_TRUTHINESS_TERNARY = "truthiness_ternary"  # x if x else v / x ? x : v
KIND_NULLISH_COALESCE = "coalesce"  # x ?? v
KIND_NULLISH_ASSIGN = "coalesce_assign"  # x ??= v
KIND_NULLISH_TERNARY = "nullish_ternary"  # x if x is not None else v / x == null ? v : x
KIND_EXCEPTION_CONSTANT = "handler_returns_constant"  # except ...: return DEFAULT (module constant)
KIND_EXCEPTION_HELPER = (
    "handler_returns_helper"  # except ...: return fallback() (helper returns a literal)
)
KIND_ENV_GET = "env_get"  # os.getenv("X", v) / os.environ.get("X", v) / os.environ.setdefault
KIND_ENV_GET_IMPLICIT = "env_get_implicit"  # os.getenv("X") / os.environ.get("X"): None when unset
KIND_ENV_TRUTHINESS = "env_or"  # process.env.X || v / os.environ.get("X") or v
KIND_ENV_NULLISH = "env_coalesce"  # process.env.X ?? v
KIND_ENV_DESTRUCTURING = "env_destructuring"  # const { X = v } = process.env

# Syntactic context of a fallback expression.
CONTEXT_ASSIGNMENT = "assignment"  # value of an assignment, declaration, or object property
CONTEXT_RETURN = "return"  # returned value (or arrow-function expression body)
CONTEXT_ARGUMENT = "argument"  # call argument
CONTEXT_TEST = "test"  # condition of if/while/assert/ternary, or operand of not/comparison
CONTEXT_EXPRESSION = "expression"  # anything else
CONTEXT_DECLARATION = "declaration"  # the construct is a declaration (parameter, field, pattern)


@dataclass(frozen=True)
class DefaultFact:
    """One place where source code substitutes a value for something that is absent.

    ``subject`` is the thing being defaulted as written (a parameter name, a key,
    the left operand); ``fallback`` is the substituted expression as written and
    ``fallback_constant`` says whether it is literal- or constant-shaped (a
    literal, a container of literals, an UPPER_CASE name, or an empty
    constructor call). ``context`` is where the expression sits. ``confidence``
    is ``exact`` when the shape is unambiguous and ``approximate`` when the
    analyzer could not establish a type (the receiver of ``.get``) or an
    intent (a non-constant right operand of ``or``). ``detail`` explains the
    judgement in words.
    """

    span: Span
    scope: str
    family: str
    kind: str
    subject: str
    fallback: str
    fallback_constant: bool
    context: str
    confidence: str
    detail: str


# Control-tree node kinds (Milestone E). Both adapters reduce a unit's body to this
# language-neutral tree; the complexity metrics read only the tree, so two units with
# the same tree get the same numbers whatever language they were written in.
CK_BLOCK = "block"  # a statement list; children are the control-relevant statements
CK_IF = "if"  # children: condition EXPR, then BLOCK, optional else (BLOCK or an elif IF)
CK_ELIF = "elif"  # an IF that continues a chain (``elif`` / ``else if``); same children as IF
CK_LOOP = "loop"  # children: condition EXPR, body BLOCK, optional else BLOCK (Python)
CK_TRY = "try"  # children: body BLOCK, HANDLER..., optional TRY_ELSE, optional FINALLY
CK_HANDLER = "handler"  # one except/catch clause; children are its statements
CK_TRY_ELSE = "try_else"  # Python ``try/else`` body
CK_FINALLY = "finally"
CK_SWITCH = "switch"  # children: subject EXPR, CASE...
CK_CASE = "case"  # children: guard EXPR, body BLOCK; label "default" for default/wildcard arms
CK_CONDITIONAL = "conditional"  # ternary: children: condition EXPR, then EXPR, else EXPR
CK_EXPR = "expr"  # an expression summary: boolean operators/sequences plus nested nodes
CK_RECURSION = "recursion"  # a direct call of the unit's own name
CK_JUMP = "jump"  # a labeled break/continue (JavaScript); Python never emits one

LOOP_FOR = "for"
LOOP_WHILE = "while"
LOOP_DO = "do"
LOOP_COMPREHENSION = "comprehension"
CASE_DEFAULT = "default"

# Unit kinds.
UNIT_MODULE = "module"
UNIT_CLASS = "class"
UNIT_FUNCTION = "function"
UNIT_METHOD = "method"
UNIT_LAMBDA = "lambda"
UNIT_ARROW = "arrow"

# Call-site shapes.
CALL_NAME = "name"  # f(x): a bare name is called
CALL_ATTRIBUTE = "attribute"  # a.b.c(x): a dotted chain rooted in a name (or self/this)
CALL_DYNAMIC = "dynamic"  # o[k](), f()(), getattr(o, n)(), (cond ? f : g)(): the callee is computed
CALL_ARGUMENT = "argument"  # a bare name passed as an argument (higher-order use)
CALL_NEW = "new"  # JavaScript ``new C()``

# Import kinds.
IMPORT_MODULE = "module"  # import a.b / import * as ns / const m = require("m")
IMPORT_NAMES = "names"  # from a import b as c / import {b as c} from "a" / const {b} = require("a")
IMPORT_REEXPORT = "reexport"  # export {x} from "a" / export * from "a"
IMPORT_DYNAMIC = "dynamic"  # import(expr) / require(expr): the target is computed

# Module-level binding kinds.
BINDING_FUNCTION = "function"
BINDING_CLASS = "class"
BINDING_VARIABLE = "variable"
BINDING_IMPORT = "import"

# Kinds of write to a module-level binding from inside a unit.
WRITE_ASSIGN = "assign"  # rebinding (Python needs a ``global`` declaration; JavaScript ``x = v``)
WRITE_MUTATE = "mutate"  # in-place mutation: x.append(v), x[k] = v, x.k = v, x += v


@dataclass(frozen=True)
class ControlNode:
    """One node of a unit's control tree.

    ``operators`` and ``sequences`` are meaningful on EXPR nodes: the number of binary
    short-circuit operators in the expression (``and``/``or``, ``&&``/``||``/``??``,
    logical assignment) and the number of maximal runs of one operator in
    source order. ``label`` carries the loop form, ``elif``, or ``default``;
    ``labeled`` marks a JavaScript labeled jump.
    """

    kind: str
    children: tuple["ControlNode", ...]
    operators: int
    sequences: int
    label: str
    labeled: bool


EMPTY_EXPR = ControlNode(CK_EXPR, (), 0, 0, "", False)


def control_node(kind: str, children: tuple[ControlNode, ...], label: str) -> ControlNode:
    return ControlNode(kind, children, 0, 0, label, False)


def expr_node(operators: int, sequences: int, children: tuple[ControlNode, ...]) -> ControlNode:
    return ControlNode(CK_EXPR, children, operators, sequences, "", False)


@dataclass(frozen=True)
class CallSite:
    """A call performed inside a unit, as written, before any resolution.

    ``callee`` is the dotted text of the callee for ``name``/``attribute`` shapes
    (``"self.helper"``, ``"os.path.join"``), the argument name for ``argument``,
    and a short excerpt for ``dynamic``. ``receiver_self`` is true when the
    chain is rooted in the method's receiver (``self``/``cls``/``this``).
    """

    span: Span
    callee: str
    shape: str
    receiver_self: bool


@dataclass(frozen=True)
class FunctionFact:
    """One unit of measurement: a module body, class body, function, method, lambda or arrow.

    Nested units are separate facts; a unit's tree, statements, lines and calls
    exclude the bodies of units nested inside it. ``name`` is the qualified name
    within the module (``"Outer.inner"``, ``"<module>"``, ``"f.<lambda>"``);
    ``class_name`` is the enclosing class for methods. ``locals`` are the names
    the unit binds itself (parameters included); ``globals_declared`` the names
    a Python ``global`` statement names; ``writes`` the module-level-looking
    names the unit assigns or mutates.
    """

    name: str
    kind: str
    is_async: bool
    is_generator: bool
    span: Span
    parameters: int
    statements: int
    logical_lines: int
    control: ControlNode
    calls: tuple[CallSite, ...]
    class_name: str | None
    locals: frozenset[str]
    globals_declared: frozenset[str]
    writes: tuple[tuple[str, str], ...]  # (name, WRITE_ASSIGN | WRITE_MUTATE)


@dataclass(frozen=True)
class ImportFact:
    """One import or re-export. ``module`` is the specifier as written (``"pkg.mod"``,
    ``".errors"``, ``"./utils.js"``, ``"lodash"``); ``names`` pairs each imported name
    with the local name it binds (``("*", "*")`` for a star import, ``("", alias)``
    for a whole-module import); ``level`` is the Python relative-import level."""

    span: Span
    kind: str
    module: str
    level: int
    names: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ModuleBinding:
    """A name bound at module level. ``mutable`` marks variables bound to a mutable
    container (or declared ``let``/``var``, or named by a ``global`` statement)."""

    name: str
    kind: str
    mutable: bool
    span: Span


@dataclass(frozen=True)
class ModuleFacts:
    language: str
    parser: str
    numeric_literals: tuple[NumericLiteral, ...]
    comments: tuple[Comment, ...]
    catches: tuple[CatchFact, ...]
    managers: tuple[ManagerFact, ...]
    defaults: tuple[DefaultFact, ...]
    functions: tuple[FunctionFact, ...]
    imports: tuple[ImportFact, ...]
    bindings: tuple[ModuleBinding, ...]
    parse_failure: ParseFailure | None


def failed_facts(language: str, parser: str, failure: ParseFailure) -> ModuleFacts:
    """Facts for a file that did not parse: every tuple empty, the failure recorded."""
    return ModuleFacts(
        language=language,
        parser=parser,
        numeric_literals=(),
        comments=(),
        catches=(),
        managers=(),
        defaults=(),
        functions=(),
        imports=(),
        bindings=(),
        parse_failure=failure,
    )
