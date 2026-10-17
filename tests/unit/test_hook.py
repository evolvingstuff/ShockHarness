"""Edit-time feedback: `shockharness hook claude-code post-edit` and `skills install --hook`."""

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions
from shockharness.cli import main
from shockharness.config import EffectiveConfig
from shockharness.errors import UsageError
from shockharness.hook import edited_path, parse_event, run_post_edit
from shockharness.skills.install import HOOK_COMMAND, install_claude_hook

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)
SOURCE = "def f(x=3):\n    return x\n"  # DEF001 and MAGIC001: errors


def event(path: Path) -> str:
    return json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(path)}})


def test_the_edited_path_comes_from_tool_input() -> None:
    assert edited_path(parse_event(event(Path("/p/a.py"))).value) == "/p/a.py"
    assert edited_path(parse_event('{"tool_name": "Bash", "tool_input": {}}').value) is None
    assert edited_path(parse_event("[1]").value) is None
    assert parse_event("not json").problem.startswith("shockharness hook: the hook input")


def test_post_edit_feeds_findings_back_with_exit_2(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    (empty_root / "src").mkdir()
    edited = empty_root / "src" / "a.py"
    edited.write_text(SOURCE, encoding="utf-8")
    result = run_post_edit(event(edited), empty_root, strict_config, OPTIONS, "warning")
    assert result.exit_code == 2
    assert result.message.startswith("shockharness: 2 finding(s) in src/a.py after this edit")
    assert "src/a.py:1:9: DEF001 error" in result.message
    edited.write_text("def f(x):\n    return x\n", encoding="utf-8")
    clean = run_post_edit(event(edited), empty_root, strict_config, OPTIONS, "warning")
    assert (clean.exit_code, clean.message) == (0, "")


def test_post_edit_is_quiet_outside_the_project_and_loud_on_bad_input(
    empty_root: Path, tmp_path: Path, strict_config: EffectiveConfig
) -> None:
    outside = tmp_path / "elsewhere.py"
    outside.write_text(SOURCE, encoding="utf-8")
    assert (
        run_post_edit(event(outside), empty_root, strict_config, OPTIONS, "warning").exit_code == 0
    )
    # Found by the under-the-gate experiment: editing pyproject.toml fed an
    # "unsupported file type" error back to the agent as if it were a finding.
    (empty_root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    config_edit = event(empty_root / "pyproject.toml")
    assert run_post_edit(config_edit, empty_root, strict_config, OPTIONS, "warning").exit_code == 0
    bad = run_post_edit("{", empty_root, strict_config, OPTIONS, "warning")
    assert bad.exit_code == 1  # a notice to the user: the agent did nothing wrong
    assert "not JSON" in bad.message


def test_fail_on_chooses_what_is_fed_back(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    edited = empty_root / "a.py"
    edited.write_text("def f(items):\n    return items or []\n", encoding="utf-8")  # DEF003
    config = make_config("")
    assert run_post_edit(event(edited), empty_root, config, OPTIONS, "warning").exit_code == 0
    edited.write_text("def f(items):\n    return items or ()\n", encoding="utf-8")
    review = run_post_edit(event(edited), empty_root, config, OPTIONS, "review")
    assert review.exit_code == 2
    assert "DEF003 review" in review.message


def test_hook_command_line(
    empty_root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    edited = empty_root / "a.py"
    edited.write_text(SOURCE, encoding="utf-8")
    monkeypatch.setattr("sys.stdin.read", lambda: event(edited))
    code = main(["hook", "claude-code", "post-edit", "--root", str(empty_root), "--no-cache"])
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "a.py:1:9: DEF001 error" in captured.err


def test_install_appends_the_hook_once(empty_root: Path) -> None:
    settings = empty_root / ".claude" / "settings.json"
    settings.parent.mkdir()
    existing = {"hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": []}]}, "model": "x"}
    settings.write_text(json.dumps(existing), encoding="utf-8")
    assert install_claude_hook(empty_root) == (settings, "added")
    assert install_claude_hook(empty_root) == (settings, "already present")
    document = json.loads(settings.read_text(encoding="utf-8"))
    assert document["model"] == "x"
    groups = document["hooks"]["PostToolUse"]
    assert [g["matcher"] for g in groups] == ["Bash", "Edit|Write|MultiEdit|Bash"]
    assert groups[1]["hooks"] == [{"type": "command", "command": HOOK_COMMAND, "timeout": 60}]


def test_install_creates_settings_and_refuses_malformed_ones(empty_root: Path) -> None:
    settings, status = install_claude_hook(empty_root)
    assert status == "added"
    assert json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PostToolUse"][0]["matcher"]
    settings.write_text('{"hooks": []}', encoding="utf-8")
    with pytest.raises(UsageError, match="'hooks' must be a JSON object"):
        install_claude_hook(empty_root)
    settings.write_text("{", encoding="utf-8")
    with pytest.raises(UsageError, match="not valid JSON"):
        install_claude_hook(empty_root)


def test_skills_install_offers_the_hook(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["skills", "install", "--agent", "claude", "--project", str(empty_root)]) == 0
    assert "rerun with --hook" in capsys.readouterr().out
    assert not (empty_root / ".claude" / "settings.json").exists()
    flags = ["skills", "install", "--agent", "claude", "--project", str(empty_root), "--force"]
    assert main([*flags, "--hook"]) == 0
    assert "(added)" in capsys.readouterr().out
    assert main(["skills", "install", "--agent", "codex", "--hook"]) == 2
    assert "--hook is for --agent claude" in capsys.readouterr().err


def bash_event() -> str:
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": "cat > a.py <<EOF"}})


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def runs(root: Path) -> list[dict]:
    log = root / ".shockharness-cache" / "hook" / "runs.jsonl"
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def test_shell_edits_are_checked_through_git_status(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    # Found by the under-the-gate experiment: every builder wrote files through Bash, so
    # a hook on Edit / Write never ran.
    git(empty_root, "init", "-q")
    (empty_root / "clean.py").write_text("def g(x):\n    return x\n", encoding="utf-8")
    (empty_root / "notes.md").write_text("x = 3\n", encoding="utf-8")  # not source
    (empty_root / "a.py").write_text(SOURCE, encoding="utf-8")
    result = run_post_edit(bash_event(), empty_root, strict_config, OPTIONS, "warning")
    assert result.exit_code == 2
    assert "finding(s) in a.py after this edit" in result.message
    assert "clean.py" not in result.message
    again = run_post_edit(bash_event(), empty_root, strict_config, OPTIONS, "warning")
    assert (again.exit_code, again.message) == (0, "")  # unchanged since: not told twice
    (empty_root / "a.py").write_text("def f(x=4):\n    return x\n", encoding="utf-8")
    changed = run_post_edit(bash_event(), empty_root, strict_config, OPTIONS, "warning")
    assert changed.exit_code == 2
    logged = runs(empty_root)
    assert [r["tool"] for r in logged] == ["Bash", "Bash", "Bash"]
    assert [r["files"] for r in logged] == [["a.py", "clean.py"], [], ["a.py"]]
    assert [r["exit"] for r in logged] == [2, 0, 2]


def test_shell_edits_without_git_are_logged_not_checked(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    (empty_root / "a.py").write_text(SOURCE, encoding="utf-8")
    result = run_post_edit(bash_event(), empty_root, strict_config, OPTIONS, "warning")
    assert (result.exit_code, result.message) == (0, "")
    assert runs(empty_root)[0]["note"].startswith("shell edits are not checked")


def test_install_updates_an_older_matcher(empty_root: Path) -> None:
    settings = empty_root / ".claude" / "settings.json"
    settings.parent.mkdir()
    older = {"type": "command", "command": HOOK_COMMAND, "timeout": 60}
    document = {"hooks": {"PostToolUse": [{"matcher": "Edit|Write|MultiEdit", "hooks": [older]}]}}
    settings.write_text(json.dumps(document), encoding="utf-8")
    assert install_claude_hook(empty_root) == (settings, "matcher updated")
    groups = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PostToolUse"]
    assert [g["matcher"] for g in groups] == ["Edit|Write|MultiEdit|Bash"]
    assert install_claude_hook(empty_root) == (settings, "already present")


def test_a_hook_that_cannot_keep_its_files_says_so(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    (empty_root / ".shockharness-cache").write_text("not a directory", encoding="utf-8")
    edited = empty_root / "clean.py"
    edited.write_text("def g(x):\n    return x\n", encoding="utf-8")
    result = run_post_edit(event(edited), empty_root, strict_config, OPTIONS, "warning")
    assert result.exit_code == 1  # a notice for the user; the agent did nothing wrong
    assert "could not be written" in result.message
