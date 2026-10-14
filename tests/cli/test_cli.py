"""CLI contract tests.

In-process via ``main`` for speed; one subprocess test proves the entry point.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from shockharness.cli import main
from shockharness.version import __version__
from tests.conftest import commit_all, init_repo


def write(root: Path, relative: str, body: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def run(args: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = main(args)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_subprocess_entry_point_and_version() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "shockharness", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stdout.strip() == f"shockharness {__version__}"


def test_no_command_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as info:
        main([])
    assert info.value.code == 2


def test_rules_list_and_explain(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(["rules", "list"], capsys)
    assert code == 0
    assert "MAGIC001  error    implemented" in out
    assert "EXC001    error    implemented" in out
    assert "DEF001    error    implemented" in out
    assert "DEF003    review   implemented" in out
    assert "CPLX001   warning  planned" in out
    code, out, _ = run(["rules", "explain", "MAGIC001"], capsys)
    assert code == 0
    assert "Detection guarantees" in out
    assert "range(2)" in out
    code, _, err = run(["rules", "explain", "NOPE"], capsys)
    assert code == 2
    assert "unknown rule ID" in err


def test_init_refuses_to_overwrite(empty_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = empty_root / ".shockharness.toml"
    code, _, _ = run(["init", "--path", str(target)], capsys)
    assert code == 0
    assert target.exists()
    assert "[tool.shockharness]" in target.read_text(encoding="utf-8")
    target.write_text("custom", encoding="utf-8")
    code, _, err = run(["init", "--path", str(target)], capsys)
    assert code == 2
    assert "already exists" in err
    assert target.read_text(encoding="utf-8") == "custom"
    code, _, _ = run(["init", "--path", str(target), "--force"], capsys)
    assert code == 0
    assert "[tool.shockharness]" in target.read_text(encoding="utf-8")


def test_config_validate_and_effective(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = run(["config", "validate", "--root", str(empty_root)], capsys)
    assert code == 0
    assert "configuration is valid (bundled" in out
    write(empty_root, ".shockharness.toml", "[tool.shockharness]\nnonsense = 1\n")
    code, _, err = run(["config", "validate", "--root", str(empty_root)], capsys)
    assert code == 2
    assert "nonsense: unknown key" in err
    write(empty_root, ".shockharness.toml", '[tool.shockharness]\nparse_errors = "warn"\n')
    code, out, _ = run(["config", "effective", "--root", str(empty_root)], capsys)
    assert code == 0
    data = json.loads(out)
    assert data["values"]["parse_errors"] == "warn"
    assert data["origins"]["parse_errors"] == "dedicated"
    assert data["origins"]["profile"] == "bundled"


def test_scan_exit_codes(empty_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(empty_root, "src/clean.py", "x = 1\n")
    code, out, _ = run(["scan", str(empty_root / "src"), "--root", str(empty_root)], capsys)
    assert code == 0
    assert "gate: PASS (exit 0)" in out

    write(empty_root, "src/dirty.py", "for i in range(2):\n    pass\n")
    code, out, _ = run(["scan", str(empty_root / "src"), "--root", str(empty_root)], capsys)
    assert code == 1
    assert "src/dirty.py:1:16: MAGIC001 error" in out

    write(empty_root, "src/broken.js", "function (\n")
    code, out, _ = run(["scan", str(empty_root / "src"), "--root", str(empty_root)], capsys)
    assert code == 3
    assert "parse_error" in out

    code, _, err = run(["scan", str(empty_root / "missing"), "--root", str(empty_root)], capsys)
    assert code == 2
    assert "does not exist" in err


def test_milestone_b_acceptance_python_and_js(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """range(2) fails in Python and for(;i<2;) fails in JS.

    Both pass with the rule disabled, and the report says why.
    """
    write(empty_root, "src/a.py", "for i in range(2):\n    pass\n")
    write(empty_root, "src/b.js", "for (let i = 0; i < 2; i++) {}\n")
    code, out, _ = run(
        ["scan", str(empty_root / "src"), "--root", str(empty_root), "--format", "json"], capsys
    )
    assert code == 1
    data = json.loads(out)
    assert [(f["path"], f["span"]["line"], f["span"]["column"]) for f in data["findings"]] == [
        ("src/a.py", 1, 16),
        ("src/b.js", 1, 21),
    ]

    write(
        empty_root,
        ".shockharness.toml",
        "[tool.shockharness.rules.magic_numbers]\nenabled = false\n",
    )
    code, out, _ = run(
        ["scan", str(empty_root / "src"), "--root", str(empty_root), "--format", "json"], capsys
    )
    assert code == 0
    data = json.loads(out)
    assert data["findings"] == []
    assert data["coverage"]["rules_disabled_globally"] == ["MAGIC001"]
    assert "rules.magic_numbers is disabled" in data["config"]["deviations"]
    assert all(
        {"rule_id": "MAGIC001", "reason": "rules.magic_numbers.enabled = false", "origin": "config"}
        in f["rules_disabled"]
        for f in data["files"]
    )


def test_milestone_c_acceptance_exceptions(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Approved network failure handling passes only inside its verified boundary.

    Broad catches fail; an unresolved exception type is an explicit diagnostic.
    """
    narrow = (
        "from requests.exceptions import Timeout\n"
        "def fetch(session, url):\n"
        "    try:\n"
        "        response = session.get(url)\n"
        "    except Timeout as exc:\n"
        "        raise Upstream(url) from exc\n"
        "    return response.json()\n"
    )
    write(empty_root, "src/net/client.py", narrow)
    write(empty_root, "src/core/client.py", narrow)
    write(
        empty_root,
        "src/net/broad.py",
        "def load(raw):\n    try:\n        return parse(raw)\n    except Exception:\n"
        "        return None\n",
    )
    write(
        empty_root,
        "src/net/unknown.py",
        "def load(raw):\n    try:\n        return parse(raw)\n    except Mystery as exc:\n"
        "        raise Failed() from exc\n",
    )
    write(
        empty_root,
        "src/net/wide.py",
        "from requests.exceptions import Timeout\n"
        "def fetch(session, url):\n"
        "    try:\n"
        "        response = session.get(url)\n"
        "        data = response.json()\n"
        "    except Timeout as exc:\n"
        "        raise Upstream(url) from exc\n"
        "    return data\n",
    )
    write(
        empty_root,
        ".shockharness.toml",
        "[[tool.shockharness.rules.exceptions.boundaries]]\n"
        'path = "src/net/**"\nlanguage = "python"\n'
        'exception = "requests.exceptions.Timeout"\nreason = "external HTTP call"\n',
    )
    code, out, _ = run(
        ["scan", str(empty_root / "src"), "--root", str(empty_root), "--format", "json"], capsys
    )
    assert code == 1
    data = json.loads(out)
    rows = [(f["path"], f["rule_id"], f["span"]["line"], f["confidence"]) for f in data["findings"]]
    assert rows == [
        ("src/core/client.py", "EXC001", 5, "exact"),
        ("src/net/broad.py", "DEF005", 4, "exact"),  # return_fallback: DEF005 owns it (Milestone D)
        ("src/net/broad.py", "EXC001", 4, "exact"),
        ("src/net/unknown.py", "EXC001", 4, "unresolved"),
        ("src/net/wide.py", "EXC003", 5, "exact"),
    ]
    by_path = {f["path"]: f["message"] for f in data["findings"] if f["rule_id"] == "EXC001"}
    assert "not approved by any boundary" in by_path["src/core/client.py"]
    assert "broad catch of 'Exception'" in by_path["src/net/broad.py"]
    assert "'Mystery' could not be resolved" in by_path["src/net/unknown.py"]
    assert any("boundaries[0] approves catching" in d for d in data["config"]["deviations"])
    assert "EXC001" in data["coverage"]["rules_implemented"]


