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
class ConstantDefinition:
    """A module-level named constant whose value is a numeric literal or literal
    arithmetic: the definitions ``named_constant_definitions`` covers (``MAX_PAGES = 8``,
    ``const SETTLE_MS = 400``). ``span`` is the name's. MAGIC004 reads the name."""

    name: str
    span: Span


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
CATCH_CSHARP = "catch (C#)"  # C# ``catch`` clause of ``try`` (G2)

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
class ManagerCall:
    """A call expression that may construct an exception-capturing context manager.

    ``qualified`` and ``confidence`` are the callee resolved through the module's
    symbol table; ``identities`` are the positional arguments that resolve as
    exception types; ``unreadable_arguments`` counts positional arguments that are
    not names (a string, a call); keyword arguments are ignored.
    """

    callee: str
    qualified: str | None
    confidence: str
    identities: tuple[ExceptionIdentity, ...]
    unreadable_arguments: int


# How a plain name used as a ``with`` context expression was bound (0.3.0, item 1).
BOUND_ASSIGNMENT = "assignment"  # ``name = <value>`` / ``name: T = <value>``
BOUND_WITH_AS = "with_as"  # ``with <expr> as name:`` (binds what __enter__ returns)
BOUND_IMPORT = "import"  # ``import name`` / ``from m import name``
BOUND_LOOP_TARGET = "loop_target"  # ``for name in ...:``
BOUND_DEFINITION = "definition"  # ``def name`` / ``class name``
BOUND_OTHER = "other"  # augmented assignment, tuple unpacking, walrus, except-as, global


@dataclass(frozen=True)
class NameBinding:
    """One statement of the enclosing scope that binds the ``with``'s name.

    ``call`` is the bound value when it is a call (``name = M(T)``), or the context
    expression for a ``with M(T) as name``; ``value`` is the bound value as written.
    ``dominating`` is true when the binding's block encloses the ``with`` (the same
    block, or an outer one); false when it sits in a branch or loop body the
    ``with`` is not inside, so the binding may not have run.
    """

    kind: str
    line: int
    call: ManagerCall | None
    value: str
    dominating: bool


@dataclass(frozen=True)
class NameResolution:
    """How a ``with name:`` resolves within its scope (0.3.0, item 1).

    ``preceding`` lists every binding of ``name`` in the enclosing scope (function or
    module body) before the ``with``, in source order; ``parameter`` says whether the
    name is a parameter of the enclosing function and ``comprehension_target``
    whether a comprehension in the scope binds it; ``elsewhere`` holds the calls
    the name is bound to anywhere else in the module (another scope, or after the
    ``with``). Which calls count as capture managers is the rule's decision.
    """

    name: str
    preceding: tuple[NameBinding, ...]
    parameter: bool
    comprehension_target: bool
    elsewhere: tuple[ManagerCall, ...]


@dataclass(frozen=True)
class ManagerFact:
    """A ``with`` item whose context expression is a call or a plain name: a candidate
    exception capture.

    The adapter records every such item (``with open(p) as f:`` and ``with lock:``
    included) because it does not know which managers catch; ``rules.exceptions``
    turns the ones that do (``contextlib.suppress`` and the configured
    ``capture_managers``) into :class:`CatchFact` entries of kind ``context
    manager``. ``call`` is the inline call (``with M(T):``); ``resolution`` is set
    instead when the context expression is a plain name (``with capture:``), and
    ``callee`` is then that name. ``body_statements`` are the ``with`` body,
    attributed like a ``try`` body.
    """

    span: Span
    scope: str
    callee: str
    call: ManagerCall | None
    resolution: NameResolution | None
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
KIND_DISCARDED_REMOVAL = "discarded_removal"  # m.pop(k, None) as a statement: remove if present
KIND_GETATTR = "getattr"  # getattr(o, name, v)
KIND_MEMBERSHIP_TERNARY = "membership_ternary"  # m[k] if k in m else v / k in o ? o[k] : v
KIND_MEMBERSHIP_RETURN = "membership_return"  # if k in m: return m[k] / return v (decision 34)
KIND_FALLBACK_HELPER = "fallback_helper"  # value_or(m, k, v): a helper that is m.get(k, v)
KIND_DESTRUCTURING = "destructuring"  # const {x = v} = o / const [x = v] = a
KIND_MEMBER_NULLISH = "member_nullish"  # obj?.x ?? v / obj.x ?? v / m.get(k) ?? v
KIND_TRUTHINESS_OR = "or"  # x or v / x || v (and chains ending in v)
KIND_TRUTHINESS_ASSIGN = "or_assign"  # x ||= v
KIND_TRUTHINESS_TERNARY = "truthiness_ternary"  # x if x else v / x ? x : v
KIND_NULLISH_COALESCE = "coalesce"  # x ?? v
KIND_NULLISH_ASSIGN = "coalesce_assign"  # x ??= v
KIND_NULLISH_TERNARY = "nullish_ternary"  # x if x is not None else v / x == null ? v : x
KIND_EXCEPTION_CONSTANT = "handler_returns_constant"  # except ...: return DEFAULT (module constant)
# Decision 37: a top-level function's handler returns a module constant bound to a non-zero
# int (an exit status). DEF005 skips it inside a declared boundary when the function is the
# entry point: ENTRY when the adapter sees it (main, or called under __main__), EXIT when
# only [project.scripts] can say.
KIND_EXCEPTION_EXIT_STATUS = "handler_returns_exit_status"
KIND_EXCEPTION_ENTRY_EXIT = "handler_returns_entry_exit_status"
KIND_EXCEPTION_HELPER = (
    "handler_returns_helper"  # except ...: return fallback() (helper returns a literal)
)
KIND_ENV_GET = "env_get"  # os.getenv("X", v) / os.environ.get("X", v) / os.environ.setdefault
KIND_ENV_GET_IMPLICIT = "env_get_implicit"  # os.getenv("X") / os.environ.get("X"): None when unset
KIND_ENV_TRUTHINESS = "env_or"  # process.env.X || v / os.environ.get("X") or v
KIND_ENV_NULLISH = "env_coalesce"  # process.env.X ?? v
KIND_ENV_DESTRUCTURING = "env_destructuring"  # const { X = v } = process.env
KIND_SETTING_GET = (
    "setting_get"  # C#: ProjectSettings.GetSetting(name, v) / config.GetValue(s, k, v)
)

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


