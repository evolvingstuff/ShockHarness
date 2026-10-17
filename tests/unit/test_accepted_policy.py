"""Spec 21.1 decision 35: the test exemption ``init`` writes, VERIFY003 against the accepted
configuration in ``check`` and the edit hook, the rule-switching severity in ``gate``, and
``skills install --hook --lock``."""

import json
import shutil
from pathlib import Path

import pytest

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions
from shockharness.cli import main
from shockharness.config import (
    CliOverrides,
    load_config,
    load_config_with_overrides,
    render_profile_config_toml,
)
from shockharness.hook import run_post_edit
from shockharness.loosening import Loosening, is_remedy
from shockharness.rules.accepted_policy import accepted_policy
from shockharness.skills.lock import lock_path, render_lock
from tests.conftest import commit_all, git, init_repo

DATE = "2026-01-01T12:00:00+00:00"
LATER = "2026-01-02T12:00:00+00:00"
EMAIL = "one@example.invalid"
OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)
CONFIG = ".shockharness.toml"
OVERRIDE = '[[tool.shockharness.overrides]]\npaths = ["a.py"]\ndisable = ["EXC001"]\nreason = "r"\n'


def boundary(path: str) -> str:
    return (
        "[[tool.shockharness.rules.exceptions.boundaries]]\n"
        f'path = "{path}"\nlanguage = "python"\nexception = "OSError"\nreason = "file read"\n'
    )


def write_config(root: Path, body: str) -> None:
    (root / CONFIG).write_text("[tool.shockharness]\n\n" + body, encoding="utf-8")


def committed(root: Path, body: str) -> None:
    init_repo(root)
    (root / "a.py").write_text("def f(x: int) -> int:\n    return x\n", encoding="utf-8")
    write_config(root, body)
    commit_all(root, "accepted", DATE, EMAIL)


def messages(root: Path) -> list[str]:
    return [f.message for f in accepted_policy(root, None).findings]


def test_init_writes_the_test_exemption_for_every_profile(empty_root: Path) -> None:
    for profile in ("strict", "recommended", "minimal"):
        (empty_root / CONFIG).write_text(render_profile_config_toml(profile), encoding="utf-8")
        config = load_config(empty_root, None)
        assert config.values["overrides"][0]["roles"] == ["test"]
        assert config.values["overrides"][0]["disable"] == ["MAGIC001", "DEF001"]


def test_a_one_file_boundary_is_a_remedy_and_a_glob_boundary_is_not(empty_root: Path) -> None:
    write_config(empty_root, boundary("a.py") + "\n" + boundary("src/**"))
    config = load_config(empty_root, None)
    lines = [line for line in config.deviations if line.startswith("rules.exceptions")]
    assert [is_remedy(Loosening("", line), config.values) for line in lines] == [True, False]
    assert not is_remedy(Loosening("overrides", "overrides[0] disables EXC001"), config.values)


def test_a_rule_switched_off_since_head_is_an_error_until_committed(empty_root: Path) -> None:
    committed(empty_root, "")
    write_config(empty_root, OVERRIDE + "\n" + boundary("a.py") + "\n" + boundary("src/**"))
    result = accepted_policy(empty_root, None)
    assert {f.severity for f in result.findings} == {"error"}
    found = [f.message for f in result.findings]
    assert len(found) == 2  # the override and the glob boundary; the one-file boundary is a remedy
    assert any(m.startswith("overrides[0] disables EXC001 for a.py") for m in found)
    assert any("boundaries[1] approves catching OSError in src/**" in m for m in found)
    assert all("since HEAD (" in m and "do not commit it yourself" in m for m in found)
    assert result.coverage["status"] == "compared"
    commit_all(empty_root, "accepted by a person", LATER, EMAIL)
    assert messages(empty_root) == []


