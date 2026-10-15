"""Bundled agent skills: shipped files, adapter table, install/update/check, CLI exit codes."""

import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from shockharness.cli import main
from shockharness.errors import UsageError
from shockharness.rules import registry
from shockharness.skills import (
    SKILL_NAMES,
    Frontmatter,
    parse_frontmatter,
    shipped_frontmatter,
    skill_bytes,
    skill_names,
    skill_text,
)
from shockharness.skills.adapters import (
    ADAPTERS,
    AGENTS,
    get_adapter,
    pointer_line,
    resolve_destination,
)
from shockharness.skills.install import (
    MANIFEST_FILENAME,
    STATUS_EDITED,
    STATUS_MISSING,
    STATUS_NEW,
    STATUS_REMOVED,
    STATUS_STALE,
    STATUS_UP_TO_DATE,
    install_skills,
    load_manifest,
    parse_manifest,
    sha256_hex,
    update_skills,
)
from shockharness.version import __version__
from tests.conftest import REPO_ROOT

RULE_ID = re.compile(r"\b(?:MAGIC|EXC|DEF|SUPP|CPLX)\d{3}\b")
ADOPTION_HEADING = "## Adopting ShockHarness\n"
SKILLS_SOURCE = REPO_ROOT / "src" / "shockharness" / "skills"


