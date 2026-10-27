"""The finish-time gate: `shockharness hook claude-code stop` / `session-start` and
`skills install --stop-hook` (docs/proposal-stop-hook.md)."""

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from shockharness.analysis import CACHE_BYPASSED, CACHE_CONFIGURED, AnalysisOptions
from shockharness.cli import main
from shockharness.config import EffectiveConfig, load_config
from shockharness.errors import ConfigError
from shockharness.gating.diff import diff_working_tree
from shockharness.hook import run_post_edit
from shockharness.hook_stop import run_session_start, run_stop
from shockharness.skills.install import (
    SESSION_START_COMMAND,
    STOP_COMMAND,
    install_claude_stop_hook,
)

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_CONFIGURED)
CLEAN = "def f(x):\n    return x\n"
VIOLATION = "def f(x=3):\n    return x\n"  # DEF001 and MAGIC001: errors


def git(root: Path, *args: str) -> str:
    identity = ["-c", "user.email=agent@example.com", "-c", "user.name=agent"]
    done = subprocess.run(
        ["git", *identity, *args], cwd=root, check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


def stop_event(*, continuing: bool) -> str:
    return json.dumps(
        {"session_id": "s1", "hook_event_name": "Stop", "stop_hook_active": continuing}
    )


START = json.dumps({"session_id": "s1", "hook_event_name": "SessionStart", "source": "startup"})


@pytest.fixture
def repository(empty_root: Path) -> Path:
    git(empty_root, "init", "-q")
    (empty_root / ".gitignore").write_text(".shockharness-cache/\n", encoding="utf-8")
    (empty_root / "a.py").write_text(CLEAN, encoding="utf-8")
    git(empty_root, "add", "-A")
    git(empty_root, "commit", "-q", "-m", "start")
    return empty_root


def runs(root: Path) -> list[dict]:
    log = root / ".shockharness-cache" / "hook" / "runs.jsonl"
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def test_a_commit_made_during_the_session_does_not_hide_its_findings(
    repository: Path, strict_config: EffectiveConfig
) -> None:
    start = run_session_start(START, repository, strict_config)
    assert (start.exit_code, start.message) == (0, "")  # SessionStart output joins the context
    base = git(repository, "rev-parse", "HEAD")
    quiet = run_stop(stop_event(continuing=False), repository, strict_config, OPTIONS, None)
    assert (quiet.exit_code, quiet.message) == (0, "")
    assert runs(repository)[-1]["note"] == "nothing changed since the base"
    (repository / "a.py").write_text(VIOLATION, encoding="utf-8")
    git(repository, "commit", "-q", "-am", "the agent commits")
    blocked = run_stop(stop_event(continuing=False), repository, strict_config, OPTIONS, None)
    assert blocked.exit_code == 2
    assert blocked.message.startswith(
        f"shockharness: this change is not finished: against {base[:12]}, the commit this "
        "session started from, the gate fails:\n"
        '  2 new hard violation(s) and gates.new_hard_violations = "fail"\n'
    )
    assert "a.py:1:9: DEF001 error" in blocked.message
    assert "do not suppress, skip or loosen the configuration" in blocked.message
    assert "a decision only the user can make" in blocked.message


def test_a_fixed_change_passes_and_the_same_tree_is_not_analyzed_again(
    repository: Path, strict_config: EffectiveConfig
) -> None:
    run_session_start(START, repository, strict_config)
    (repository / "a.py").write_text(VIOLATION, encoding="utf-8")
    first = run_stop(stop_event(continuing=False), repository, strict_config, OPTIONS, None)
    assert first.exit_code == 2
    (repository / "a.py").write_text(CLEAN + "\n\ndef g(y):\n    return y\n", encoding="utf-8")
    fixed = run_stop(stop_event(continuing=True), repository, strict_config, OPTIONS, None)
    assert (fixed.exit_code, fixed.message) == (0, "")
    assert runs(repository)[-1]["gate"] == "pass"
    again = run_stop(stop_event(continuing=False), repository, strict_config, OPTIONS, None)
    assert again.exit_code == 0
    assert runs(repository)[-1]["note"] == "as at the last stop let through"


def test_the_cache_directory_is_not_a_change_even_when_git_does_not_ignore_it(
    repository: Path, strict_config: EffectiveConfig
) -> None:
    (repository / ".gitignore").unlink()
    git(repository, "commit", "-q", "-am", "no ignore file")
    run_session_start(START, repository, strict_config)
    assert (repository / ".shockharness-cache" / "hook" / "state.json").is_file()
    quiet = run_stop(stop_event(continuing=False), repository, strict_config, OPTIONS, None)
    assert quiet.exit_code == 0
    assert runs(repository)[-1]["note"] == "nothing changed since the base"


def test_untracked_files_are_part_of_the_change(
    repository: Path, strict_config: EffectiveConfig
) -> None:
    run_session_start(START, repository, strict_config)
    (repository / "new.py").write_text(VIOLATION, encoding="utf-8")
    blocked = run_stop(stop_event(continuing=False), repository, strict_config, OPTIONS, None)
    assert blocked.exit_code == 2
    assert "new.py:1:9: DEF001 error" in blocked.message


def test_the_guard_lets_a_stop_through_when_nothing_was_fixed(
    repository: Path, strict_config: EffectiveConfig
) -> None:
    run_session_start(START, repository, strict_config)
    (repository / "a.py").write_text(VIOLATION, encoding="utf-8")
    assert (
        run_stop(stop_event(continuing=False), repository, strict_config, OPTIONS, None).exit_code
        == 2
    )
    # The agent replies without fixing anything: Claude Code asks to stop again.
    (repository / "notes.md").write_text("tried\n", encoding="utf-8")
    left = run_stop(stop_event(continuing=True), repository, strict_config, OPTIONS, None)
    assert left.exit_code == 1  # a notice to the user; the stop goes ahead
    assert left.message.startswith(
        "shockharness stop hook: the agent stopped with nothing fixed since the last block"
    )
    assert "a.py:1:9: DEF001 error" in left.message
    # A new turn starts afresh: the same findings block again.
    assert (
        run_stop(stop_event(continuing=False), repository, strict_config, OPTIONS, None).exit_code
        == 2
    )


def test_the_guard_lets_a_stop_through_after_max_blocks(
    repository: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    config = make_config("[tool.shockharness.hooks.stop]\nmax_blocks = 1\nshown = 1\n")
    git(repository, "add", ".shockharness.toml")
    git(repository, "commit", "-q", "-m", "configuration")
    run_session_start(START, repository, config)
    (repository / "a.py").write_text(VIOLATION, encoding="utf-8")
    first = run_stop(stop_event(continuing=False), repository, config, OPTIONS, None)
    assert first.exit_code == 2
    assert "  ... and 1 more\n" in first.message  # shown = 1 of DEF001 and MAGIC001
    (repository / "a.py").write_text("def f(x=4):\n    return x\n", encoding="utf-8")
    second = run_stop(stop_event(continuing=True), repository, config, OPTIONS, None)
    assert second.exit_code == 1
    assert second.message.startswith("shockharness stop hook: the agent stopped after 1 block(s)")


def test_the_first_hook_run_of_a_session_records_its_base(
    repository: Path, strict_config: EffectiveConfig
) -> None:
    base = git(repository, "rev-parse", "HEAD")
    edit = json.dumps(
        {
            "session_id": "s1",
            "tool_name": "Edit",
            "tool_input": {"file_path": str(repository / "a.py")},
        }
    )
    no_cache = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)
    assert run_post_edit(edit, repository, strict_config, no_cache, "warning").exit_code == 0
    (repository / "a.py").write_text(VIOLATION, encoding="utf-8")
    git(repository, "commit", "-q", "-am", "the agent commits")
    blocked = run_stop(stop_event(continuing=False), repository, strict_config, OPTIONS, None)
    assert blocked.exit_code == 2
    assert f"against {base[:12]}," in blocked.message


def test_base_names_a_branch_whose_merge_base_is_used(
    repository: Path, strict_config: EffectiveConfig
) -> None:
    base = git(repository, "rev-parse", "HEAD")
    branch = git(repository, "branch", "--show-current")
    git(repository, "checkout", "-q", "-b", "work")
    (repository / "a.py").write_text(VIOLATION, encoding="utf-8")
    git(repository, "commit", "-q", "-am", "on the branch")
    blocked = run_stop(stop_event(continuing=False), repository, strict_config, OPTIONS, branch)
    assert blocked.exit_code == 2
    assert f"against {base[:12]}," in blocked.message
    unknown = run_stop(stop_event(continuing=False), repository, strict_config, OPTIONS, "nope")
    assert unknown.exit_code == 1
    assert unknown.message.startswith("shockharness stop hook: no base: --base nope:")


def test_bad_input_is_a_notice(repository: Path, strict_config: EffectiveConfig) -> None:
    assert run_stop("{", repository, strict_config, OPTIONS, None).exit_code == 1
    assert run_session_start("{", repository, strict_config).exit_code == 1


def test_the_working_tree_diff_matches_the_revision_diff(
    repository: Path, strict_config: EffectiveConfig
) -> None:
    base = git(repository, "rev-parse", "HEAD")
    (repository / "a.py").write_text(VIOLATION, encoding="utf-8")
    tree = diff_working_tree(repository, base, strict_config, OPTIONS)
    git(repository, "commit", "-q", "-am", "head")
    no_cache = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)
    committed = diff_working_tree(repository, base, strict_config, no_cache)
    assert tree.summary() == committed.summary()
    assert tree.summary()["new_hard_violations"] == 2
    assert tree.head.ref == "working tree"
    assert (repository / ".shockharness-cache" / "base" / "index.json").is_file()


