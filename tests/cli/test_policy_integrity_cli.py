"""H2 part 2 end to end: VERIFY003 and the ``--policy`` tier on real git history.

The adversarial fixtures (a) to (j) of spec section 21 each weaken the verification of a
small repository in one head commit. With ``rules.verification.severity = "error"``
committed at base, ``gate`` must exit 1 for every one of them. Samples are written from
strings, so this repository's own files never contain a real skip marker or tautology.
"""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from shockharness.cli import main
from tests.conftest import REPO_ROOT, commit_all, init_repo
from tests.unit.test_gate_and_report import _check

BASE_DATE = "2026-01-01T12:00:00+00:00"
HEAD_DATE = "2026-01-02T12:00:00+00:00"

CONFIG = '[tool.shockharness.rules.verification]\nseverity = "error"\n'
APP = "def clamp(value, limit):\n    return min(value, limit)\n"
TEST_PY = "from app import clamp\n\n\ndef test_clamp():\n    assert clamp(high(), low()) == low()\n"
TEST_JS = (
    'describe("clamp", () => {\n  it("caps", () => { expect(clamp(limit)).toBe(limit); });\n});\n'
)
WORKFLOW = """\
name: ci
on: [push]
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - run: python -m pip install "shockharness==0.3.0"
      - run: shockharness gate --base origin/main --head HEAD
  unit:
    runs-on: ubuntu-latest
    steps:
      - run: python -m pytest
"""
PYPROJECT = '[tool.ruff.lint]\nselect = ["E", "F"]\n'


def schema(name: str) -> dict:
    return json.loads((REPO_ROOT / "schemas" / name).read_text(encoding="utf-8"))


BASELINE_ENTRY = {"fingerprint": "a" * 64, "rule_id": "MAGIC001", "path": "src/app.py"}