EMPTY_EXPR = ControlNode(CK_EXPR, (), 0, 0, "", labeled=False)


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


# --- Verification facts (H2) -------------------------------------------------------------
# What VERIFY001, VERIFY002 and VERIFY004 compare between a base and a head revision.
# The facts are syntax only; the rules (rules/verification.py) decide what counts as added.

MARKER_SKIP = "skip"  # the test does not run (pytest.mark.skip, it.skip, xit, ...)
MARKER_XFAIL = "xfail"  # the test runs but its failure is expected (xfail, expectedFailure)
MARKER_FOCUS = "focus"  # only this test or suite runs (it.only, fit, fdescribe, ...)
MARKER_KINDS = (MARKER_SKIP, MARKER_XFAIL, MARKER_FOCUS)

DIRECTIVE_SCOPE_LINE = "line"
DIRECTIVE_SCOPE_NEXT_LINE = "next-line"
DIRECTIVE_SCOPE_REGION = "region"  # an eslint-disable or coverage region until re-enabled
DIRECTIVE_SCOPE_FILE = "file"


@dataclass(frozen=True)
class SkipMarker:
    """A marker that takes a test, class or suite out of the run or excuses its failure.

    ``test`` is the qualified name it applies to (``"test_add"``, ``"TestMath.test_add"``,
    ``"math > adds"`` for JavaScript suites, ``"<module>"`` for a module-wide
    ``pytestmark``); ``text`` is the marker as written with whitespace collapsed;
    ``reason`` is its reason argument when that is a string literal.
    """

    kind: str
    test: str
    text: str
    reason: str | None
    span: Span


@dataclass(frozen=True)
class SuppressionDirective:
    """A comment that silences a linter, type checker, coverage tool or ShockHarness.

    ``tool`` names the directive family (``noqa``, ``type-ignore``, ``eslint-disable``,
    ...); ``codes`` are the rule codes it names; ``narrow`` is true when it names at
    least one code (and, for ShockHarness, carries a reason). ``text`` is the directive
    as written with whitespace collapsed.
    """

    tool: str
    scope: str
    codes: tuple[str, ...]
    narrow: bool
    text: str
    span: Span


@dataclass(frozen=True)
class Tautology:
    """An assertion that cannot fail (``assert True``, ``expect(1).toBe(1)``)."""

    text: str
    span: Span


@dataclass(frozen=True)
class CaseFact:
    """One test case: a ``test*`` function or method, or an ``it``/``test`` call.

    ``assertions`` counts assert statements, ``assert*``/``expect*`` calls and
    assertion contexts (``pytest.raises``) anywhere in its body; ``body_empty`` is true
    when the body is only ``pass``/``...``/a docstring, or an empty block.
    """

    name: str
    span: Span
    assertions: int
    tautologies: tuple[Tautology, ...]
    body_empty: bool


@dataclass(frozen=True)
class VerificationFacts:
    markers: tuple[SkipMarker, ...]
    suppressions: tuple[SuppressionDirective, ...]
    cases: tuple[CaseFact, ...]


NO_VERIFICATION = VerificationFacts(markers=(), suppressions=(), cases=())


# --- Guardrail facts (H3) ----------------------------------------------------------------
# Syntax for EXC004, STUB001, ASSERT001, BOOL001 and IMPORT001 (rules/guardrails.py).
# STUB002 reads ``imports`` and STATE001 reads ``bindings`` and ``functions``.

EXIT_RETURN = "return"
EXIT_BREAK = "break"
EXIT_CONTINUE = "continue"

PLACEHOLDER_NOT_IMPLEMENTED = (
    "not_implemented"  # raise NotImplementedError / throw new Error("not implemented")
)
PLACEHOLDER_NOT_IMPLEMENTED_CONSTANT = "not_implemented_constant"  # raise NotImplemented
PLACEHOLDER_EMPTY_BODY = "empty_body"  # a function whose body is only pass / ... / a docstring


@dataclass(frozen=True)
class FinallyExit:
    """A ``return``/``break``/``continue`` that leaves a ``finally`` block, discarding the
    exception in flight (one inside a loop or nested function within the block does not)."""

    kind: str
    span: Span


@dataclass(frozen=True)
class ExitException:
    """EXC006: ``class <name>(SystemExit)``, a class raised like an error that ``except
    Exception`` does not catch and that ends the process. Python only."""

    name: str
    base: str
    span: Span


