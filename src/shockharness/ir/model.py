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
    text including the sign operators.
    """

    span: Span
    raw: str
    value: int | float | complex
    negated: bool
    in_annotation: bool
    scope: str


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
    """

    span: Span
    kind: str
    scope: str
    identities: tuple[ExceptionIdentity, ...]
    bare: bool
    bound_name: str | None
    body: HandlerBody
    try_statements: tuple[TryStatement, ...]


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


@dataclass(frozen=True)
class ModuleFacts:
    language: str
    parser: str
    numeric_literals: tuple[NumericLiteral, ...]
    comments: tuple[Comment, ...]
    catches: tuple[CatchFact, ...]
    defaults: tuple[DefaultFact, ...]
    parse_failure: ParseFailure | None
