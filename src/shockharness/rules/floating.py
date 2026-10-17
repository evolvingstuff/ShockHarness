"""DOM002: a floating control a page-level press handler treats as outside (decision 32).

The project names, in ``rules.dom.press_exclusions``, the functions that hold the skip
lists of its page-level press handlers (``path:function``): the handlers that leave a
mode or swallow the next click when a press lands outside what they skip. Every control
the code attaches to ``document.body`` (or to a container a function attaches there and
returns) must match one selector of each list; one that matches none is reported where
it is attached. Nothing is reported until a project names a function: most press
handlers only close their own widget, and for them every other element is meant to be
outside.

Selectors are matched on their last compound (``.modal .x`` on ``.x``): its class, id
and tag tokens must all be among the element's; attribute and pseudo parts are not
evaluated. Constants are resolved in the file, then through its imports.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from shockharness.complexity.callgraph import ModuleEdge
from shockharness.findings import STATUS_UNKNOWN, STATUS_VIOLATION, Finding
from shockharness.ir.model import (
    CONFIDENCE_APPROXIMATE,
    CONFIDENCE_UNRESOLVED,
    DomFacts,
    FloatingElement,
    ImportFact,
    Span,
)
from shockharness.rules.imports import ClassKey, imported_names
from shockharness.rules.registry import DOM002
from shockharness.source import SourceText

ENTRY_SEPARATOR = ":"
SUBSTITUTION = "${"
COMBINATORS = re.compile(r"\s*[>+~]\s*|\s+")
BRACKETS = re.compile(r"\[[^\]]*\]")
PSEUDO = re.compile(r"::?[\w-]+(?:\([^)]*\))?")
TOKEN = re.compile(r"[.#]?[A-Za-z_][\w-]*")
FIRST_LINE = Span(line=1, column=1, end_line=1, end_column=1)


@dataclass(frozen=True)
class FloatingFile:
    path: str
    dom: DomFacts
    imports: tuple[ImportFact, ...]
    source: SourceText
    applies: bool


@dataclass(frozen=True)
class Exclusion:
    """A named skip list: where it is, and the selector compounds it skips."""

    entry: str
    compounds: tuple[frozenset[str], ...]


@dataclass(frozen=True)
class Control:
    file: FloatingFile
    span: Span
    names: tuple[str, ...]
    container: tuple[str, ...] | None
    where: str


def compounds(selector: str) -> list[frozenset[str]]:
    """The last compound of each comma part, as tokens (``.a``, ``#b``, ``tag``); a part
    with nothing evaluable (``[data-x]``) or built by a substitution yields none."""
    found: list[frozenset[str]] = []
    for part in selector.split(","):
        if SUBSTITUTION in part:
            continue
        pieces = [piece for piece in COMBINATORS.split(part.strip()) if piece != ""]
        if len(pieces) == 0:
            continue
        last = PSEUDO.sub("", BRACKETS.sub("", pieces[len(pieces) - 1]))
        tokens = frozenset(TOKEN.findall(last))
        if len(tokens) > 0:
            found.append(tokens)
    return found


def _constant_values(
    file: FloatingFile,
    name: str,
    by_path: Mapping[str, FloatingFile],
    imported: Mapping[tuple[str, str], ClassKey],
) -> list[str]:
    """A constant's strings: defined in the file, or imported from an analyzed one."""
    for constant in file.dom.constants:
        if constant.name == name:
            return list(constant.values)
    if (file.path, name) not in imported:
        return []
    target, original = imported[(file.path, name)]
    if target not in by_path:
        return []
    return [v for c in by_path[target].dom.constants if c.name == original for v in c.values]


def _selectors(
    key: ClassKey,
    by_path: Mapping[str, FloatingFile],
    imported: Mapping[tuple[str, str], ClassKey],
    seen: set[ClassKey],
) -> list[str] | None:
    """The selectors a function tests, its helpers' included (followed in the file and
    through its imports); None when the function holds no selector list."""
    path, function = key
    if key in seen or path not in by_path:
        return []
    seen.add(key)
    file = by_path[path]
    lists = [s for s in file.dom.selector_lists if s.function == function]
    if len(lists) == 0:
        return None
    selectors = [selector for s in lists for selector in s.selectors]
    for s in lists:
        for name in s.constants:
            selectors.extend(_constant_values(file, name, by_path, imported))
        for helper in s.calls:
            found = _selectors(_resolved(path, helper, imported), by_path, imported, seen)
            if found is not None:
                selectors.extend(found)
    return selectors


def _resolved(path: str, name: str, imported: Mapping[tuple[str, str], ClassKey]) -> ClassKey:
    """Where a name a file uses is defined: imported from an analyzed file, or its own."""
    if (path, name) in imported:  # shockharness: ignore[DEF002] reason="not imported: its own"
        return imported[(path, name)]
    return (path, name)


def _exclusion(
    entry: str, by_path: Mapping[str, FloatingFile], imported: Mapping[tuple[str, str], ClassKey]
) -> Exclusion | None:
    path, _separator, function = entry.rpartition(ENTRY_SEPARATOR)
    selectors = _selectors((path, function), by_path, imported, set())
    if selectors is None or path not in by_path:
        return None
    return Exclusion(entry, tuple(c for selector in selectors for c in compounds(selector)))


def _matches(control: Control, exclusion: Exclusion) -> bool:
    """``closest`` looks at the element and its ancestors: the control, or the
    container it is appended into."""
    candidates = [set(control.names)]
    if control.container is not None:
        candidates.append(set(control.container))
    return any(compound <= own for own in candidates for compound in exclusion.compounds)


def _containers(files: Sequence[FloatingFile]) -> dict[ClassKey, FloatingElement]:
    """Functions that attach an element to the body and return it, by (path, name)."""
    return {
        (file.path, element.function): element
        for file in files
        for element in file.dom.floating
        if element.returned and element.function != ""
    }


def _label(names: Sequence[str]) -> str:
    if len(names) == 0:
        return "no id or class"
    return ", ".join(names)


def _controls(
    files: Sequence[FloatingFile], imported: Mapping[tuple[str, str], ClassKey]
) -> list[Control]:
    """Pressable elements on the body: attached directly, or appended into a container
    a function attaches and returns."""
    containers = _containers(files)
    found: list[Control] = []
    for file in (f for f in files if f.applies):
        found.extend(
            Control(file, element.span, element.names, None, "is attached")
            for element in file.dom.floating
            if element.interactive and not element.transient
        )
        for fill in file.dom.fills:
            key = (file.path, fill.callee)
            if key not in containers:
                key = _resolved(file.path, fill.callee, imported)
            if key not in containers:
                continue
            container = containers[key].names
            where = f"is appended into {fill.callee}() ({_label(container)}), on the body"
            found.append(Control(file, fill.span, fill.names, container, where))
    return found


def _finding(
    file: FloatingFile, span: Span, message: str, severity: str, status: str, confidence: str
) -> Finding:
    return Finding(
        rule_id=DOM002.rule_id,
        rule_version=DOM002.version,
        severity=severity,
        path=file.path,
        span=span,
        message=message,
        evidence=file.source.excerpt(span.line),
        confidence=confidence,
        status=status,
        remediation=DOM002.remediation,
        safe_autofix=False,
        scope=None,
        suppression=None,
        fingerprint=None,
        baseline=None,
    )


def _unresolved(
    entries: Sequence[str], by_path: Mapping[str, FloatingFile], severity: str
) -> list[Finding]:
    """An entry whose file was analyzed but holds no such skip list: nothing is checked
    against it, which is said rather than passed over."""
    found: list[Finding] = []
    for entry in entries:
        path, _separator, function = entry.rpartition(ENTRY_SEPARATOR)
        if path not in by_path:
            continue
        message = (
            f"rules.dom.press_exclusions names {function}, and no function of that name here "
            "calls closest(...) or matches(...): DOM002 checks nothing against it"
        )
        found.append(
            _finding(
                by_path[path], FIRST_LINE, message, severity, STATUS_UNKNOWN, CONFIDENCE_UNRESOLVED
            )
        )
    return found


def _exclusions(
    entries: Sequence[str],
    by_path: Mapping[str, FloatingFile],
    imported: Mapping[tuple[str, str], ClassKey],
) -> tuple[list[Exclusion], list[str]]:
    """(the skip lists found, the entries naming none)."""
    resolved: list[Exclusion] = []
    missing: list[str] = []
    for entry in entries:
        exclusion = _exclusion(entry, by_path, imported)
        if exclusion is None:
            missing.append(entry)
        else:
            resolved.append(exclusion)
    return resolved, missing


def _violation(control: Control, entries: Sequence[str], severity: str) -> Finding:
    message = (
        f"this pressable element ({_label(control.names)}) {control.where}, and matches "
        f"no selector that {', '.join(entries)} skips: a press on it reaches that "
        "handler as a press outside, which can leave the current mode or swallow the "
        "click before its own action runs"
    )
    return _finding(
        control.file, control.span, message, severity, STATUS_VIOLATION, CONFIDENCE_APPROXIMATE
    )


def run_dom002(
    files: Sequence[FloatingFile], module_edges: Sequence[ModuleEdge], settings: Mapping[str, Any]
) -> dict[str, list[Finding]]:
    entries = [str(e) for e in settings["press_exclusions"]]
    if len(entries) == 0:
        return {}
    severity = str(settings["dom002_severity"])
    by_path = {file.path: file for file in files}
    imported = imported_names([(f.path, f.imports) for f in files], module_edges)
    resolved, missing = _exclusions(entries, by_path, imported)
    found = _unresolved(missing, by_path, severity)
    for control in _controls(files, imported):
        skipped_by_none = [e.entry for e in resolved if not _matches(control, e)]
        if len(skipped_by_none) > 0:
            found.append(_violation(control, skipped_by_none, severity))
    by_file: dict[str, list[Finding]] = {}
    for finding in found:
        if finding.path not in by_file:
            by_file[finding.path] = []
        by_file[finding.path].append(finding)
    return by_file
