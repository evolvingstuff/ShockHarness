"""H2 end to end: VERIFY001, VERIFY002, VERIFY004 through the CLI on real git history.

Each test builds a throwaway repository with a base commit and a head commit. Samples are
written from strings, so this repository's own tests never contain a real skip marker,
tautology or blanket suppression.
"""

import json
from pathlib import Path

import pytest

from shockharness.cli import main
from tests.conftest import commit_all, git, init_repo

BASE_DATE = "2026-01-01T12:00:00+00:00"
HEAD_DATE = "2026-01-02T12:00:00+00:00"
LATER_DATE = "2026-01-03T12:00:00+00:00"

BASE_PY = """\
import pytest


@pytest.mark.skip(reason="old debt")
def test_old():
    assert run() == expected()


def test_add():
    assert add(one, one) == two


def test_sub():
    assert sub(two, one) == one
"""

HEAD_PY = """\
import pytest


@pytest.mark.skip(reason="old debt")
def test_old():
    assert run() == expected()


@pytest.mark.skip(reason="flaky on CI")
def test_add():
    assert True


def test_sub():
    pass
"""

BASE_JS = (
    'describe("calc", () => {\n  it("adds", () => { expect(add(one, one)).toBe(two); });\n});\n'
)
HEAD_JS = 'describe("calc", () => {\n  it.only("adds", () => { expect(1).toBe(1); });\n});\n'
BASE_SRC = "def run():\n    return compute()\n"
HEAD_SRC = "def run():\n    return compute()  # noqa\n"

VERIFY_EXPECTED = [
    ("VERIFY002", "src/app.py", 2),
    ("VERIFY001", "tests/calc.test.js", 2),
    ("VERIFY004", "tests/calc.test.js", 2),
    ("VERIFY001", "tests/test_calc.py", 9),
    ("VERIFY004", "tests/test_calc.py", 11),
    ("VERIFY004", "tests/test_calc.py", 14),
]


