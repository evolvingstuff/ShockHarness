"""MAGIC003: a small number standing in for a project's own meaning (decision 30).

MAGIC001 permits -1, 0 and 1 because they are the building blocks of counting and
indexing. Sometimes they are not: ``selected_index = -1`` for "nothing selected",
``exit_code = -1`` for "never ran". MAGIC003 reports the configured values (``-1`` by
default) only where they stand for a value (assigned, returned, passed, an entry of a
dict or object literal), never in a subscript, a slice, arithmetic or a comparison, and
not as an argument of a callee that takes an index or a count (``range``, ``.slice``,
``.at``, ``.split``). An UPPER_SNAKE_CASE target is the name the rule asks for.
"""

from collections.abc import Mapping
from typing import Any

from shockharness.constants import NEGATIVE_ONE
from shockharness.findings import STATUS_VIOLATION, Finding
from shockharness.ir.model import (
    CONFIDENCE_APPROXIMATE,
    SENTINEL_ARGUMENT,
    SENTINEL_ASSIGN,
    SENTINEL_ENTRY,
    ModuleFacts,
    SentinelUse,
)
from shockharness.rules.guardrails import import_aliases, qualified_callee
from shockharness.rules.registry import MAGIC003, PYTHON
from shockharness.source import SourceText

KEYWORD_SEPARATOR = "="
METHOD_PREFIX = "."


def _exempt(callee: str, aliases: Mapping[str, str], index_callees: frozenset[str]) -> bool:
    if qualified_callee(callee, aliases) in index_callees:
        return True
    receiver, dot, name = callee.rpartition(METHOD_PREFIX)
    return dot != "" and receiver != "" and METHOD_PREFIX + name in index_callees


def _where(use: SentinelUse) -> str:
    if use.kind == SENTINEL_ASSIGN:
        return f"is assigned to {use.target}"
    if use.kind == SENTINEL_ENTRY:
        return f"is the value of {use.target}"
    if use.kind == SENTINEL_ARGUMENT:
        callee, _separator, keyword = use.target.partition(KEYWORD_SEPARATOR)
        if keyword != "":
            return f"is passed to {callee}(...) as {keyword}"
        return f"is passed to {callee}(...)"
    return "is returned"


def _standard(use: SentinelUse, standard_targets: frozenset[str]) -> bool:
    """An assignment to, or an entry of, a name whose -1 a platform standard defines."""
    if use.kind not in (SENTINEL_ASSIGN, SENTINEL_ENTRY):
        return False
    _receiver, _dot, name = use.target.rpartition(METHOD_PREFIX)
    return name in standard_targets


def _directions(facts: ModuleFacts) -> frozenset[str]:
    """Callees (with their keyword) the file also passes ``1``: there a ``-1`` is the
    opposite step (``move(-1)`` beside ``move(1)``), not a sentinel."""
    return frozenset(
        use.target for use in facts.sentinels if use.kind == SENTINEL_ARGUMENT and use.value == 1
    )


def _checked(settings: Mapping[str, Any], magic: Mapping[str, Any]) -> set[float]:
    """The configured values MAGIC001 permits (the others MAGIC001 reports itself)."""
    permitted = {float(v) for v in magic["allowed_values"]}
    if magic["allow_unary_negative_one"] is True:
        permitted.add(NEGATIVE_ONE)
    return {float(v) for v in settings["values"]} & permitted


def run_magic003(
    facts: ModuleFacts,
    source: SourceText,
    path: str,
    language: str,
    settings: Mapping[str, Any],
    magic: Mapping[str, Any],
) -> list[Finding]:
    """MAGIC003 for one file; ``magic`` is rules.magic_numbers (a value MAGIC001 already
    reports is not reported twice)."""
    checked = _checked(settings, magic)
    prefix = "python" if language == PYTHON else "javascript"
    index_callees = frozenset(str(c) for c in settings[f"{prefix}_index_callees"])
    standard_targets = frozenset(str(t) for t in settings["standard_targets"])
    directions = _directions(facts)
    aliases = import_aliases(facts.imports, language)
    found: list[Finding] = []
    for use in facts.sentinels:
        if use.value not in checked or _standard(use, standard_targets):
            continue
        if use.kind == SENTINEL_ARGUMENT:
            callee = use.target.partition(KEYWORD_SEPARATOR)[0]
            if _exempt(callee, aliases, index_callees) or use.target in directions:
                continue
        message = (
            f"{use.raw} {_where(use)}: if it stands for something this program means "
            f'("nothing selected", "never ran", "no limit"), give it a name'
        )
        found.append(
            Finding(
                rule_id=MAGIC003.rule_id,
                rule_version=MAGIC003.version,
                severity=str(settings["severity"]),
                path=path,
                span=use.span,
                message=message,
                evidence=source.excerpt(use.span.line),
                confidence=CONFIDENCE_APPROXIMATE,
                status=STATUS_VIOLATION,
                remediation=MAGIC003.remediation,
                safe_autofix=False,
                scope=None,
                suppression=None,
                fingerprint=None,
                baseline=None,
            )
        )
    return found
