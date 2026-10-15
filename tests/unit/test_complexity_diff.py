"""Complexity in revision diffs: per-unit regressions, the gates.complexity_regressions
policy, a plain check that never fails on complexity, and the experimental
abstraction-displacement heuristic."""

import json
from pathlib import Path

import pytest

from shockharness.cli import main
from tests.conftest import commit_all, init_repo

SIMPLE = "def f(a):\n    if a:\n        return 1\n    return 0\n"
GROWN = (
    "def f(a, b, c):\n    if a:\n        if b:\n            if c:\n                return c\n"
    "            return b\n        return 1\n    return 0\n"
)


def _write(root: Path, relative: str, body: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _config(root: Path, body: str) -> None:
    (root / ".shockharness.toml").write_text("[tool.shockharness]\n" + body, encoding="utf-8")


def _two_revisions(root: Path, config: str, base: str, head: str) -> tuple[str, str]:
    init_repo(root)
    _config(root, config)
    _write(root, "src/a.py", base)
    c1 = commit_all(root, "base", "2026-01-01T12:00:00+00:00", "a@example.invalid")
    _write(root, "src/a.py", head)
    c2 = commit_all(root, "head", "2026-01-02T12:00:00+00:00", "a@example.invalid")
    return c1, c2


def _run(args: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = main(args)
    out = capsys.readouterr().out
    return code, out


WARN_CONFIG = "[tool.shockharness.complexity]\ncognitive_warn = 2\n"
FAIL_CONFIG = WARN_CONFIG + '[tool.shockharness.gates]\ncomplexity_regressions = "fail"\n'
IGNORE_CONFIG = WARN_CONFIG + '[tool.shockharness.gates]\ncomplexity_regressions = "ignore"\n'


def test_regression_is_listed_and_warned_by_default(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    c1, c2 = _two_revisions(empty_root, WARN_CONFIG, SIMPLE, GROWN)
    code, out = _run(
        ["gate", "--base", c1, "--head", c2, "--format", "json", "--root", str(empty_root)], capsys
    )
    assert code == 0
    data = json.loads(out)
    regressions = data["metrics"]["complexity"]["regressions"]
    assert [
        (r["rule_id"], r["name"], r["metric"], r["base"], r["head"], r["threshold"])
        for r in regressions
    ] == [
        ("CPLX002", "f", "cognitive", 1, 6, 2),
    ]
    assert regressions[0]["convention"] == "cognitive/1"
    assert regressions[0]["new_unit"] is False
    assert regressions[0]["key"] == "src/a.py::f"
    assert data["metrics"]["complexity"]["regression_policy"] == "warn"
    assert data["summary"]["complexity_regressions"] == 1
    assert data["gate"]["status"] == "pass"
    assert data["gate"]["complexity_regressions"] == 1
    assert any("1 complexity regression(s)" in r and "warn" in r for r in data["gate"]["reasons"])
    assert [f["rule_id"] for f in data["findings"]] == ["CPLX002"]
    assert data["findings"][0]["status"] == "new"
    code, out = _run(["gate", "--base", c1, "--head", c2, "--root", str(empty_root)], capsys)
    assert "complexity regressions against base: 1" in out
    assert "gate: PASS (exit 0)" in out


def test_regression_fails_the_gate_only_under_the_fail_policy(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    c1, c2 = _two_revisions(empty_root, FAIL_CONFIG, SIMPLE, GROWN)
    root = ["--root", str(empty_root)]
    code, out = _run(["gate", "--base", c1, "--head", c2, "--format", "json", *root], capsys)
    assert code == 1
    data = json.loads(out)
    assert data["gate"]["status"] == "fail"
    assert data["gate"]["new_hard_violations"] == 0
    assert any('complexity_regressions = "fail"' in r for r in data["gate"]["reasons"])
    # the reverse direction shrinks: nothing regresses
    code, out = _run(["gate", "--base", c2, "--head", c1, "--format", "json", *root], capsys)
    assert code == 0
    assert json.loads(out)["metrics"]["complexity"]["regressions"] == []
    # `diff` reports but never exits 1
    code, out = _run(["diff", "--base", c1, "--head", c2, *root], capsys)
    assert code == 0
    assert "gate: FAIL (exit 1)" in out
    # --exit-zero masks the exit code, not the verdict
    code, out = _run(["gate", "--base", c1, "--head", c2, "--exit-zero", *root], capsys)
    assert code == 0
    assert "advisory run" in out


def test_plain_check_never_fails_on_complexity_whatever_the_policy(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _two_revisions(empty_root, FAIL_CONFIG, SIMPLE, GROWN)
    code, out = _run(
        ["check", str(empty_root / "src"), "--format", "json", "--root", str(empty_root)], capsys
    )
    assert code == 0
    data = json.loads(out)
    assert [f["rule_id"] for f in data["findings"]] == ["CPLX002"]
    assert data["gate"]["status"] == "pass"
    assert data["gate"]["complexity_regressions"] == 0
    assert "regressions" not in data["metrics"]["complexity"]


def test_regressions_can_be_ignored_and_new_units_count(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    c1, c2 = _two_revisions(
        empty_root, IGNORE_CONFIG, SIMPLE, SIMPLE + "\n\n" + GROWN.replace("def f", "def g")
    )
    code, out = _run(
        ["gate", "--base", c1, "--head", c2, "--format", "json", "--root", str(empty_root)], capsys
    )
    assert code == 0
    data = json.loads(out)
    (regression,) = data["metrics"]["complexity"]["regressions"]
    assert (
        regression["name"] == "g" and regression["new_unit"] is True and regression["base"] is None
    )
    assert not any("complexity regression" in r for r in data["gate"]["reasons"])


def test_abstraction_displacement_is_experimental_and_off_by_default(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = (
        "def f(items):\n    total = 0\n    for item in items:\n        if item.ok:\n"
        "            total += 1\n    return total\n"
    )
    head = (
        "def score(item):\n    if item.ok:\n        if item.value:\n            return 2\n"
        "        return 1\n    return 0\n\n\n"
        "def f(items):\n    total = 0\n    for item in items:\n        total += score(item)\n"
        "    return total\n"
    )
    c1, c2 = _two_revisions(empty_root, "", base, head)
    root = ["--root", str(empty_root)]
    code, out = _run(["diff", "--base", c1, "--head", c2, "--format", "json", *root], capsys)
    assert code == 0
    section = json.loads(out)["metrics"]["graph"]["abstraction_displacement"]
    assert section == {
        **section,
        "enabled": False,
        "experimental": True,
        "status": "disabled",
        "findings": [],
    }
    _config(empty_root, "[tool.shockharness.complexity]\nabstraction_displacement = true\n")
    code, out = _run(["diff", "--base", c1, "--head", c2, "--format", "json", *root], capsys)
    section = json.loads(out)["metrics"]["graph"]["abstraction_displacement"]
    assert section["status"] == "available" and section["enabled"] is True
    (finding,) = section["findings"]
    assert finding == {
        **finding,
        "name": "f",
        "path": "src/a.py",
        "local": {"base": 3, "head": 1},
        "reachable_burden": {"base": 3, "head": 4},
        "confidence": "approximate",
        "experimental": True,
    }
    assert "delegation is not inherently bad" in section["note"]
    assert not any(f["rule_id"] not in ("MAGIC001",) for f in json.loads(out)["findings"])
    code, out = _run(["diff", "--base", c1, "--head", c2, *root], capsys)
    assert "abstraction displacement (experimental, approximate): 1 unit(s)" in out
