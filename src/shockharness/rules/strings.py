"""MAGIC002: one string literal repeated across files (decision 31).

A status ("pending"), an error code ("E404"), a platform or command name written out at
several places, and compared in more than one file, is one decision copied around: a
rename or a typo in one copy silently splits it. Requiring comparisons is what separates
a decision string from a word that happens to repeat (measured on pip, pytest,
hypothesis, build, hatchling and npm: 956 repeated values, 179 compared in two files).

Cross-file: the string facts of every file where the rule applies, grouped by value; a
value long enough, used often enough in enough files, compared in enough of them and not
allowed, is reported once, at its first use, with the other places in the message.
Messages (log calls, exceptions) and the kinds the configuration leaves out are not
counted.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from shockharness.constants import STRING_PLACES_SHOWN, STRING_VALUE_SHOWN
from shockharness.findings import STATUS_VIOLATION, Finding
from shockharness.ir.model import (
    CONFIDENCE_APPROXIMATE,
    STRING_ARGUMENT,
    STRING_COMPARE,
    StringUse,
)
from shockharness.rules.registry import MAGIC002
from shockharness.source import SourceText

MODE_FAIL = "fail"
SEVERITY_FOR_FAIL = "error"
METHOD_PREFIX = "."
# A call whose last name ends with one of these builds an exception or a warning, whose
# message is prose, not a constant.
EXCEPTION_SUFFIXES = ("Error", "Exception", "Warning")


@dataclass(frozen=True)
class StringFile:
    path: str
    strings: tuple[StringUse, ...]
    source: SourceText
    applies: bool


@dataclass(frozen=True)
class Use:
    file: StringFile
    use: StringUse


def _is_message(use: StringUse, message_callees: frozenset[str]) -> bool:
    if use.kind != STRING_ARGUMENT or use.callee == "":
        return False
    _receiver, _dot, name = use.callee.rpartition(METHOD_PREFIX)
    return name in message_callees or name.endswith(EXCEPTION_SUFFIXES)


def _counted(use: StringUse, settings: Mapping[str, Any], messages: frozenset[str]) -> bool:
    if use.kind not in {str(k) for k in settings["kinds"]}:
        return False
    if len(use.value.strip()) < int(settings["min_length"]):
        return False
    if use.value in {str(v) for v in settings["allowed"]}:
        return False
    return not _is_message(use, messages)


def _groups(files: Sequence[StringFile], settings: Mapping[str, Any]) -> dict[str, list[Use]]:
    messages = frozenset(str(c) for c in settings["message_callees"])
    groups: dict[str, list[Use]] = {}
    for file in files:
        if not file.applies:
            continue
        for use in file.strings:
            if not _counted(use, settings, messages):
                continue
            if use.value not in groups:
                groups[use.value] = []
            groups[use.value].append(Use(file, use))
    return groups


def _shown(value: str) -> str:
    if len(value) > STRING_VALUE_SHOWN:
        return repr(value[:STRING_VALUE_SHOWN] + "...")
    return repr(value)


def _finding(value: str, uses: Sequence[Use], files: int, severity: str) -> Finding:
    first = uses[0]
    others = ", ".join(
        f"{u.file.path}:{u.use.span.line}" for u in uses[1 : STRING_PLACES_SHOWN + 1]
    )
    more = ""
    if len(uses) > STRING_PLACES_SHOWN + 1:
        more = f" and {len(uses) - STRING_PLACES_SHOWN - 1} more"
    message = (
        f"{_shown(value)} is written out {len(uses)} times in {files} files (also {others}"
        f"{more}): if it names one thing (a status, an endpoint, a header, a code), give it "
        "one name"
    )
    return Finding(
        rule_id=MAGIC002.rule_id,
        rule_version=MAGIC002.version,
        severity=severity,
        path=first.file.path,
        span=first.use.span,
        message=message,
        evidence=first.file.source.excerpt(first.use.span.line),
        confidence=CONFIDENCE_APPROXIMATE,
        status=STATUS_VIOLATION,
        remediation=MAGIC002.remediation,
        safe_autofix=False,
        scope=None,
        suppression=None,
        fingerprint=None,
        baseline=None,
    )


def run_magic002(
    files: Sequence[StringFile], settings: Mapping[str, Any]
) -> dict[str, list[Finding]]:
    """MAGIC002 findings per path (the path of each value's first use)."""
    severity = MAGIC002.default_severity
    if settings["mode"] == MODE_FAIL:
        severity = SEVERITY_FOR_FAIL
    found: dict[str, list[Finding]] = {}
    for value, uses in sorted(_groups(files, settings).items()):
        ordered = sorted(uses, key=lambda u: (u.file.path, u.use.span))
        files_used = len({u.file.path for u in ordered})
        compared = len({u.file.path for u in ordered if u.use.kind == STRING_COMPARE})
        if len(ordered) < int(settings["min_occurrences"]):
            continue
        if files_used < int(settings["min_files"]) or compared < int(
            settings["min_compared_files"]
        ):
            continue
        finding = _finding(value, ordered, files_used, severity)
        if finding.path not in found:
            found[finding.path] = []
        found[finding.path].append(finding)
    return found