def write(root: Path, relative: str, body: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def run(args: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = main(args)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def weakened_repo(root: Path) -> tuple[str, str]:
    """A base commit with honest tests and a head commit that weakens them."""
    init_repo(root)
    write(root, "tests/test_calc.py", BASE_PY)
    write(root, "tests/calc.test.js", BASE_JS)
    write(root, "src/app.py", BASE_SRC)
    base = commit_all(root, "base", BASE_DATE, "one@example.invalid")
    write(root, "tests/test_calc.py", HEAD_PY)
    write(root, "tests/calc.test.js", HEAD_JS)
    write(root, "src/app.py", HEAD_SRC)
    head = commit_all(root, "head", HEAD_DATE, "two@example.invalid")
    return base, head


def verify_rows(data: dict) -> list[tuple[str, str, int]]:
    return [
        (f["rule_id"], f["path"], f["span"]["line"])
        for f in data["findings"]
        if f["rule_id"].startswith("VERIFY")
    ]


def test_diff_reports_every_weakening_as_new_policy_integrity(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base, _ = weakened_repo(empty_root)
    code, out, _ = run(
        ["diff", "--base", base, "--head", "HEAD", "--format", "json", "--root", str(empty_root)],
        capsys,
    )
    assert code == 0
    data = json.loads(out)
    assert verify_rows(data) == VERIFY_EXPECTED
    verify = [f for f in data["findings"] if f["rule_id"].startswith("VERIFY")]
    assert {f["status"] for f in verify} == {"new"}
    assert {f["category"] for f in verify} == {"policy_integrity"}
    assert {f["finding_status"] for f in verify} == {"violation"}
    assert {f["severity"] for f in verify} == {"warning"}
    assert data["summary"]["new_policy_integrity"] == len(VERIFY_EXPECTED)
    coverage = data["coverage"]["verification"]
    assert coverage["status"] == "analyzed"
    assert coverage["base_commit"] == base
    assert coverage["files_compared"] == 3
    assert coverage["rules"] == ["VERIFY001", "VERIFY002", "VERIFY003", "VERIFY004"]
    test_file = next(f for f in data["head"]["files"] if f["path"] == "tests/test_calc.py")
    assert {"VERIFY001", "VERIFY002", "VERIFY004"} <= set(test_file["rules_applied"])
    assert data["gate"]["status"] == "pass"


def test_diff_text_lists_policy_integrity_first(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base, _ = weakened_repo(empty_root)
    code, out, _ = run(
        ["diff", "--base", base, "--head", "HEAD", "--root", str(empty_root)], capsys
    )
    assert code == 0
    lines = out.splitlines()
    assert lines[0] == "policy integrity (the change weakened its own verification):"
    assert lines[1].startswith("  new: src/app.py:2:")
    assert "VERIFY002 warning: blanket suppression # noqa added" in lines[1]
    assert any(
        line.startswith("  verification: VERIFY001, VERIFY002, VERIFY003, VERIFY004 against base ")
        and "3 source file(s) compared" in line
        for line in lines
    )


def test_gate_passes_by_default_and_fails_when_raised_to_error(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base, _ = weakened_repo(empty_root)
    revision = ["--base", base, "--head", "HEAD", "--root", str(empty_root)]
    code, out, _ = run(["gate", *revision], capsys)
    assert code == 0
    assert "gate: PASS (exit 0)" in out
    write(
        empty_root,
        ".shockharness.toml",
        '[tool.shockharness.rules.verification]\nseverity = "error"\n',
    )
    code, out, _ = run(["gate", *revision, "--format", "json"], capsys)
    assert code == 1
    data = json.loads(out)
    assert data["gate"]["status"] == "fail"
    assert data["gate"]["new_hard_violations"] == len(VERIFY_EXPECTED)
    code, out, _ = run(["gate", *revision, "--exit-zero"], capsys)
    assert code == 0
    assert "advisory run (--exit-zero)" in out


ALLOWED_CONFIG = (
    '[tool.shockharness.rules.verification]\nseverity = "review"\n'
    'allowed_skip_reasons = ["flaky on CI"]\n'
)


def test_allowed_skip_reason_and_review_severity_are_deviations(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Committed at base: the change under review did not grant itself the exemption.
    init_repo(empty_root)
    write(empty_root, ".shockharness.toml", ALLOWED_CONFIG)
    write(empty_root, "tests/test_calc.py", BASE_PY)
    base = commit_all(empty_root, "base", BASE_DATE, "one@example.invalid")
    write(empty_root, "tests/test_calc.py", HEAD_PY)
    commit_all(empty_root, "head", HEAD_DATE, "two@example.invalid")
    code, out, _ = run(
        ["diff", "--base", base, "--head", "HEAD", "--format", "json", "--root", str(empty_root)],
        capsys,
    )
    assert code == 0
    data = json.loads(out)
    rows = verify_rows(data)
    assert ("VERIFY001", "tests/test_calc.py", 9) not in rows
    assert ("VERIFY004", "tests/test_calc.py", 11) in rows
    assert {f["severity"] for f in data["findings"] if f["rule_id"].startswith("VERIFY")} == {
        "review"
    }
    deviations = "\n".join(data["config"]["deviations"])
    assert "rules.verification.severity is 'review'" in deviations
    assert (
        "allowed_skip_reasons[0] accepts an added skip marker whose reason is 'flaky on CI'"
        in deviations
    )


def test_an_exemption_granted_in_the_same_change_does_not_apply(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Strictest of base: the head may not lower or exempt the VERIFY rules reporting it.
    base, _ = weakened_repo(empty_root)
    write(empty_root, ".shockharness.toml", ALLOWED_CONFIG)
    commit_all(empty_root, "exempt", LATER_DATE, "two@example.invalid")
    code, out, _ = run(
        ["diff", "--base", base, "--head", "HEAD", "--format", "json", "--root", str(empty_root)],
        capsys,
    )
    assert code == 0
    data = json.loads(out)
    rows = verify_rows(data)
    assert ("VERIFY001", "tests/test_calc.py", 9) in rows
    severities = {f["severity"] for f in data["findings"] if f["rule_id"].startswith("VERIFY")}
    assert severities == {"warning"}
    loosened = [f["message"] for f in data["findings"] if f["rule_id"] == "VERIFY003"]
    assert any("allowed_skip_reasons" in message for message in loosened)
    assert any("rules.verification.severity" in message for message in loosened)


def test_plain_check_reports_verification_as_not_applicable(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    weakened_repo(empty_root)
    _, out, _ = run(
        ["check", str(empty_root), "--root", str(empty_root), "--format", "json"], capsys
    )
    data = json.loads(out)
    assert [f for f in data["findings"] if f["rule_id"].startswith("VERIFY")] == []
    assert data["coverage"]["verification"]["status"] == "not_applicable"
    assert data["coverage"]["rules_needing_base_revision"] == [
        "VERIFY001",
        "VERIFY002",
        "VERIFY003",
        "VERIFY004",
    ]
    _code, out, _ = run(["check", str(empty_root), "--root", str(empty_root)], capsys)
    assert "rules needing a base revision (not analyzed in this run" in out
    applied = next(line for line in out.splitlines() if line.startswith("  rules applied:"))
    assert "VERIFY" not in applied


def test_inline_suppression_of_a_verify_rule_is_supp001(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(empty_root, "src/a.py", 'x = 1  # shockharness: ignore[VERIFY001] reason="trust me"\n')
    code, out, _ = run(["check", str(empty_root / "src"), "--root", str(empty_root)], capsys)
    assert code == 1
    assert "SUPP001 error: VERIFY001 cannot be suppressed inline" in out


def test_renamed_test_file_keeps_its_old_markers_as_debt(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    init_repo(empty_root)
    write(empty_root, "tests/test_calc.py", BASE_PY)
    base = commit_all(empty_root, "base", BASE_DATE, "one@example.invalid")
    git(empty_root, "mv", "tests/test_calc.py", "tests/test_math.py")
    commit_all(empty_root, "rename", HEAD_DATE, "one@example.invalid")
    _code, out, _ = run(
        ["diff", "--base", base, "--head", "HEAD", "--format", "json", "--root", str(empty_root)],
        capsys,
    )
    data = json.loads(out)
    assert verify_rows(data) == []
    assert data["coverage"]["verification"]["renamed"] == 1


def test_unparseable_base_makes_findings_unknown(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    init_repo(empty_root)
    write(empty_root, "tests/test_calc.py", "def broken(:\n")
    base = commit_all(empty_root, "base", BASE_DATE, "one@example.invalid")
    write(empty_root, "tests/test_calc.py", BASE_PY)
    commit_all(empty_root, "head", HEAD_DATE, "one@example.invalid")
    _code, out, _ = run(
        ["diff", "--base", base, "--head", "HEAD", "--format", "json", "--root", str(empty_root)],
        capsys,
    )
    data = json.loads(out)
    verify = [f for f in data["findings"] if f["rule_id"].startswith("VERIFY")]
    assert [(f["rule_id"], f["finding_status"], f["confidence"]) for f in verify] == [
        ("VERIFY001", "unknown", "unresolved")
    ]
    assert data["coverage"]["verification"]["base_unanalyzable"] == 1
    assert data["gate"]["unknown"] == 1


def test_diff_json_is_byte_identical_across_runs(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base, head = weakened_repo(empty_root)
    args = ["diff", "--base", base, "--head", head, "--format", "json", "--root", str(empty_root)]
    _, first, _ = run(args, capsys)
    _, second, _ = run(args, capsys)
    assert first == second


def test_sarif_carries_the_category(empty_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base, _ = weakened_repo(empty_root)
    code, out, _ = run(
        ["diff", "--base", base, "--head", "HEAD", "--format", "sarif", "--root", str(empty_root)],
        capsys,
    )
    assert code == 0
    run_data = json.loads(out)["runs"][0]
    verify = [r for r in run_data["results"] if r["ruleId"].startswith("VERIFY")]
    assert len(verify) == len(VERIFY_EXPECTED)
    assert {r["properties"]["category"] for r in verify} == {"policy_integrity"}
    rules = {r["id"]: r for r in run_data["tool"]["driver"]["rules"]}
    assert rules["VERIFY001"]["properties"]["needs_base_revision"] is True
    assert rules["MAGIC001"]["properties"]["needs_base_revision"] is False


def test_tool_tolerates_an_existing_later_commit(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Comparing two older commits ignores later history entirely."""
    base, head = weakened_repo(empty_root)
    write(empty_root, "src/app.py", BASE_SRC)
    commit_all(empty_root, "revert noqa", LATER_DATE, "one@example.invalid")
    code, out, _ = run(
        ["diff", "--base", base, "--head", head, "--format", "json", "--root", str(empty_root)],
        capsys,
    )
    assert code == 0
    assert verify_rows(json.loads(out)) == VERIFY_EXPECTED
