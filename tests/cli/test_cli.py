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


def test_sarif_is_refused_loudly(empty_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(empty_root, "src/a.py", "x = 1\n")
    code, _, err = run(
        ["scan", str(empty_root / "src"), "--root", str(empty_root), "--format", "sarif"], capsys
    )
    assert code == 2
    assert "not implemented" in err


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