@dataclass(frozen=True)
class Placeholder:
    """Code that stands in for an implementation. ``scope`` is the enclosing unit."""

    kind: str
    text: str
    scope: str
    span: Span


@dataclass(frozen=True)
class AssertFact:
    """A Python ``assert`` statement. ``narrowing`` is true when its test only narrows types
    (``x is not None``, ``isinstance(x, T)``, or an ``and`` of those)."""

    text: str
    narrowing: bool
    span: Span


@dataclass(frozen=True)
class BooleanArgument:
    """A ``True``/``False`` (``true``/``false``) literal passed positionally to a call that
    takes more than one positional argument. ``callee`` is the dotted callee as written."""

    callee: str
    position: int
    text: str
    span: Span


@dataclass(frozen=True)
class ImportTimeCall:
    """A call executed when the module is imported (module body, class bodies, decorators,
    default values; not function bodies, not under ``if __name__ == "__main__"`` or
    ``if TYPE_CHECKING``). ``callee`` is the dotted callee as written."""

    callee: str
    text: str
    span: Span


@dataclass(frozen=True)
class ElementGuard:
    """DOM001: an ``instanceof`` test on an event target (``event.target instanceof
    HTMLElement``) that guards a later ``.closest(...)`` on the same value (JavaScript and
    TypeScript)."""

    span: Span
    subject: str
    class_name: str
    closest: Span


@dataclass(frozen=True)
class EarlyPublication:
    """STATE002: in one function, a shared object is published before it is initialized.
    ``name`` (a ``global`` name, or ``self.<attr>`` outside a constructor) is assigned a
    newly constructed object at ``published``; a later statement of the same function
    writes one of its attributes at ``written``. Python only."""

    name: str
    published: Span
    written: Span
    publish_text: str
    write_text: str


@dataclass(frozen=True)
class UnlockedRead:
    """STATE003: ``name`` (``self.<attr>`` or a module ``global``) is read at ``span`` in
    ``scope`` outside the ``locks``, while ``writer`` assigns it under one of them at
    ``written``. Python only."""

    span: Span
    scope: str
    name: str
    locks: tuple[str, ...]
    writer: str
    written: Span


@dataclass(frozen=True)
class GuardrailFacts:
    finally_exits: tuple[FinallyExit, ...]
    placeholders: tuple[Placeholder, ...]
    asserts: tuple[AssertFact, ...]
    boolean_arguments: tuple[BooleanArgument, ...]
    import_time_calls: tuple[ImportTimeCall, ...]
    element_guards: tuple[ElementGuard, ...]
    early_publications: tuple[EarlyPublication, ...]
    unlocked_reads: tuple[UnlockedRead, ...]
    exit_exceptions: tuple[ExitException, ...]


NO_GUARDRAILS = GuardrailFacts(
    finally_exits=(),
    placeholders=(),
    asserts=(),
    boolean_arguments=(),
    import_time_calls=(),
    element_guards=(),
    early_publications=(),
    unlocked_reads=(),
    exit_exceptions=(),
)


# --- Async lifecycle facts (H4) ----------------------------------------------------------
# What ASYNC001-ASYNC003 need (rules/async_lifecycle.py). ASYNC001 also needs the call
# graph's per-site resolution, which the cross-file phase supplies.


@dataclass(frozen=True)
class DiscardedCall:
    """A call whose result is thrown away: an expression statement (Python ``f()``,
    JavaScript ``f();``) or a JavaScript ``void f()``. ``callee`` is the dotted callee as
    written (``str.join`` for a method of a string literal, ``", ".join(...)``, whose
    type is known); ``span`` is the call's span (the same as its ``CallSite``). ``bound_by`` is,
    for ``name.method(...)``, the dotted callee of the ``with``/``async with`` that bound
    ``name`` in the enclosing function (``asyncio.TaskGroup`` for ``tg.create_task``).
    ``arguments`` counts the positional arguments, None when some are unpacked
    (``*args``, ``**kw``, ``...xs``) or the call is a tagged template. ``in_try``: the
    statement is in the body of a ``try`` that has a handler, so it may run for what it
    raises (``host.encode("idna")`` to validate)."""

    callee: str
    text: str
    void: bool
    in_async: bool
    bound_by: str | None
    arguments: int | None
    in_try: bool
    span: Span


@dataclass(frozen=True)
class SettledBatch:
    """``asyncio.gather(..., return_exceptions=True)`` or ``Promise.allSettled(...)``:
    failures come back as values. ``discarded`` when the result is thrown away;
    ``inspected`` when the enclosing function checks a result for failure
    (``isinstance(r, ...Exception)``, ``.status``, ``.reason``, ``"rejected"``) or returns
    the batch to its caller. ``cancellation_wait`` (Python): the gather is in a ``finally``
    or ``except`` block of a function that cancelled tasks before it, the standard wait
    for cancellation to finish (failures surfaced in the try body already)."""

    callee: str
    text: str
    discarded: bool
    inspected: bool
    cancellation_wait: bool
    span: Span


@dataclass(frozen=True)
class RejectionHandler:
    """A global listener for unhandled Promise rejections (JavaScript):
    ``window.addEventListener("unhandledrejection", h)``, ``process.on("unhandledRejection",
    h)``, ``window.onunhandledrejection = h``. ``reports``: the handler does more than
    ``preventDefault()`` (a named handler is assumed to)."""

    span: Span
    reports: bool


