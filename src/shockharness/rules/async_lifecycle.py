"""H4 async lifecycle: ASYNC001, ASYNC002, ASYNC003.

* ASYNC001: a coroutine or Promise is created and thrown away (a call statement, or
  JavaScript ``void``), so its failure is never observed: the callee is a configured
  coroutine/Promise API (``asyncio.sleep``, ``fetch``) resolved through the file's own
  imports, or a project function the call graph resolves to an ``async`` unit. A
  ``probable`` graph edge makes the finding ``unknown``.
* ASYNC002 (Python): a task is spawned and its handle dropped (``asyncio.create_task(...)``
  as a statement), unless the receiver was bound by a configured supervisor
  (``async with asyncio.TaskGroup() as group: group.create_task(...)``). A dropped task can
  be garbage-collected mid-flight and its exception is never retrieved.
* ASYNC003: a batch that turns failures into values (``asyncio.gather(...,
  return_exceptions=True)``, ``Promise.allSettled``) whose results are thrown away, or
  whose enclosing function never checks them for failure.

The facts are syntax (ir/python_async.py, ir/javascript_async.py); ASYNC001's project
callees come from the call graph built in the cross-file phase.
"""

from collections.abc import Mapping
from typing import Any

from shockharness.complexity.callgraph import (
    CONFIDENCE_PROBABLE,
    CONFIDENCE_RESOLVED,
    TARGET_UNIT,
    SiteResolution,
)
from shockharness.findings import STATUS_UNKNOWN, STATUS_VIOLATION, Finding
from shockharness.ir.model import (
    CONFIDENCE_APPROXIMATE,
    CONFIDENCE_EXACT,
    CONFIDENCE_UNRESOLVED,
    DiscardedCall,
    ModuleFacts,
    Span,
)
from shockharness.rules.guardrails import import_aliases, qualified_callee
from shockharness.rules.registry import ASYNC001, ASYNC002, ASYNC003, PYTHON, RuleSpec
from shockharness.source import SourceText

ASYNC_RULES = (ASYNC001, ASYNC002, ASYNC003)
SPAWNERS = frozenset({"create_task", "ensure_future"})


def _finding(
    rule: RuleSpec,
    severity: str,
    path: str,
    span: Span,
    message: str,
    source: SourceText,
    confidence: str,
    status: str,
) -> Finding:
    return Finding(
        rule_id=rule.rule_id,
        rule_version=rule.version,
        severity=severity,
        path=path,
        span=span,
        message=message,
        evidence=source.excerpt(span.line),
        confidence=confidence,
        status=status,
        remediation=rule.remediation,
        safe_autofix=False,
        scope=None,
        suppression=None,
        fingerprint=None,
        baseline=None,
    )


def _violation(
    rule: RuleSpec, severity: str, path: str, span: Span, message: str, source: SourceText
) -> Finding:
    return _finding(rule, severity, path, span, message, source, CONFIDENCE_EXACT, STATUS_VIOLATION)


def _dropped(call: DiscardedCall) -> str:
    if call.void:
        return "is discarded with void, which hides the rejection instead of handling it"
    return "is created and thrown away"


def _async_callee(
    resolution: SiteResolution, async_units: frozenset[str]
) -> tuple[str, str, str] | None:
    """(confidence, status, message note) when the call graph resolved the call to an async
    unit: a resolved edge is a violation, a probable one (matched by name) unknown."""
    if resolution.target.kind != TARGET_UNIT or resolution.target.identifier not in async_units:
        return None
    if resolution.confidence == CONFIDENCE_RESOLVED:
        return CONFIDENCE_EXACT, STATUS_VIOLATION, ""
    if resolution.confidence == CONFIDENCE_PROBABLE:
        return (
            CONFIDENCE_UNRESOLVED,
            STATUS_UNKNOWN,
            "; the callee was matched by name only (a probable call-graph edge)",
        )
    return None


