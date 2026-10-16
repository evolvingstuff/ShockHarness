"""Inline suppression comments.

Exact form, on the same line as the construct it covers::

    x = 30  # shockharness: ignore[MAGIC001] reason="RFC 7231 status class"
    x = 30; // shockharness: ignore[MAGIC001] reason="RFC 7231 status class"

Several rule IDs may be listed, comma-separated. A comment that starts the
``shockharness:`` prefix but does not match the form, names an unknown rule, or
has an empty reason is a SUPP001 finding. A suppression that silences nothing is
a SUPP002 finding. Suppressed findings stay in the report with their suppression
attached; only the gate ignores them.
"""

import re
from dataclasses import dataclass

from shockharness.findings import CONFIDENCE_EXACT, STATUS_VIOLATION, Finding, SuppressionRecord
from shockharness.ir.model import Comment, Span
from shockharness.rules import registry
from shockharness.rules.registry import SUPP001, SUPP002
from shockharness.source import SourceText

PREFIX = "shockharness:"
FORM = re.compile(
    r"shockharness:\s*ignore\[(?P<ids>[^\]]*)\]\s*reason=\"(?P<reason>[^\"]*)\"\s*(?:\*/)?\s*$"
)


@dataclass(frozen=True)
class Suppression:
    span: Span
    rule_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class SuppressionProblem:
    span: Span
    message: str


def parse_suppressions(
    comments: tuple[Comment, ...],
) -> tuple[tuple[Suppression, ...], tuple[SuppressionProblem, ...]]:
    suppressions: list[Suppression] = []
    problems: list[SuppressionProblem] = []
    for comment in comments:
        index = comment.text.find(PREFIX)
        if index < 0:
            continue
        match = FORM.match(comment.text[index:])
        if match is None:
            problems.append(
                SuppressionProblem(
                    span=comment.span,
                    message=(
                        'malformed suppression; expected shockharness: ignore[RULEID] reason="..."'
                    ),
                )
            )
            continue
        raw_ids = [part.strip() for part in match.group("ids").split(",")]
        rule_ids = tuple(part for part in raw_ids if part != "")
        reason = match.group("reason").strip()
        valid = True
        if len(rule_ids) == 0:
            problems.append(SuppressionProblem(comment.span, "suppression names no rule ID"))
            valid = False
        for rule_id in rule_ids:
            if not registry.is_known_rule(rule_id):
                problems.append(
                    SuppressionProblem(comment.span, f"suppression names unknown rule {rule_id!r}")
                )
                valid = False
            elif registry.needs_base_revision(registry.get_rule(rule_id)):
                # Spec 21.1 decision 5: a change cannot excuse its own weakening of the
                # checks with a comment it adds itself; exceptions are central policy.
                problems.append(
                    SuppressionProblem(
                        comment.span,
                        f"{rule_id} cannot be suppressed inline; record an exception in "
                        "rules.verification or an [[overrides]] entry instead",
                    )
                )
                valid = False
        if reason == "":
            problems.append(SuppressionProblem(comment.span, "suppression has an empty reason"))
            valid = False
        if valid:
            suppressions.append(Suppression(span=comment.span, rule_ids=rule_ids, reason=reason))
    return tuple(suppressions), tuple(problems)


def _problem_finding(path: str, problem: SuppressionProblem, evidence: str) -> Finding:
    return Finding(
        rule_id=SUPP001.rule_id,
        rule_version=SUPP001.version,
        severity=SUPP001.default_severity,
        path=path,
        span=problem.span,
        message=problem.message,
        evidence=evidence,
        confidence=CONFIDENCE_EXACT,
        status=STATUS_VIOLATION,
        remediation=SUPP001.remediation,
        safe_autofix=False,
        scope=None,
        suppression=None,
        fingerprint=None,
        baseline=None,
    )


def _unused_finding(path: str, suppression: Suppression, rule_id: str, evidence: str) -> Finding:
    return Finding(
        rule_id=SUPP002.rule_id,
        rule_version=SUPP002.version,
        severity=SUPP002.default_severity,
        path=path,
        span=suppression.span,
        message=f"suppression of {rule_id} on this line silences nothing",
        evidence=evidence,
        confidence=CONFIDENCE_EXACT,
        status=STATUS_VIOLATION,
        remediation=SUPP002.remediation,
        safe_autofix=False,
        scope=None,
        suppression=None,
        fingerprint=None,
        baseline=None,
    )


def apply_suppressions(
    path: str,
    findings: list[Finding],
    comments: tuple[Comment, ...],
    source: SourceText,
    honor_inline: bool,
    supp001_enabled: bool,
    supp002_enabled: bool,
) -> list[Finding]:
    """Attach suppressions to findings and append SUPP001/SUPP002 findings.

    ``source`` supplies evidence excerpts. When ``honor_inline`` is
    false (``--no-inline-suppressions``), nothing is suppressed and every
    suppression comment becomes a SUPP001 finding stating the policy.
    """
    suppressions, problems = parse_suppressions(comments)
    result: list[Finding] = []

    if not honor_inline:
        result.extend(findings)
        if supp001_enabled:
            for suppression in suppressions:
                excerpt = source.excerpt(suppression.span.line)
                result.append(
                    _problem_finding(
                        path,
                        SuppressionProblem(
                            suppression.span,
                            "inline suppressions are disabled by policy (--no-inline-suppressions)",
                        ),
                        excerpt,
                    )
                )
            for problem in problems:
                excerpt = source.excerpt(problem.span.line)
                result.append(_problem_finding(path, problem, excerpt))
        return result

    by_line: dict[int, list[Suppression]] = {}
    for suppression in suppressions:
        if suppression.span.line not in by_line:
            by_line[suppression.span.line] = []
        by_line[suppression.span.line].append(suppression)

    used: set[tuple[int, str]] = set()
    for finding in findings:
        matched: Suppression | None = None
        if finding.span.line in by_line:
            for candidate in by_line[finding.span.line]:
                if finding.rule_id in candidate.rule_ids:
                    matched = candidate
                    break
        if matched is None:
            result.append(finding)
            continue
        used.add((finding.span.line, finding.rule_id))
        result.append(
            finding.with_suppression(
                SuppressionRecord(line=matched.span.line, reason=matched.reason)
            )
        )

    if supp001_enabled:
        for problem in problems:
            excerpt = source.excerpt(problem.span.line)
            result.append(_problem_finding(path, problem, excerpt))
    if supp002_enabled:
        for suppression in suppressions:
            for rule_id in suppression.rule_ids:
                if (suppression.span.line, rule_id) in used:
                    continue
                excerpt = source.excerpt(suppression.span.line)
                result.append(_unused_finding(path, suppression, rule_id, excerpt))
    return result
