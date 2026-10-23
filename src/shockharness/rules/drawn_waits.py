"""ASYNC004: a gated command waits on the page being drawn (JavaScript; spec H4).

A browser does not run animations for a page it does not draw, so an animation's
``.finished`` stays pending until the page is shown. A command that awaits one while a gate
is held (a command queue, a lock) holds it that long, and every later command waits.

The facts are syntax (ir/javascript_async.py): each function's drawn waits, the calls whose
promises it waits on (held calls), and every function written as a call's argument. This
module joins them through the call graph: from each drawn wait it walks back through held
calls to the functions that wait on it, and reports the wait once when the callback of a
configured gate (``rules.async_lifecycle.gates``) is among them, naming every command that
reaches it.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from shockharness.complexity.callgraph import CONFIDENCE_PROBABLE, TARGET_UNIT, SiteResolution
from shockharness.findings import STATUS_VIOLATION, Finding
from shockharness.ir.model import CONFIDENCE_APPROXIMATE, CONFIDENCE_EXACT, AsyncFacts, Span
from shockharness.rules.registry import ASYNC004
from shockharness.source import SourceText

LAST_ARGUMENT = "last"  # a gate whose callback is its last argument (navigator.locks.request)


@dataclass(frozen=True)
class DrawnFile:
    path: str
    source: SourceText
    units: tuple[tuple[str, Span], ...]  # (unit key, span)
    asynchrony: AsyncFacts
    applies: bool  # ASYNC004 applies to the file


@dataclass(frozen=True)
class Gate:
    callee: str
    index: int | None  # None: the last argument


@dataclass(frozen=True)
class Command:
    """A gate call whose callback reaches a drawn wait."""

    label: str
    path: str
    line: int
    probable: bool  # some step on the way was a probable call-graph edge


def _gates(settings: Mapping[str, Any]) -> tuple[Gate, ...]:
    gates: list[Gate] = []
    for entry in settings["gates"]:
        callee, _colon, where = str(entry).rpartition(":")
        index = None if where == LAST_ARGUMENT else int(where)
        gates.append(Gate(callee, index))
    return tuple(gates)


def _start(span: Span) -> tuple[int, int]:
    return span.line, span.column


def _contains(outer: Span, inner: Span) -> bool:
    return _start(outer) <= _start(inner) and (inner.end_line, inner.end_column) <= (
        outer.end_line,
        outer.end_column,
    )


def _unit_at(file: DrawnFile, span: Span) -> str | None:
    """The innermost unit holding ``span``."""
    holding = [(key, unit) for key, unit in file.units if _contains(unit, span)]
    if len(holding) == 0:
        return None
    return max(holding, key=lambda pair: _start(pair[1]))[0]


def _callers(
    files: Sequence[DrawnFile], sites: Mapping[tuple[str, Span], SiteResolution]
) -> dict[str, list[tuple[str, bool]]]:
    """Callee unit -> (caller unit, through a probable edge) for every held call."""
    callers: dict[str, list[tuple[str, bool]]] = {}
    for file in files:
        for held in file.asynchrony.held_calls:
            site = (file.path, held.span)
            if site not in sites or sites[site].target.kind != TARGET_UNIT:
                continue
            caller = _unit_at(file, held.span)
            if caller is None:
                continue
            target = sites[site].target.identifier
            if target not in callers:
                callers[target] = []
            callers[target].append((caller, sites[site].confidence == CONFIDENCE_PROBABLE))
    return callers


def _waiting(start: str, callers: Mapping[str, list[tuple[str, bool]]]) -> dict[str, bool]:
    """Every unit that waits on ``start`` (itself included), with whether the first path
    found to it took a probable edge."""
    reached = {start: False}
    queue = [start]
    while len(queue) > 0:
        unit = queue.pop()
        if unit not in callers:
            continue
        for caller, probable in callers[unit]:
            if caller in reached:
                continue
            if probable:
                reached[caller] = True
            else:
                reached[caller] = reached[unit]
            queue.append(caller)
    return reached


def _gated(callee: str, index: int, count: int, gates: Sequence[Gate]) -> bool:
    for gate in gates:
        if gate.callee != callee:
            continue
        if gate.index is None and index == count - 1:
            return True
        if gate.index == index:
            return True
    return False


def _commands(files: Sequence[DrawnFile], gates: Sequence[Gate]) -> list[tuple[str, Command]]:
    """(the callback's unit key, the command) for every gate call in the project."""
    commands: list[tuple[str, Command]] = []
    for file in files:
        starts = {_start(span): key for key, span in file.units}
        for callback in file.asynchrony.callbacks:
            if not _gated(callback.callee, callback.index, callback.count, gates):
                continue
            if _start(callback.span) not in starts:
                continue
            unit = starts[_start(callback.span)]
            command = Command(callback.label, file.path, callback.span.line, probable=False)
            commands.append((unit, command))
    return commands


def _message(text: str, reaching: Sequence[Command]) -> str:
    named = ", ".join(f"'{c.label}' ({c.path}:{c.line})" for c in reaching)
    return (
        f"awaits {text}, which a page that is not drawn does not settle, while a gated "
        f"command runs: {len(reaching)} command(s) wait on it and hold the gate meanwhile: "
        f"{named}"
    )


def _finding(file: DrawnFile, span: Span, message: str, severity: str, probable: bool) -> Finding:
    confidence = CONFIDENCE_APPROXIMATE if probable else CONFIDENCE_EXACT
    return Finding(
        rule_id=ASYNC004.rule_id,
        rule_version=ASYNC004.version,
        severity=severity,
        path=file.path,
        span=span,
        message=message,
        evidence=file.source.excerpt(span.line),
        confidence=confidence,
        status=STATUS_VIOLATION,
        remediation=ASYNC004.remediation,
        safe_autofix=False,
        scope=None,
        suppression=None,
        fingerprint=None,
        baseline=None,
    )


def _reaching(
    file: DrawnFile,
    span: Span,
    callers: Mapping[str, list[tuple[str, bool]]],
    commands: Sequence[tuple[str, Command]],
) -> list[Command]:
    """The gated commands that wait on the drawn wait at ``span``, in source order."""
    unit = _unit_at(file, span)
    if unit is None:
        return []
    reached = _waiting(unit, callers)
    reaching = [
        Command(c.label, c.path, c.line, reached[key]) for key, c in commands if key in reached
    ]
    return sorted(reaching, key=lambda c: (c.path, c.line))


def run_async004(
    files: Sequence[DrawnFile],
    sites: Mapping[tuple[str, Span], SiteResolution],
    settings: Mapping[str, Any],
) -> dict[str, list[Finding]]:
    """Each drawn wait a gated command reaches, reported in its file once."""
    callers = _callers(files, sites)
    commands = _commands(files, _gates(settings))
    severity = str(settings["severity"])
    found: dict[str, list[Finding]] = {}
    for file in files:
        if not file.applies:
            continue
        for wait in file.asynchrony.drawn_waits:
            reaching = _reaching(file, wait.span, callers, commands)
            if len(reaching) == 0:
                continue
            probable = any(c.probable for c in reaching)
            if file.path not in found:
                found[file.path] = []
            found[file.path].append(
                _finding(file, wait.span, _message(wait.text, reaching), severity, probable)
            )
    return found
