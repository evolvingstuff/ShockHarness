"""Skills reach an agent through the commands: init installs them, check notices none."""

import json
from pathlib import Path

import pytest

from shockharness.cli import main
from shockharness.skills import SKILL_NAMES
from shockharness.skills.adapters import get_adapter
from shockharness.skills.install import MANIFEST_FILENAME, install_skills
from shockharness.skills.presence import (
    KNOWN_AGENTS,
    OPT_OUT,
    POINTER_ADDED,
    POINTER_PRESENT,
    add_pointer,
    detected_agents,
    known_agent,
    missing_skills_notices,
)

CLAUDE_COMMAND = "shockharness skills install --agent claude"
CODEX_COMMAND = "shockharness skills install --agent codex"


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A home directory of the test's own, so a real per-user install never counts."""
    directory = tmp_path / "home"
    directory.mkdir()
    monkeypatch.setenv("HOME", str(directory))
    return directory


@pytest.fixture
def project(tmp_path: Path) -> Path:
    directory = tmp_path / "project"
    directory.mkdir()
    return directory


def run(args: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = main(args)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_known_agents_use_the_adapters_directories() -> None:
    for known in KNOWN_AGENTS:
        adapter = get_adapter(known.agent)
        assert (adapter.project_subdir, adapter.user_subdir) == (known.skills_dir, known.skills_dir)


def test_agents_are_found_by_their_files(project: Path) -> None:
    assert detected_agents(project) == []
    (project / "AGENTS.md").write_text("# agents\n", encoding="utf-8")
    assert [known.agent for known in detected_agents(project)] == ["codex"]
    (project / ".claude").mkdir()
    assert [known.agent for known in detected_agents(project)] == ["claude", "codex"]


def test_each_agent_without_skills_gets_one_line(project: Path, home: Path) -> None:
    (project / "CLAUDE.md").write_text("# claude\n", encoding="utf-8")
    (project / "AGENTS.md").write_text("# agents\n", encoding="utf-8")
    claude, codex = missing_skills_notices(project, home)
    assert claude == (
        "skills: none installed for Claude Code, which works here (CLAUDE.md found); "
        f"run: {CLAUDE_COMMAND} ({OPT_OUT})"
    )
    assert codex.startswith("skills: none installed for Codex")
    install_skills(project / ".agents" / "skills", "codex", force=False)
    assert missing_skills_notices(project, home) == [claude]


def test_a_per_user_install_counts(project: Path, home: Path) -> None:
    (project / "CLAUDE.md").write_text("# claude\n", encoding="utf-8")
    install_skills(home / ".claude" / "skills", "claude", force=False)
    assert missing_skills_notices(project, home) == []


def test_no_agent_files_names_every_command(project: Path, home: Path) -> None:
    (notice,) = missing_skills_notices(project, home)
    assert CLAUDE_COMMAND in notice
    assert CODEX_COMMAND in notice
    install_skills(project / ".claude" / "skills", "claude", force=False)
    assert missing_skills_notices(project, home) == []


def test_the_pointer_is_appended_once(project: Path) -> None:
    instructions = project / "AGENTS.md"
    instructions.write_text("# agents\nno newline at the end", encoding="utf-8")
    path, status = add_pointer(project, known_agent("codex"))
    assert (path, status) == (instructions, POINTER_ADDED)
    text = instructions.read_text(encoding="utf-8")
    assert text.startswith("# agents\nno newline at the end\n\nBefore writing, fixing")
    assert ".agents/skills/<name>/SKILL.md" in text
    assert add_pointer(project, known_agent("codex")) == (instructions, POINTER_PRESENT)
    assert instructions.read_text(encoding="utf-8") == text


def test_an_instruction_file_that_names_the_skills_is_kept(project: Path) -> None:
    own = "Use the repository skills in `.claude/skills/` before editing.\n"
    (project / "CLAUDE.md").write_text(own, encoding="utf-8")
    assert add_pointer(project, known_agent("claude"))[1] == POINTER_PRESENT
    assert (project / "CLAUDE.md").read_text(encoding="utf-8") == own


def test_init_installs_the_skills_for_the_agents_found(
    project: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (project / ".claude").mkdir()
    (project / "AGENTS.md").write_text("# agents\n", encoding="utf-8")
    code, out, _ = run(["init", "--path", str(project / ".shockharness.toml")], capsys)
    assert code == 0
    for known in KNOWN_AGENTS:
        destination = project / known.skills_dir
        assert (destination / MANIFEST_FILENAME).is_file()
        assert sorted(path.parent.name for path in destination.glob("*/SKILL.md")) == sorted(
            SKILL_NAMES
        )
        assert known.skills_dir in (project / known.instructions).read_text(encoding="utf-8")
        assert f"installed {len(SKILL_NAMES)} skill(s) for {known.agent}" in out
    assert "--hook" in out
    code, out, _ = run(["init", "--path", str(project / ".shockharness.toml"), "--force"], capsys)
    assert code == 0
    assert "claude: already installed" in out
    assert (project / "AGENTS.md").read_text(encoding="utf-8").count(".agents/skills") == 1


def test_init_without_agent_files_prints_the_commands(
    project: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = run(["init", "--path", str(project / ".shockharness.toml")], capsys)
    assert code == 0
    assert "skills not installed: no coding agent's files" in out
    assert CLAUDE_COMMAND in out
    assert not (project / ".claude").exists()


def test_init_agent_and_no_skills(
    project: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = str(project / ".shockharness.toml")
    code, out, _ = run(["init", "--path", target, "--no-skills"], capsys)
    assert code == 0
    assert "skills not installed (--no-skills)" in out
    assert not (project / ".claude").exists()
    code, _, _ = run(["init", "--path", target, "--force", "--agent", "claude"], capsys)
    assert code == 0
    assert (project / ".claude" / "skills" / MANIFEST_FILENAME).is_file()
    assert ".claude/skills" in (project / "CLAUDE.md").read_text(encoding="utf-8")
    assert not (project / ".agents").exists()


def test_skills_install_adds_the_pointer(
    project: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = run(["skills", "install", "--agent", "codex", "--project", str(project)], capsys)
    assert code == 0
    assert f"pointer    {project / 'AGENTS.md'}: {POINTER_ADDED}" in out
    assert ".agents/skills" in (project / "AGENTS.md").read_text(encoding="utf-8")


def configured(project: Path, extra: str) -> None:
    (project / ".shockharness.toml").write_text(
        f'[tool.shockharness]\nprofile = "strict"\n{extra}', encoding="utf-8"
    )
    (project / "a.py").write_text("x = 0\n", encoding="utf-8")


def check(project: Path, capsys: pytest.CaptureFixture[str]) -> str:
    main(["check", str(project), "--root", str(project), "--format", "json"])
    captured = capsys.readouterr()
    json.loads(captured.out)  # the report itself stays valid JSON
    return captured.err


def test_check_notices_a_configured_project_without_skills(
    project: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (project / "CLAUDE.md").write_text("# claude\n", encoding="utf-8")
    configured(project, "")
    assert "shockharness: skills: none installed for Claude Code" in check(project, capsys)
    install_skills(project / ".claude" / "skills", "claude", force=False)
    assert "skills:" not in check(project, capsys)


def test_the_notice_can_be_turned_off_and_needs_a_configured_project(
    project: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (project / "CLAUDE.md").write_text("# claude\n", encoding="utf-8")
    (project / "a.py").write_text("x = 0\n", encoding="utf-8")
    assert "skills:" not in check(project, capsys)  # bundled defaults: not a ShockHarness project
    configured(project, "\n[tool.shockharness.skills]\nnotify_missing = false\n")
    assert "skills:" not in check(project, capsys)
