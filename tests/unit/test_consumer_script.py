"""The pure helpers of scripts/consumer_upgrade_check.py; the full run is a CI job."""

import importlib.util
import shutil
from pathlib import Path
from types import ModuleType

import pytest

from shockharness.analysis import CACHE_CONFIGURED, AnalysisOptions
from shockharness.api import analyze_paths
from shockharness.config import load_config
from tests.conftest import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts" / "consumer_upgrade_check.py"
EXAMPLES = REPO_ROOT / "examples"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("consumer_upgrade_check", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_find_wheel_requires_exactly_one(tmp_path: Path) -> None:
    script = load_script()
    with pytest.raises(SystemExit, match="exactly one"):
        script.find_wheel(tmp_path)
    wheel = tmp_path / "shockharness-9.9.9-py3-none-any.whl"
    wheel.write_bytes(b"")
    assert script.find_wheel(tmp_path) == wheel
    assert script.wheel_version(wheel) == "9.9.9"
    (tmp_path / "shockharness-9.9.10-py3-none-any.whl").write_bytes(b"")
    with pytest.raises(SystemExit, match="exactly one"):
        script.find_wheel(tmp_path)


@pytest.mark.parametrize("example", ["python", "js"])
def test_examples_pass_clean_and_fail_after_the_injected_violation(
    example: str, tmp_path: Path
) -> None:
    """In-process twin of the script's check steps (no venv, the checkout's own code)."""
    script = load_script()
    repo = tmp_path / example
    script.copy_example(EXAMPLES / example, repo)
    assert not (repo / ".git").exists()
    config = load_config(repo, None)
    assert config.source.tier == "dedicated"
    assert config.values["profile"] == "strict"
    report = analyze_paths(
        [repo], repo, config, AnalysisOptions(inline_suppressions=True, cache=CACHE_CONFIGURED)
    )
    assert report.gate.status == "pass", report.gate.reasons
    assert report.analysis_status == "complete"
    # The cited status constant is a named constant: no finding, no suppression (decision 36).
    assert [f.rule_id for f in report.findings] == []

    changed = script.introduce_violation(repo, example)
    report = analyze_paths(
        [repo], repo, config, AnalysisOptions(inline_suppressions=True, cache=CACHE_CONFIGURED)
    )
    assert report.gate.status == "fail"
    new = [f for f in report.findings if not f.is_suppressed]
    assert [(f.rule_id, f.path) for f in new] == [
        ("MAGIC001", changed.relative_to(repo).as_posix())
    ]


def test_example_pins_agree() -> None:
    script = load_script()
    assert script.pinned_versions(EXAMPLES / "python") == ["0.19.0", "0.19.0"]
    assert script.pinned_versions(EXAMPLES / "js") == ["0.19.0"]


def test_script_is_stdlib_only() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    imports = [
        line.split()[1].split(".")[0]
        for line in text.splitlines()
        if line.startswith("import ") or line.startswith("from ")
    ]
    assert "shockharness" not in imports
    assert shutil.which("git") is not None  # the script shells out to git
