"""Per-unit and per-file complexity numbers in their report shape."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from shockharness.complexity import cognitive as cognitive_module
from shockharness.complexity import cyclomatic as cyclomatic_module
from shockharness.complexity import nesting as nesting_module
from shockharness.complexity import npath as npath_module
from shockharness.complexity import size as size_module
from shockharness.ir.model import FunctionFact

SETTING_BOOLEAN_OPERATORS = "cyclomatic_counts_boolean_operators"
SETTING_NPATH_CAP = "npath_cap"

CONVENTIONS: Mapping[str, str] = {
    "cyclomatic": cyclomatic_module.CONVENTION,
    "cognitive": cognitive_module.CONVENTION,
    "nesting": nesting_module.CONVENTION,
    "npath": npath_module.CONVENTION,
    "size": size_module.CONVENTION,
}
NESTED_UNITS_NOTE = (
    "every function, method, lambda, arrow, class body and module body is measured as a "
    "separate unit; a unit's numbers exclude the bodies of units nested inside it"
)
NOT_A_SONAR_SCORE = (
    "cognitive/1 follows the published description of cognitive complexity but is not a "
    "SonarSource score"
)


@dataclass(frozen=True)
class UnitMetrics:
    key: str  # "<path>::<name>" with "#n" for the n-th unit of the same name (n >= 2)
    path: str
    name: str
    kind: str
    is_async: bool
    is_generator: bool
    fact: FunctionFact
    cyclomatic: int
    cognitive: int
    nesting: int
    npath: int
    npath_saturated: bool
    npath_cap: int

    def npath_text(self) -> str:
        if self.npath_saturated:
            return f">= {self.npath_cap}"
        return str(self.npath)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "path": self.path,
            "name": self.name,
            "kind": self.kind,
            "async": self.is_async,
            "generator": self.is_generator,
            "span": self.fact.span.to_json_dict(),
            "size": size_module.size(self.fact),
            "cyclomatic": self.cyclomatic,
            "cognitive": self.cognitive,
            "nesting": self.nesting,
            "npath": {
                "value": self.npath,
                "saturated": self.npath_saturated,
                "cap": self.npath_cap,
                "text": self.npath_text(),
            },
        }


def unit_keys(path: str, facts: Sequence[FunctionFact]) -> list[str]:
    """Stable keys: path and qualified name, with an occurrence suffix for duplicates."""
    seen: dict[str, int] = {}
    keys: list[str] = []
    for fact in facts:
        if fact.name not in seen:
            seen[fact.name] = 0
        seen[fact.name] += 1
        if seen[fact.name] == 1:
            keys.append(f"{path}::{fact.name}")
        else:
            keys.append(f"{path}::{fact.name}#{seen[fact.name]}")
    return keys


def measure_units(
    path: str, facts: Sequence[FunctionFact], settings: Mapping[str, Any]
) -> tuple[UnitMetrics, ...]:
    count_boolean = bool(settings[SETTING_BOOLEAN_OPERATORS])
    cap = int(settings[SETTING_NPATH_CAP])
    # Source order, an enclosing unit before the units nested in it.
    ordered = sorted(
        facts,
        key=lambda f: (f.span.line, f.span.column, -f.span.end_line, -f.span.end_column, f.name),
    )
    keys = unit_keys(path, ordered)
    measured: list[UnitMetrics] = []
    for key, fact in zip(keys, ordered, strict=True):
        npath_value, saturated = npath_module.npath(fact.control, cap)
        measured.append(
            UnitMetrics(
                key=key,
                path=path,
                name=fact.name,
                kind=fact.kind,
                is_async=fact.is_async,
                is_generator=fact.is_generator,
                fact=fact,
                cyclomatic=cyclomatic_module.cyclomatic(fact.control, count_boolean),
                cognitive=cognitive_module.cognitive(fact.control),
                nesting=nesting_module.nesting_depth(fact.control),
                npath=npath_value,
                npath_saturated=saturated,
                npath_cap=cap,
            )
        )
    return tuple(measured)


def file_aggregate(units: Sequence[UnitMetrics]) -> dict[str, Any]:
    return {
        "units": len(units),
        "cyclomatic_total": sum(u.cyclomatic for u in units),
        "cyclomatic_max": max((u.cyclomatic for u in units), default=0),
        "cognitive_total": sum(u.cognitive for u in units),
        "cognitive_max": max((u.cognitive for u in units), default=0),
        "nesting_max": max((u.nesting for u in units), default=0),
        "npath_max": max((u.npath for u in units), default=0),
        "npath_saturated_units": sum(1 for u in units if u.npath_saturated),
        "logical_lines": sum(u.fact.logical_lines for u in units),
        "statements": sum(u.fact.statements for u in units),
    }


def conventions_json(settings: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **dict(CONVENTIONS),
        "cyclomatic_counts_boolean_operators": bool(settings[SETTING_BOOLEAN_OPERATORS]),
        "optional_chaining_counted": False,
        "nested_units": NESTED_UNITS_NOTE,
        "cognitive_note": NOT_A_SONAR_SCORE,
    }