def _async001(
    facts: ModuleFacts,
    source: SourceText,
    path: str,
    language: str,
    settings: Mapping[str, Any],
    sites: Mapping[tuple[str, Span], SiteResolution],
    async_units: frozenset[str],
) -> list[Finding]:
    severity = str(settings["severity"])
    key = "python_coroutine_apis" if language == PYTHON else "javascript_promise_apis"
    apis = {str(a) for a in settings[key]}
    aliases = import_aliases(facts.imports, language)
    kind = "coroutine" if language == PYTHON else "Promise"
    found: list[Finding] = []
    for call in facts.asynchrony.discarded_calls:
        qualified = qualified_callee(call.callee, aliases)
        if qualified in apis:
            message = f"the {kind} from {qualified}(...) {_dropped(call)}: {call.text}"
            found.append(_violation(ASYNC001, severity, path, call.span, message, source))
            continue
        site = (path, call.span)
        if site not in sites:
            continue
        verdict = _async_callee(sites[site], async_units)
        if verdict is None:
            continue
        confidence, status, note = verdict
        found.append(
            _finding(
                ASYNC001,
                severity,
                path,
                call.span,
                f"{call.callee}(...) is async; its {kind} {_dropped(call)}{note}: {call.text}",
                source,
                confidence,
                status,
            )
        )
    return found


def _is_supervisor(bound_by: str | None, supervisors: frozenset[str]) -> bool:
    if bound_by is None:
        return False
    _receiver, _dot, last = bound_by.rpartition(".")
    return bound_by in supervisors or last in supervisors


def _async002(
    facts: ModuleFacts, source: SourceText, path: str, settings: Mapping[str, Any]
) -> list[Finding]:
    supervisors = frozenset(str(s) for s in settings["supervisors"])
    aliases = import_aliases(facts.imports, PYTHON)
    found: list[Finding] = []
    for call in facts.asynchrony.discarded_calls:
        _receiver, _dot, last = call.callee.rpartition(".")
        if last not in SPAWNERS or _is_supervisor(call.bound_by, supervisors):
            continue
        qualified = qualified_callee(call.callee, aliases)
        confidence = (
            CONFIDENCE_EXACT if qualified.startswith("asyncio.") else CONFIDENCE_APPROXIMATE
        )
        found.append(
            _finding(
                ASYNC002,
                str(settings["severity"]),
                path,
                call.span,
                f"{qualified}(...) starts a task and drops its handle: nothing awaits it, keeps it "
                f"alive or retrieves its exception: {call.text}",
                source,
                confidence,
                STATUS_VIOLATION,
            )
        )
    return found


def _async003(
    facts: ModuleFacts, source: SourceText, path: str, settings: Mapping[str, Any]
) -> list[Finding]:
    found: list[Finding] = []
    for batch in facts.asynchrony.settled_batches:
        if batch.cancellation_wait:
            continue  # waiting for cancelled tasks to finish, in a finally / except block
        if batch.discarded:
            message = (
                f"{batch.callee}(...) turns failures into values and its results are thrown "
                f"away: every failure in the batch disappears: {batch.text}"
            )
            confidence = CONFIDENCE_EXACT
        elif not batch.inspected:
            message = (
                f"{batch.callee}(...) turns failures into values, and nothing in this function "
                f"checks the results for failure: {batch.text}"
            )
            confidence = CONFIDENCE_APPROXIMATE
        else:
            continue
        found.append(
            _finding(
                ASYNC003,
                str(settings["severity"]),
                path,
                batch.span,
                message,
                source,
                confidence,
                STATUS_VIOLATION,
            )
        )
    return found


def run_async_rules(
    facts: ModuleFacts,
    source: SourceText,
    settings: Mapping[str, Any],
    path: str,
    language: str,
    active: frozenset[str],
    sites: Mapping[tuple[str, Span], SiteResolution],
    async_units: frozenset[str],
) -> list[Finding]:
    """Findings of the active ASYNC rules for one file. ``sites`` and ``async_units`` come
    from the call graph (every file's call sites; the keys of ``async`` units)."""
    found: list[Finding] = []
    if ASYNC001.rule_id in active:
        found.extend(_async001(facts, source, path, language, settings, sites, async_units))
    if ASYNC002.rule_id in active and language == PYTHON:
        found.extend(_async002(facts, source, path, settings))
    if ASYNC003.rule_id in active:
        found.extend(_async003(facts, source, path, settings))
    return found