def run(args: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = main(args)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def section(text: str, heading: str) -> str:
    """The text from ``heading`` to the next ``## `` heading (or the end), stripped."""
    start = text.index(heading)
    rest = text[start + len(heading) :]
    match = re.search(r"^## ", rest, flags=re.MULTILINE)
    if match is None:
        return rest.strip()
    return rest[: match.start()].strip()


# ----------------------------------------------------------------- shipped files


def test_four_skills_ship_with_valid_frontmatter() -> None:
    assert skill_names() == (
        "write-compliant-code",
        "fix-violations",
        "refactor-complexity",
        "pre-commit-review",
    )
    for name in SKILL_NAMES:
        text = skill_text(name)
        assert text.startswith("---\n"), name
        frontmatter = shipped_frontmatter(name)
        assert frontmatter.name == name, "name must match the directory"
        assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", frontmatter.name)
        assert len(frontmatter.name) <= 64
        assert 1 <= len(frontmatter.description) <= 1024
        assert "\n" not in frontmatter.description
        assert (SKILLS_SOURCE / name / "SKILL.md").read_bytes() == skill_bytes(name)
        assert text.count("\n") < 500, f"{name}: keep SKILL.md under 500 lines"


def test_parse_frontmatter_rejects_malformed_documents() -> None:
    assert parse_frontmatter("---\nname: a-b\ndescription: d\n---\nbody\n") == Frontmatter(
        "a-b", "d"
    )
    for bad in (
        "name: x\n",
        "---\nname: x\n",
        "---\nname: x\n---\n",
        "---\nname: x\ndescription: d\nname: y\n---\n",
        "---\nname x\ndescription: d\n---\n",
        "---\n name: x\ndescription: d\n---\n",
    ):
        with pytest.raises(ValueError):
            parse_frontmatter(bad)


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_skill_mentions_only_registered_rule_ids(name: str) -> None:
    mentioned = set(RULE_ID.findall(skill_text(name)))
    assert mentioned, name
    unknown = sorted(rule_id for rule_id in mentioned if not registry.is_known_rule(rule_id))
    assert unknown == [], f"{name} mentions unknown rule IDs: {unknown}"


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_skill_has_examples_commands_workflow_checklist_and_adoption(name: str) -> None:
    text = skill_text(name)
    assert "```python" in text and "```javascript" in text, name
    assert "shockharness check" in text, name
    assert "## Checklist" in text, name
    assert "- [ ]" in text, name
    assert ADOPTION_HEADING in text, name
    for line in text.splitlines():
        # No relative Markdown links: skills are read wherever they are installed.
        assert not re.search(r"\]\((?!https?://)[^)]*\)", line), f"{name}: {line}"


def test_refactor_complexity_does_not_claim_complexity_rules_exist() -> None:
    text = skill_text("refactor-complexity")
    assert "not implemented" in text
    assert "Milestone E" in text
    for rule in registry.RULES:
        if rule.family == "complexity":
            assert not rule.implemented
            assert rule.rule_id in text


def test_adoption_section_is_identical_in_readme_and_every_skill() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    expected = section(readme, ADOPTION_HEADING)
    assert "uv tool install" in expected and "uvx --from" in expected
    assert "shockharness init" in expected
    for path in (
        "baseline create",
        'profile = "minimal"',
        'new_hard_violations = "warn"',
        "--exit-zero",
    ):
        assert path in expected
    assert "check.yml@" in expected and "dependabot" in expected.lower()
    assert "skills install --agent claude" in expected
    assert "skills install --agent codex" in expected
    assert f"shockharness=={__version__}" in expected
    # Self-contained: no relative links, only absolute GitHub URLs.
    assert not re.search(r"\]\((?!https?://)[^)]*\)", expected)
    assert "https://github.com/evolvingstuff/ShockHarness/blob/main/docs/" in expected
    for name in SKILL_NAMES:
        assert section(skill_text(name), ADOPTION_HEADING) == expected, name


# ----------------------------------------------------------------- adapters


def test_adapter_table() -> None:
    assert AGENTS == ("claude", "codex", "generic")
    by_agent = {adapter.agent: adapter for adapter in ADAPTERS}
    assert by_agent["claude"].project_subdir == ".claude/skills"
    assert by_agent["claude"].user_subdir == ".claude/skills"
    assert by_agent["codex"].project_subdir == ".agents/skills"
    assert by_agent["codex"].user_subdir == ".agents/skills"
    assert by_agent["generic"].project_subdir is None
    assert by_agent["generic"].user_subdir is None
    for adapter in ADAPTERS:
        assert adapter.documentation.startswith("https://")
        assert "2026-10-14" in adapter.documentation
    with pytest.raises(UsageError, match="unknown agent"):
        get_adapter("copilot")


def test_resolve_destination(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "repo"
    assert resolve_destination(get_adapter("claude"), project, False, home) == (
        project / ".claude" / "skills"
    )
    assert resolve_destination(get_adapter("claude"), project, True, home) == (
        home / ".claude" / "skills"
    )
    assert resolve_destination(get_adapter("codex"), project, False, home) == (
        project / ".agents" / "skills"
    )
    assert resolve_destination(get_adapter("codex"), project, True, home) == (
        home / ".agents" / "skills"
    )
    assert resolve_destination(get_adapter("generic"), project / "skills", False, home) == (
        project / "skills"
    )
    with pytest.raises(UsageError, match="--user is not supported"):
        resolve_destination(get_adapter("generic"), project, True, home)


def test_pointer_line_names_every_skill() -> None:
    line = pointer_line(Path("docs/agent-skills"))
    assert "docs/agent-skills/<name>/SKILL.md" in line
    for name in SKILL_NAMES:
        assert name in line


# ----------------------------------------------------------------- install / update


def installed_paths(destination: Path) -> list[Path]:
    return [destination / name / "SKILL.md" for name in SKILL_NAMES]


def test_fresh_install_writes_skills_and_manifest(tmp_path: Path) -> None:
    destination = tmp_path / ".claude" / "skills"
    result = install_skills(destination, "claude", False)
    assert result.exit_code == 0
    assert [file.status for file in result.files] == ["written"] * len(SKILL_NAMES)
    for name in SKILL_NAMES:
        assert (destination / name / "SKILL.md").read_bytes() == skill_bytes(name)
    manifest = load_manifest(destination / MANIFEST_FILENAME)
    assert manifest.schema_version == "1"
    assert manifest.tool_version == __version__
    assert manifest.agent == "claude"
    assert set(manifest.skills) == set(SKILL_NAMES)
    for name, entry in manifest.skills.items():
        assert entry.path == f"{name}/SKILL.md"
        assert entry.sha256 == sha256_hex(skill_bytes(name))
    document = json.loads((destination / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert list(document) == ["agent", "schema_version", "skills", "tool_version"]
    # Nothing outside the destination was created.
    assert sorted(p.name for p in tmp_path.iterdir()) == [".claude"]
    assert sorted(p.name for p in (tmp_path / ".claude").iterdir()) == ["skills"]


def test_reinstall_refuses_without_force_and_writes_nothing(tmp_path: Path) -> None:
    destination = tmp_path / "skills"
    install_skills(destination, "generic", False)
    target = destination / "fix-violations" / "SKILL.md"
    target.write_text("mine", encoding="utf-8")
    before = {p: p.read_bytes() for p in destination.rglob("*") if p.is_file()}
    with pytest.raises(UsageError, match="--force"):
        install_skills(destination, "generic", False)
    assert {p: p.read_bytes() for p in destination.rglob("*") if p.is_file()} == before
    result = install_skills(destination, "generic", True)
    assert result.exit_code == 0
    assert target.read_bytes() == skill_bytes("fix-violations")


def test_install_refuses_when_only_one_file_exists(tmp_path: Path) -> None:
    destination = tmp_path / "skills"
    stray = destination / "pre-commit-review" / "SKILL.md"
    stray.parent.mkdir(parents=True)
    stray.write_text("hand-written", encoding="utf-8")
    with pytest.raises(UsageError, match="already exist"):
        install_skills(destination, "generic", False)
    assert stray.read_text(encoding="utf-8") == "hand-written"
    assert not (destination / MANIFEST_FILENAME).exists()


def test_update_without_manifest_or_with_other_agent_is_a_usage_error(tmp_path: Path) -> None:
    with pytest.raises(UsageError, match="skills install"):
        update_skills(tmp_path, "claude", False)
    install_skills(tmp_path, "codex", False)
    with pytest.raises(UsageError, match="written for --agent codex"):
        update_skills(tmp_path, "claude", False)


def test_update_on_a_fresh_install_is_a_no_op(tmp_path: Path) -> None:
    install_skills(tmp_path, "claude", False)
    manifest_before = (tmp_path / MANIFEST_FILENAME).read_bytes()
    result = update_skills(tmp_path, "claude", False)
    assert result.exit_code == 0
    assert {file.status for file in result.files} == {STATUS_UP_TO_DATE}
    assert (tmp_path / MANIFEST_FILENAME).read_bytes() == manifest_before
    check = update_skills(tmp_path, "claude", True)
    assert check.exit_code == 0


def test_update_preserves_edited_file_and_reports_conflict(tmp_path: Path) -> None:
    install_skills(tmp_path, "claude", False)
    edited = tmp_path / "fix-violations" / "SKILL.md"
    edited.write_text(skill_text("fix-violations") + "\n# my note\n", encoding="utf-8")
    old_hash = load_manifest(tmp_path / MANIFEST_FILENAME).skills["fix-violations"].sha256

    check = update_skills(tmp_path, "claude", True)
    assert check.exit_code == 1
    by_skill = {file.skill: file for file in check.files}
    assert by_skill["fix-violations"].status == STATUS_EDITED
    assert "skills show fix-violations" in by_skill["fix-violations"].detail
    assert edited.read_text(encoding="utf-8").endswith("# my note\n")

    result = update_skills(tmp_path, "claude", False)
    assert result.exit_code == 1
    assert edited.read_text(encoding="utf-8").endswith("# my note\n"), "edited file untouched"
    manifest = load_manifest(tmp_path / MANIFEST_FILENAME)
    assert manifest.skills["fix-violations"].sha256 == old_hash, "old generated hash kept"
    # Still a conflict next time: the edit is never silently adopted.
    assert update_skills(tmp_path, "claude", True).exit_code == 1


def test_update_detects_stale_file_and_rewrites_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_skills(tmp_path, "claude", False)
    # Simulate an older install: the file and the manifest agree on old content.
    old_content = b"---\nname: pre-commit-review\ndescription: old\n---\nold body\n"
    target = tmp_path / "pre-commit-review" / "SKILL.md"
    target.write_bytes(old_content)
    manifest_path = tmp_path / MANIFEST_FILENAME
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["skills"]["pre-commit-review"]["sha256"] = sha256_hex(old_content)
    document["tool_version"] = "0.0.1"
    manifest_path.write_text(json.dumps(document), encoding="utf-8")

    check = update_skills(tmp_path, "claude", True)
    assert check.exit_code == 1
    statuses = {file.skill: file.status for file in check.files}
    assert statuses["pre-commit-review"] == STATUS_STALE
    assert target.read_bytes() == old_content, "--check writes nothing"
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == document

    result = update_skills(tmp_path, "claude", False)
    assert result.exit_code == 0
    assert target.read_bytes() == skill_bytes("pre-commit-review")
    manifest = load_manifest(manifest_path)
    assert manifest.tool_version == __version__
    assert manifest.skills["pre-commit-review"].sha256 == sha256_hex(
        skill_bytes("pre-commit-review")
    )
    assert update_skills(tmp_path, "claude", True).exit_code == 0


def test_update_adds_new_skill_restores_missing_and_reports_removed(tmp_path: Path) -> None:
    install_skills(tmp_path, "codex", False)
    manifest_path = tmp_path / MANIFEST_FILENAME
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    # "write-compliant-code" was not known to the older install; "old-skill" was.
    del document["skills"]["write-compliant-code"]
    (tmp_path / "write-compliant-code" / "SKILL.md").unlink()
    document["skills"]["old-skill"] = {"path": "old-skill/SKILL.md", "sha256": "0" * 64}
    (tmp_path / "old-skill").mkdir()
    (tmp_path / "old-skill" / "SKILL.md").write_text("old", encoding="utf-8")
    manifest_path.write_text(json.dumps(document), encoding="utf-8")
    (tmp_path / "refactor-complexity" / "SKILL.md").unlink()

    check = update_skills(tmp_path, "codex", True)
    assert check.exit_code == 1
    statuses = {file.skill: file.status for file in check.files}
    assert statuses["write-compliant-code"] == STATUS_NEW
    assert statuses["refactor-complexity"] == STATUS_MISSING
    assert statuses["old-skill"] == STATUS_REMOVED
    assert not (tmp_path / "write-compliant-code" / "SKILL.md").exists()

    result = update_skills(tmp_path, "codex", False)
    assert result.exit_code == 0
    assert (tmp_path / "write-compliant-code" / "SKILL.md").read_bytes() == skill_bytes(
        "write-compliant-code"
    )
    assert (tmp_path / "refactor-complexity" / "SKILL.md").read_bytes() == skill_bytes(
        "refactor-complexity"
    )
    assert (tmp_path / "old-skill" / "SKILL.md").read_text(encoding="utf-8") == "old"
    manifest = load_manifest(manifest_path)
    assert set(manifest.skills) == set(SKILL_NAMES)
    assert update_skills(tmp_path, "codex", True).exit_code == 0


def test_update_treats_unrecorded_existing_file_as_edited(tmp_path: Path) -> None:
    install_skills(tmp_path, "claude", False)
    manifest_path = tmp_path / MANIFEST_FILENAME
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    del document["skills"]["fix-violations"]
    manifest_path.write_text(json.dumps(document), encoding="utf-8")
    (tmp_path / "fix-violations" / "SKILL.md").write_text("theirs", encoding="utf-8")
    result = update_skills(tmp_path, "claude", False)
    assert result.exit_code == 1
    assert {f.skill: f.status for f in result.files}["fix-violations"] == STATUS_EDITED
    assert (tmp_path / "fix-violations" / "SKILL.md").read_text(encoding="utf-8") == "theirs"


def test_manifest_validation() -> None:
    with pytest.raises(UsageError, match="not valid JSON"):
        parse_manifest("{", "m")
    with pytest.raises(UsageError, match="JSON object"):
        parse_manifest("[]", "m")
    with pytest.raises(UsageError, match="schema_version"):
        parse_manifest('{"agent": "claude"}', "m")
    with pytest.raises(UsageError, match="not supported"):
        parse_manifest(
            '{"schema_version": "9", "tool_version": "1", "agent": "claude", "skills": {}}', "m"
        )
    with pytest.raises(UsageError, match="'skills'"):
        parse_manifest('{"schema_version": "1", "tool_version": "1", "agent": "claude"}', "m")
    with pytest.raises(UsageError, match="sha256"):
        parse_manifest(
            '{"schema_version": "1", "tool_version": "1", "agent": "claude", '
            '"skills": {"x": {"path": "x/SKILL.md"}}}',
            "m",
        )


# ----------------------------------------------------------------- CLI


def test_cli_install_update_check_exit_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = tmp_path / "repo"
    project.mkdir()
    code, out, _ = run(
        ["skills", "install", "--agent", "claude", "--project", str(project)], capsys
    )
    assert code == 0
    assert "installed 4 skill(s) for claude" in out
    assert (project / ".claude" / "skills" / MANIFEST_FILENAME).is_file()
    code, _, err = run(
        ["skills", "install", "--agent", "claude", "--project", str(project)], capsys
    )
    assert code == 2 and "--force" in err
    code, out, _ = run(
        ["skills", "update", "--agent", "claude", "--project", str(project), "--check"], capsys
    )
    assert code == 0 and out.rstrip().endswith("4 skill(s) up to date")
    (project / ".claude" / "skills" / "fix-violations" / "SKILL.md").write_text(
        "x", encoding="utf-8"
    )
    code, out, _ = run(
        ["skills", "update", "--agent", "claude", "--project", str(project), "--check"], capsys
    )
    assert code == 1 and "edited" in out and "drifted" in out
    code, out, _ = run(["skills", "update", "--agent", "claude", "--project", str(project)], capsys)
    assert code == 1 and "conflict" in out
    code, _, _ = run(
        ["skills", "install", "--agent", "claude", "--project", str(project), "--force"], capsys
    )
    assert code == 0
    code, out, _ = run(["skills", "update", "--agent", "claude", "--project", str(project)], capsys)
    assert code == 0 and out.rstrip().endswith("4 skill(s) up to date")


def test_cli_codex_destination_and_user_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "repo"
    project.mkdir()
    code, _, _ = run(["skills", "install", "--agent", "codex", "--project", str(project)], capsys)
    assert code == 0
    assert (project / ".agents" / "skills" / "write-compliant-code" / "SKILL.md").is_file()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    code, _, _ = run(["skills", "install", "--agent", "codex", "--user"], capsys)
    assert code == 0
    assert (home / ".agents" / "skills" / MANIFEST_FILENAME).is_file()
    code, _, _ = run(["skills", "update", "--agent", "codex", "--user", "--check"], capsys)
    assert code == 0
    with pytest.raises(SystemExit) as info:
        main(["skills", "install", "--agent", "codex", "--user", "--project", str(project)])
    assert info.value.code == 2, "--project and --user are mutually exclusive"


def test_cli_generic_requires_project_and_prints_pointer(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, err = run(["skills", "install", "--agent", "generic"], capsys)
    assert code == 2 and "--project" in err
    code, _, err = run(["skills", "install", "--agent", "generic", "--user"], capsys)
    assert code == 2 and "--user is not supported" in err
    target = tmp_path / "docs" / "agent-skills"
    code, out, _ = run(
        ["skills", "install", "--agent", "generic", "--project", str(target)], capsys
    )
    assert code == 0
    assert "AGENTS.md" in out and pointer_line(target) in out
    assert (target / "pre-commit-review" / "SKILL.md").is_file()
    code, _, err = run(["skills", "update", "--agent", "generic", "--check"], capsys)
    assert code == 2
    code, _, _ = run(
        ["skills", "update", "--agent", "generic", "--project", str(target), "--check"], capsys
    )
    assert code == 0


def test_cli_list_and_show(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(["skills", "list"], capsys)
    assert code == 0
    for name in SKILL_NAMES:
        assert name in out
        assert shipped_frontmatter(name).description in out
    code, out, _ = run(["skills", "show", "fix-violations"], capsys)
    assert code == 0 and out == skill_text("fix-violations")
    with pytest.raises(SystemExit) as info:
        main(["skills", "show", "nope"])
    assert info.value.code == 2
    with pytest.raises(SystemExit) as info:
        main(["skills", "install", "--agent", "copilot"])
    assert info.value.code == 2


def test_cli_corrupt_manifest_is_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    install_skills(tmp_path, "generic", False)
    (tmp_path / MANIFEST_FILENAME).write_text("{not json", encoding="utf-8")
    code, _, err = run(
        ["skills", "update", "--agent", "generic", "--project", str(tmp_path)], capsys
    )
    assert code == 2 and "not valid JSON" in err


# ----------------------------------------------------------------- packaging


@pytest.mark.slow
def test_wheel_contains_every_skill(tmp_path: Path) -> None:
    pytest.importorskip("build")
    completed = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(tmp_path), str(REPO_ROOT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    wheels = list(tmp_path.glob("shockharness-*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as wheel:
        names = set(wheel.namelist())
        for name in SKILL_NAMES:
            member = f"shockharness/skills/{name}/SKILL.md"
            assert member in names, member
            assert wheel.read(member) == skill_bytes(name)
        assert "shockharness/skills/__init__.py" in names
        assert "shockharness/skills/adapters.py" in names
        assert "shockharness/skills/install.py" in names