def test_scan_json_output_file(empty_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(empty_root, "src/a.py", "x = 2\n")
    out_file = empty_root / "report.json"
    code, out, _ = run(
        [
            "scan",
            str(empty_root / "src"),
            "--root",
            str(empty_root),
            "--format",
            "json",
            "--output",
            str(out_file),
        ],
        capsys,
    )
    assert code == 1
    assert "report written to" in out
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1"
    assert data["gate"]["exit_code"] == 1


def test_scan_output_is_deterministic(empty_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(empty_root, "src/a.py", "x = 2\ny = 3\n")
    write(empty_root, "src/b.js", "const z = 4;\n")
    args = ["scan", str(empty_root / "src"), "--root", str(empty_root), "--format", "json"]
    _, first, _ = run(args, capsys)
    _, second, _ = run(args, capsys)
    assert first == second


def test_sarif_output_is_a_single_run(empty_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(empty_root, "src/a.py", "x = 2\n")
    code, out, _ = run(
        ["scan", str(empty_root / "src"), "--root", str(empty_root), "--format", "sarif"], capsys
    )
    assert code == 1
    data = json.loads(out)
    assert data["version"] == "2.1.0"
    assert len(data["runs"]) == 1
    assert data["runs"][0]["results"][0]["ruleId"] == "MAGIC001"


def test_no_inline_suppressions_flag(empty_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(empty_root, "src/a.py", 'x = 2  # shockharness: ignore[MAGIC001] reason="r"\n')
    code, _, _ = run(["scan", str(empty_root / "src"), "--root", str(empty_root)], capsys)
    assert code == 0
    code, out, _ = run(
        ["scan", str(empty_root / "src"), "--root", str(empty_root), "--no-inline-suppressions"],
        capsys,
    )
    assert code == 1
    assert "SUPP001" in out


def test_unsupported_explicit_file(empty_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ts = write(empty_root, "a.ts", "")
    code, _, err = run(["scan", str(ts), "--root", str(empty_root)], capsys)
    assert code == 2
    assert "unsupported file type" in err


def test_invalid_config_is_exit_2_before_scanning(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(empty_root, "src/a.py", "x = 2\n")
    write(empty_root, ".shockharness.toml", "[tool.shockharness]\ninclude = 5\n")
    code, _, err = run(["scan", str(empty_root / "src"), "--root", str(empty_root)], capsys)
    assert code == 2
    assert "include: expected a list" in err


# --- Milestone F: baselines, diff, gate, SARIF -------------------------------------------


def test_baseline_create_then_scan_with_baseline(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A reviewed baseline makes legacy findings non-gating while still listing them."""
    write(empty_root, "src/a.py", "x = 2\ndef f():\n    return 3\n")
    baseline = empty_root / "baseline.json"
    root = ["--root", str(empty_root)]
    code, out, _ = run(
        ["baseline", "create", str(empty_root / "src"), "--output", str(baseline), *root], capsys
    )
    assert code == 0
    assert "wrote" in out and "2 fingerprint(s)" in out
    data = json.loads(baseline.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1"
    assert data["tool_version"] == __version__
    assert len(data["config_digest"]) == 64
    assert [e["evidence"] for e in data["fingerprints"]] == ["x = 2", "return 3"]

    # never auto-updated: a second create refuses unless forced
    code, _, err = run(
        ["baseline", "create", str(empty_root / "src"), "--output", str(baseline), *root], capsys
    )
    assert code == 2
    assert "never updated automatically" in err

    # lines move; the baseline still matches and the gate passes
    write(empty_root, "src/a.py", "import os\n\nx = 2\n\n\ndef f():\n    return 3\n")
    code, out, _ = run(
        ["scan", str(empty_root / "src"), "--baseline", str(baseline), *root], capsys
    )
    assert code == 0
    assert "src/a.py:3:5: MAGIC001 error" in out and "(baseline: matched)" in out
    assert "gate: PASS (exit 0)" in out
    assert "2 legacy finding(s) matched the baseline" in out

    # a new violation fails; the legacy ones are still marked
    write(empty_root, "src/a.py", "import os\n\nx = 2\ny = 4\n\n\ndef f():\n    return 3\n")
    code, out, _ = run(
        ["scan", str(empty_root / "src"), "--baseline", str(baseline), "--format", "json", *root],
        capsys,
    )
    assert code == 1
    data = json.loads(out)
    assert [(f["span"]["line"], f["baseline"]) for f in data["findings"]] == [
        (3, "matched"),
        (4, None),
        (8, "matched"),
    ]
    assert data["gate"]["new_hard_violations"] == 1
    assert data["gate"]["baseline"]["source"] == "file"
    assert data["gate"]["baseline"]["origin"] == str(baseline)
    assert data["execution_summary"]["baselined"] == 2

    # without the baseline, everything fails as before
    code, _, _ = run(["scan", str(empty_root / "src"), *root], capsys)
    assert code == 1

    # the same is true through `gate PATH... --baseline`
    code, _, _ = run(["gate", str(empty_root / "src"), "--baseline", str(baseline), *root], capsys)
    assert code == 1
    write(empty_root, "src/a.py", "import os\n\nx = 2\n\n\ndef f():\n    return 3\n")
    code, _, _ = run(["gate", str(empty_root / "src"), "--baseline", str(baseline), *root], capsys)
    assert code == 0


def test_baseline_create_refuses_incomplete_analysis(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(empty_root, "src/bad.js", "function (\n")
    baseline = empty_root / "baseline.json"
    code, _, err = run(
        [
            "baseline",
            "create",
            str(empty_root / "src"),
            "--output",
            str(baseline),
            "--root",
            str(empty_root),
        ],
        capsys,
    )
    assert code == 2
    assert "no baseline was written" in err
    assert not baseline.exists()


def test_baseline_file_is_deterministic(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(empty_root, "src/a.py", "x = 2\ny = 3\n")
    write(empty_root, "src/b.js", "const z = 4;\n")
    first = empty_root / "one.json"
    second = empty_root / "two.json"
    for target in (first, second):
        code, _, _ = run(
            [
                "baseline",
                "create",
                str(empty_root / "src"),
                "--output",
                str(target),
                "--root",
                str(empty_root),
            ],
            capsys,
        )
        assert code == 0
    assert first.read_bytes() == second.read_bytes()


def test_missing_baseline_file_is_a_usage_error(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(empty_root, "src/a.py", "x = 1\n")
    code, _, err = run(
        [
            "scan",
            str(empty_root / "src"),
            "--baseline",
            str(empty_root / "nope.json"),
            "--root",
            str(empty_root),
        ],
        capsys,
    )
    assert code == 2
    assert "cannot read baseline" in err


def _two_commit_repo(root: Path) -> tuple[str, str]:
    """c1 has violations in a.py and b.js; c2 fixes one, moves one, adds one in c.js."""
    init_repo(root)
    write(root, "src/a.py", "x = 2\ndef f():\n    return 3\n")
    write(root, "src/b.js", "const y = 4;\n")
    c1 = commit_all(root, "c1", "2026-01-01T12:00:00+00:00", "one@example.invalid")
    write(root, "src/a.py", "# inserted\n\nx = 2\ndef f():\n    return 'fixed'\n")
    (root / "src" / "b.js").unlink()
    write(root, "src/c.js", "const z = 7;\n")
    c2 = commit_all(root, "c2", "2026-01-02T12:00:00+00:00", "two@example.invalid")
    return c1, c2


def test_gate_between_two_commits(empty_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The acceptance criterion for Milestone F: a reproducible gate on two commits with a
    complete provenance trail, failing only on new hard violations."""
    c1, c2 = _two_commit_repo(empty_root)
    write(empty_root, "src/dirty.py", "dirty = 9\n")  # uncommitted: must not take part
    root = ["--root", str(empty_root)]

    code, out, _ = run(["gate", "--base", c1, "--head", "HEAD", "--format", "json", *root], capsys)
    assert code == 1
    data = json.loads(out)
    assert data["report_kind"] == "diff"
    assert data["tool_version"] == __version__
    assert len(data["config_digest"]) == 64
    assert data["base"] == {**data["base"], "ref": c1, "commit": c1}
    assert data["head"] == {**data["head"], "ref": "HEAD", "commit": c2}
    rows = [(f["status"], f["path"], f["span"]["line"], f["evidence"]) for f in data["findings"]]
    assert rows == [
        ("unchanged", "src/a.py", 3, "x = 2"),
        ("fixed", "src/a.py", 3, "return 3"),
        ("fixed", "src/b.js", 1, "const y = 4;"),
        ("new", "src/c.js", 1, "const z = 7;"),
    ]
    assert data["summary"] == {
        "new": 1,
        "fixed": 2,
        "unchanged": 1,
        "new_hard_violations": 1,
        "fixed_hard_violations": 2,
        "unchanged_hard_violations": 1,
    }
    assert data["gate"]["status"] == "fail"
    assert data["gate"]["new_hard_violations"] == 1
    assert data["gate"]["hard_violations"] == 2
    assert data["gate"]["baseline"]["source"] == "base_revision"
    assert data["gate"]["baseline"]["origin"] == c1
    assert all(f["path"] != "src/dirty.py" for f in data["findings"])
    assert data["metrics"]["history"]["status"] == "available"
    assert data["metrics"]["history"]["revision"]["commit"] == c2

    # the reverse direction: the only "new" finding is the fixed one; c1 -> c1 has none
    code, out, _ = run(["gate", "--base", "HEAD", "--head", c1, *root], capsys)
    assert code == 1
    assert "new: src/a.py:3:12: MAGIC001" in out
    code, out, _ = run(["gate", "--base", c1, "--head", c1, *root], capsys)
    assert code == 0
    assert "0 new, 0 fixed, 3 unchanged" in out
    assert "gate: PASS (exit 0)" in out

    # fixed violations never fail: head without the new c.js violation passes against c1
    (empty_root / "src" / "dirty.py").unlink()
    (empty_root / "src" / "c.js").unlink()
    c3 = commit_all(empty_root, "c3", "2026-01-03T12:00:00+00:00", "two@example.invalid")
    code, out, _ = run(["gate", "--base", c1, "--head", c3, *root], capsys)
    assert code == 0
    assert "0 new, 2 fixed, 1 unchanged" in out

    # diff is reporting only: same content, exit 0
    code, out_diff, _ = run(
        ["diff", "--base", c1, "--head", "HEAD", "--format", "json", *root], capsys
    )
    assert code == 0
    assert json.loads(out_diff)["gate"]["status"] == "pass"


def test_gate_legacy_fail_counts_unchanged_findings(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    c1, _c2 = _two_commit_repo(empty_root)
    (empty_root / "src" / "c.js").unlink()
    c3 = commit_all(empty_root, "c3", "2026-01-03T12:00:00+00:00", "two@example.invalid")
    root = ["--root", str(empty_root)]
    code, _, _ = run(["gate", "--base", c1, "--head", c3, *root], capsys)
    assert code == 0
    write(empty_root, ".shockharness.toml", '[tool.shockharness.gates]\nlegacy = "fail"\n')
    code, out, _ = run(["gate", "--base", c1, "--head", c3, *root], capsys)
    assert code == 1
    assert 'gates.legacy = "fail"' in out


def test_diff_output_is_byte_identical_across_runs(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    c1, c2 = _two_commit_repo(empty_root)
    args = ["diff", "--base", c1, "--head", c2, "--format", "json", "--root", str(empty_root)]
    _, first, _ = run(args, capsys)
    _, second, _ = run(args, capsys)
    assert first == second
    args = ["diff", "--base", c1, "--head", c2, "--format", "sarif", "--root", str(empty_root)]
    _, first, _ = run(args, capsys)
    _, second, _ = run(args, capsys)
    assert first == second
    data = json.loads(first)
    states = [r["baselineState"] for r in data["runs"][0]["results"]]
    assert states == ["unchanged", "absent", "absent", "new"]


def test_diff_report_matches_published_schema(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from tests.conftest import REPO_ROOT
    from tests.unit.test_gate_and_report import _check

    c1, c2 = _two_commit_repo(empty_root)
    _, out, _ = run(
        ["diff", "--base", c1, "--head", c2, "--format", "json", "--root", str(empty_root)], capsys
    )
    schema = json.loads((REPO_ROOT / "schemas" / "diff-v1.schema.json").read_text(encoding="utf-8"))
    assert _check(schema, json.loads(out), "$") == []


def test_diff_with_a_subdirectory_root(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    init_repo(empty_root)
    write(empty_root, "pkg/src/a.py", "x = 1\n")
    write(empty_root, "other/b.py", "y = 5\n")  # outside the root: never analyzed
    c1 = commit_all(empty_root, "c1", "2026-01-01T12:00:00+00:00", "one@example.invalid")
    write(empty_root, "pkg/src/a.py", "x = 6\n")
    c2 = commit_all(empty_root, "c2", "2026-01-02T12:00:00+00:00", "one@example.invalid")
    code, out, _ = run(
        ["diff", "--base", c1, "--head", c2, "--format", "json", "--root", str(empty_root / "pkg")],
        capsys,
    )
    assert code == 0
    data = json.loads(out)
    assert [(f["status"], f["path"]) for f in data["findings"]] == [("new", "src/a.py")]


def test_diff_head_parse_failure_is_exit_3(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    init_repo(empty_root)
    write(empty_root, "src/a.py", "x = 1\n")
    c1 = commit_all(empty_root, "c1", "2026-01-01T12:00:00+00:00", "one@example.invalid")
    write(empty_root, "src/bad.js", "function (\n")
    c2 = commit_all(empty_root, "c2", "2026-01-02T12:00:00+00:00", "one@example.invalid")
    code, out, _ = run(["diff", "--base", c1, "--head", c2, "--root", str(empty_root)], capsys)
    assert code == 3
    assert "head src/bad.js: parse_error" in out


def test_diff_usage_errors(empty_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(empty_root, "src/a.py", "x = 1\n")
    root = ["--root", str(empty_root)]
    code, _, err = run(["diff", "--base", "HEAD~1", "--head", "HEAD", *root], capsys)
    assert code == 2
    assert "needs a git repository" in err
    init_repo(empty_root)
    commit_all(empty_root, "c1", "2026-01-01T12:00:00+00:00", "one@example.invalid")
    code, _, err = run(["diff", "--base", "no-such-ref", "--head", "HEAD", *root], capsys)
    assert code == 2
    assert "cannot resolve revision 'no-such-ref'" in err
    code, _, err = run(["gate", "--base", "HEAD", *root], capsys)
    assert code == 2
    assert "must be given together" in err
    code, _, err = run(["gate", *root], capsys)
    assert code == 2
    assert "needs PATH... or --base and --head" in err
    code, _, err = run(
        ["gate", str(empty_root / "src"), "--base", "HEAD", "--head", "HEAD", *root], capsys
    )
    assert code == 2
    assert "cannot be combined" in err
    code, _, err = run(
        ["gate", "--base", "HEAD", "--head", "HEAD", "--baseline", "b.json", *root], capsys
    )
    assert code == 2
    assert "--baseline cannot be combined" in err


def test_scan_report_carries_history(empty_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    init_repo(empty_root)
    write(empty_root, "src/a.py", "x = 1\n")
    commit_all(empty_root, "c1", "2026-01-01T12:00:00+00:00", "one@example.invalid")
    code, out, _ = run(
        ["scan", str(empty_root / "src"), "--format", "json", "--root", str(empty_root)], capsys
    )
    assert code == 0
    history = json.loads(out)["metrics"]["history"]
    assert history["status"] == "available"
    assert history["files"]["src/a.py"]["commits"] == 1
    code, out, _ = run(["scan", str(empty_root / "src"), "--root", str(empty_root)], capsys)
    assert "history: 1 commit(s) in 90 day(s)" in out