def write(root: Path, relative: str, body: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def read(root: Path, relative: str) -> str:
    return (root / relative).read_text(encoding="utf-8")


def baseline(entries: list[dict[str, str]]) -> str:
    return json.dumps({"fingerprint_version": "1", "fingerprints": entries}, indent=2) + "\n"


def run(args: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = main(args)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def base_repo(root: Path) -> str:
    init_repo(root)
    write(root, ".shockharness.toml", CONFIG)
    write(root, "src/app.py", APP)
    write(root, "tests/test_app.py", TEST_PY)
    write(root, "tests/app.test.js", TEST_JS)
    write(root, ".github/workflows/ci.yml", WORKFLOW)
    write(root, "pyproject.toml", PYPROJECT)
    write(root, "shockharness-baseline.json", baseline([BASELINE_ENTRY]))
    return commit_all(root, "base", BASE_DATE, "one@example.invalid")


def append(relative: str, text: str) -> Callable[[Path], None]:
    return lambda root: write(root, relative, read(root, relative) + text)


def replace(relative: str, old: str, new: str) -> Callable[[Path], None]:
    def change(root: Path) -> None:
        body = read(root, relative)
        assert old in body
        write(root, relative, body.replace(old, new))

    return change


def grow_baseline(root: Path) -> None:
    extra = {"fingerprint": "b" * 64, "rule_id": "DEF001", "path": "src/app.py"}
    write(root, "shockharness-baseline.json", baseline([BASELINE_ENTRY, extra]))


ADVERSARIAL = [
    pytest.param(
        append(".shockharness.toml", "[tool.shockharness.rules.magic_numbers]\nenabled = false\n"),
        "VERIFY003",
        ".shockharness.toml",
        "rules.magic_numbers",
        id="a-disable-magic-numbers",
    ),
    pytest.param(
        replace(
            ".shockharness.toml",
            "[tool.shockharness.rules",
            '[tool.shockharness]\nexclude = ["src/**"]\n\n[tool.shockharness.rules',
        ),
        "VERIFY003",
        ".shockharness.toml",
        "src/app.py",
        id="b-exclude-drops-src",
    ),
    pytest.param(
        replace("tests/app.test.js", 'it("caps"', 'it.only("caps"'),
        "VERIFY001",
        "tests/app.test.js",
        "only",
        id="c-test-only",
    ),
    pytest.param(
        replace("tests/test_app.py", "assert clamp(high(), low()) == low()", "assert True"),
        "VERIFY004",
        "tests/test_app.py",
        "",
        id="d-tautology",
    ),
    pytest.param(
        grow_baseline,
        "VERIFY003",
        "shockharness-baseline.json",
        "DEF001",
        id="e-baseline-entry",
    ),
    pytest.param(
        replace(
            ".github/workflows/ci.yml",
            "  gate:\n    runs-on: ubuntu-latest\n",
            "  gate:\n    runs-on: ubuntu-latest\n    continue-on-error: true\n",
        ),
        "VERIFY003",
        ".github/workflows/ci.yml",
        "continue-on-error",
        id="f-continue-on-error",
    ),
    pytest.param(
        replace(".github/workflows/ci.yml", WORKFLOW.split("  gate:")[1].split("  unit:")[0], ""),
        "VERIFY003",
        ".github/workflows/ci.yml",
        "'gate'",
        id="g-delete-gate-job",
    ),
    pytest.param(
        replace(".github/workflows/ci.yml", "--head HEAD", "--head HEAD --exit-zero"),
        "VERIFY003",
        ".github/workflows/ci.yml",
        "--exit-zero",
        id="h-exit-zero",
    ),
    pytest.param(
        append("pyproject.toml", '\n[tool.ruff.lint.per-file-ignores]\n"src/app.py" = ["F401"]\n'),
        "VERIFY003",
        "pyproject.toml",
        "per-file-ignores",
        id="i-ruff-per-file-ignore",
    ),
]


def _matching(data: dict, rule: str, path: str, needle: str) -> list[dict]:
    return [
        f
        for f in data["findings"]
        if f["rule_id"] == rule and f["path"] == path and needle in f["message"]
    ]


@pytest.mark.parametrize(("weaken", "rule", "path", "needle"), ADVERSARIAL)
def test_each_adversarial_fixture_fails_the_gate_at_error(
    empty_root: Path,
    capsys: pytest.CaptureFixture[str],
    weaken: Callable[[Path], None],
    rule: str,
    path: str,
    needle: str,
) -> None:
    base = base_repo(empty_root)
    weaken(empty_root)
    commit_all(empty_root, "weaken", HEAD_DATE, "two@example.invalid")
    revision = ["--base", base, "--head", "HEAD", "--root", str(empty_root)]
    code, out, _ = run(["gate", *revision, "--format", "json"], capsys)
    data = json.loads(out)
    found = _matching(data, rule, path, needle)
    assert found != [], [(f["rule_id"], f["path"], f["message"]) for f in data["findings"]]
    assert {f["status"] for f in found} == {"new"}
    assert {f["severity"] for f in found} == {"error"}
    assert {f["category"] for f in found} == {"policy_integrity"}
    assert code == 1
    assert data["gate"]["status"] == "fail"


def test_the_untouched_repository_passes_and_reports_coverage(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = base_repo(empty_root)
    write(empty_root, "src/other.py", "def other(value):\n    return value\n")
    commit_all(empty_root, "honest", HEAD_DATE, "two@example.invalid")
    revision = ["--base", base, "--head", "HEAD", "--root", str(empty_root)]
    code, out, _ = run(["gate", *revision, "--format", "json"], capsys)
    data = json.loads(out)
    assert _check(schema("diff-v1.schema.json"), data, "$") == []
    assert [f for f in data["findings"] if f["rule_id"] == "VERIFY003"] == []
    assert code == 0
    coverage = data["coverage"]["verification"]
    assert "VERIFY003" in coverage["rules"]
    assert coverage["policy"]["configuration"] == "compared"
    assert coverage["policy"]["workflows_checked"] is True
    assert coverage["policy"]["baselines"] == ["shockharness-baseline.json"]
    assert coverage["policy"]["read_errors"] == {}
    assert coverage["policy_attempts"] == 0


def policy_file(tmp_path: Path) -> Path:
    path = tmp_path / "policy" / "shockharness-policy.toml"
    write(
        path.parent,
        path.name,
        "[tool.shockharness.complexity]\ncognitive_warn = 15\n"
        '[tool.shockharness.rules.verification]\nseverity = "error"\n',
    )
    return path


def test_j_loosening_a_policy_key_is_reverted_and_fails_the_gate(
    tmp_path: Path, empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    policy = policy_file(tmp_path)
    base = base_repo(empty_root)
    append(".shockharness.toml", "[tool.shockharness.complexity]\ncognitive_warn = 40\n")(
        empty_root
    )
    commit_all(empty_root, "loosen", HEAD_DATE, "two@example.invalid")
    revision = ["--base", base, "--head", "HEAD", "--root", str(empty_root)]
    code, out, _ = run(["gate", *revision, "--policy", str(policy), "--format", "json"], capsys)
    data = json.loads(out)
    assert _check(schema("diff-v1.schema.json"), data, "$") == []
    assert code == 1
    (attempt,) = data["config"]["policy_attempts"]
    assert attempt["key"] == "complexity.cognitive_warn"
    assert attempt["policy_value"] == 15 and attempt["attempted_value"] == 40
    reverted = _matching(data, "VERIFY003", ".shockharness.toml", "the policy's value applies")
    assert len(reverted) == 1 and reverted[0]["severity"] == "error"
    assert (
        reverted[0]["span"]["line"]
        == read(empty_root, ".shockharness.toml").splitlines().index("cognitive_warn = 40") + 1
    )


def test_plain_check_with_policy_reports_attempts(
    tmp_path: Path, empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    policy = policy_file(tmp_path)
    write(
        empty_root,
        ".shockharness.toml",
        "[tool.shockharness.complexity]\ncognitive_warn = 40\n"
        '[tool.shockharness.rules.verification]\nseverity = "review"\n',
    )
    write(empty_root, "src/app.py", APP)
    target = [str(empty_root / "src"), "--root", str(empty_root), "--no-cache"]
    code, out, _ = run(["check", *target, "--policy", str(policy), "--format", "json"], capsys)
    data = json.loads(out)
    assert _check(schema("report-v1.schema.json"), data, "$") == []
    assert code == 1
    keys = sorted(a["key"] for a in data["config"]["policy_attempts"])
    assert keys == ["complexity.cognitive_warn", "rules.verification.severity"]
    attempts = [f for f in data["findings"] if f["rule_id"] == "VERIFY003"]
    assert len(attempts) == len(keys)
    assert {f["severity"] for f in attempts} == {"error"}
    assert data["config"]["policy"]["keys"] == [
        "complexity.cognitive_warn",
        "rules.verification.severity",
    ]
    code, out, _ = run(["check", *target, "--policy", str(policy)], capsys)
    assert code == 1
    assert "policy: " in out


def test_a_policy_inside_the_root_is_refused(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(empty_root, "policy.toml", "[tool.shockharness.complexity]\ncognitive_warn = 15\n")
    write(empty_root, "src/app.py", APP)
    target = [str(empty_root / "src"), "--root", str(empty_root)]
    code, _, err = run(["check", *target, "--policy", str(empty_root / "policy.toml")], capsys)
    assert code == 2
    assert "must live outside the analyzed root" in err


def test_without_policy_a_plain_check_has_no_verify_findings(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(empty_root, ".shockharness.toml", "[tool.shockharness.complexity]\ncognitive_warn = 40\n")
    write(empty_root, "src/app.py", APP)
    target = [str(empty_root / "src"), "--root", str(empty_root), "--format", "json"]
    code, out, _ = run(["check", *target], capsys)
    data = json.loads(out)
    assert code == 0
    assert [f for f in data["findings"] if f["rule_id"].startswith("VERIFY")] == []
    assert data["config"]["policy"] is None
    assert data["config"]["policy_attempts"] == []
