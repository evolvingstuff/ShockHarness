"""Whether a project's installed skills are behind the installed ShockHarness.

``check`` and the edit-time hook print one line when a project holds a skills manifest
(written by ``skills install`` for an agent whose skills live at a known place in the
project: Claude Code's ``.claude/skills``, Codex's ``.agents/skills``) and ``skills
update`` would change something: a skill file the package now ships newer (stale), a skill
it ships that the manifest lacks (new), or one missing on disk. The agents working in the
repository then learn that the update is due without anyone reading release notes. Edited
files are left out (``update`` does not change them), and so is a ``generic`` install,
whose directory only its user knows.
"""

from dataclasses import dataclass
from pathlib import Path

from shockharness.errors import UsageError
from shockharness.skills.adapters import ADAPTERS
from shockharness.skills.install import (
    MANIFEST_FILENAME,
    STATUS_MISSING,
    STATUS_NEW,
    STATUS_STALE,
    classify_skills,
    load_manifest,
    shipped_contents,
)
from shockharness.version import __version__

# What ``skills update`` would fix, and how the notice names each.
FIXED_BY_UPDATE = ((STATUS_STALE, "out of date"), (STATUS_NEW, "new"), (STATUS_MISSING, "missing"))


@dataclass(frozen=True)
class SkillsDrift:
    """One installed set of skills that ``skills update`` would change. ``key`` is what
    the edit-time hook remembers so that it tells the agent once per upgrade."""

    agent: str
    notice: str
    key: str


def _command(agent: str) -> str:
    return f"shockharness skills update --agent {agent}"


def _statuses(destination: Path) -> tuple[str, list[str]]:
    """(the version the skills were installed with, each skill's status)."""
    manifest = load_manifest(destination / MANIFEST_FILENAME)
    rows = classify_skills(manifest, shipped_contents(), destination)
    return manifest.tool_version, [status for _name, _path, status, _detail in rows]


def _drift(agent: str, destination: Path) -> SkillsDrift | None:
    manifest_path = destination / MANIFEST_FILENAME
    # Boundary (declared in .shockharness.toml): the manifest and the installed files are
    # external input; a damaged manifest becomes the notice, never a failed check.
    try:
        installed_with, statuses = _statuses(destination)
    except UsageError as error:
        notice = (
            f"skills: the {agent} skills manifest {manifest_path} cannot be read ({error}); "
            f"run: shockharness skills install --agent {agent} --force"
        )
        return SkillsDrift(agent, notice, f"{agent}:unreadable:{__version__}")
    counts = [(statuses.count(status), label) for status, label in FIXED_BY_UPDATE]
    parts = [f"{count} {label}" for count, label in counts if count > 0]
    if len(parts) == 0:
        return None
    notice = (
        f"skills: {', '.join(parts)} since they were installed with ShockHarness "
        f"{installed_with} ({__version__} is installed); run: {_command(agent)}"
    )
    return SkillsDrift(agent, notice, f"{agent}:{installed_with}:{__version__}")


def skills_drift(project: Path) -> list[SkillsDrift]:
    """The installed skill sets of ``project`` that ``skills update`` would change."""
    found: list[SkillsDrift] = []
    for adapter in ADAPTERS:
        if adapter.project_subdir is None:
            continue
        destination = project / adapter.project_subdir
        if not (destination / MANIFEST_FILENAME).is_file():
            continue
        drift = _drift(adapter.agent, destination)
        if drift is not None:
            found.append(drift)
    return found
