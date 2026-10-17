"""What makes one ShockHarness configuration looser than another (H2 part 2).

Shared by the ``--policy`` tier (a repository key may not loosen a key the policy file
sets) and by VERIFY003 (a change may not loosen the committed configuration without
it being reported). Pure functions over configuration *values* and their *deviation
lines*; the caller computes the deviations (``config._deviations``), so this module
does not import the configuration loader.

Three sources of looseness, each reported once per key:

1. **Deviation lines.** Every documented loosening relative to the strict profile is
   already a deviation line (disabled families, lowered severities, allowed values,
   boundaries, guards, capture managers, overrides, profile, parse_errors,
   fail_on_unknown, allowed skip reasons ...). A line present after and absent before
   is a loosening. List indices are normalized away (``boundaries[3]`` and
   ``boundaries[0]`` are the same entry text) and lines are matched as a multiset, so
   reordering a list is not a loosening.
2. **Ordered settings** that are not deviations: gate modes, ``unsupported_sources``,
   the VERIFY severity, the fan-out severity. Moving towards the end of the order is
   looser.
3. **Thresholds and scope.** A raised complexity threshold; a pattern added to
   ``exclude``; a pattern removed from ``include``.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

INDEX = re.compile(r"\[\d+\]")
LEADING_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")

# Strictest first: a later value is looser.
ORDERED_SETTINGS: Mapping[str, tuple[str, ...]] = {
    "gates.new_hard_violations": ("fail", "warn"),
    "gates.legacy": ("fail", "baseline", "ignore"),
    "gates.complexity_regressions": ("fail", "warn", "ignore"),
    "unsupported_sources": ("fail", "warn", "ignore"),
    "parse_errors": ("fail", "warn"),
    "rules.verification.severity": ("error", "warning", "review"),
    # Allowing -1 is the default; a project that had it off and turns it on loosens.
    "rules.magic_numbers.allow_unary_negative_one": ("False", "True"),
    "complexity.fan_out_severity": ("warning", "review"),
    "rules.stubs.severity": ("error", "warning", "review"),
    "rules.assertions.severity": ("error", "warning", "review"),
    "rules.boolean_arguments.severity": ("error", "warning", "review"),
    "rules.module_state.severity": ("error", "warning", "review"),
    "rules.import_effects.severity": ("error", "warning", "review"),
    "rules.async_lifecycle.severity": ("error", "warning", "review"),
    "rules.stubs.stub003_severity": ("error", "warning", "review"),
    "rules.processes.severity": ("error", "warning", "review"),
    "rules.results.severity": ("error", "warning", "review"),
    "rules.types.severity": ("error", "warning", "review"),
    "rules.sleep.severity": ("error", "warning", "review"),
    "rules.retry.severity": ("error", "warning", "review"),
    "rules.batches.severity": ("error", "warning", "review"),
    "rules.role_integrity.severity": ("error", "warning", "review"),
    "rules.role_integrity.empty_test_severity": ("error", "warning", "review"),
    "rules.input.severity": ("error", "warning", "review"),
    "rules.assertions.assert002_severity": ("error", "warning", "review"),
    "rules.input.input002_severity": ("error", "warning", "review"),
    "rules.consistency.severity": ("error", "warning", "review"),
    "rules.sentinels.severity": ("error", "warning", "review"),
    "rules.dom.severity": ("error", "warning", "review"),
}
# A higher value reports less.
THRESHOLDS = (
    "complexity.cognitive_warn",
    "complexity.cyclomatic_warn",
    "complexity.max_nesting_warn",
    "complexity.npath_warn",
    "complexity.fan_out_warn",
    "complexity.max_lines_warn",
)
INCLUDE_KEY = "include"
EXCLUDE_KEY = "exclude"


@dataclass(frozen=True)
class Loosening:
    """``key`` is the dotted key the loosening concerns (for anchoring and for the
    ``--policy`` revert); ``message`` says what got looser."""

    key: str
    message: str


def value_at(values: Mapping[str, Any], dotted: str) -> Any:
    node: Any = values
    for part in dotted.split("."):
        node = node[part]
    return node


def has_key(values: Mapping[str, Any], dotted: str) -> bool:
    node: Any = values
    for part in dotted.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return False
        node = node[part]
    return True


def deviation_key(line: str) -> str:
    """The dotted key a deviation line starts with (``overrides[2] disables ...`` ->
    ``overrides``; ``rules.magic_numbers is disabled`` -> ``rules.magic_numbers``)."""
    match = LEADING_KEY.match(INDEX.sub("", line))
    if match is None:
        return ""
    return match.group(0).rstrip(".")


def _normalized(line: str) -> str:
    return INDEX.sub("[]", line)


def new_deviations(before: Sequence[str], after: Sequence[str]) -> list[str]:
    """Deviation lines of ``after`` not matched by one of ``before`` (a multiset
    difference on index-normalized text). Returned as written in ``after``."""
    remaining: dict[str, int] = {}
    for line in before:
        key = _normalized(line)
        if key not in remaining:
            remaining[key] = 0
        remaining[key] += 1
    added: list[str] = []
    for line in after:
        key = _normalized(line)
        if key in remaining and remaining[key] > 0:
            remaining[key] -= 1
            continue
        added.append(line)
    return added


def _ordered(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[Loosening]:
    found: list[Loosening] = []
    for key, order in ORDERED_SETTINGS.items():
        if not has_key(before, key) or not has_key(after, key):
            continue
        old, new = str(value_at(before, key)), str(value_at(after, key))
        if old not in order or new not in order:
            continue
        if order.index(new) > order.index(old):
            found.append(Loosening(key, f"{key} changed from {old!r} to {new!r} (looser)"))
    return found


def _thresholds(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[Loosening]:
    found: list[Loosening] = []
    for key in THRESHOLDS:
        if not has_key(before, key) or not has_key(after, key):
            continue
        old, new = value_at(before, key), value_at(after, key)
        if isinstance(old, int) and isinstance(new, int) and new > old:
            found.append(
                Loosening(key, f"{key} raised from {old} to {new}: fewer units are reported")
            )
    return found


def _scope(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[Loosening]:
    found: list[Loosening] = []
    removed = [p for p in before[INCLUDE_KEY] if p not in after[INCLUDE_KEY]]
    if len(removed) > 0:
        found.append(
            Loosening(INCLUDE_KEY, "include no longer lists " + ", ".join(map(repr, removed)))
        )
    added = [p for p in after[EXCLUDE_KEY] if p not in before[EXCLUDE_KEY]]
    if len(added) > 0:
        found.append(
            Loosening(EXCLUDE_KEY, "exclude now also lists " + ", ".join(map(repr, added)))
        )
    return found


def loosenings(
    before_values: Mapping[str, Any],
    before_deviations: Sequence[str],
    after_values: Mapping[str, Any],
    after_deviations: Sequence[str],
) -> list[Loosening]:
    """Everything in ``after`` that is looser than ``before``, one entry per cause."""
    found = [
        Loosening(deviation_key(line), line)
        for line in new_deviations(before_deviations, after_deviations)
    ]
    reported = {item.key for item in found}
    for item in [
        *_ordered(before_values, after_values),
        *_thresholds(before_values, after_values),
        *_scope(before_values, after_values),
    ]:
        if item.key in reported:
            continue
        found.append(item)
        reported.add(item.key)
    return found
