"""Per-file churn from local git history, and the (not yet computed) hotspot score.

Everything here is file-level and advisory: ``metrics.history`` never feeds the
gate. When git is absent, the root is not inside a repository, or history is
disabled, the status says so with a reason; the section is never silently empty.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

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
HOTSPOTS_REASON = (
    "not computed: the hotspot score (log1p(churn) * normalized complexity) needs the "
    "complexity metrics of Milestone E, which are not implemented"
)


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
        "hotspots_reason": HOTSPOTS_REASON,
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


def collect_history(
    root: Path, revision: str, paths: Sequence[str], config: EffectiveConfig
) -> dict[str, Any]:
    """``metrics.history`` for ``paths`` (root-relative) at ``revision``."""
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
    return {
        "status": STATUS_AVAILABLE,
        "reason": None,
        "granularity": GRANULARITY_FILE,
        "revision": {"ref": revision, "commit": commit},
        "horizon": {"days": horizon_days, "since": since.isoformat(), "until": until},
        "commits_considered": len(commits),
        "files": _file_churn(commits, paths),
        "cochange": [p.to_json_dict() for p in pairs],
        "cochange_min_support": min_support,
        "commits_excluded_from_cochange": excluded,
        "hotspots": None,
        "hotspots_reason": HOTSPOTS_REASON,
    }
