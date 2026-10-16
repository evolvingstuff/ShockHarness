"""EXC001, EXC002, EXC003: exception transparency.

The policy is a boundary whitelist. Every catch is forbidden (EXC001) unless
the file sits inside a configured boundary (``rules.exceptions.boundaries``:
path glob, language, qualified exception, reason) *and* every exception identity
the handler names matches that boundary's exception. A bare ``except``, an
untyped JavaScript ``catch``, and an identity the resolver could not resolve can
never be approved: strict mode fails closed and says so.

An approved catch is still checked for what it does (EXC002: swallowing,
logging only, returning a fallback, replacing the exception without its cause)
and for what it protects (EXC003: the ``try`` body must be the one sanctioned
operation, attributable to a single call).

Identity matching: an ``exact`` identity must equal the boundary's exception
string. An ``approximate`` identity (relative import, class defined in the
analyzed module, JavaScript instanceof guard) matches when the two dotted names
are equal or one is a dotted suffix of the other, so ``.errors.MyError`` matches
``pkg.errors.MyError``. The finding's confidence records which case applied.

Status (H1): an EXC001 finding is ``unknown`` when the verdict rests on something the
analyzer could not establish, and ``violation`` when the catch is provably forbidden:

* every exception identity the handler names that was not approved is ``unresolved``
  (an unbound or rebound name, a dynamic type expression): ``unknown``; one resolved
  identity that no boundary approves makes the catch a ``violation`` whatever else
  it names;
* a promise rejection handler that is a reference to a function this module does not
  define (``opaque``): ``unknown``, its body cannot be inspected for an instanceof guard;
* a ``with`` whose name cannot be tied to the capture manager it was bound to: ``unknown``;
* a capture manager none of whose positional arguments names an exception type
  (``suppress(*errors)``): ``unknown``, the set it captures cannot be read;
* a bare ``except``, an untyped JavaScript ``catch`` clause, an inline untyped
  rejection handler: ``violation``, each provably binds every exception.

EXC002 and EXC003 findings are always ``violation``. ``rules.exceptions.fail_on_unknown``
(default true: EXC001 has always failed closed) decides whether unknown ones gate.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from shockharness.findings import STATUS_UNKNOWN, STATUS_VIOLATION, Finding
from shockharness.globs import GlobSet, compile_globset
from shockharness.ir.model import (
    BODY_EMPTY,
    BODY_LOGGING_ONLY,
    BODY_OPAQUE,
    BODY_OTHER,
    BODY_RAISE_OTHER,
    BODY_RERAISE,
    BODY_RETURN_FALLBACK,
    BOUND_ASSIGNMENT,
    BOUND_WITH_AS,
    CATCH_CLAUSE,
    CATCH_EXCEPT,
    CATCH_EXCEPT_STAR,
    CATCH_MANAGER,
    CATCH_PROMISE,
    CATCH_PROMISE_THEN,
    CONFIDENCE_APPROXIMATE,
    CONFIDENCE_EXACT,
    CONFIDENCE_UNRESOLVED,
    CatchFact,
    ExceptionIdentity,
    HandlerBody,
    ManagerCall,
    ManagerFact,
    ModuleFacts,
    NameBinding,
    NameResolution,
    Span,
)
from shockharness.rules.registry import EXC001, EXC002, EXC003, RuleSpec
from shockharness.rules.severity import section_severity
from shockharness.schema import boundary_exceptions
from shockharness.source import SourceText

KIND_LABELS: Mapping[str, str] = {
    CATCH_EXCEPT: "except handler",
    CATCH_EXCEPT_STAR: "except* handler",
    CATCH_CLAUSE: "catch clause",
    CATCH_PROMISE: "promise .catch handler",
    CATCH_PROMISE_THEN: "promise .then rejection handler",
    CATCH_MANAGER: "context manager",
}
SUPPRESS_MANAGER = "contextlib.suppress"
EXC002_CLASSIFICATIONS = frozenset(
    {BODY_EMPTY, BODY_LOGGING_ONLY, BODY_RETURN_FALLBACK, BODY_RAISE_OTHER}
)


@dataclass(frozen=True)
class Boundary:
    index: int
    path: str
    language: str
    exceptions: tuple[str, ...]  # one name (`exception = ...`) or several (`exceptions = [...]`)
    reason: str
    paths: GlobSet

    def label(self) -> str:
        return f"boundaries[{self.index}] ({', '.join(self.exceptions)}: {self.reason})"


@dataclass(frozen=True)
class Approval:
    """``status`` is the EXC001 finding status when the catch is not approved (see the
    module docstring); it is ``violation`` for an approved catch, which has no finding."""

    approved: bool
    boundaries: tuple[Boundary, ...]
    problems: tuple[str, ...]
    confidence: str
    status: str


def load_boundaries(settings: Mapping[str, Any]) -> tuple[Boundary, ...]:
    found: list[Boundary] = []
    for index, raw in enumerate(settings["boundaries"]):
        found.append(
            Boundary(
                index=index,
                path=str(raw["path"]),
                language=str(raw["language"]),
                exceptions=boundary_exceptions(raw),
                reason=str(raw["reason"]),
                paths=compile_globset([str(raw["path"])]),
            )
        )
    return tuple(found)


def _dotted_tail(qualified: str) -> str:
    return qualified.lstrip(".")


def identity_matches(identity: ExceptionIdentity, boundary: Boundary) -> bool:
    return any(_name_matches(identity, name) for name in boundary.exceptions)


def _name_matches(identity: ExceptionIdentity, exception: str) -> bool:
    if identity.qualified is None or identity.confidence == CONFIDENCE_UNRESOLVED:
        return False
    if identity.confidence == CONFIDENCE_EXACT:
        return identity.qualified == exception
    tail = _dotted_tail(identity.qualified)
    return tail == exception or exception.endswith("." + tail) or tail.endswith("." + exception)


CONFIDENCE_ORDER = (CONFIDENCE_EXACT, CONFIDENCE_APPROXIMATE, CONFIDENCE_UNRESOLVED)


def _worst_confidence(identities: tuple[ExceptionIdentity, ...]) -> str:
    worst = CONFIDENCE_EXACT
    for identity in identities:
        if CONFIDENCE_ORDER.index(identity.confidence) > CONFIDENCE_ORDER.index(worst):
            worst = identity.confidence
    return worst


def _bare_problem(catch: CatchFact) -> str:
    if catch.body.classification == BODY_OPAQUE:
        return catch.body.detail
    if catch.kind in (CATCH_EXCEPT, CATCH_EXCEPT_STAR):
        return (
            "bare except catches every exception, including SystemExit and "
            "KeyboardInterrupt; no boundary can approve it"
        )
    if catch.kind == CATCH_CLAUSE:
        return (
            "untyped catch binds every error; a JavaScript catch passes only inside an approved "
            "boundary whose error class the handler checks with instanceof and otherwise rethrows"
        )
    if catch.kind == CATCH_MANAGER:
        return (
            "no positional argument names an exception type, so the manager captures an "
            "unknown set of exceptions; an untyped catch can never be approved"
        )
    return (
        "rejection handler binds every rejection; it passes only inside an approved boundary "
        "whose error class the handler checks with instanceof and otherwise rethrows"
    )


def bare_status(catch: CatchFact) -> str:
    """The EXC001 status of an untyped catch: ``unknown`` when what it binds could not be
    read (an opaque handler or manager binding, a manager without a readable exception
    type), ``violation`` when it provably binds every exception."""
    if catch.body.classification == BODY_OPAQUE or catch.kind == CATCH_MANAGER:
        return STATUS_UNKNOWN
    return STATUS_VIOLATION


def evaluate_approval(catch: CatchFact, applicable: tuple[Boundary, ...]) -> Approval:
    if catch.bare:
        return Approval(
            approved=False,
            boundaries=(),
            problems=(_bare_problem(catch),),
            confidence=CONFIDENCE_UNRESOLVED,
            status=bare_status(catch),
        )
    matched: list[Boundary] = []
    problems: list[str] = []
    unresolved = 0
    refused = 0
    for identity in catch.identities:
        if identity.confidence == CONFIDENCE_UNRESOLVED:
            unresolved += 1
            problems.append(
                f"{identity.source!r} could not be resolved to a known exception (not a builtin, "
                "an import, or a class defined in this module); strict mode fails closed"
            )
            continue
        hits = [b for b in applicable if identity_matches(identity, b)]
        if len(hits) == 0:
            refused += 1
            kind = "broad catch of" if identity.broad else "catch of"
            problems.append(
                f"{kind} {identity.qualified!r} is not approved by any boundary for this file"
            )
            continue
        matched.extend(hits)
    # Unknown only when nothing but unresolved identities stands in the way: one resolved
    # identity that no boundary approves is a violation whatever the others are.
    status = STATUS_UNKNOWN if unresolved > 0 and refused == 0 else STATUS_VIOLATION
    return Approval(
        approved=len(problems) == 0,
        boundaries=tuple(matched),
        problems=tuple(problems),
        confidence=_worst_confidence(catch.identities),
        status=status,
    )


def _finding(
    rule: RuleSpec,
    settings: Mapping[str, Any],
    path: str,
    span: Span,
    message: str,
    source: SourceText,
    confidence: str,
    status: str,
    scope: str,
) -> Finding:
    return Finding(
        rule_id=rule.rule_id,
        rule_version=rule.version,
        severity=section_severity(settings, rule.default_severity),
        path=path,
        span=span,
        message=message,
        evidence=source.excerpt(span.line),
        confidence=confidence,
        status=status,
        remediation=rule.remediation,
        safe_autofix=False,
        scope=scope,
        suppression=None,
        fingerprint=None,
        baseline=None,
    )


def _last_component(name: str) -> str:
    parts = name.split(".")
    return parts[len(parts) - 1]


def _manager_match(call: ManagerCall, capture_managers: frozenset[str]) -> str | None:
    """The confidence with which ``call`` constructs a catch, or ``None`` when it is an
    ordinary context manager. ``contextlib.suppress`` always counts; a configured
    manager counts when its resolved qualified name is listed (exact), or, when the
    callee could not be resolved, when its bare name equals a listed manager's bare
    name (approximate: the call graph's "probable")."""
    if call.qualified is not None and call.confidence != CONFIDENCE_UNRESOLVED:
        if call.qualified == SUPPRESS_MANAGER or call.qualified in capture_managers:
            return call.confidence
        return None
    bare = _last_component(call.callee)
    if any(_last_component(listed) == bare for listed in capture_managers):
        return CONFIDENCE_APPROXIMATE
    return None


@dataclass(frozen=True)
class _Resolved:
    """What a ``with`` item is once the rule has applied ``capture_managers``:
    ``call`` is the manager construction (``None`` for an unresolved binding, which is
    an untyped catch), ``confidence`` the worst of the callee's and the binding's,
    ``problem`` the explanation of an unresolved binding."""

    call: ManagerCall | None
    confidence: str
    problem: str | None


def _bound_listed(binding: NameBinding, capture_managers: frozenset[str]) -> bool:
    return binding.call is not None and _manager_match(binding.call, capture_managers) is not None


def _resolve_bound(
    resolution: NameResolution, capture_managers: frozenset[str]
) -> _Resolved | None:
    """``with name:`` against the bindings of ``name`` (0.3.0, item 1).

    The most recent binding before the ``with`` decides. An assignment to a listed
    manager (or ``contextlib.suppress``) is that catch: ``exact`` when nothing stands
    between them, ``approximate`` when the assignment sits in a branch or loop body
    the ``with`` is not inside, or the name is also a parameter or a comprehension
    target. When an earlier binding was a listed manager but the latest is something
    else, or the name is bound to a listed manager only elsewhere in the module
    (another scope, a ``with ... as`` binding, after the ``with``), the binding that
    reaches the ``with`` cannot be established: an untyped catch, never the older
    binding. A name never bound to a listed manager anywhere is an ordinary ``with``.
    """
    preceding = resolution.preceding
    latest: NameBinding | None = None
    if len(preceding) > 0:
        latest = preceding[len(preceding) - 1]
    if (
        latest is not None
        and latest.kind == BOUND_ASSIGNMENT
        and _bound_listed(latest, capture_managers)
    ):
        assert latest.call is not None
        confidence = _manager_match(latest.call, capture_managers)
        assert confidence is not None
        if not latest.dominating or resolution.parameter or resolution.comprehension_target:
            confidence = CONFIDENCE_APPROXIMATE
        return _Resolved(latest.call, confidence, None)
    earlier = [b for b in preceding if _bound_listed(b, capture_managers)]
    if len(earlier) > 0:
        assert latest is not None
        return _unresolved(_rebound_reason(resolution.name, earlier[len(earlier) - 1], latest))
    elsewhere = [c for c in resolution.elsewhere if _manager_match(c, capture_managers)]
    if len(elsewhere) == 0:
        return None
    return _unresolved(_elsewhere_reason(resolution.name, latest, elsewhere[0]))


def _unresolved(reason: str) -> _Resolved:
    return _Resolved(
        None,
        CONFIDENCE_UNRESOLVED,
        f"{reason}; the manager this with enters cannot be established, so it is an untyped "
        "catch that no boundary can approve",
    )


def _rebound_reason(name: str, listed: NameBinding, latest: NameBinding) -> str:
    assert listed.call is not None
    if listed.kind == BOUND_WITH_AS:
        return (
            f"'{name}' is bound by `with {listed.call.callee}(...) as {name}` on line "
            f"{listed.line}, which binds what the manager's __enter__ returns, not the manager"
        )
    return (
        f"'{name}' was bound to {listed.call.callee}(...) on line {listed.line} and rebound "
        f"on line {latest.line} ({latest.value}) before this with"
    )


def _elsewhere_reason(name: str, latest: NameBinding | None, listed: ManagerCall) -> str:
    if latest is None:
        where = f"'{name}' is not assigned in this scope before the with"
    else:
        where = f"'{name}' is last bound on line {latest.line} ({latest.value})"
    return f"{where} but is bound to {listed.callee}(...) elsewhere in the module"


def _resolve_manager(manager: ManagerFact, capture_managers: frozenset[str]) -> _Resolved | None:
    if manager.resolution is not None:
        return _resolve_bound(manager.resolution, capture_managers)
    assert manager.call is not None
    matched = _manager_match(manager.call, capture_managers)
    if matched is None:
        return None
    return _Resolved(manager.call, matched, None)


def manager_catches(
    managers: Sequence[ManagerFact], capture_managers: frozenset[str]
) -> list[CatchFact]:
    """The context managers that are catches, as catch facts of kind ``context manager``.

    ``contextlib.suppress`` swallows (its body classifies as empty, like ``except T:
    pass``); a configured capture manager keeps the exception for inspection after
    the block, which is ``other`` (EXC001 still judges the catch itself). An
    unreadable or absent type list, or a name whose binding cannot be established,
    is an untyped catch, like a bare ``except``.
    """
    found: list[CatchFact] = []
    for manager in managers:
        resolved = _resolve_manager(manager, capture_managers)
        if resolved is None:
            continue
        if resolved.call is None:
            assert resolved.problem is not None
            found.append(
                _manager_catch(
                    manager, (), HandlerBody(BODY_OPAQUE, resolved.problem), manager.callee
                )
            )
            continue
        call = resolved.call
        identities = call.identities
        if resolved.confidence == CONFIDENCE_APPROXIMATE:
            identities = tuple(
                ExceptionIdentity(i.source, i.qualified, CONFIDENCE_APPROXIMATE, i.broad)
                if i.confidence == CONFIDENCE_EXACT
                else i
                for i in identities
            )
        if call.qualified == SUPPRESS_MANAGER:
            body = HandlerBody(
                BODY_EMPTY,
                f"{call.callee}(...) discards the exception; nothing after the block can "
                "tell that the operation did not happen",
            )
        else:
            body = HandlerBody(
                BODY_OTHER,
                f"{call.callee}(...) keeps the captured exception for inspection after "
                "the block; what the code does with it is not inspected",
            )
        found.append(_manager_catch(manager, identities, body, manager.callee))
    return found


def _manager_catch(
    manager: ManagerFact,
    identities: tuple[ExceptionIdentity, ...],
    body: HandlerBody,
    written: str,
) -> CatchFact:
    return CatchFact(
        span=manager.span,
        kind=CATCH_MANAGER,
        scope=manager.scope,
        identities=identities,
        bare=len(identities) == 0,
        bound_name=manager.bound_name,
        body=body,
        try_statements=manager.body_statements,
        narrowed_from=None,
        guard_call=None,
        guard_body=None,
    )


def _written(catch: CatchFact) -> str:
    if catch.bare:
        return ""
    written = " of " + ", ".join(repr(i.source) for i in catch.identities)
    if catch.narrowed_from is not None:
        written += f" (narrowed from {catch.narrowed_from!r} by its isinstance guard)"
    return written


GUARD_ONLY_REMEDIES = (
    "; after the guard, handle the expected error, or log it and continue with a stated "
    "reason, or suppress this finding with a reason"
)


def _exc002_message(catch: CatchFact, body: HandlerBody, guard: str | None) -> str:
    label = KIND_LABELS[catch.kind]
    if guard is not None:
        label += f" after the transparent guard {guard}(...)"
    classification = body.classification
    if classification == BODY_EMPTY:
        message = f"{label} swallows the exception: {body.detail}"
        if guard is not None:
            # The guard re-raised everything unexpected and nothing follows it: the expected
            # errors vanish. Say what satisfies the policy (0.3.0, item 5).
            message += GUARD_ONLY_REMEDIES
        return message
    if classification == BODY_LOGGING_ONLY:
        return f"{label} only logs the exception; logging is not handling"
    if classification == BODY_RETURN_FALLBACK:
        return f"{label} converts the exception into a fallback value: {body.detail}"
    return f"{label} replaces the exception without preserving its cause: {body.detail}"


def _exc003(
    catch: CatchFact,
    approval: Approval,
    settings: Mapping[str, Any],
    path: str,
    source: SourceText,
) -> Finding | None:
    label = KIND_LABELS[catch.kind]
    approved_by = ", ".join(sorted({b.label() for b in approval.boundaries}))
    statements = catch.try_statements
    if len(statements) != 1:
        span = statements[1].span if len(statements) > 1 else catch.span
        return _finding(
            EXC003,
            settings,
            path,
            span,
            f"approved {label} protects {len(statements)} statements; a boundary may wrap only "
            f"the one sanctioned external operation (approved by {approved_by})",
            source,
            CONFIDENCE_EXACT,
            STATUS_VIOLATION,
            catch.scope,
        )
    statement = statements[0]
    if statement.attributable:
        return None
    return _finding(
        EXC003,
        settings,
        path,
        statement.span,
        f"approved {label} protects a statement that cannot be attributed to one external "
        f"operation: {statement.reason} (approved by {approved_by}); static analysis cannot "
        "tell which part may raise",
        source,
        CONFIDENCE_APPROXIMATE,
        STATUS_VIOLATION,
        catch.scope,
    )


def run_exception_rules(
    facts: ModuleFacts,
    source: SourceText,
    settings: Mapping[str, Any],
    path: str,
    language: str,
    active_rule_ids: frozenset[str],
    defer_return_fallback: bool,
) -> list[Finding]:
    """Run EXC001-EXC003 over the module's catch facts; only ``active_rule_ids`` report.

    With ``defer_return_fallback`` (DEF005 is active) the ``return_fallback``
    classification is left to DEF005 so that one handler yields one hard finding.
    """
    boundaries = load_boundaries(settings)
    applicable = tuple(b for b in boundaries if b.language == language and b.paths.matches(path))
    transparent_rethrow = bool(settings["transparent_rethrow"])
    transparent_guards = frozenset(str(name) for name in settings["transparent_guards"])
    capture_managers = frozenset(str(name) for name in settings["capture_managers"])
    catches = sorted(
        [*facts.catches, *manager_catches(facts.managers, capture_managers)],
        key=lambda c: c.span,
    )
    findings: list[Finding] = []
    for catch in catches:
        approval = evaluate_approval(catch, applicable)
        guard: str | None = None
        body = catch.body
        if catch.guard_call is not None and catch.guard_call in transparent_guards:
            # The configured guard re-raises anything unexpected: the catch itself is not
            # reported, and what the handler does is judged by the statements after it.
            guard = catch.guard_call
            assert catch.guard_body is not None
            body = catch.guard_body
        transparent = guard is not None or (
            transparent_rethrow and catch.body.classification == BODY_RERAISE
        )
        label = KIND_LABELS[catch.kind]
        if EXC001.rule_id in active_rule_ids and not approval.approved and not transparent:
            findings.append(
                _finding(
                    EXC001,
                    settings,
                    path,
                    catch.span,
                    f"{label}{_written(catch)} is forbidden: " + "; ".join(approval.problems),
                    source,
                    approval.confidence,
                    approval.status,
                    catch.scope,
                )
            )
        classification = body.classification
        # DEF005 reads the whole-body classification, so a fallback returned after a
        # transparent guard is EXC002's to report.
        deferred = defer_return_fallback and guard is None
        suppressed = classification in EXC002_CLASSIFICATIONS and not (
            deferred and classification == BODY_RETURN_FALLBACK
        )
        if catch.kind == CATCH_MANAGER and approval.approved:
            # ``with suppress(T):`` names its swallow and has no handler to inspect: a
            # boundary that approves T has approved the discard itself.
            suppressed = False
        if EXC002.rule_id in active_rule_ids and suppressed:
            findings.append(
                _finding(
                    EXC002,
                    settings,
                    path,
                    catch.span,
                    _exc002_message(catch, body, guard),
                    source,
                    CONFIDENCE_EXACT,
                    STATUS_VIOLATION,
                    catch.scope,
                )
            )
        if EXC003.rule_id in active_rule_ids and approval.approved:
            scope_finding = _exc003(catch, approval, settings, path, source)
            if scope_finding is not None:
                findings.append(scope_finding)
    return findings