@dataclass(frozen=True)
class DrawnWait:
    """An ``await`` or ``return`` (or an arrow's expression body) of a promise that settles
    only when the page is drawn (JavaScript, ASYNC004): an animation's ``.finished``
    (``element.animate(...)``, ``document.getAnimations()``, a view transition), directly,
    through a ``const`` the function bound to one, through ``.then``/``.catch``/``.finally``
    on one, or through ``Promise.all``/``race``/``allSettled``/``any`` over an array holding
    one or a ``.map`` whose callback returns one. ``span`` is the expression waited on."""

    span: Span
    text: str


@dataclass(frozen=True)
class HeldCall:
    """A call whose promise the enclosing function waits on (JavaScript, ASYNC004): awaited,
    returned, an arrow's expression body, an element of an awaited ``Promise.all([...])``,
    or the receiver of an awaited ``.then``. ``span`` is the call's (its ``CallSite``'s)."""

    span: Span


@dataclass(frozen=True)
class CallbackArgument:
    """A function written as an argument of a call (JavaScript, ASYNC004): ``callee`` as
    written, the argument's ``index`` among ``count``, its ``span`` (the start of the unit
    it is), and ``label``, the first argument's text (a command's name)."""

    callee: str
    index: int
    count: int
    span: Span
    label: str


@dataclass(frozen=True)
class AsyncFacts:
    discarded_calls: tuple[DiscardedCall, ...]
    settled_batches: tuple[SettledBatch, ...]
    rejection_handlers: tuple[RejectionHandler, ...]
    drawn_waits: tuple[DrawnWait, ...]
    held_calls: tuple[HeldCall, ...]
    callbacks: tuple[CallbackArgument, ...]


NO_ASYNC = AsyncFacts(
    discarded_calls=(),
    settled_batches=(),
    rejection_handlers=(),
    drawn_waits=(),
    held_calls=(),
    callbacks=(),
)


# --- API-catalog facts (H5) -------------------------------------------------------------
# What PROCESS001, SLEEP001, RETRY001, BATCH001, TYPE001 and STUB003 need
# (rules/api_catalog.py). RESULT001 reads the H4 discarded calls.

CHECK_TRUE = "true"
CHECK_FALSE = "false"
CHECK_ABSENT = "absent"
RETRY_LOOP = "loop"
RETRY_DECORATOR = "decorator"
TYPE_ESCAPE_ANY = "any"
TYPE_ESCAPE_CAST = "cast"
TYPE_ESCAPE_NON_NULL = "non_null"


@dataclass(frozen=True)
class ProcessCall:
    """A call whose last callee segment names a process API (``run``, ``call``,
    ``system``, ``exec``, ``spawnSync``, ...). ``shell`` is true for ``shell=True`` /
    ``{shell: true}``; ``interpolated`` when the command is built from non-literal parts
    (an f-string or template with substitutions, ``+``, ``%``, ``.format``); ``check`` is
    ``true``/``false``/``absent`` (Python ``check=``); ``discarded`` when the result is
    thrown away; ``status_read`` when the enclosing function reads ``.returncode`` /
    ``.status``; ``returned`` when the result is returned to the caller (directly or
    through a name the function returns), whose job checking the status then is."""

    callee: str
    text: str
    shell: bool
    interpolated: bool
    check: str
    discarded: bool
    status_read: bool
    returned: bool
    span: Span


@dataclass(frozen=True)
class SleepCall:
    """``time.sleep`` / ``asyncio.sleep`` (any callee whose last segment is ``sleep``), or
    a JavaScript ``new Promise((r) => setTimeout(r, ...))``. ``in_loop`` when inside a
    loop of the same function (polling); ``zero_delay`` when the delay is a literal zero or
    left out (a yield to the event loop, not a wait)."""

    callee: str
    text: str
    in_loop: bool
    zero_delay: bool
    span: Span


@dataclass(frozen=True)
class RetryFact:
    """A retry without a visible limit. ``loop``: ``while True`` (``while (true)``) whose
    body catches an exception and neither raises, returns nor breaks in the handler.
    ``decorator``: ``@retry`` / ``@backoff.on_exception`` with none of the stop
    arguments. ``callee`` names the decorator for that kind."""

    kind: str
    callee: str
    text: str
    span: Span


@dataclass(frozen=True)
class BatchLoop:
    """A loop whose body catches per-item failures and drops them: the handler only
    passes, continues or logs (no raise, no return, nothing recorded)."""

    text: str
    span: Span


@dataclass(frozen=True)
class TypeEscape:
    """``Any`` in an annotation or a ``cast(...)`` call (Python); ``any``, a type assertion
    (``x as T``, ``<T>x``) or a non-null assertion (``x!``) (TypeScript)."""

    kind: str
    text: str
    span: Span


@dataclass(frozen=True)
class ConstantPredicate:
    """A function named as a check (``is_*``, ``has_*``, ``can_*``, ``check*``,
    ``validate*``, ``verify*``, ``authorize*``, ``authenticate*``, ``allow*``) whose whole
    body returns the literal ``True`` / ``true``. ``class_name``: the class whose body
    defines it, for a method (STUB003 tells a base-class hook default from an override)."""

    name: str
    class_name: str | None
    span: Span


