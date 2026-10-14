"""Git history metrics: churn and co-change from a temporary repository, and explicit
degradation when git or a repository is missing."""

from collections.abc import Callable
from pathlib import Path

import pytest

from shockharness.analysis import AnalysisOptions
from shockharness.api import analyze_paths, with_history
from shockharness.config import EffectiveConfig
from shockharness.history import git as git_module
from shockharness.history.cochange import cochange_pairs
from shockharness.history.git import Commit, parse_log
from shockharness.history.hotspots import collect_history
from tests.conftest import commit_all, init_repo

OPTIONS = AnalysisOptions(inline_suppressions=True)
DAY_1 = "2026-01-01T12:00:00+00:00"
DAY_2 = "2026-01-02T12:00:00+00:00"
DAY_3 = "2026-01-03T12:00:00+00:00"
OLD = "2025-01-01T12:00:00+00:00"


def write(root: Path, relative: str, body: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_analyze_paths_alone_never_collects_history(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    write(empty_root, "src/a.py", "x = 1\n")
    report = analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    assert report.metrics["history"]["status"] == "not_collected"
    assert report.metrics["history"]["hotspots"] is None


def test_history_is_unavailable_outside_a_repository(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    write(empty_root, "src/a.py", "x = 1\n")
    report = analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    report = with_history(report, empty_root, "HEAD", strict_config)
    history = report.metrics["history"]
    assert history["status"] == "unavailable"
    assert "not a git repository" in history["reason"]
    assert history["files"] == {}
    assert history["hotspots"] is None
    assert "Milestone E" in history["hotspots_reason"]
    assert report.gate.status == "pass"


def test_history_is_unavailable_without_git(
    empty_root: Path, strict_config: EffectiveConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(git_module, "GIT", "shockharness-no-such-git-binary")
    history = collect_history(empty_root, "HEAD", ["src/a.py"], strict_config)
    assert history["status"] == "unavailable"
    assert "git could not be run" in history["reason"]


def test_history_disabled_says_so(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    config = make_config("[tool.shockharness.history]\nenabled = false\n")
    history = collect_history(empty_root, "HEAD", ["src/a.py"], config)
    assert history["status"] == "disabled"
    assert history["reason"] == "history.enabled = false"


def test_churn_and_cochange_from_a_temporary_repository(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    config = make_config("[tool.shockharness.history]\nmin_support = 2\nhorizon_days = 30\n")
    init_repo(empty_root)
    write(empty_root, "src/a.py", "x = 1\n")
    write(empty_root, "src/b.py", "y = 1\n")
    write(empty_root, "src/c.py", "z = 1\n")
    commit_all(empty_root, "old", OLD, "old@example.invalid")  # outside the horizon
    write(empty_root, "src/a.py", "x = 1\n\n")
    write(empty_root, "src/b.py", "y = 1\n\n")
    commit_all(empty_root, "one", DAY_1, "one@example.invalid")
    write(empty_root, "src/a.py", "x = 1\n\n\n")
    write(empty_root, "src/b.py", "y = 1\n\n\n")
    write(empty_root, "src/c.py", "z = 1\n\n")
    commit_all(empty_root, "two", DAY_2, "two@example.invalid")
    write(empty_root, "src/a.py", "x = 1\n\n\n\n")
    head = commit_all(empty_root, "three", DAY_3, "one@example.invalid")

    report = analyze_paths([empty_root / "src"], empty_root, config, OPTIONS)
    report = with_history(report, empty_root, "HEAD", config)
    history = report.metrics["history"]
    assert history["status"] == "available"
    assert history["granularity"] == "file"
    assert history["revision"] == {"ref": "HEAD", "commit": head}
    assert history["horizon"]["days"] == 30
    assert history["horizon"]["until"] == DAY_3
    assert history["commits_considered"] == 3
    assert history["files"] == {
        "src/a.py": {
            "commits": 3,
            "authors": 2,
            "first_change": DAY_1,
            "last_change": DAY_3,
        },
        "src/b.py": {
            "commits": 2,
            "authors": 2,
            "first_change": DAY_1,
            "last_change": DAY_2,
        },
        "src/c.py": {
            "commits": 1,
            "authors": 1,
            "first_change": DAY_2,
            "last_change": DAY_2,
        },
    }
    assert history["cochange"] == [
        {
            "paths": ["src/a.py", "src/b.py"],
            "support": 2,
            "confidence": {"first_to_second": 2 / 3, "second_to_first": 1.0},
        }
    ]
    assert history["cochange_min_support"] == 2
    assert history["hotspots"] is None
    assert report.gate.status == "pass"
    again = with_history(report, empty_root, "HEAD", config).metrics["history"]
    assert again == history  # deterministic: the horizon is anchored on the head commit


def test_history_at_an_older_revision_and_in_a_subdirectory_root(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    init_repo(empty_root)
    write(empty_root, "pkg/src/a.py", "x = 1\n")
    write(empty_root, "other/b.py", "y = 1\n")
    first = commit_all(empty_root, "one", DAY_1, "one@example.invalid")
    write(empty_root, "pkg/src/a.py", "x = 1\n\n")
    commit_all(empty_root, "two", DAY_2, "one@example.invalid")
    history = collect_history(empty_root / "pkg", first, ["src/a.py"], strict_config)
    assert history["status"] == "available"
    assert history["revision"]["commit"] == first
    assert history["files"]["src/a.py"]["commits"] == 1
    assert history["files"]["src/a.py"]["last_change"] == DAY_1


def test_unknown_revision_is_unavailable(empty_root: Path, strict_config: EffectiveConfig) -> None:
    init_repo(empty_root)
    history = collect_history(empty_root, "nope", ["src/a.py"], strict_config)
    assert history["status"] == "unavailable"
    assert "rev-parse failed" in history["reason"]


def test_parse_log_strips_the_prefix_and_sorts_paths() -> None:
    text = (
        "\x1eaaa\x1f2026-01-02T00:00:00+00:00\x1f2026-01-01T00:00:00+00:00\x1fa@x\n\n"
        "pkg/src/b.py\npkg/src/a.py\nother/c.py\n\n"
        "\x1ebbb\x1f2026-01-03T00:00:00+00:00\x1f2026-01-03T00:00:00+00:00\x1fb@x\n"
    )
    commits = parse_log(text, "pkg/")
    assert commits == [
        Commit(
            "aaa",
            "2026-01-02T00:00:00+00:00",
            "2026-01-01T00:00:00+00:00",
            "a@x",
            ("src/a.py", "src/b.py"),
        ),
        Commit("bbb", "2026-01-03T00:00:00+00:00", "2026-01-03T00:00:00+00:00", "b@x", ()),
    ]


def test_cochange_excludes_sweeping_commits() -> None:
    sweep = Commit("s", DAY_1, DAY_1, "a", tuple(f"f{i}.py" for i in range(60)))
    pair = Commit("p", DAY_2, DAY_2, "a", ("f0.py", "f1.py"))
    analyzed = frozenset(sweep.paths)
    pairs, excluded = cochange_pairs([sweep, pair, pair], analyzed, 2)
    assert excluded == 1
    assert [(p.first, p.second, p.support) for p in pairs] == [("f0.py", "f1.py", 2)]
    # the sweep still counts towards per-file commit totals (3 commits touched f0.py)
    assert pairs[0].confidence_first_to_second == 2 / 3
