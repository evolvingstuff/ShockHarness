"""Git history metrics: churn and co-change from a temporary repository, and explicit
degradation when git or a repository is missing."""

import math
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
# A metrics.complexity section of a run that had complexity switched off.
NO_COMPLEXITY = {"status": "disabled", "reason": "complexity.enabled = false", "files": {}}
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
    assert history["hotspots_reason"].startswith("not computed: history is unavailable")
    assert "log1p(churn)" in history["hotspots_formula"]
    assert report.gate.status == "pass"


def test_history_is_unavailable_without_git(
    empty_root: Path, strict_config: EffectiveConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(git_module, "GIT", "shockharness-no-such-git-binary")
    history = collect_history(empty_root, "HEAD", ["src/a.py"], strict_config, NO_COMPLEXITY)
    assert history["status"] == "unavailable"
    assert "git could not be run" in history["reason"]


def test_history_disabled_says_so(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    config = make_config("[tool.shockharness.history]\nenabled = false\n")
    history = collect_history(empty_root, "HEAD", ["src/a.py"], config, NO_COMPLEXITY)
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
    # every file is a flat assignment: cognitive 0 everywhere, so every score is 0
    assert [
        (h["path"], h["churn"], h["cognitive_total"], h["score"]) for h in history["hotspots"]
    ] == [
        ("src/a.py", 3, 0, 0.0),
        ("src/b.py", 2, 0, 0.0),
        ("src/c.py", 1, 0, 0.0),
    ]
    assert history["hotspots_reason"] is None
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
    history = collect_history(empty_root / "pkg", first, ["src/a.py"], strict_config, NO_COMPLEXITY)
    assert history["status"] == "available"
    assert history["hotspots"] is None
    assert history["hotspots_reason"] == "not computed: complexity metrics are disabled"
    assert history["revision"]["commit"] == first
    assert history["files"]["src/a.py"]["commits"] == 1
    assert history["files"]["src/a.py"]["last_change"] == DAY_1


def test_unknown_revision_is_unavailable(empty_root: Path, strict_config: EffectiveConfig) -> None:
    init_repo(empty_root)
    history = collect_history(empty_root, "nope", ["src/a.py"], strict_config, NO_COMPLEXITY)
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


def test_hotspots_combine_churn_with_normalized_cognitive_complexity(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    config = make_config("[tool.shockharness.history]\nhorizon_days = 30\n")
    init_repo(empty_root)
    branchy = "def f(a, b):\n    if a:\n        if b:\n            return 1\n    return 0\n"
    flat = "x = 1\n"
    write(empty_root, "src/hot.py", branchy)
    write(empty_root, "src/cold.py", branchy)
    write(empty_root, "src/flat.py", flat)
    commit_all(empty_root, "one", DAY_1, "one@example.invalid")
    write(empty_root, "src/hot.py", branchy + "\n")
    write(empty_root, "src/flat.py", flat + "\n")
    commit_all(empty_root, "two", DAY_2, "one@example.invalid")
    write(empty_root, "src/hot.py", branchy + "\n\n")
    commit_all(empty_root, "three", DAY_3, "two@example.invalid")

    report = analyze_paths([empty_root / "src"], empty_root, config, OPTIONS)
    report = with_history(report, empty_root, "HEAD", config)
    history = report.metrics["history"]
    assert history["status"] == "available"
    assert history["hotspots_reason"] is None
    assert "log1p(churn)" in history["hotspots_formula"]
    rows = [
        (h["path"], h["churn"], h["cognitive_total"], h["normalized_complexity"], h["score"])
        for h in history["hotspots"]
    ]
    assert rows == [
        ("src/hot.py", 3, 3, 1.0, math.log1p(3)),
        ("src/cold.py", 1, 3, 1.0, math.log1p(1)),
        ("src/flat.py", 2, 0, 0.0, 0.0),
    ]
    assert report.gate.status == "pass"
    # the score follows the complexity section it was given: disabled complexity, no score
    no_score = collect_history(empty_root, "HEAD", ["src/hot.py"], config, NO_COMPLEXITY)
    assert no_score["hotspots"] is None
    assert no_score["hotspots_reason"] == "not computed: complexity metrics are disabled"
    # a file that failed to parse has churn but no complexity: it gets no score, no crash
    write(empty_root, "src/broken.py", "def (\n")
    commit_all(empty_root, "four", DAY_3, "two@example.invalid")
    broken = make_config('parse_errors = "warn"\n')
    report = analyze_paths([empty_root / "src"], empty_root, broken, OPTIONS)
    report = with_history(report, empty_root, "HEAD", broken)
    assert "src/broken.py" in report.metrics["history"]["files"]
    assert "src/broken.py" not in {h["path"] for h in report.metrics["history"]["hotspots"]}