@dataclass(frozen=True)
class ClassDecl:
    """A class and the names of its bases as written (``modals.BaseModal``)."""

    name: str
    bases: tuple[str, ...]
    span: Span


# CALL001: how an ``open`` call opens its file.
OPEN_WRITE = "write"  # a literal mode or flags that write (w, a, x or +)
OPEN_READ = "read"  # a literal read mode, or none (the default reads)
OPEN_UNKNOWN = "unknown"  # a mode the analysis cannot read (a variable, a computed string)


@dataclass(frozen=True)
class OpenMode:
    """An ``open`` / ``openSync`` call and how it opens its file (CALL001's mode condition).
    Python: ``open`` and ``io``/``codecs``/``gzip``/``bz2``/``lzma``/``os`` ``.open`` read
    the mode from the second argument, any other ``.open`` (``Path.open``) from the first,
    and ``mode=`` from either. JavaScript: the flags are the second argument. ``span`` is
    the call's (its ``CallSite``'s)."""

    span: Span
    mode: str


@dataclass(frozen=True)
class CatalogFacts:
    process_calls: tuple[ProcessCall, ...]
    sleeps: tuple[SleepCall, ...]
    retries: tuple[RetryFact, ...]
    batch_loops: tuple[BatchLoop, ...]
    type_escapes: tuple[TypeEscape, ...]
    constant_predicates: tuple[ConstantPredicate, ...]
    classes: tuple[ClassDecl, ...]
    open_modes: tuple[OpenMode, ...]


NO_CATALOG = CatalogFacts(
    process_calls=(),
    sleeps=(),
    retries=(),
    batch_loops=(),
    type_escapes=(),
    constant_predicates=(),
    classes=(),
    open_modes=(),
)


# --- Dataflow facts (H6) -----------------------------------------------------------------
# What a unit computes, as value dependencies, for INPUT001-INPUT002 and the cross-site
# rules. Syntax only: which reads are sources, which calls are sinks or validators, and how
# units compose across files is decided by the rules (rules/dataflow.py) with the
# configured catalogs and the call graph. Every value is a set of origins, strings of three
# shapes, so a fact never refers to a node:
ORIGIN_PARAMETER = "p"  # "p:<i>": the unit's i-th parameter (FlowUnit.parameters)
ORIGIN_READ = "r"  # "r:<i>": the unit's i-th read (FlowUnit.reads)
ORIGIN_CALL = "c"  # "c:<i>": the result of the unit's i-th call (FlowUnit.calls)
ORIGIN_SEPARATOR = ":"


@dataclass(frozen=True)
class FlowRead:
    """A dotted read rooted at a name the unit does not bind (``request.args``,
    ``sys.argv``, ``process.env.HOME``) or at one of its parameters (``req.body``). A
    string-literal subscript extends the text (``process.env["HOME"]`` reads
    ``process.env.HOME``)."""

    span: Span
    text: str
    on_parameter: bool


@dataclass(frozen=True)
class FlowGuard:
    """A call known to have returned a true value where another call runs (GUARD001):
    ``if has(x): ...``, ``if not has(x): return`` before it, ``assert has(x)`` before
    it. ``argument`` is the text of the guard's first argument."""

    callee: str
    argument: str


@dataclass(frozen=True)
class FlowCall:
    """A call (or construction) and the origins of what it is given. ``callee`` is the
    dotted text as written (the CallSite convention; ``"<dynamic>"`` otherwise), so the
    call graph's per-site resolution is found by (path, span)."""

    span: Span
    callee: str
    text: str
    receiver: tuple[str, ...]
    arguments: tuple[tuple[str, ...], ...]
    keywords: tuple[tuple[str, tuple[str, ...]], ...]
    first_argument: str
    guards: tuple[FlowGuard, ...]


@dataclass(frozen=True)
class FlowStore:
    """A value that leaves the unit other than by return: assigned to an attribute or
    subscript, or bound at module level (in the module unit)."""

    span: Span
    target: str
    origins: tuple[str, ...]


@dataclass(frozen=True)
class FlowReturn:
    span: Span
    origins: tuple[str, ...]


@dataclass(frozen=True)
class FlowAssert:
    """A Python ``assert`` and every origin its test looks at (ASSERT001)."""

    span: Span
    origins: tuple[str, ...]


@dataclass(frozen=True)
class FlowUnit:
    """One unit's value dependencies; ``name`` is its FunctionFact name. ``tested`` holds
    every origin a condition of the unit looks at (if, while, assert, ternary and
    Boolean-operator tests). ``bound_receiver``: a Python method whose first parameter
    receives the instance (``self``/``cls``), so call arguments shift by one.
    ``checks``: the guards the unit's leading statements establish before anything else
    runs (``if not isinstance(tags, str): raise ...``, ``assert has(x)``; GUARD001).
    ``truncated``: code nested past DATAFLOW_MAX_DEPTH was not followed."""

    name: str
    parameters: tuple[str, ...]
    bound_receiver: bool
    reads: tuple[FlowRead, ...]
    calls: tuple[FlowCall, ...]
    stores: tuple[FlowStore, ...]
    returns: tuple[FlowReturn, ...]
    tested: tuple[str, ...]
    asserts: tuple[FlowAssert, ...]
    checks: tuple[FlowGuard, ...]
    truncated: bool


@dataclass(frozen=True)
class DataflowFacts:
    units: tuple[FlowUnit, ...]


