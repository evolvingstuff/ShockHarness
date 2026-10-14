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
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from shockharness.findings import Finding
from shockharness.globs import GlobSet, compile_globset
from shockharness.ir.model import (
    BODY_EMPTY,
    BODY_LOGGING_ONLY,
    BODY_OPAQUE,
    BODY_RAISE_OTHER,
    BODY_RERAISE,
    BODY_RETURN_FALLBACK,
    CATCH_CLAUSE,
    CATCH_EXCEPT,
    CATCH_EXCEPT_STAR,
    CATCH_PROMISE,
    CATCH_PROMISE_THEN,
    CONFIDENCE_APPROXIMATE,
    CONFIDENCE_EXACT,
    CONFIDENCE_UNRESOLVED,
    CatchFact,
    ExceptionIdentity,
    ModuleFacts,
    Span,
)
from shockharness.rules.registry import EXC001, EXC002, EXC003, RuleSpec
from shockharness.rules.severity import section_severity
from shockharness.source import SourceText

KIND_LABELS: Mapping[str, str] = {
    CATCH_EXCEPT: "except handler",
    CATCH_EXCEPT_STAR: "except* handler",
    CATCH_CLAUSE: "catch clause",
    CATCH_PROMISE: "promise .catch handler",
    CATCH_PROMISE_THEN: "promise .then rejection handler",
}
EXC002_CLASSIFICATIONS = frozenset(
    {BODY_EMPTY, BODY_LOGGING_ONLY, BODY_RETURN_FALLBACK, BODY_RAISE_OTHER}
)


@dataclass(frozen=True)
class Boundary:
    index: int
    path: str
    language: str
    exception: str
    reason: str
    paths: GlobSet

    def label(self) -> str:
        return f"boundaries[{self.index}] ({self.exception}: {self.reason})"


@dataclass(frozen=True)
class Approval:
    approved: bool
    boundaries: tuple[Boundary, ...]
    problems: tuple[str, ...]
    confidence: str


def load_boundaries(settings: Mapping[str, Any]) -> tuple[Boundary, ...]:
    found: list[Boundary] = []
    for index, raw in enumerate(settings["boundaries"]):
        found.append(
            Boundary(
                index=index,
                path=str(raw["path"]),
                language=str(raw["language"]),
                exception=str(raw["exception"]),
                reason=str(raw["reason"]),
                paths=compile_globset([str(raw["path"])]),
            )
        )
    return tuple(found)


def _dotted_tail(qualified: str) -> str:
    return qualified.lstrip(".")


def identity_matches(identity: ExceptionIdentity, boundary: Boundary) -> bool:
    if identity.qualified is None or identity.confidence == CONFIDENCE_UNRESOLVED:
        return False
    if identity.confidence == CONFIDENCE_EXACT:
        return identity.qualified == boundary.exception
    tail = _dotted_tail(identity.qualified)
    return (
        tail == boundary.exception
        or boundary.exception.endswith("." + tail)
        or tail.endswith("." + boundary.exception)
    )


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
    return (
        "rejection handler binds every rejection; it passes only inside an approved boundary "
        "whose error class the handler checks with instanceof and otherwise rethrows"
    )


def evaluate_approval(catch: CatchFact, applicable: tuple[Boundary, ...]) -> Approval:
    if catch.bare:
        return Approval(False, (), (_bare_problem(catch),), CONFIDENCE_UNRESOLVED)
    matched: list[Boundary] = []
    problems: list[str] = []
    for identity in catch.identities:
        if identity.confidence == CONFIDENCE_UNRESOLVED:
            problems.append(
                f"{identity.source!r} could not be resolved to a known exception (not a builtin, "
                "an import, or a class defined in this module); strict mode fails closed"
            )
            continue
        hits = [b for b in applicable if identity_matches(identity, b)]
        if len(hits) == 0:
            kind = "broad catch of" if identity.broad else "catch of"
            problems.append(
                f"{kind} {identity.qualified!r} is not approved by any boundary for this file"
            )
            continue
        matched.extend(hits)
    return Approval(
        approved=len(problems) == 0,
        boundaries=tuple(matched),
        problems=tuple(problems),
        confidence=_worst_confidence(catch.identities),
    )


def _finding(
    rule: RuleSpec,
    settings: Mapping[str, Any],
    path: str,
    span: Span,
    message: str,
    source: SourceText,
    confidence: str,
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
        remediation=rule.remediation,
        safe_autofix=False,
        scope=scope,
        suppression=None,
        fingerprint=None,
        baseline=None,
    )


def _written(catch: CatchFact) -> str:
    if catch.bare:
        return ""
    return " of " + ", ".join(repr(i.source) for i in catch.identities)


def _exc002_message(catch: CatchFact) -> str:
    label = KIND_LABELS[catch.kind]
    classification = catch.body.classification
    if classification == BODY_EMPTY:
        return f"{label} swallows the exception: {catch.body.detail}"
    if classification == BODY_LOGGING_ONLY:
        return f"{label} only logs the exception; logging is not handling"
    if classification == BODY_RETURN_FALLBACK:
        return f"{label} converts the exception into a fallback value: {catch.body.detail}"
    return f"{label} replaces the exception without preserving its cause: {catch.body.detail}"


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
    findings: list[Finding] = []
    for catch in facts.catches:
        approval = evaluate_approval(catch, applicable)
        transparent = transparent_rethrow and catch.body.classification == BODY_RERAISE
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
                    catch.scope,
                )
            )
        classification = catch.body.classification
        suppressed = classification in EXC002_CLASSIFICATIONS and not (
            defer_return_fallback and classification == BODY_RETURN_FALLBACK
        )
        if EXC002.rule_id in active_rule_ids and suppressed:
            findings.append(
                _finding(
                    EXC002,
                    settings,
                    path,
                    catch.span,
                    _exc002_message(catch),
                    source,
                    CONFIDENCE_EXACT,
                    catch.scope,
                )
            )
        if EXC003.rule_id in active_rule_ids and approval.approved:
            scope_finding = _exc003(catch, approval, settings, path, source)
            if scope_finding is not None:
                findings.append(scope_finding)
    return findings
