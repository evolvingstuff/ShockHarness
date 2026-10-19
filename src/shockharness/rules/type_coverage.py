"""TYPE002 (decision 33): Python type annotations that nothing checks. One finding per run.

Reported when at least ``annotated_share`` of the production functions where the rule
applies, and at least ``min_annotated_functions`` of them, carry an annotation, and no
Python type checker is configured at the analysis root: mypy, pyright, basedpyright, pyre
or ty, through their own files, their ``pyproject.toml`` tables, or ``[mypy]`` in
``setup.cfg`` / ``tox.ini``.

A configured checker is not proof that it runs: the rule reads configuration only.
TypeScript is not covered: a TypeScript project that builds has a ``tsconfig.json``.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shockharness.findings import CONFIDENCE_EXACT, STATUS_VIOLATION, Finding
from shockharness.ir.model import MODULE_SCOPE, AnnotationFacts, Span
from shockharness.rules.policy_integrity import read_text
from shockharness.rules.registry import PYTHON, TYPE002
from shockharness.rules.tool_configs import (
    CHECKER_INI_FILES,
    PYPROJECT,
    PYTHON_CHECKER_FILES,
    python_checkers_in,
)
from shockharness.source import SourceText

SETTING_SHARE = "annotated_share"
SETTING_MINIMUM = "min_annotated_functions"
SETTING_SEVERITY = "type002_severity"


@dataclass(frozen=True)
class TypedFile:
    path: str
    language: str
    source: SourceText
    annotations: AnnotationFacts


def python_checkers(root: Path) -> frozenset[str]:
    """The Python type checkers configured at ``root``; an unreadable file configures
    nothing."""
    found: set[str] = {name for name in PYTHON_CHECKER_FILES if (root / name).is_file()}
    for name in (PYPROJECT, *CHECKER_INI_FILES):
        if not (root / name).is_file():
            continue
        text, _error = read_text(root / name)
        if text is not None:
            checkers, _invalid = python_checkers_in(name, text)
            found.update(checkers)
    return frozenset(found)


def _finding(path: str, span: Span, message: str, source: SourceText, severity: str) -> Finding:
    return Finding(
        rule_id=TYPE002.rule_id,
        rule_version=TYPE002.version,
        severity=severity,
        path=path,
        span=span,
        message=message,
        evidence=source.excerpt(span.line),
        confidence=CONFIDENCE_EXACT,
        status=STATUS_VIOLATION,
        remediation=TYPE002.remediation,
        safe_autofix=False,
        scope=MODULE_SCOPE,
        suppression=None,
        fingerprint=None,
        baseline=None,
    )


def _python(
    files: Sequence[TypedFile], root: Path, settings: Mapping[str, Any], severity: str
) -> list[Finding]:
    python = [f for f in files if f.language == PYTHON]
    functions = sum(f.annotations.functions for f in python)
    annotated = sum(f.annotations.annotated for f in python)
    share = float(settings[SETTING_SHARE])
    if annotated < int(settings[SETTING_MINIMUM]) or annotated < share * functions:
        return []
    if len(python_checkers(root)) > 0:
        return []
    ordered = sorted(python, key=lambda f: f.path)
    anchor = next(f for f in ordered if f.annotations.first is not None)
    assert anchor.annotations.first is not None, "an annotated file has a first function"
    message = (
        f"{annotated} of {functions} functions carry type annotations, and no Python type "
        "checker is configured (mypy, pyright, basedpyright, pyre or ty): nothing verifies "
        "what the annotations claim"
    )
    return [_finding(anchor.path, anchor.annotations.first, message, anchor.source, severity)]


def run_type002(
    files: Sequence[TypedFile], root: Path, settings: Mapping[str, Any]
) -> dict[str, list[Finding]]:
    severity = str(settings[SETTING_SEVERITY])
    found: dict[str, list[Finding]] = {}
    for finding in _python(files, root, settings, severity):
        if finding.path not in found:
            found[finding.path] = []
        found[finding.path].append(finding)
    return found