NO_DATAFLOW = DataflowFacts(units=())


def origin(kind: str, index: int) -> str:
    return f"{kind}{ORIGIN_SEPARATOR}{index}"


def origin_parts(value: str) -> tuple[str, int]:
    kind, _separator, index = value.partition(ORIGIN_SEPARATOR)
    return kind, int(index)


# --- Sentinel facts (MAGIC003) -----------------------------------------------------------
# A small numeric literal (a unary sign folded in) in a position where it stands for a
# value: assigned, returned, passed, or the value of a dict / object entry. Which values
# count and which callees take an index is the rule's catalog (rules.sentinels).
SENTINEL_ASSIGN = "assign"  # x = -1, self.selected = -1, let i = -1, a class field
SENTINEL_RETURN = "return"  # return -1, () => -1
SENTINEL_ARGUMENT = "argument"  # f(x, -1), f(timeout=-1)
SENTINEL_ENTRY = "entry"  # {"selected": -1}, { selected: -1 }


@dataclass(frozen=True)
class SentinelUse:
    """``target`` is the assigned name, the callee (with ``=name`` for a keyword), the
    entry's key, or empty for a return."""

    span: Span
    value: float
    raw: str
    kind: str
    target: str


# --- Floating elements (DOM002) ----------------------------------------------------------
# Elements attached to document.body, and the selector lists press handlers skip
# (ir/javascript_floating.py; Python has none).


@dataclass(frozen=True)
class FloatingElement:
    """``document.body.append(x)``: ``names`` are the selectors the building function
    gives ``x`` (``.class``, ``#id``, the created tag); ``interactive``: that function
    makes something pressable; ``transient``: ``x`` is a helper, not a control (removed
    again, clicked or submitted by the code, hidden); ``returned``: the function returns
    ``x`` (a container other modules fill)."""

    span: Span
    function: str
    names: tuple[str, ...]
    interactive: bool
    transient: bool
    returned: bool


@dataclass(frozen=True)
class ContainerFill:
    """``callee().append(card)`` (or through a local assigned from the call) with a
    pressable ``card``; ``names`` are the card's selectors."""

    span: Span
    callee: str
    names: tuple[str, ...]
    interactive: bool


@dataclass(frozen=True)
class SelectorList:
    """The ``closest`` / ``matches`` arguments of one function: selector strings, the
    names of the constants it uses for them, and the plain functions it calls (helpers
    that test more selectors: ``isContextMenuTarget(target)``)."""

    function: str
    span: Span
    selectors: tuple[str, ...]
    constants: tuple[str, ...]
    calls: tuple[str, ...]


@dataclass(frozen=True)
class StringConstant:
    """A module-level ``const NAME = "..."``, or an array of strings."""

    name: str
    values: tuple[str, ...]


# --- Text positions (DOM003) ---------------------------------------------------------------
# What a function's values hold, for the cross-file judgment of selections saved as text
# positions and found again through text nodes only (ir/javascript_positions.py).

POSITION_DIRECT = "direct"  # <range>.toString().length: a point's text position
POSITION_CALL = "call"  # the result of a call (``name``; ``member`` for obj.name(...))
POSITION_PARAMETER = "parameter"  # the function's parameter at ``index``
POSITION_PROPERTY = "property"  # obj.name


@dataclass(frozen=True)
class PositionSource:
    """One thing a value may hold. ``guarded``: a call whose point is tested as a text
    node around it (``if (n.nodeType === Node.TEXT_NODE)``), so its position is exact."""

    kind: str
    name: str
    index: int
    member: bool
    guarded: bool


@dataclass(frozen=True)
class PositionCall:
    """A call in a function, with what each argument may hold."""

    span: Span
    callee: str
    member: bool
    arguments: tuple[tuple[PositionSource, ...], ...]


@dataclass(frozen=True)
class PositionFunction:
    """A named function: what it returns, whether it walks text nodes only (a SHOW_TEXT
    walker or iterator, or a hand-written walk testing nodeType against text and reading
    lengths), the parameters it counts with there (compared or added, in order), and its
    calls that pass something on."""

    name: str
    span: Span
    returns: tuple[PositionSource, ...]
    walks_text: bool
    counted_parameters: tuple[int, ...]
    calls: tuple[PositionCall, ...]


@dataclass(frozen=True)
class PositionStore:
    """``{name: value}`` or ``obj.name = value`` in a function: what the property holds."""

    name: str
    sources: tuple[PositionSource, ...]


@dataclass(frozen=True)
class TextPositionFacts:
    functions: tuple[PositionFunction, ...]
    stores: tuple[PositionStore, ...]


NO_TEXT_POSITIONS = TextPositionFacts(functions=(), stores=())


@dataclass(frozen=True)
class DomFacts:
    floating: tuple[FloatingElement, ...]
    fills: tuple[ContainerFill, ...]
    selector_lists: tuple[SelectorList, ...]
    constants: tuple[StringConstant, ...]
    positions: TextPositionFacts


NO_DOM = DomFacts(
    floating=(), fills=(), selector_lists=(), constants=(), positions=NO_TEXT_POSITIONS
)


