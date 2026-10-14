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


@dataclass(frozen=True)
class ModuleFacts:
    language: str
    parser: str
    numeric_literals: tuple[NumericLiteral, ...]
    comments: tuple[Comment, ...]
    catches: tuple[CatchFact, ...]
    parse_failure: ParseFailure | None
