"""The notice check and the hook give when installed skills are behind the package."""

import json
from pathlib import Path

import pytest

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions
from shockharness.cli import main
from shockharness.config import EffectiveConfig
from shockharness.hook import run_post_edit
from shockharness.skills import SKILL_NAMES, skill_relative_path
from shockharness.skills.freshness import skills_drift
from shockharness.skills.install import MANIFEST_FILENAME, install_skills, sha256_hex
from shockharness.version import __version__

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)
OLD_VERSION = "0.1.0"
OLD_TEXT = b"---\nname: old\ndescription: an older version of the skill\n---\n"
COMMAND = "run: shockharness skills update --agent claude"


def installed(project: Path) -> Path:
    destination = project / ".claude" / "skills"
    install_skills(destination, "claude", force=False)
    return destination


def age(destination: Path, *, stale: list[str], drop: list[str], delete: list[str]) -> None:
    """Make the install look older: files written by an earlier version (stale), skills it
    did not ship (new), files gone from disk (missing)."""
    manifest_path = destination / MANIFEST_FILENAME
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["tool_version"] = OLD_VERSION
    for name in stale:
        (destination / skill_relative_path(name)).write_bytes(OLD_TEXT)
        document["skills"][name]["sha256"] = sha256_hex(OLD_TEXT)
    for name in drop:
        del document["skills"][name]
        (destination / skill_relative_path(name)).unlink()
    for name in delete:
        (destination / skill_relative_path(name)).unlink()
    manifest_path.write_text(json.dumps(document), encoding="utf-8")


def test_a_fresh_install_and_no_install_say_nothing(tmp_path: Path) -> None:
    assert skills_drift(tmp_path) == []
    installed(tmp_path)
    assert skills_drift(tmp_path) == []


def test_skills_behind_the_package_are_counted_with_the_command(tmp_path: Path) -> None:
    destination = installed(tmp_path)
    age(destination, stale=list(SKILL_NAMES[:2]), drop=[SKILL_NAMES[2]], delete=[SKILL_NAMES[3]])
    (drift,) = skills_drift(tmp_path)
    assert drift.notice == (
        f"skills: 2 out of date, 1 new, 1 missing since they were installed with ShockHarness "
        f"{OLD_VERSION} ({__version__} is installed); {COMMAND}"
    )


def test_edited_skills_alone_are_left_to_their_owner(tmp_path: Path) -> None:
    destination = installed(tmp_path)
    (destination / skill_relative_path(SKILL_NAMES[0])).write_text("my notes\n", encoding="utf-8")
    assert skills_drift(tmp_path) == []


def test_a_damaged_manifest_asks_for_a_reinstall(tmp_path: Path) -> None:
    destination = installed(tmp_path)
    (destination / MANIFEST_FILENAME).write_text("{", encoding="utf-8")
    (drift,) = skills_drift(tmp_path)
    assert "cannot be read" in drift.notice
    assert drift.notice.endswith("run: shockharness skills install --agent claude --force")


def test_check_prints_the_notice_beside_the_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    age(installed(tmp_path), stale=[SKILL_NAMES[0]], drop=[], delete=[])
    (tmp_path / "a.py").write_text("x = 0\n", encoding="utf-8")
    main(["check", str(tmp_path), "--root", str(tmp_path), "--format", "json"])
    captured = capsys.readouterr()
    json.loads(captured.out)  # the report itself stays valid JSON
    assert f"skills: 1 out of date since they were installed with ShockHarness {OLD_VERSION}" in (
        captured.err
    )


def test_the_hook_tells_the_agent_once_per_upgrade(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    age(installed(empty_root), stale=[SKILL_NAMES[0]], drop=[], delete=[])
    edited = empty_root / "a.py"
    edited.write_text("x = 0\n", encoding="utf-8")
    event = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(edited)}})
    first = run_post_edit(event, empty_root, strict_config, OPTIONS, "warning")
    assert first.exit_code == 2
    assert first.message.startswith("shockharness: skills: 1 out of date")
    assert first.message.rstrip().endswith(COMMAND)
    again = run_post_edit(event, empty_root, strict_config, OPTIONS, "warning")
    assert (again.exit_code, again.message) == (0, "")