def test_install_adds_both_hooks_once(empty_root: Path) -> None:
    settings = empty_root / ".claude" / "settings.json"
    settings.parent.mkdir()
    existing = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "say done"}]}]}}
    settings.write_text(json.dumps(existing), encoding="utf-8")
    path, status = install_claude_stop_hook(empty_root, None)
    assert (path, status) == (settings, "Stop added, SessionStart added")
    assert (
        install_claude_stop_hook(empty_root, None)[1]
        == "Stop already present, SessionStart already present"
    )
    hooks = json.loads(settings.read_text(encoding="utf-8"))["hooks"]
    assert hooks["Stop"][0]["hooks"][0]["command"] == "say done"
    assert hooks["Stop"][1] == {
        "hooks": [{"type": "command", "command": STOP_COMMAND, "timeout": 600}]
    }
    assert hooks["SessionStart"][0]["hooks"][0]["command"] == SESSION_START_COMMAND
    lock = empty_root / "lock.toml"
    assert (
        install_claude_stop_hook(empty_root, lock)[1]
        == "Stop command updated, SessionStart command updated"
    )
    hooks = json.loads(settings.read_text(encoding="utf-8"))["hooks"]
    assert hooks["Stop"][1]["hooks"][0]["command"] == f'{STOP_COMMAND} --policy "{lock}"'