def test_a_branch_is_compared_with_its_merge_base_with_origin_head(empty_root: Path) -> None:
    committed(empty_root, "")
    git(empty_root, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(empty_root, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    git(empty_root, "checkout", "-q", "-b", "feature")
    write_config(empty_root, OVERRIDE)
    commit_all(empty_root, "committed on the branch", LATER, EMAIL)
    found = messages(empty_root)
    assert len(found) == 1 and "since the merge base with origin/HEAD (" in found[0]


def test_lowering_the_rule_switching_severity_is_itself_reported_as_an_error(
    empty_root: Path,
) -> None:
    committed(empty_root, "")
    write_config(
        empty_root, '[tool.shockharness.rules.verification]\nrule_switching_severity = "review"\n'
    )
    result = accepted_policy(empty_root, None)
    assert [f.severity for f in result.findings] == ["error"]
    assert "rule_switching_severity" in result.findings[0].message


def test_without_a_commit_the_init_configuration_is_accepted(empty_root: Path) -> None:
    init_repo(empty_root)
    (empty_root / CONFIG).write_text(render_profile_config_toml("strict"), encoding="utf-8")
    result = accepted_policy(empty_root, None)
    assert result.findings == ()
    assert result.coverage["accepted"].endswith("(no commit yet)")
    write_config(empty_root, OVERRIDE)
    assert len(messages(empty_root)) == 1


def test_a_head_without_configuration_accepts_what_init_writes(empty_root: Path) -> None:
    init_repo(empty_root)
    commit_all(empty_root, "empty", DATE, EMAIL)
    (empty_root / CONFIG).write_text(render_profile_config_toml("strict"), encoding="utf-8")
    result = accepted_policy(empty_root, None)
    assert result.findings == ()
    assert "has no configuration" in result.coverage["accepted"]


def test_outside_git_nothing_is_compared_and_coverage_says_why(empty_root: Path) -> None:
    write_config(empty_root, OVERRIDE)
    result = accepted_policy(empty_root, None)
    assert result.findings == ()
    assert result.coverage["status"] == "not_compared"
    assert result.coverage["reason"].startswith("not a git repository")


def test_an_unreadable_accepted_configuration_is_unknown_never_a_pass(empty_root: Path) -> None:
    committed(empty_root, "")
    (empty_root / CONFIG).write_text("[tool.shockharness]\nnot_a_key = 1\n", encoding="utf-8")
    commit_all(empty_root, "invalid", LATER, EMAIL)
    write_config(empty_root, "")
    result = accepted_policy(empty_root, None)
    assert result.coverage["status"] == "unknown"
    assert [f.status for f in result.findings] == ["unknown"]


def test_check_fails_and_names_the_comparison(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    committed(empty_root, "")
    write_config(empty_root, OVERRIDE)
    code = main(["check", str(empty_root), "--root", str(empty_root), "--format", "json"])
    data = json.loads(capsys.readouterr().out)
    assert code == 1
    assert [f["rule_id"] for f in data["findings"]] == ["VERIFY003"]
    assert data["coverage"]["accepted_configuration"]["status"] == "compared"
    main(["check", str(empty_root), "--root", str(empty_root)])
    assert "  VERIFY003: configuration compared with HEAD (" in capsys.readouterr().out


def test_gate_fails_on_a_committed_rule_switch(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    committed(empty_root, "")
    base = git(empty_root, "rev-parse", "HEAD").strip()
    write_config(empty_root, OVERRIDE)
    commit_all(empty_root, "switch a rule off", LATER, EMAIL)
    args = ["gate", "--base", base, "--head", "HEAD", "--root", str(empty_root), "--format", "json"]
    code = main(args)
    data = json.loads(capsys.readouterr().out)
    assert code == 1
    switched = [f for f in data["findings"] if f["rule_id"] == "VERIFY003"]
    assert [f["severity"] for f in switched] == ["error"]


def test_the_hook_feeds_a_changed_configuration_back_once(empty_root: Path) -> None:
    committed(empty_root, "")
    bash = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})
    config = load_config(empty_root, None)
    assert run_post_edit(bash, empty_root, config, OPTIONS, "warning").exit_code == 0
    write_config(empty_root, OVERRIDE)
    config = load_config(empty_root, None)
    result = run_post_edit(bash, empty_root, config, OPTIONS, "warning")
    assert result.exit_code == 2
    assert result.message.startswith("shockharness: 1 finding(s) in .shockharness.toml")
    assert "VERIFY003 error: overrides[0] disables EXC001" in result.message
    assert run_post_edit(bash, empty_root, config, OPTIONS, "warning").exit_code == 0


def test_the_lock_round_trips_and_blocks_a_loosening(empty_root: Path, tmp_path: Path) -> None:
    write_config(empty_root, boundary("a.py"))
    config = load_config(empty_root, None)
    lock = tmp_path / "home" / "lock.toml"
    lock.parent.mkdir()
    lock.write_text(render_lock(config, empty_root), encoding="utf-8")
    locked = CliOverrides(profile=None, parse_errors=None, policy=lock)
    same = load_config_with_overrides(empty_root, None, locked)
    assert same.policy_attempts == () and same.values == config.values
    assert "boundaries =" not in lock.read_text(encoding="utf-8")
    write_config(empty_root, boundary("a.py") + "\n" + boundary("b.py") + "\n" + OVERRIDE)
    loosened = load_config_with_overrides(empty_root, None, locked)
    assert [a.key for a in loosened.policy_attempts] == ["overrides"]
    assert loosened.values["overrides"] == []
    assert len(loosened.values["rules"]["exceptions"]["boundaries"]) == 2


def test_skills_install_writes_the_config_and_the_lock(
    empty_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    install = ["skills", "install", "--agent", "claude", "--project", str(empty_root), "--hook"]
    assert main([*install, "--lock"]) == 0
    out = capsys.readouterr().out
    assert "config     .shockharness.toml: written" in out
    lock = lock_path(empty_root, home)
    assert lock.is_file() and f"lock       {lock}: written" in out
    settings = json.loads((empty_root / ".claude" / "settings.json").read_text(encoding="utf-8"))
    command = settings["hooks"]["PostToolUse"][0]["hooks"][0]["command"]
    assert command.endswith(f'--policy "{lock}"')
    assert main([*install, "--lock", "--force"]) == 0
    assert "config     .shockharness.toml: kept as it is" in capsys.readouterr().out
    shutil.rmtree(empty_root / ".claude" / "skills")  # so only the lock decides
    assert main([*install, "--lock"]) == 0
    assert f"lock       {lock}: kept" in capsys.readouterr().out
    assert (
        main(["skills", "install", "--agent", "claude", "--project", str(empty_root), "--lock"])
        == 2
    )
