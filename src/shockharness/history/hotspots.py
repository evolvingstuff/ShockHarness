"""Per-file churn from local git history, and the hotspot score.

Everything here is file-level and advisory: ``metrics.history`` never feeds the
gate. When git is absent, the root is not inside a repository, or history is
disabled, the status says so with a reason; the section is never silently empty.

The hotspot score of a file is ``log1p(churn) * normalized_complexity`` where
``churn`` is the file's commit count inside the horizon and
``normalized_complexity`` is the file's summed cognitive complexity
(``metrics.complexity.files[path].cognitive_total``) divided by the largest
such total among the analyzed files. It needs both history and complexity;
when either is unavailable ``hotspots`` is ``null`` and ``hotspots_reason``
says which.
"""

import math
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from shockharness.complexity.coupling import STATUS_AVAILABLE as COMPLEXITY_AVAILABLE
from shockharness.config import EffectiveConfig
from shockharness.history.cochange import cochange_pairs
from shockharness.history.git import (
    Commit,
    commit_date,
    locate_repository,
    log_since,
    resolve_commit,
)

STATUS_AVAILABLE = "available"
STATUS_UNAVAILABLE = "unavailable"
STATUS_DISABLED = "disabled"
GRANULARITY_FILE = "file"
HOTSPOTS_FORMULA = (
    "log1p(churn) * normalized_complexity; churn = commits touching the file inside the "
    "horizon, normalized_complexity = the file's cognitive_total divided by the largest "
    "cognitive_total among the analyzed files (file granularity, never gating)"
)
COGNITIVE_TOTAL = "cognitive_total"


def _empty(status: str, reason: str, horizon_days: int, min_support: int) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "granularity": GRANULARITY_FILE,
        "revision": None,
        "horizon": {"days": horizon_days, "since": None, "until": None},
        "commits_considered": 0,
        "files": {},
        "cochange": [],
        "cochange_min_support": min_support,
        "commits_excluded_from_cochange": 0,
        "hotspots": None,
        "hotspots_reason": f"not computed: history is {status} ({reason})",
        "hotspots_formula": HOTSPOTS_FORMULA,
    }


def _file_churn(commits: Sequence[Commit], paths: Sequence[str]) -> dict[str, dict[str, Any]]:
    churn: dict[str, dict[str, Any]] = {}
    for path in sorted(paths):
        churn[path] = {"commits": 0, "authors": 0, "first_change": None, "last_change": None}
    authors: dict[str, set[str]] = {path: set() for path in churn}
    # git log is newest first, so the first commit seen for a path is its last change.
    for commit in commits:
        for path in commit.paths:
            if path not in churn:
                continue
            entry = churn[path]
            entry["commits"] += 1
            authors[path].add(commit.author)
            if entry["last_change"] is None:
                entry["last_change"] = commit.author_date
            entry["first_change"] = commit.author_date
    for path in churn:
        churn[path]["authors"] = len(authors[path])
    return churn


def hotspot_scores(
    churn: Mapping[str, Mapping[str, Any]], complexity: Mapping[str, Any]
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """``(hotspots, reason)``: exactly one is set."""
    if complexity["status"] != COMPLEXITY_AVAILABLE:
        return None, f"not computed: complexity metrics are {complexity['status']}"
    files: Mapping[str, Mapping[str, Any]] = complexity["files"]
    totals = {path: int(files[path][COGNITIVE_TOTAL]) for path in churn if path in files}
    largest = max(totals.values(), default=0)
    scores: list[dict[str, Any]] = []
    for path in sorted(churn):
        if path not in totals:
            continue  # the file failed to parse: no complexity, no score
        commits = int(churn[path]["commits"])
        normalized = 0.0 if largest == 0 else totals[path] / largest
        scores.append(
            {
                "path": path,
                "churn": commits,
                COGNITIVE_TOTAL: totals[path],
                "normalized_complexity": normalized,
                "score": math.log1p(commits) * normalized,
            }
        )
    scores.sort(key=lambda s: (-s["score"], s["path"]))
    return scores, None


def collect_history(
    root: Path,
    revision: str,
    paths: Sequence[str],
    config: EffectiveConfig,
    complexity: Mapping[str, Any],
) -> dict[str, Any]:
    """``metrics.history`` for ``paths`` (root-relative) at ``revision``.

    ``complexity`` is the report's ``metrics.complexity`` section; hotspots combine it
    with the churn.
    """
    section = config.values["history"]
    horizon_days = int(section["horizon_days"])
    min_support = int(section["min_support"])
    if section["enabled"] is False:
        return _empty(STATUS_DISABLED, "history.enabled = false", horizon_days, min_support)
    location, error = locate_repository(root)
    if location is None:
        assert error is not None
        return _empty(STATUS_UNAVAILABLE, error, horizon_days, min_support)
    commit, error = resolve_commit(root, revision)
    if commit is None:
        assert error is not None
        return _empty(STATUS_UNAVAILABLE, error, horizon_days, min_support)
    until, error = commit_date(root, commit)
    if until is None:
        assert error is not None
        return _empty(STATUS_UNAVAILABLE, error, horizon_days, min_support)
    since = datetime.fromisoformat(until) - timedelta(days=horizon_days)
    commits, error = log_since(root, commit, since, location.prefix)
    if commits is None:
        assert error is not None
        return _empty(STATUS_UNAVAILABLE, error, horizon_days, min_support)
    analyzed = frozenset(paths)
    pairs, excluded = cochange_pairs(commits, analyzed, min_support)
    churn = _file_churn(commits, paths)
    hotspots, reason = hotspot_scores(churn, complexity)
    return {
        "status": STATUS_AVAILABLE,
        "reason": None,
        "granularity": GRANULARITY_FILE,
        "revision": {"ref": revision, "commit": commit},
        "horizon": {"days": horizon_days, "since": since.isoformat(), "until": until},
        "commits_considered": len(commits),
        "files": churn,
        "cochange": [p.to_json_dict() for p in pairs],
        "cochange_min_support": min_support,
        "commits_excluded_from_cochange": excluded,
        "hotspots": hotspots,
        "hotspots_reason": reason,
        "hotspots_formula": HOTSPOTS_FORMULA,
    }
