"""DUP001 and DUP002: the same helper written out in several files.

Both read the function shapes of the files where the rules apply (``ir/*_shapes.py``):
a body's tokens with layout, comments and the function's own names set aside.

* DUP001: copies with identical shapes in two or more files. One finding per group, at its
  first copy, listing the others.
* DUP002: versions that have drifted apart: functions whose names match once leading
  underscores and case are set aside, in two or more files, whose shapes differ but are at
  least ``similarity`` alike (difflib's ratio over the tokens). One finding per group of
  versions, at the first copy of its most common version, with the first line where the
  two most common versions differ.

Python and JavaScript are compared separately; JavaScript and TypeScript together.
"""

import difflib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from shockharness.findings import CONFIDENCE_EXACT, STATUS_VIOLATION, Finding
from shockharness.ir.model import FunctionShape, ReceiverClass, Span
from shockharness.rules.registry import DUP001, DUP002, PYTHON, RuleSpec
from shockharness.source import SourceText

SETTING_MIN_STATEMENTS = "min_statements"
SETTING_MIN_TOKENS = "min_tokens"
SETTING_SIMILARITY = "similarity"
SETTING_SEVERITY = "severity"
SETTING_DUP002_SEVERITY = "dup002_severity"
LISTED = 6  # copies named in a message; the rest are counted
UNDERSCORE = "_"
JAVASCRIPT_FAMILY = "javascript"
DIFF_CONTEXT = 0
REMOVED = "-"
ADDED = "+"
DIFF_HEADERS = ("---", "+++")
# Constructors differ by what they construct; DUP001 still reports identical ones.
CONSTRUCTORS = frozenset({"__init__", "constructor"})
NAME = re.compile(r"[A-Za-z_$][\w$]*")
NAME_MASK = "x"
EQUAL = "equal"  # difflib's opcode for an unchanged run


@dataclass(frozen=True)
class ShapeFile:
    path: str
    language: str
    applied: frozenset[str]  # which of DUP001/DUP002 apply to the file
    source: SourceText
    shapes: tuple[FunctionShape, ...]
    classes: tuple[ReceiverClass, ...]


@dataclass(frozen=True)
class Copy:
    file: ShapeFile
    shape: FunctionShape

    @property
    def where(self) -> str:
        return f"{self.file.path}:{self.shape.line}"

    def body(self) -> list[str]:
        source = self.file.source
        lines = range(self.shape.line, self.shape.end_line + 1)
        return [source.line_text(n).strip() for n in lines]


def _family(language: str) -> str:
    return PYTHON if language == PYTHON else JAVASCRIPT_FAMILY


def _copies(files: Sequence[ShapeFile], settings: Mapping[str, Any]) -> list[Copy]:
    floor = int(settings[SETTING_MIN_STATEMENTS])
    tokens = int(settings[SETTING_MIN_TOKENS])
    return [
        Copy(f, shape)
        for f in files
        for shape in f.shapes
        if shape.statements >= floor and len(shape.tokens) >= tokens
    ]


def _listing(copies: Sequence[Copy]) -> str:
    shown = ", ".join(c.where for c in copies[:LISTED])
    rest = len(copies) - LISTED
    if rest > 0:
        return f"{shown} and {rest} more"
    return shown


def _finding(rule: RuleSpec, severity: str, anchor: Copy, message: str) -> Finding:
    shape = anchor.shape
    span = Span(shape.line, shape.column, shape.end_line, shape.column)
    return Finding(
        rule_id=rule.rule_id,
        rule_version=rule.version,
        severity=severity,
        path=anchor.file.path,
        span=span,
        message=message,
        evidence=anchor.file.source.excerpt(shape.line),
        confidence=CONFIDENCE_EXACT,
        status=STATUS_VIOLATION,
        remediation=rule.remediation,
        safe_autofix=False,
        scope=shape.name,
        suppression=None,
        fingerprint=None,
        baseline=None,
    )


def _ordered(copies: Sequence[Copy]) -> list[Copy]:
    return sorted(copies, key=lambda c: (c.file.path, c.shape.line))


def _anchor(copies: Sequence[Copy], rule: RuleSpec) -> Copy | None:
    """The first copy in a file where the rule applies."""
    for copy in copies:
        if rule.rule_id in copy.file.applied:
            return copy
    return None


# -- DUP001 -----------------------------------------------------------------------------------


def _exact_groups(copies: Sequence[Copy]) -> list[list[Copy]]:
    groups: dict[tuple[str, tuple[str, ...]], list[Copy]] = {}
    for copy in copies:
        key = (_family(copy.file.language), copy.shape.tokens)
        if key not in groups:
            groups[key] = []
        groups[key].append(copy)
    return [_ordered(group) for group in groups.values() if len({c.file.path for c in group}) > 1]


def _dup001(copies: Sequence[Copy], severity: str) -> list[Finding]:
    found: list[Finding] = []
    for group in _exact_groups(copies):
        anchor = _anchor(group, DUP001)
        if anchor is None:
            continue
        files = len({c.file.path for c in group})
        others = [c for c in group if c is not anchor]
        message = (
            f"{anchor.shape.name} is written out in {files} files, identical once layout, "
            f"comments and local names are set aside: also {_listing(others)}"
        )
        found.append(_finding(DUP001, severity, anchor, message))
    return found


# -- DUP002 -----------------------------------------------------------------------------------


def _bare(name: str) -> str:
    return name.lstrip(UNDERSCORE).lower()


