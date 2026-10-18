"""Property contracts end to end (P1a): ``config validate`` resolves the catalog's
references, and a commit that removes a sink is a VERIFY003 loosening at the gate."""

import json
import shutil
from pathlib import Path

import pytest

from shockharness.cli import main
from tests.conftest import FIXTURES, commit_all, init_repo

CASE = FIXTURES / "property_contracts" / "python" / "callee_sink"
BASE_DATE = "2026-01-01T12:00:00+00:00"
HEAD_DATE = "2026-01-02T12:00:00+00:00"
LIBRARY_SINK = """
[[tool.shockharness.rules.property_contracts.sinks]]
language = "python"
callee = "json.dumps:0"
requires = ["cloud_disclosable"]
reason = "serialized content is what the uploader sends"
"""


def run(args: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = main(args)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_config_validate_reports_an_unresolved_producer(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    shutil.copytree(CASE, root)
    assert run(["config", "validate", "--root", str(root)], capsys)[0] == 0
    config = root / ".shockharness.toml"
    text = config.read_text(encoding="utf-8")
    config.write_text(text.replace("app.privacy.evaluate", "app.privacy.evaluat"), encoding="utf-8")
    code, _out, err = run(["config", "validate", "--root", str(root)], capsys)
    assert code == 2
    assert "properties[0].producers[0]" in err
    assert "app.privacy.evaluat" in err and "does not resolve" in err


def test_removing_a_sink_is_a_verify003_loosening(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    shutil.copytree(CASE, root)
    config = root / ".shockharness.toml"
    text = config.read_text(encoding="utf-8")
    severity = '[tool.shockharness.rules.verification]\nrule_switching_severity = "error"\n\n'
    config.write_text(severity + text, encoding="utf-8")
    init_repo(root)
    base = commit_all(root, "base", BASE_DATE, "one@example.invalid")
    assert LIBRARY_SINK in config.read_text(encoding="utf-8")
    config.write_text(
        config.read_text(encoding="utf-8").replace(LIBRARY_SINK, ""), encoding="utf-8"
    )
    commit_all(root, "drop the sink", HEAD_DATE, "two@example.invalid")
    revision = ["--base", base, "--head", "HEAD", "--root", str(root), "--format", "json"]
    code, out, _err = run(["gate", *revision], capsys)
    data = json.loads(out)
    found = [
        f
        for f in data["findings"]
        if f["rule_id"] == "VERIFY003"
        and "no longer lists the sink python json.dumps:0" in f["message"]
    ]
    assert len(found) == 1, [(f["rule_id"], f["message"]) for f in data["findings"]]
    assert (found[0]["severity"], found[0]["status"]) == ("error", "new")
    assert code == 1