# --- String facts (MAGIC002) -------------------------------------------------------------
# Every string literal that could be a repeated constant, with its position. Docstrings,
# the literal parts of f-strings and templates, type annotations, import specifiers and
# __all__ are never recorded; which kinds and callees count is the rule's configuration.
STRING_ARGUMENT = "argument"  # f("pending"); ``callee`` names f
STRING_SUBSCRIPT = "subscript"  # row["status"], headers["X-Request-Id"]
STRING_KEY = "key"  # {"status": ...}, { "Content-Type": ... }
STRING_COMPARE = "compare"  # status == "pending", x in ("a", "b")
STRING_JSX = "jsx"  # <div className="card">
STRING_VALUE = "value"  # assigned, returned, a container element


@dataclass(frozen=True)
class StringUse:
    span: Span
    value: str
    kind: str
    callee: str


# --- Receiver facts (docs/proposal-receivers.md, R1) ---------------------------------------
# What the call graph needs to resolve a method call through its receiver: Python (R1)
# and JavaScript (R2).


@dataclass(frozen=True)
class ReceiverClass:
    """A module-level class: its bases as written (``""`` for a base that is not a plain or
    dotted name, such as ``Generic[T]``) and the methods its body defines (properties
    excluded)."""

    name: str
    bases: tuple[str, ...]
    methods: tuple[str, ...]


@dataclass(frozen=True)
class ReceiverObject:
    """A JavaScript module-level object literal: each method's name and where its unit
    starts (line, column), since object methods are not named after their object."""

    name: str
    methods: tuple[tuple[str, int, int], ...]


@dataclass(frozen=True)
class ReceiverFacts:
    singletons: tuple[tuple[str, str], ...]  # (module-level name, its constructor)
    # (unit, local, its constructor): the unit by name in Python, by "line:column" of its
    # start in JavaScript (object methods are not named after their object)
    constructed: tuple[tuple[str, str, str], ...]
    classes: tuple[ReceiverClass, ...]
    objects: tuple[ReceiverObject, ...]  # JavaScript only


NO_RECEIVER_FACTS = ReceiverFacts(singletons=(), constructed=(), classes=(), objects=())


# --- Disguised numbers (MAGIC005) ---------------------------------------------------------
# A number written as something else, so that MAGIC001 does not see it: the length of a
# literal, a literal string converted to a number, numbers inside an inline string that is
# parsed, spaces given where an indent count is meant.

DISGUISE_LENGTH = "length"  # len("  ") of whitespace only, len((a, b)), [a, b].length
DISGUISE_CONVERSION = "conversion"  # int("30"), float("2.5"), Number("3000"), +"30"
DISGUISE_PARSED = "parsed"  # json.loads("[2, 3]"), tomllib.loads("x = 24"), JSON.parse
DISGUISE_INDENT = "indent"  # json.dumps(v, indent="  "), JSON.stringify(v, null, "  ")


@dataclass(frozen=True)
class Disguise:
    span: Span
    kind: str
    values: tuple[int | float, ...]  # the numbers it stands for (several when parsed)
    text: str  # the expression as written, shortened
    scope: str


# --- Annotation coverage (TYPE002, decision 33) -------------------------------------------


@dataclass(frozen=True)
class AnnotationFacts:
    """Python functions and methods (lambdas aside) and how many carry a type annotation:
    a parameter other than the receiver, or the return. ``first`` is the first annotated
    one, where a project-level finding is anchored."""

    functions: int
    annotated: int
    first: Span | None


NO_ANNOTATIONS = AnnotationFacts(functions=0, annotated=0, first=None)


# --- Uses of functions (DEAD001, DEAD002) -------------------------------------------------
# What the call graph does not record: a function named as a value instead of called
# (passed, stored, bound, read as an attribute), and what registers one without a call.


@dataclass(frozen=True)
class UsageReference:
    """A name used as a value, not called, inside the unit that starts at (line, column).
    ``member`` for an attribute (``obj.name``, ``obj['name']``, ``getattr(obj, 'name')``),
    else a bare name the file defines as a function or binds by an import."""

    line: int
    column: int
    name: str
    member: bool


@dataclass(frozen=True)
class DeclaredFunction:
    """A function the dead-code rules judge, by the start of its unit: a def or method, a
    JavaScript function declaration or method, or a function bound to a declared name or a
    class field. ``registered`` names what reaches it without a call (a decorator,
    ``__all__``); empty for nothing."""

    line: int
    column: int
    registered: str


@dataclass(frozen=True)
class UsageFacts:
    declared: tuple[DeclaredFunction, ...]
    references: tuple[UsageReference, ...]
    # Classes whose instances the file hands to a library by assigning them to an
    # attribute of an imported module (``sys.stdout = stream``): the library calls their
    # methods. Names as written; the rule keeps the project's classes.
    handed: tuple[str, ...]
    # C# (G3): the type names the file mentions outside their own declarations (``new T``,
    # ``GetNode<T>``, ``T x``, ``is T``, ``typeof(T)``, a base list), simple names. A Godot
    # script whose class no file names, no scene attaches and no autoload loads is dead.
    types: tuple[str, ...]


NO_USAGE = UsageFacts(declared=(), references=(), handed=(), types=())


# --- Test stubs (VERIFY005) ---------------------------------------------------------------
# A test's patches of project code, and what tells which tests run them.


