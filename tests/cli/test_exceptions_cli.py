"""`shockharness exceptions` (0.5.0, docs/shockharness-suggestions-4.md item 7)."""

import json
from pathlib import Path

import pytest

from shockharness.cli import main
from shockharness.constants import BASELINE_SCHEMA_VERSION, FINGERPRINT_VERSION
from tests.conftest import REPO_ROOT
from tests.unit.test_gate_and_report import _check

CONFIG = """\
[tool.shockharness]
exclude = ["**/legacy/**"]

[[tool.shockharness.rules.exceptions.boundaries]]
path = "src/io.py"
language = "python"
exception = "OSError"
reason = "reading user files"

[[tool.shockharness.overrides]]
paths = ["src/gen_*.py"]
disable = ["MAGIC001"]
reason = "generated tables"
"""
APP = """\
LIMIT = 3  # shockharness: ignore[MAGIC001] reason="documented limit"
x = 1  # shockharness: ignore[DEF002] reason="nothing to silence"
y = 2  # shockharness: ignore[MAGIC001]
"""


def write(root: Path, relative: str, body: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def run(args: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = main(args)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def project(root: Path) -> list[str]:
    write(root, ".shockharness.toml", CONFIG)
    write(root, "src/app.py", APP)
    return [str(root / "src"), "--root", str(root)]


def baseline_file(root: Path) -> Path:
    entries = [
        {"fingerprint": "a" * 64, "rule_id": "MAGIC001", "path": "src/old.py"},
        {"fingerprint": "b" * 64, "rule_id": "MAGIC001", "path": "src/old.py"},
        {"fingerprint": "c" * 64, "rule_id": "DEF002", "path": "src/other.py"},
    ]
    path = root / "shockharness-baseline.json"
    body = {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "fingerprint_version": FINGERPRINT_VERSION,
        "tool_version": "0.4.0",
        "config_digest": "0" * 64,
        "fingerprints": [
            {**entry, "scope": None, "evidence": "x", "occurrence": 0} for entry in entries
        ],
    }
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def test_every_exception_appears_once_with_its_source(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = project(empty_root)
    baseline = baseline_file(empty_root)
    code, out, _ = run(["exceptions", *target, "--baseline", str(baseline)], capsys)
    assert code == 0
    lines = out.splitlines()
    assert lines[0].endswith(
        "2 inline suppression(s) (1 with unused rules, 1 invalid), 3 configuration "
        "exception(s), 0 policy attempt(s), 3 baseline entr(ies)"
    )
    assert "  src/app.py:1  MAGIC001  reason: documented limit" in lines
    assert "  src/app.py:2  DEF002  reason: nothing to silence  [unused: DEF002]" in lines
    assert any(line.startswith("  src/app.py:3  malformed suppression") for line in lines)
    assert (
        "  .shockharness.toml:4  rules.exceptions.boundaries[0] approves catching OSError "
        "in src/io.py (python): reading user files" in lines
    )
    assert (
        "  .shockharness.toml:10  overrides[0] disables MAGIC001 for src/gen_*.py: "
        "generated tables" in lines
    )
    assert "  .shockharness.toml:2  exclude drops '**/legacy/**' from analysis" in lines
    assert "baseline shockharness-baseline.json:" in lines
    assert "  by rule: DEF002 1, MAGIC001 2" in lines
    assert "  by file: src/old.py 2, src/other.py 1" in lines


def test_json_validates_and_is_byte_identical(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = project(empty_root)
    _, first, _ = run(["exceptions", *target, "--format", "json"], capsys)
    _, second, _ = run(["exceptions", *target, "--format", "json", "--no-cache"], capsys)
    assert first == second
    data = json.loads(first)
    schema = json.loads(
        (REPO_ROOT / "schemas" / "exceptions-v1.schema.json").read_text(encoding="utf-8")
    )
    assert _check(schema, data, "$") == []
    assert data["report_kind"] == "exceptions"
    assert data["config_source"] == {"tier": "dedicated", "path": ".shockharness.toml"}
    assert data["baseline"] is None
    assert data["summary"]["suppressions"] == 2
    (used, unused) = data["suppressions"]
    assert used["used"] == ["MAGIC001"] and used["unused"] == []
    assert unused["used"] == [] and unused["unused"] == ["DEF002"]


def test_profile_and_policy_entries_name_their_origin(
    tmp_path: Path, empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = project(empty_root)
    write(
        empty_root,
        ".shockharness.toml",
        CONFIG + "[tool.shockharness.complexity]\ncognitive_warn = 40\n",
    )
    policy = tmp_path / "org" / "policy.toml"
    write(policy.parent, policy.name, "[tool.shockharness.complexity]\ncognitive_warn = 15\n")
    args = ["exceptions", *target, "--profile", "recommended", "--policy", str(policy)]
    code, out, _ = run([*args, "--format", "json"], capsys)
    assert code == 0
    data = json.loads(out)
    origins = {entry["key"]: entry["origin"] for entry in data["configuration"]}
    assert origins["profile"] == "command line"
    assert origins["rules.defaults.fail_on_unknown"] == "profile:recommended"
    (attempt,) = data["policy_attempts"]
    assert attempt["key"] == "complexity.cognitive_warn"
    assert attempt["path"] == ".shockharness.toml" and attempt["line"] == 15


def test_exceptions_never_gate_and_reject_invalid_configuration(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(empty_root, "src/bad.py", "x = 2\ntry:\n    pass\nexcept Exception:\n    pass\n")
    code, out, _ = run(["exceptions", str(empty_root / "src"), "--root", str(empty_root)], capsys)
    assert code == 0
    assert "0 inline suppression(s)" in out
    write(empty_root, ".shockharness.toml", "[tool.shockharness]\nparse_errors = 3\n")
    code, _, err = run(["exceptions", str(empty_root / "src"), "--root", str(empty_root)], capsys)
    assert code == 2
    assert "error" in err
