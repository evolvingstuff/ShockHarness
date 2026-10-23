"""CALL001: a call across a boundary the project declared ("only these files may call it").

Each ``[[rules.call_boundaries.forbidden]]`` entry binds the files its ``callers`` globs
match, less those its ``allowed_callers`` match, and names the calls they may not make:

* a qualified name and everything below it (``shutil``, ``os.replace``, ``fetch``,
  ``fs/promises.writeFile``), resolved through the file's own imports, as the H5 rules do;
  a name no import binds is a global, matched only when neither the module nor the calling
  function binds it itself; JavaScript's ``window.`` / ``globalThis.`` / ``self.`` prefix
  is dropped; ``new X(...)`` is a call of ``X``;
* a method on any receiver (``.write_text``), matched by name: approximate;
* either with ``/mode=write``: the call counts only when its literal mode writes
  (``OpenMode`` facts); a mode the analysis cannot read is an unknown finding;
* a catalog, ``@disk_writes`` or ``@network``, expanded from the section's lists for the
  file's language.

The call is judged in the file that makes it: a wrapper that writes is the file reported,
not its callers.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from shockharness.findings import STATUS_UNKNOWN, STATUS_VIOLATION, Finding
from shockharness.globs import GlobSet, compile_globset
from shockharness.ir.model import (
    CALL_ARGUMENT,
    CALL_DYNAMIC,
    CONFIDENCE_APPROXIMATE,
    CONFIDENCE_EXACT,
    OPEN_READ,
    OPEN_UNKNOWN,
    CallSite,
    ModuleFacts,
    Span,
)
from shockharness.rules.guardrails import import_aliases, qualified_callee
from shockharness.rules.registry import CALL001, JAVASCRIPT_FAMILY, PYTHON
from shockharness.schema import call_boundary_entry
from shockharness.source import SourceText

MODE_WRITE = "/mode=write"
METHOD_PREFIX = "."
CATALOG_PREFIX = "@"
# Each catalog's list per language family.
CATALOG_KEYS: Mapping[str, Mapping[str, str]] = {
    "@disk_writes": {PYTHON: "python_disk_writes", "javascript": "javascript_disk_writes"},
    "@network": {PYTHON: "python_network", "javascript": "javascript_network"},
}
JAVASCRIPT_KEY = "javascript"
GLOBAL_OWNERS = ("window.", "globalThis.", "self.")


@dataclass(frozen=True)
class CallName:
    name: str  # qualified, or ".method"
    write_mode: bool  # counts only when the call's literal mode writes


@dataclass(frozen=True)
class Boundary:
    callers: GlobSet
    exempt: GlobSet
    exempt_patterns: tuple[str, ...]
    calls: tuple[CallName, ...]
    reason: str


@dataclass(frozen=True)
class Match:
    called: str  # the call as resolved
    boundary: Boundary
    approximate: bool  # a method matched by name
    mode_unknown: bool  # a mode condition the analysis could not decide


def _call_name(text: str) -> CallName:
    if text.endswith(MODE_WRITE):
        return CallName(text[: len(text) - len(MODE_WRITE)], write_mode=True)
    return CallName(text, write_mode=False)


def _family(language: str) -> str:
    return JAVASCRIPT_KEY if language in JAVASCRIPT_FAMILY else PYTHON


def _expanded(names: Sequence[str], settings: Mapping[str, Any], language: str) -> list[str]:
    """``calls`` with each catalog replaced by its list for the file's language."""
    expanded: list[str] = []
    for name in names:
        if not name.startswith(CATALOG_PREFIX):
            expanded.append(name)
            continue
        expanded.extend(str(item) for item in settings[CATALOG_KEYS[name][_family(language)]])
    return expanded


def _boundaries(settings: Mapping[str, Any], language: str, path: str) -> tuple[Boundary, ...]:
    """The entries that bind ``path``."""
    bound: list[Boundary] = []
    for raw in settings["forbidden"]:
        entry = call_boundary_entry(raw)
        callers = compile_globset([str(p) for p in entry["callers"]])
        exempt_patterns = tuple(str(p) for p in entry["allowed_callers"])
        exempt = compile_globset(list(exempt_patterns))
        if not callers.matches(path) or exempt.matches(path):
            continue
        calls = tuple(_call_name(n) for n in _expanded(entry["calls"], settings, language))
        bound.append(Boundary(callers, exempt, exempt_patterns, calls, str(entry["reason"])))
    return tuple(bound)