def _alike(first: tuple[str, ...], second: tuple[str, ...], similarity: float) -> bool:
    matcher = difflib.SequenceMatcher(None, first, second, autojunk=False)
    return (
        matcher.real_quick_ratio() >= similarity
        and matcher.quick_ratio() >= similarity
        and matcher.ratio() >= similarity
    )


def _versions(copies: Sequence[Copy]) -> dict[tuple[str, ...], list[Copy]]:
    found: dict[tuple[str, ...], list[Copy]] = {}
    for copy in copies:
        if copy.shape.tokens not in found:
            found[copy.shape.tokens] = []
        found[copy.shape.tokens].append(copy)
    return found


def _components(
    versions: Sequence[tuple[str, ...]], similarity: float
) -> list[list[tuple[str, ...]]]:
    """Versions linked by similarity, in groups of two or more."""
    parent = {v: v for v in versions}

    def find(v: tuple[str, ...]) -> tuple[str, ...]:
        while parent[v] != v:
            v = parent[v]
        return v

    for i, first in enumerate(versions):
        for second in versions[i + 1 :]:
            if find(first) != find(second) and _alike(first, second, similarity):
                parent[find(second)] = find(first)
    groups: dict[tuple[str, ...], list[tuple[str, ...]]] = {}
    for v in versions:
        root = find(v)
        if root not in groups:
            groups[root] = []
        groups[root].append(v)
    return [g for g in groups.values() if len(g) > 1]


def _masked(line: str) -> str:
    return NAME.sub(NAME_MASK, line)


def _difference(first: Copy, second: Copy) -> str:
    """The first pair of changed lines between two copies' sources that differ in more than
    their names, else the first changed pair; "" when no line pairs up."""
    a, b = first.body(), second.body()
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    pairs = [
        pair
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != EQUAL
        for pair in zip(a[i1:i2], b[j1:j2], strict=False)
    ]
    if len(pairs) == 0:
        return ""
    removed, added = pairs[0]
    for candidate in pairs:
        if _masked(candidate[0]) != _masked(candidate[1]):
            removed, added = candidate
            break
    return f"; where they differ, {first.where} has `{removed}` and {second.where} has `{added}`"


def _final(dotted: str) -> str:
    _head, _dot, last = dotted.rpartition(".")
    return last


class _Families:
    """Classes related by inheritance (by name, through the project's module-level
    classes): overrides of one method in related classes differ by design."""

    def __init__(self, files: Sequence[ShapeFile]) -> None:
        self.parent: dict[str, str] = {}
        for f in files:
            for cls in f.classes:
                self._union(cls.name, *(_final(base) for base in cls.bases if base != ""))

    def _find(self, name: str) -> str:
        if name not in self.parent:
            self.parent[name] = name
        while self.parent[name] != name:
            name = self.parent[name]
        return name

    def _union(self, name: str, *bases: str) -> None:
        for base in bases:
            self.parent[self._find(base)] = self._find(name)

    def overrides(self, copies: Sequence[Copy]) -> bool:
        """Every copy is a method, and all of their classes are one family."""
        if any(c.shape.owner == "" for c in copies):
            return False
        return len({self._find(c.shape.owner) for c in copies}) == 1


def _drift_message(name: str, versions: list[list[Copy]]) -> str:
    files = len({c.file.path for copies in versions for c in copies})
    described = "; ".join(f"{len(copies)} like {_listing(copies)}" for copies in versions)
    return (
        f"{name} exists in {len(versions)} versions that have drifted apart across {files} "
        f"files ({described}){_difference(versions[0][0], versions[1][0])}"
    )


def _buckets(copies: Sequence[Copy]) -> list[list[Copy]]:
    """Copies by language family and bare name (constructors left out), in buckets that
    span two or more files."""
    buckets: dict[tuple[str, str], list[Copy]] = {}
    for copy in copies:
        if copy.shape.name in CONSTRUCTORS:
            continue
        key = (_family(copy.file.language), _bare(copy.shape.name))
        if key not in buckets:
            buckets[key] = []
        buckets[key].append(copy)
    return [b for b in buckets.values() if len({c.file.path for c in b}) > 1]


def _drift(
    versions: Mapping[tuple[str, ...], list[Copy]],
    component: Sequence[tuple[str, ...]],
    families: _Families,
    severity: str,
) -> Finding | None:
    grouped = sorted(
        (_ordered(versions[v]) for v in component), key=lambda cs: (-len(cs), cs[0].where)
    )
    members = [c for cs in grouped for c in cs]
    if len({c.file.path for c in members}) <= 1 or families.overrides(members):
        return None
    anchor = _anchor(members, DUP002)
    if anchor is None:
        return None
    return _finding(DUP002, severity, anchor, _drift_message(grouped[0][0].shape.name, grouped))


def _dup002(
    copies: Sequence[Copy], families: _Families, similarity: float, severity: str
) -> list[Finding]:
    found: list[Finding] = []
    for bucket in _buckets(copies):
        versions = _versions(bucket)
        for component in _components(sorted(versions), similarity):
            finding = _drift(versions, component, families, severity)
            if finding is not None:
                found.append(finding)
    return found


def run_duplicates(
    files: Sequence[ShapeFile], settings: Mapping[str, Any]
) -> dict[str, list[Finding]]:
    copies = _copies(files, settings)
    similarity = float(settings[SETTING_SIMILARITY])
    findings = [
        *_dup001(copies, str(settings[SETTING_SEVERITY])),
        *_dup002(copies, _Families(files), similarity, str(settings[SETTING_DUP002_SEVERITY])),
    ]
    found: dict[str, list[Finding]] = {}
    for finding in findings:
        if finding.path not in found:
            found[finding.path] = []
        found[finding.path].append(finding)
    return found
