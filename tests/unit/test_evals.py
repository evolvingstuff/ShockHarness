"""The skill evaluation corpus: layout, the pure helpers, and the runner on the references."""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from tests.conftest import REPO_ROOT

EVALS = REPO_ROOT / "evals"
RUNNER = EVALS / "run_evals.py"
TASKS = sorted(path for path in (EVALS / "tasks").iterdir() if path.is_dir())


def load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_evals", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_corpus_layout() -> None:
    names = [task.name for task in TASKS]
    assert len(names) >= 8
    assert sum(1 for name in names if name.startswith("py-")) >= 4
    assert sum(1 for name in names if name.startswith("js-")) >= 4
    runner = load_runner()
    for task in TASKS:
        assert (task / "task.md").is_file(), task.name
        assert (task / "start" / ".shockharness.toml").is_file(), task.name
        assert (task / "reference" / ".shockharness.toml").is_file(), task.name
        assert any((task / "tests").iterdir()), task.name
        expected = runner.load_expected(task)
        assert expected.max_findings == 0
        assert expected.tests_must_pass
        if task.name.startswith("py-"):
            assert expected.language == "python"
            assert list((task / "tests").glob("test_*.py")), task.name
        else:
            assert expected.language == "javascript"
            assert list((task / "tests").glob("*.test.js")), task.name
            assert (task / "start" / "package.json").is_file(), task.name


def test_count_suppressions_and_tail(tmp_path: Path) -> None:
    runner = load_runner()
    (tmp_path / "a.py").write_text(
        'X = 404  # shockharness: ignore[MAGIC001] reason="RFC"\nY = 1\n', encoding="utf-8"
    )
    (tmp_path / "b.js").write_text(
        'const A = 1; // shockharness:ignore[MAGIC001] reason="r"\n', encoding="utf-8"
    )
    (tmp_path / "notes.md").write_text("shockharness: ignore[MAGIC001]", encoding="utf-8")
    assert runner.count_suppressions(tmp_path) == 2
    assert runner.tail("a\n\nb\n  \n") == "b"
    assert runner.tail("") == "(no output)"


def test_reference_suppression_budgets_match_expected() -> None:
    runner = load_runner()
    for task in TASKS:
        expected = runner.load_expected(task)
        added = runner.count_suppressions(task / "reference") - runner.count_suppressions(
            task / "start"
        )
        assert 0 <= added <= expected.max_suppressions_added, task.name


@pytest.mark.slow
def test_runner_scores_every_reference_clean_and_every_start_dirty(tmp_path: Path) -> None:
    if shutil.which("node") is None:
        pytest.skip("node is required for the JavaScript tasks")
    scorecard = tmp_path / "reference.json"
    completed = subprocess.run(
        [sys.executable, str(RUNNER), "--reference", "--output", str(scorecard)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    document = json.loads(scorecard.read_text(encoding="utf-8"))
    assert document["schema"] == "shockharness-evals/1"
    assert document["summary"]["tasks"] == len(TASKS)
    assert document["summary"]["failed"] == 0
    assert document["summary"]["unsuppressed_findings"] == 0
    assert document["summary"]["test_failures"] == 0
    for scored in document["tasks"]:
        assert scored["passed"], scored
        assert scored["analyzer"]["exit_code"] == 0
        assert scored["analyzer"]["unsuppressed_findings"] == 0
        assert scored["tests"]["exit_code"] == 0

    # The starting file sets are candidates that must fail: violations and failing tests.
    candidates = tmp_path / "starts"
    for task in TASKS:
        shutil.copytree(task / "start", candidates / task.name)
    scorecard = tmp_path / "starts.json"
    completed = subprocess.run(
        [sys.executable, str(RUNNER), "--candidates", str(candidates), "--output", str(scorecard)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 1, completed.stdout + completed.stderr
    document = json.loads(scorecard.read_text(encoding="utf-8"))
    assert document["summary"]["passed"] == 0
    for scored in document["tasks"]:
        assert scored["analyzer"]["exit_code"] == 1, scored["task"]
        assert scored["analyzer"]["unsuppressed_findings"] > 0, scored["task"]
        assert scored["tests"]["exit_code"] != 0, scored["task"]


def test_single_task_mode_and_argument_validation(tmp_path: Path) -> None:
    task = next(t for t in TASKS if t.name.startswith("py-"))
    completed = subprocess.run(
        [sys.executable, str(RUNNER), "--task", str(task), "--candidate", str(task / "reference")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert f"{task.name}: PASS" in completed.stdout
    completed = subprocess.run(
        [sys.executable, str(RUNNER), "--task", str(task)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 2
    assert "--task and --candidate" in completed.stderr