def _resolved(call: CallSite, aliases: Mapping[str, str], bound_here: frozenset[str]) -> str | None:
    """The call's qualified name; None for a name the file binds itself (not the global)."""
    callee = call.callee
    head = callee.partition(".")[0]
    if head in aliases:
        return qualified_callee(callee, aliases)
    if head in bound_here:
        return None
    for owner in GLOBAL_OWNERS:
        if callee.startswith(owner):
            return callee[len(owner) :]
    return callee


def _names(called: str, name: str) -> bool:
    return called == name or called.startswith(name + ".")


def _method(called: str, name: str) -> bool:
    """``x.write_text`` for ``.write_text``: the last segment, on some receiver."""
    _receiver, dot, method = called.rpartition(METHOD_PREFIX)
    return dot == METHOD_PREFIX and METHOD_PREFIX + method == name


def _named(call: CallName, called: str, raw: str) -> bool:
    """Whether ``call`` names this call, before any mode condition."""
    if call.name.startswith(METHOD_PREFIX):
        return _method(raw, call.name)
    return _names(called, call.name)


def _match(
    called: str, raw: str, span: Span, boundaries: Sequence[Boundary], modes: Mapping[Span, str]
) -> Match | None:
    """The first boundary forbidding the call, and how it matched. A mode condition on a
    call with no mode fact (not an ``open``) cannot be decided: unknown."""
    for boundary in boundaries:
        for call in boundary.calls:
            if not _named(call, called, raw):
                continue
            approximate = call.name.startswith(METHOD_PREFIX)
            if not call.write_mode:
                return Match(called, boundary, approximate, mode_unknown=False)
            if span not in modes:
                return Match(called, boundary, approximate, mode_unknown=True)
            if modes[span] != OPEN_READ:
                return Match(called, boundary, approximate, modes[span] == OPEN_UNKNOWN)
    return None


def _message(match: Match) -> str:
    boundary = match.boundary
    who = "which this file may not call"
    if len(boundary.exempt_patterns) > 0:
        who = f"which only {', '.join(boundary.exempt_patterns)} may call"
    if match.mode_unknown:
        return (
            f"calls {match.called} with a mode the analysis cannot read; if it writes, "
            f"{who.removeprefix('which ')}: {boundary.reason}"
        )
    return f"calls {match.called}, {who}: {boundary.reason}"


def _finding(match: Match, path: str, span: Span, source: SourceText, severity: str) -> Finding:
    confidence = CONFIDENCE_APPROXIMATE if match.approximate else CONFIDENCE_EXACT
    status = STATUS_UNKNOWN if match.mode_unknown else STATUS_VIOLATION
    return Finding(
        rule_id=CALL001.rule_id,
        rule_version=CALL001.version,
        severity=severity,
        path=path,
        span=span,
        message=_message(match),
        evidence=source.excerpt(span.line),
        confidence=confidence,
        status=status,
        remediation=CALL001.remediation,
        safe_autofix=False,
        scope=None,
        suppression=None,
        fingerprint=None,
        baseline=None,
    )


def _called(call: CallSite, aliases: Mapping[str, str], bound_here: frozenset[str]) -> str | None:
    """What a call site calls, for matching; None for a name passed as a value or one the
    file binds itself. A computed callee keeps its text (``Path(p).write_text``)."""
    if call.shape == CALL_ARGUMENT:
        return None
    if call.shape == CALL_DYNAMIC:
        return call.callee
    return _resolved(call, aliases, bound_here)


def run_call001(
    facts: ModuleFacts, source: SourceText, path: str, language: str, settings: Mapping[str, Any]
) -> list[Finding]:
    boundaries = _boundaries(settings, language, path)
    if len(boundaries) == 0:
        return []
    aliases = import_aliases(facts.imports, language)
    module_names = frozenset(binding.name for binding in facts.bindings)
    modes = {mode.span: mode.mode for mode in facts.catalog.open_modes}
    severity = str(settings["severity"])
    found: list[Finding] = []
    for function in facts.functions:
        bound_here = module_names | function.locals
        for call in function.calls:
            called = _called(call, aliases, bound_here)
            if called is None:
                continue
            match = _match(called, call.callee, call.span, boundaries, modes)
            if match is not None:
                found.append(_finding(match, path, call.span, source, severity))
    return found
