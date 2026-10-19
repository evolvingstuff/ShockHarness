"""Per-unit complexity regressions between two revisions, and the experimental
abstraction-displacement heuristic. Both read the two reports' ``metrics``
sections, so they compare exactly what each report shows."""

from collections.abc import Mapping
from typing import Any

from shockharness.complexity.assemble import SETTING_DISPLACEMENT
from shockharness.complexity.callgraph import CONFIDENCE_RESOLVED, TARGET_UNIT
from shockharness.complexity.coupling import STATUS_AVAILABLE
from shockharness.ir.model import CONFIDENCE_APPROXIMATE, UNIT_MODULE
from shockharness.rules.complexity import METRIC_OF_RULE, METRIC_SIZE, THRESHOLD_OF_RULE
from shockharness.rules.registry import CPLX004, CPLX006

METRIC_NPATH = "npath"


def _functions_by_key(complexity: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {entry["key"]: entry for entry in complexity["functions"]}


def _value(entry: Mapping[str, Any], metric: str) -> int:
    if metric == METRIC_NPATH:
        return int(entry[METRIC_NPATH]["value"])
    if metric == METRIC_SIZE:
        return int(entry[METRIC_SIZE]["logical_lines"])
    return int(entry[metric])


def exceeds_threshold(entry: Mapping[str, Any], rule_id: str, settings: Mapping[str, Any]) -> bool:
    """Whether a ``metrics.complexity.functions`` entry is above the rule's threshold
    (``settings`` needs only the threshold keys, so ``metrics.complexity.thresholds`` works)."""
    metric = METRIC_OF_RULE[rule_id]
    threshold = int(settings[THRESHOLD_OF_RULE[rule_id]])
    if rule_id == CPLX004.rule_id:
        return bool(entry[METRIC_NPATH]["saturated"]) or _value(entry, metric) >= threshold
    if rule_id == CPLX006.rule_id and entry["kind"] == UNIT_MODULE:
        return False  # module bodies are exempt from CPLX006, in diffs as in checks
    return _value(entry, metric) > threshold


def complexity_regressions(
    base: Mapping[str, Any], head: Mapping[str, Any], settings: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Head units above a threshold whose value grew relative to the same unit at base.

    A unit absent at base (new, renamed, moved) counts as regressed when it is above
    the threshold: nothing at base justifies it. Sorted by path, span, metric.
    """
    if head["status"] != STATUS_AVAILABLE or base["status"] != STATUS_AVAILABLE:
        return []
    base_units = _functions_by_key(base)
    found: list[dict[str, Any]] = []
    for entry in head["functions"]:
        new_unit = entry["key"] not in base_units
        for rule_id, metric in METRIC_OF_RULE.items():
            if not exceeds_threshold(entry, rule_id, settings):
                continue
            head_value = _value(entry, metric)
            base_value = 0
            if not new_unit:
                base_value = _value(base_units[entry["key"]], metric)
            if head_value <= base_value:
                continue
            found.append(
                {
                    "rule_id": rule_id,
                    "key": entry["key"],
                    "path": entry["path"],
                    "name": entry["name"],
                    "span": dict(entry["span"]),
                    "metric": metric,
                    "base": None if new_unit else base_value,
                    "head": head_value,
                    "threshold": int(settings[THRESHOLD_OF_RULE[rule_id]]),
                    "convention": head["conventions"][metric],
                    "new_unit": new_unit,
                }
            )
    found.sort(key=lambda r: (r["path"], r["span"]["line"], r["span"]["column"], r["metric"]))
    return found


def _reachable_burden(complexity: Mapping[str, Any], graph: Mapping[str, Any]) -> dict[str, int]:
    """Summed cognitive complexity of each unit and everything reachable from it through
    resolved call edges to analyzed units (the unit itself included)."""
    cognitive = {entry["key"]: int(entry["cognitive"]) for entry in complexity["functions"]}
    successors: dict[str, list[str]] = {key: [] for key in cognitive}
    for edge in graph["edges"]:
        if edge["confidence"] != CONFIDENCE_RESOLVED or edge["to"]["kind"] != TARGET_UNIT:
            continue
        target = edge["to"]["id"]
        if edge["from"] in successors and target in cognitive:
            successors[edge["from"]].append(target)
    burden: dict[str, int] = {}
    for start in cognitive:
        seen = {start}
        stack = [start]
        total = 0
        while len(stack) > 0:
            node = stack.pop()
            total += cognitive[node]
            for child in successors[node]:
                if child not in seen:
                    seen.add(child)
                    stack.append(child)
        burden[start] = total
    return burden


def abstraction_displacement(
    base_metrics: Mapping[str, Any], head_metrics: Mapping[str, Any], settings: Mapping[str, Any]
) -> dict[str, Any]:
    """Units whose own cognitive score fell while the reachable burden grew (experimental)."""
    enabled = bool(settings[SETTING_DISPLACEMENT])
    note = (
        "experimental heuristic: a unit's own cognitive/1 fell between base and head while "
        "the cognitive/1 summed over everything reachable from it through resolved call edges "
        "grew; delegation is not inherently bad, and unresolved or probable edges are not "
        "followed, so every entry is approximate"
    )
    if not enabled:
        return {
            "enabled": False,
            "experimental": True,
            "status": "disabled",
            "reason": "complexity.abstraction_displacement = false",
            "findings": [],
            "note": note,
        }
    base_c = base_metrics["complexity"]
    head_c = head_metrics["complexity"]
    if base_c["status"] != STATUS_AVAILABLE or head_c["status"] != STATUS_AVAILABLE:
        return {
            "enabled": True,
            "experimental": True,
            "status": "unavailable",
            "reason": "complexity metrics are not available at both revisions",
            "findings": [],
            "note": note,
        }
    base_burden = _reachable_burden(base_c, base_metrics["graph"])
    head_burden = _reachable_burden(head_c, head_metrics["graph"])
    base_units = _functions_by_key(base_c)
    findings: list[dict[str, Any]] = []
    for entry in head_c["functions"]:
        key = entry["key"]
        if key not in base_units:
            continue
        before = base_units[key]
        local_before = int(before["cognitive"])
        local_after = int(entry["cognitive"])
        if local_after >= local_before or head_burden[key] <= base_burden[key]:
            continue
        findings.append(
            {
                "key": key,
                "path": entry["path"],
                "name": entry["name"],
                "span": dict(entry["span"]),
                "local": {"base": local_before, "head": local_after},
                "reachable_burden": {"base": base_burden[key], "head": head_burden[key]},
                "confidence": CONFIDENCE_APPROXIMATE,
                "experimental": True,
            }
        )
    findings.sort(key=lambda f: (f["path"], f["span"]["line"], f["span"]["column"]))
    return {
        "enabled": True,
        "experimental": True,
        "status": STATUS_AVAILABLE,
        "reason": None,
        "findings": findings,
        "note": note,
    }


__all__ = ["abstraction_displacement", "complexity_regressions"]
