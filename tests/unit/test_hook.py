"""Edit-time feedback: `shockharness hook claude-code post-edit` and `skills install --hook`."""

import json
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
    assert [g["matcher"] for g in groups] == ["Bash", "Edit|Write|MultiEdit"]
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
