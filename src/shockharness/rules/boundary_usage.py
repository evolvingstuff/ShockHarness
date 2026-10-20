"""EXC005: a declared catch boundary that no catch uses.

A boundary (``rules.exceptions.boundaries[i]``) approves catching its exception types in
the files its ``path`` glob matches, in its language. For each exception it names,
EXC005 asks whether any catch in those files (``except``/``catch`` clauses and capture
managers, as EXC001 sees them) catches it. A name nothing catches is reported at the
boundary's line in the configuration file: it approves a catch nobody has written, or no
longer writes. In the under-the-gate experiment (round 3), agents declared boundaries for
files before writing them, which pre-approved every future catch there.

A boundary is judged only when it covers at least one file of the tree and every file it
covers was analyzed in this run: the hook and ``check src/one.py`` analyze part of the
tree, and a boundary for a file that does not exist yet is not judged either. Severity:
the registry's ``warning`` (the section's review cap lowers errors only).
"""

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from shockharness.config import EffectiveConfig
from shockharness.discovery import DiscoveredFile, discover
from shockharness.findings import CONFIDENCE_EXACT, STATUS_VIOLATION, Finding
from shockharness.ir.model import MODULE_SCOPE, CatchFact, Span
from shockharness.rules.exceptions import (
    BOUNDARY_LANGUAGES,
    Boundary,
    load_boundaries,
    name_matches,
)
from shockharness.rules.policy_integrity import FIRST_LINE, USER_TIERS, fingerprinted, read_text
from shockharness.rules.registry import EXC005
from shockharness.rules.severity import section_severity

EXCEPTIONS_SECTION = "rules.exceptions"
# A boundary's `path = "<glob>"`, inline or in its own table (`paths = [...]` of an
# override does not match).
PATH_ASSIGNMENT = r'\bpath\s*=\s*"{}"'


def _covers(boundary: Boundary, discovered: DiscoveredFile) -> bool:
    languages = BOUNDARY_LANGUAGES[discovered.language]
    return boundary.language in languages and boundary.paths.matches(discovered.relative)


def _caught(name: str, catches: Sequence[CatchFact]) -> bool:
    return any(name_matches(identity, name) for catch in catches for identity in catch.identities)


def _boundary_lines(text: str | None, boundaries: Sequence[Boundary]) -> dict[int, int]:
    """Boundary index -> the line of its ``path = "<glob>"``: the k-th such line for the
    k-th boundary with that glob, else the first line."""
    lines: list[str] = []
    if text is not None:
        lines = text.splitlines()
    seen: dict[str, int] = {}
    found: dict[int, int] = {}
    for boundary in boundaries:
        if boundary.path not in seen:
            seen[boundary.path] = 0
        occurrence = seen[boundary.path]
        seen[boundary.path] = occurrence + 1
        pattern = re.compile(PATH_ASSIGNMENT.format(re.escape(boundary.path)))
        hits = [n for n, line in enumerate(lines, start=FIRST_LINE) if pattern.search(line)]
        found[boundary.index] = FIRST_LINE
        if occurrence < len(hits):
            found[boundary.index] = hits[occurrence]
    return found


def config_anchor(root: Path, config: EffectiveConfig) -> str:
    source = Path(config.source.path).resolve()
    if source.is_relative_to(root.resolve()):
        return source.relative_to(root.resolve()).as_posix()
    return source.name


def _finding(
    path: str, line: int, boundary: Boundary, name: str, severity: str, evidence: str
) -> Finding:
    return Finding(
        rule_id=EXC005.rule_id,
        rule_version=EXC005.version,
        severity=severity,
        path=path,
        span=Span(line, FIRST_LINE, line, FIRST_LINE),
        message=(
            f"rules.exceptions.boundaries[{boundary.index}] approves catching {name} in "
            f"{boundary.path} ({boundary.language}), but no catch there catches it; a boundary "
            "nothing uses pre-approves catches nobody has reviewed"
        ),
        evidence=evidence,
        confidence=CONFIDENCE_EXACT,
        status=STATUS_VIOLATION,
        remediation=EXC005.remediation,
        safe_autofix=False,
        scope=MODULE_SCOPE,
        suppression=None,
        fingerprint=None,
        baseline=None,
    )


def _judgeable(
    boundary: Boundary,
    every: Sequence[DiscoveredFile],
    analyzed: Mapping[str, Sequence[CatchFact]],
) -> list[DiscoveredFile] | None:
    """The files the boundary covers, or None when it cannot be judged in this run."""
    covered = [discovered for discovered in every if _covers(boundary, discovered)]
    if len(covered) == 0 or any(d.relative not in analyzed for d in covered):
        return None
    return covered


def unused_boundary_findings(
    catches: Mapping[str, Sequence[CatchFact]], root: Path, config: EffectiveConfig
) -> tuple[Finding, ...]:
    """EXC005 for every exception a declared boundary names that no covered catch catches.
    ``catches`` holds every parsed file's catches (``AnalysisOutcome.catches``)."""
    settings: Mapping[str, Any] = config.section(EXCEPTIONS_SECTION)
    boundaries = load_boundaries(settings)
    if settings["enabled"] is not True or len(boundaries) == 0:
        return ()
    if config.source.tier not in USER_TIERS:
        return ()
    every = discover(root, [root], config).files
    text, _error = read_text(Path(config.source.path))
    lines = _boundary_lines(text, boundaries)
    path = config_anchor(root, config)
    severity = section_severity(settings, EXC005.default_severity)
    findings: list[Finding] = []
    for boundary in boundaries:
        covered = _judgeable(boundary, every, catches)
        if covered is None:
            continue
        found = [catch for d in covered for catch in catches[d.relative]]
        for name in boundary.exceptions:
            if _caught(name, found):
                continue
            evidence = f"boundaries[{boundary.index}] {name} in {boundary.path}: unused"
            findings.append(
                _finding(path, lines[boundary.index], boundary, name, severity, evidence)
            )
    return fingerprinted(findings)