@dataclass(frozen=True)
class StubPatch:
    """One patch: ``monkeypatch.setattr(obj, "name", ...)`` (``target`` the object as
    written, ``attribute`` the name), ``monkeypatch.setattr("a.b.c", ...)``,
    ``patch("a.b.c")`` (``target`` empty, ``attribute`` the dotted string) or
    ``patch.object(obj, "name")``. ``holder`` is the start of the function it is in.
    ``tripwire``: the stub is there to be not called (it raises, fails the test, or
    records into a list the test asserts empty)."""

    span: Span
    holder_line: int
    holder_column: int
    target: str
    attribute: str
    tripwire: bool


@dataclass(frozen=True)
class StubFacts:
    patches: tuple[StubPatch, ...]
    fixtures: tuple[tuple[int, int, str], ...]  # (line, column) of a fixture, its name
    tests: tuple[tuple[int, int, tuple[str, ...]], ...]  # a test function, its parameters


NO_STUBS = StubFacts(patches=(), fixtures=(), tests=())


# --- Function shapes (DUP001, DUP002) -----------------------------------------------------
# What a function's body is, independent of layout and of the names it gives its own
# values, so that copies in different files compare equal.

SHAPE_MIN_STATEMENTS = 3  # smaller bodies are not recorded (rules.duplicates may raise it)
SHAPE_FILE = "<file>"  # a string's mention of the file it is in
SHAPE_NAME = "<name>"  # a string's mention of the function's own name


@dataclass(frozen=True)
class FunctionShape:
    """A named function with at least ``SHAPE_MIN_STATEMENTS`` statements, by the start
    and last line of its unit, and the class it is a method of. ``tokens``: its body in
    source order with comments, layout and docstrings dropped, parameters and locals
    renamed by first appearance, and every string's mention of the file's own path or the
    function's own name replaced."""

    line: int
    column: int
    end_line: int
    name: str
    owner: str  # the class a method is defined in; "" for a function
    statements: int
    tokens: tuple[str, ...]
    # The annotated types of its parameters (the receiver aside) and of its return, as
    # written; empty when nothing is annotated. Versions that take different types are
    # parallel implementations, not one helper drifted.
    signature: tuple[str, ...]


# --- Godot names (GODOT001-GODOT005, milestone G4) -----------------------------------------
# The names a C# script uses that Godot defines elsewhere: in project.godot, a scene, or a
# [Signal] declaration. The rules (rules/godot_names.py) read them against the project files.

GODOT_ACTION = "action"  # Input.IsActionPressed("jump"), @event.IsAction("jump")
GODOT_ACTION_ADDED = "action_added"  # InputMap.AddAction("jump")
GODOT_NODE_PATH = "node_path"  # GetNode<Label>("HUD/Score"), GetNode("%Health")
GODOT_GROUP_READ = "group_read"  # GetNodesInGroup("enemies"), IsInGroup, CallGroup
GODOT_GROUP_ADDED = "group_added"  # AddToGroup("enemies")
GODOT_SIGNAL_USE = "signal_use"  # EmitSignal("Hit"), Connect("Hit", ...) on this object
GODOT_SIGNAL_DECLARED = "signal_declared"  # [Signal] delegate void HitEventHandler(...)


@dataclass(frozen=True)
class GodotNameUse:
    """One Godot name as written. ``owner``: the class the code is in (``None`` outside
    one); ``on_self``: the call is on the script's own object (no receiver, or ``this``),
    which node paths and signal names need."""

    kind: str
    name: str
    owner: str | None
    on_self: bool
    span: Span


@dataclass(frozen=True)
class ModuleFacts:
    language: str
    parser: str
    numeric_literals: tuple[NumericLiteral, ...]
    constants: tuple[ConstantDefinition, ...]
    comments: tuple[Comment, ...]
    catches: tuple[CatchFact, ...]
    managers: tuple[ManagerFact, ...]
    defaults: tuple[DefaultFact, ...]
    functions: tuple[FunctionFact, ...]
    imports: tuple[ImportFact, ...]
    bindings: tuple[ModuleBinding, ...]
    verification: VerificationFacts
    guardrails: GuardrailFacts
    asynchrony: AsyncFacts
    catalog: CatalogFacts
    dataflow: DataflowFacts
    sentinels: tuple[SentinelUse, ...]
    strings: tuple[StringUse, ...]
    dom: DomFacts
    receivers: ReceiverFacts
    disguises: tuple[Disguise, ...]
    annotations: AnnotationFacts
    usage: UsageFacts
    shapes: tuple[FunctionShape, ...]
    stubs: StubFacts
    godot: tuple["GodotNameUse", ...]
    parse_failure: ParseFailure | None


def failed_facts(language: str, parser: str, failure: ParseFailure) -> ModuleFacts:
    """Facts for a file that did not parse: every tuple empty, the failure recorded."""
    return ModuleFacts(
        language=language,
        parser=parser,
        numeric_literals=(),
        constants=(),
        comments=(),
        catches=(),
        managers=(),
        defaults=(),
        functions=(),
        imports=(),
        bindings=(),
        verification=NO_VERIFICATION,
        guardrails=NO_GUARDRAILS,
        asynchrony=NO_ASYNC,
        catalog=NO_CATALOG,
        dataflow=NO_DATAFLOW,
        sentinels=(),
        strings=(),
        dom=NO_DOM,
        receivers=NO_RECEIVER_FACTS,
        disguises=(),
        annotations=NO_ANNOTATIONS,
        usage=NO_USAGE,
        shapes=(),
        stubs=NO_STUBS,
        godot=(),
        parse_failure=failure,
    )
