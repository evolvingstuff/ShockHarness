"""Findings of the property-contracts rules, shared by the Python and JavaScript checks.

A finding is placed by a language's own ``locate`` (its span and the node's text as
evidence). Each rule is reported only in files where it applies; a malformed
``enable(...)`` in a test bootstrap is PROP006 placed under PROP005's scope.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from shockharness.contracts.python_flow import PropSet
from shockharness.findings import STATUS_UNKNOWN, STATUS_VIOLATION, Finding
from shockharness.ir.model import CONFIDENCE_EXACT, Span
from shockharness.rules.registry import PROP001, PROP003, RuleSpec
from shockharness.source import SourceText

SEVERITY_ERROR = "error"
SEVERITY_REVIEW = "review"


@dataclass(frozen=True)
class ContractFile:
    path: str
    language: str
    source: SourceText
    applies: frozenset[str]  # the PROP rule IDs applied to this file


@dataclass(frozen=True)
class Located:
    span: Span
    evidence: str


@dataclass(frozen=True)
class Issue:
    rule: RuleSpec
    node: object  # a node of the file's language, placed by the reporter's locate
    message: str
    # The rule whose scope decides whether it is reported: the rule itself, or PROP005
    # for a malformed enable(...) in a test bootstrap (PROP006 there, spec §6.2).
    scope: RuleSpec


@dataclass(frozen=True)
class Requirement:
    """How a PROP001 message states what is required: "<subject> <properties><where>;
    <noun> has ..."."""

    subject: str
    where: str
    noun: str


PASSED = "the value passed here"
ASSIGNED = "the value assigned here"


def quoted(properties: frozenset[str]) -> str:
    return ", ".join(repr(p) for p in sorted(properties))


class Reporter:
    def __init__(
        self,
        file: ContractFile,
        settings: Mapping[str, Any],
        locate: Callable[[object], Located],
    ) -> None:
        self.file = file
        self.severities = settings["severities"]
        self.allow_undeclared = settings["allow_undeclared"] is True
        self.locate = locate
        self.found: dict[tuple[str, int, int, str], Finding] = {}

    def severity(self, rule: RuleSpec) -> str:
        severity = str(self.severities[rule.rule_id])
        if rule is PROP003 and self.allow_undeclared and severity == SEVERITY_ERROR:
            return SEVERITY_REVIEW  # the catalog accepted unlisted names (§7)
        return severity

    def add(self, rule: RuleSpec, node: object, message: str, status: str) -> None:
        if rule.rule_id in self.file.applies:
            self._record(rule, node, message, status)

    def add_issue(self, issue: Issue) -> None:
        if issue.scope.rule_id in self.file.applies:
            self._record(issue.rule, issue.node, issue.message, STATUS_VIOLATION)

    def _record(self, rule: RuleSpec, node: object, message: str, status: str) -> None:
        at = self.locate(node)
        key = (rule.rule_id, at.span.line, at.span.column, message)
        if key in self.found:
            return  # a loop or a finally block walked twice
        self.found[key] = Finding(
            rule_id=rule.rule_id,
            rule_version=rule.version,
            severity=self.severity(rule),
            path=self.file.path,
            span=at.span,
            message=message,
            evidence=at.evidence,
            confidence=CONFIDENCE_EXACT,
            status=status,
            remediation=rule.remediation,
            safe_autofix=False,
            scope=None,
            suppression=None,
            fingerprint=None,
            baseline=None,
        )

    def check(
        self, node: object, value: PropSet, required: frozenset[str], stated: Requirement
    ) -> None:
        """PROP001 unless ``value`` carries ``required``."""
        missing = required - value.known
        if len(missing) == 0:
            return
        prefix = f"{stated.subject} {quoted(missing)}{stated.where}"
        if value.exact:
            message = f"{prefix}; {stated.noun} has {value.render()}"
            if value.why != "":
                message = f"{message} ({value.why})"
            self.add(PROP001, node, message, STATUS_VIOLATION)
            return
        pronoun = "it" if len(missing) == 1 else "them"
        message = (
            f"{prefix}; the analysis cannot tell whether {stated.noun} carries {pronoun}: "
            f"{value.why}"
        )
        self.add(PROP001, node, message, STATUS_UNKNOWN)
