"""Co-change pairs: analyzed files that keep appearing in the same commits.

File granularity. ``support`` is the number of commits touching both files;
``confidence`` is directional (support over each file's own commit count).
A commit touching more than ``COCHANGE_MAX_FILES_PER_COMMIT`` analyzed files is
excluded from pairing and counted in the report: a sweep says nothing about
which files belong together.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from shockharness.constants import COCHANGE_MAX_FILES_PER_COMMIT
from shockharness.history.git import Commit


@dataclass(frozen=True)
class CoChangePair:
    first: str
    second: str
    support: int
    confidence_first_to_second: float
    confidence_second_to_first: float

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "paths": [self.first, self.second],
            "support": self.support,
            "confidence": {
                "first_to_second": self.confidence_first_to_second,
                "second_to_first": self.confidence_second_to_first,
            },
        }


def cochange_pairs(
    commits: Sequence[Commit], analyzed: frozenset[str], min_support: int
) -> tuple[list[CoChangePair], int]:
    """Pairs with support >= ``min_support``, sorted by support (desc) then paths."""
    per_file: dict[str, int] = {}
    pair_counts: dict[tuple[str, str], int] = {}
    excluded = 0
    for commit in commits:
        touched = sorted(p for p in commit.paths if p in analyzed)
        for path in touched:
            if path not in per_file:
                per_file[path] = 0
            per_file[path] += 1
        if len(touched) > COCHANGE_MAX_FILES_PER_COMMIT:
            excluded += 1
            continue
        for index, first in enumerate(touched):
            for second in touched[index + 1 :]:
                key = (first, second)
                if key not in pair_counts:
                    pair_counts[key] = 0
                pair_counts[key] += 1
    pairs: list[CoChangePair] = []
    for (first, second), support in pair_counts.items():
        if support < min_support:
            continue
        pairs.append(
            CoChangePair(
                first=first,
                second=second,
                support=support,
                confidence_first_to_second=support / per_file[first],
                confidence_second_to_first=support / per_file[second],
            )
        )
    pairs.sort(key=lambda p: (-p.support, p.first, p.second))
    return pairs, excluded
