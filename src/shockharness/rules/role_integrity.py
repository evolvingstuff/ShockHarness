"""ROLE001: is code classified as a test really a test? (spec 21.1 decision 24)

The test role is an exemption: the H3/H5 rules apply to production files only. So the
claim "this is a test" is checked from two directions, in the cross-file phase:

* **who imports it** (exact): a production-role file that imports a test-role file,
  through a resolved edge of the module graph, ships that test-role code. The finding is
  at the import, in the production file;
* **what it contains** (review by default): a test-role file whose verification facts
  hold no test case, and that matches none of ``support_files``.

The third direction (a change that newly classifies a production file as a test) needs a
base revision and is VERIFY003's (rules/policy_integrity.py).
"""

from collections.abc import Mapping, Sequence
from typing import Any

from shockharness.complexity.callgraph import CONFIDENCE_RESOLVED, CallGraph
from shockharness.findings import STATUS_VIOLATION, Finding
from shockharness.globs import compile_globset
from shockharness.ir.model import CONFIDENCE_APPROXIMATE, CONFIDENCE_EXACT, ModuleFacts, Span
from shockharness.roles import ROLE_PRODUCTION, ROLE_TEST
from shockharness.rules.registry import ROLE001
from shockharness.source import SourceText

FIRST_LINE_SPAN = Span(line=1, column=1, end_line=1, end_column=1)


class RoleFile:
    """What ROLE001 needs from one analyzed file."""

    def __init__(
        self,
        path: str,
        role: str,
        role_pattern: str | None,
        facts: ModuleFacts,
        source: SourceText,
        applies: bool,
    ) -> None:
        self.path = path
        self.role = role
        self.role_pattern = role_pattern
        self.facts = facts
        self.source = source
        self.applies = applies


def _finding(severity: str, file: RoleFile, span: Span, message: str, confidence: str) -> Finding:
    return Finding(
        rule_id=ROLE001.rule_id,
        rule_version=ROLE001.version,
        severity=severity,
        path=file.path,
        span=span,
        message=message,
        evidence=file.source.excerpt(span.line),
        confidence=confidence,
        status=STATUS_VIOLATION,
        remediation=ROLE001.remediation,
        safe_autofix=False,
        scope=None,
        suppression=None,
        fingerprint=None,
        baseline=None,
    )


def _classified(file: RoleFile) -> str:
    if file.role_pattern is None:
        return "classified as a test file"
    return f"classified as a test file by {file.role_pattern!r}"


def _imports_of_tests(
    files: Mapping[str, RoleFile], graph: CallGraph, severity: str
) -> list[Finding]:
    found: list[Finding] = []
    for edge in graph.module_edges:
        if edge.confidence != CONFIDENCE_RESOLVED or edge.target is None:
            continue
        if edge.source not in files or edge.target not in files:
            continue
        importer, imported = files[edge.source], files[edge.target]
        if not importer.applies or importer.role != ROLE_PRODUCTION or imported.role != ROLE_TEST:
            continue
        found.append(
            _finding(
                severity,
                importer,
                edge.span,
                f"production code imports {imported.path}, {_classified(imported)}: that code "
                "ships, yet the production rules do not apply to it",
                CONFIDENCE_EXACT,
            )
        )
    return found


def _empty_tests(files: Mapping[str, RoleFile], settings: Mapping[str, Any]) -> list[Finding]:
    support = compile_globset([str(g) for g in settings["support_files"]])
    severity = str(settings["empty_test_severity"])
    found: list[Finding] = []
    for file in files.values():
        if not file.applies or file.role != ROLE_TEST or support.matches(file.path):
            continue
        if len(file.facts.verification.cases) > 0:
            continue
        found.append(
            _finding(
                severity,
                file,
                FIRST_LINE_SPAN,
                f"{file.path} is {_classified(file)} but contains no test case; if it is support "
                "code, list it in rules.role_integrity.support_files, otherwise it should not be "
                "exempt from the production rules",
                CONFIDENCE_APPROXIMATE,
            )
        )
    return found


def run_role_integrity(
    files: Sequence[RoleFile], graph: CallGraph, settings: Mapping[str, Any]
) -> dict[str, list[Finding]]:
    """ROLE001 findings per path, for the files where the rule applies."""
    by_path = {file.path: file for file in files}
    found: dict[str, list[Finding]] = {}
    for finding in [
        *_imports_of_tests(by_path, graph, str(settings["severity"])),
        *_empty_tests(by_path, settings),
    ]:
        if finding.path not in found:
            found[finding.path] = []
        found[finding.path].append(finding)
    return found