def test_skills_install_stop_hook(empty_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    flags = ["skills", "install", "--agent", "claude", "--project", str(empty_root)]
    assert main([*flags, "--stop-hook"]) == 0
    assert "stop hook" in capsys.readouterr().out
    assert "Stop" in json.loads((empty_root / ".claude" / "settings.json").read_text())["hooks"]
    assert main(["skills", "install", "--agent", "codex", "--stop-hook"]) == 2
    assert "--stop-hook is for --agent claude" in capsys.readouterr().err
    assert main(["skills", "install", "--agent", "claude", "--user", "--stop-hook"]) == 2
    assert "it needs a project, not --user" in capsys.readouterr().err


def test_the_hooks_table_is_validated_and_not_digested(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    plain = load_config(empty_root, None)
    tuned = make_config("[tool.shockharness.hooks.stop]\nmax_blocks = 5\n")
    assert tuned.values["hooks"]["stop"] == {"max_blocks": 5, "shown": 20}
    assert tuned.digest == make_config("").digest
    assert plain.values["hooks"]["stop"]["max_blocks"] == 3
    with pytest.raises(ConfigError):
        make_config("[tool.shockharness.hooks.stop]\nmax_blocks = 0\n")


def test_hook_stop_command_line(
    repository: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin.read", lambda: START)
    assert main(["hook", "claude-code", "session-start", "--root", str(repository)]) == 0
    (repository / "a.py").write_text(VIOLATION, encoding="utf-8")
    monkeypatch.setattr("sys.stdin.read", lambda: stop_event(continuing=False))
    assert main(["hook", "claude-code", "stop", "--root", str(repository)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "a.py:1:9: DEF001 error" in captured.err
