"""``skills install`` and ``skills update``: writing skills and tracking them in a manifest.

The manifest, ``.shockharness-skills.json`` in the destination directory, records the
agent, the package version that wrote the files and a SHA-256 per written file. It
lets ``update`` tell a file the tool generated (hash equals the manifest) from one the
user edited (hash differs): generated files are rewritten when the package ships a
newer version, edited files are never touched and are reported as conflicts.

Skills and the manifest are written only into the destination directory; the edit hook
into the project's ``.claude/settings.json``, and the ``--lock`` policy file into
``~/.config/shockharness/locks/`` (``skills/lock.py``).
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shockharness.constants import (
    HOOK_TIMEOUT_SECONDS,
    EXIT_OK,
    EXIT_VIOLATIONS,
    JSON_INDENT,
    SKILLS_MANIFEST_SCHEMA_VERSION,
)
from shockharness.errors import UsageError
from shockharness.skills import SKILL_NAMES, skill_bytes, skill_relative_path
from shockharness.version import __version__

MANIFEST_FILENAME = ".shockharness-skills.json"

# File statuses reported by install and update.
STATUS_WRITTEN = "written"  # install: file created (or replaced under --force)
STATUS_UP_TO_DATE = "up-to-date"  # file equals the manifest hash and the package content
STATUS_STALE = "stale"  # file equals the manifest hash; the package ships newer content
STATUS_EDITED = "edited"  # file differs from the manifest hash: the user changed it
STATUS_MISSING = "missing"  # file is in the manifest but absent on disk
STATUS_NEW = "new"  # skill is shipped but not in the manifest
STATUS_REMOVED = "removed"  # skill is in the manifest but no longer shipped

# What update did (or, under --check, would do) about a status.
ACTION_NONE = "left unchanged"
ACTION_REWRITTEN = "rewritten from the package"
ACTION_RESTORED = "restored from the package"
ACTION_ADDED = "added from the package"
ACTION_CONFLICT = "left unchanged: conflict"
ACTION_REPORTED = "reported; the file is not deleted"
# Statuses that mean the destination no longer matches the installed package.
DRIFT_STATUSES = (STATUS_STALE, STATUS_EDITED, STATUS_MISSING, STATUS_NEW, STATUS_REMOVED)


@dataclass(frozen=True)
class ManifestEntry:
    path: str  # relative to the destination, forward slashes
    sha256: str


@dataclass(frozen=True)
class Manifest:
    schema_version: str
    tool_version: str
    agent: str
    skills: dict[str, ManifestEntry]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "tool_version": self.tool_version,
            "agent": self.agent,
            "skills": {
                name: {"path": entry.path, "sha256": entry.sha256}
                for name, entry in sorted(self.skills.items())
            },
        }


@dataclass(frozen=True)
class FileReport:
    skill: str
    path: Path
    status: str
    action: str
    detail: str


@dataclass(frozen=True)
class SkillsResult:
    destination: Path
    manifest_path: Path
    files: tuple[FileReport, ...]
    exit_code: int

    def count(self, status: str) -> int:
        return sum(1 for file in self.files if file.status == status)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def shipped_contents() -> dict[str, bytes]:
    return {name: skill_bytes(name) for name in SKILL_NAMES}


def build_manifest(agent: str, written: dict[str, bytes]) -> Manifest:
    return Manifest(
        schema_version=SKILLS_MANIFEST_SCHEMA_VERSION,
        tool_version=__version__,
        agent=agent,
        skills={
            name: ManifestEntry(path=skill_relative_path(name), sha256=sha256_hex(data))
            for name, data in written.items()
        },
    )


def render_manifest(manifest: Manifest) -> str:
    return json.dumps(manifest.to_json_dict(), indent=JSON_INDENT, sort_keys=True) + "\n"


def read_bytes(path: Path) -> bytes:
    # Boundary (declared in .shockharness.toml): reading a file in the user's destination.
    try:
        return path.read_bytes()
    except OSError as exc:
        raise UsageError(f"cannot read: {exc}", str(path)) from exc


def _create_parent_and_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def write_bytes(path: Path, data: bytes) -> None:
    # Boundary (declared in .shockharness.toml): writing into the user's destination.
    try:
        _create_parent_and_write(path, data)
    except OSError as exc:
        raise UsageError(f"cannot write: {exc}", str(path)) from exc


def _string_field(document: dict[str, Any], key: str, origin: str) -> str:
    if key not in document or not isinstance(document[key], str):
        raise UsageError(f"skills manifest is missing the string field {key!r}", origin)
    return document[key]


def parse_manifest(text: str, origin: str) -> Manifest:
    # Boundary (declared in .shockharness.toml): manifest content is external input.
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise UsageError(f"skills manifest is not valid JSON: {exc}", origin) from exc
    if not isinstance(document, dict):
        raise UsageError("skills manifest must be a JSON object", origin)
    schema_version = _string_field(document, "schema_version", origin)
    if schema_version != SKILLS_MANIFEST_SCHEMA_VERSION:
        raise UsageError(
            f"skills manifest schema version {schema_version!r} is not supported "
            f"(expected {SKILLS_MANIFEST_SCHEMA_VERSION!r})",
            origin,
        )
    tool_version = _string_field(document, "tool_version", origin)
    agent = _string_field(document, "agent", origin)
    if "skills" not in document or not isinstance(document["skills"], dict):
        raise UsageError("skills manifest is missing the object field 'skills'", origin)
    skills: dict[str, ManifestEntry] = {}
    for name, raw in document["skills"].items():
        where = f"{origin} (skill {name!r})"
        if not isinstance(raw, dict):
            raise UsageError("skills manifest entry must be a JSON object", where)
        skills[name] = ManifestEntry(
            path=_string_field(raw, "path", where), sha256=_string_field(raw, "sha256", where)
        )
    return Manifest(
        schema_version=schema_version, tool_version=tool_version, agent=agent, skills=skills
    )


def load_manifest(path: Path) -> Manifest:
    data = read_bytes(path)
    # Boundary (declared in .shockharness.toml): manifest bytes are external input.
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UsageError(f"skills manifest is not UTF-8: {exc}", str(path)) from exc
    return parse_manifest(text, str(path))


def install_skills(destination: Path, agent: str, force: bool) -> SkillsResult:
    """Write every shipped skill and the manifest into ``destination``.

    Refuses, writing nothing, when any target file exists and ``force`` is false.
    """
    contents = shipped_contents()
    manifest_path = destination / MANIFEST_FILENAME
    targets = {name: destination / skill_relative_path(name) for name in contents}
    existing = [path for path in [*targets.values(), manifest_path] if path.exists()]
    if len(existing) > 0 and not force:
        listed = ", ".join(str(path) for path in existing)
        raise UsageError(
            "skill files already exist and would be overwritten; pass --force to replace "
            "them, or run `skills update` to refresh unedited files and keep edited ones: "
            + listed,
            str(destination),
        )
    files: list[FileReport] = []
    for name, data in contents.items():
        write_bytes(targets[name], data)
        files.append(FileReport(name, targets[name], STATUS_WRITTEN, STATUS_WRITTEN, ""))
    write_bytes(manifest_path, render_manifest(build_manifest(agent, contents)).encode("utf-8"))
    return SkillsResult(destination, manifest_path, tuple(files), EXIT_OK)


def conflict_remediation(agent: str, name: str) -> str:
    return (
        "the file is yours, so it is left unchanged. To take the shipped "
        f"version: save your edits, delete the file, run `shockharness skills update "
        f"--agent {agent}` (the file is restored), then re-apply your edits. To read the "
        f"shipped version: `shockharness skills show {name}`."
    )


def _classify(
    manifest: Manifest, contents: dict[str, bytes], destination: Path
) -> list[tuple[str, Path, str, str]]:
    """(skill, path, status, detail) for every shipped and every recorded skill."""
    rows: list[tuple[str, Path, str, str]] = []
    for name, data in contents.items():
        path = destination / skill_relative_path(name)
        if name not in manifest.skills:
            if path.is_file():
                rows.append(
                    (name, path, STATUS_EDITED, "exists on disk but is not in the manifest")
                )
            else:
                rows.append((name, path, STATUS_NEW, "shipped by the package, not in the manifest"))
            continue
        recorded = manifest.skills[name].sha256
        shipped = sha256_hex(data)
        if not path.is_file():
            rows.append((name, path, STATUS_MISSING, "in the manifest but absent on disk"))
            continue
        current = sha256_hex(read_bytes(path))
        if current != recorded:
            rows.append((name, path, STATUS_EDITED, "content differs from the manifest hash"))
        elif shipped != recorded:
            rows.append(
                (
                    name,
                    path,
                    STATUS_STALE,
                    f"unchanged since install with {manifest.tool_version}; "
                    f"the package ({__version__}) ships a newer version",
                )
            )
        else:
            rows.append((name, path, STATUS_UP_TO_DATE, ""))
    for name, entry in manifest.skills.items():
        if name not in contents:
            rows.append(
                (
                    name,
                    destination / entry.path,
                    STATUS_REMOVED,
                    f"in the manifest but no longer shipped by {__version__}",
                )
            )
    return rows


def update_skills(destination: Path, agent: str, check: bool) -> SkillsResult:
    """Refresh generated files, keep edited ones, report everything; ``check`` writes nothing.

    Exit code: under ``check``, 1 when any skill drifted (stale, edited, missing, new or
    removed), else 0. Otherwise 1 when an edited file blocked its update (a conflict),
    else 0.
    """
    manifest_path = destination / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise UsageError(
            "no skills manifest here; run `shockharness skills install --agent "
            f"{agent}` first (a manifest {MANIFEST_FILENAME} is written next to the skills)",
            str(destination),
        )
    manifest = load_manifest(manifest_path)
    if manifest.agent != agent:
        raise UsageError(
            f"the manifest was written for --agent {manifest.agent}, not {agent}",
            str(manifest_path),
        )
    contents = shipped_contents()
    files: list[FileReport] = []
    written: dict[str, bytes] = {}
    for name, path, status, detail in _classify(manifest, contents, destination):
        action = ACTION_NONE
        if status == STATUS_EDITED:
            action = ACTION_CONFLICT
            detail = f"{detail}; {conflict_remediation(agent, name)}"
        elif status == STATUS_REMOVED:
            action = ACTION_REPORTED
            detail = detail + "; delete it if you no longer want it"
        elif status == STATUS_STALE:
            action = ACTION_REWRITTEN
        elif status == STATUS_MISSING:
            action = ACTION_RESTORED
        elif status == STATUS_NEW:
            action = ACTION_ADDED
        if status in (STATUS_STALE, STATUS_MISSING, STATUS_NEW) and not check:
            write_bytes(path, contents[name])
            written[name] = contents[name]
        if check and action not in (ACTION_NONE, ACTION_CONFLICT, ACTION_REPORTED):
            action = f"would be {action}"
        files.append(FileReport(name, path, status, action, detail))

    if check:
        drifted = sum(1 for file in files if file.status in DRIFT_STATUSES)
        exit_code = EXIT_OK if drifted == 0 else EXIT_VIOLATIONS
        return SkillsResult(destination, manifest_path, tuple(files), exit_code)

    # The new manifest: written files carry their new hash; edited and up-to-date files
    # keep the hash of the content the tool last generated; removed skills are dropped.
    entries: dict[str, ManifestEntry] = {}
    for name in contents:
        if name in written:
            entries[name] = ManifestEntry(skill_relative_path(name), sha256_hex(written[name]))
        elif name in manifest.skills:
            entries[name] = ManifestEntry(skill_relative_path(name), manifest.skills[name].sha256)
    new_manifest = Manifest(
        schema_version=SKILLS_MANIFEST_SCHEMA_VERSION,
        tool_version=__version__,
        agent=agent,
        skills=entries,
    )
    write_bytes(manifest_path, render_manifest(new_manifest).encode("utf-8"))
    conflicts = sum(1 for file in files if file.status == STATUS_EDITED)
    exit_code = EXIT_OK if conflicts == 0 else EXIT_VIOLATIONS
    return SkillsResult(destination, manifest_path, tuple(files), exit_code)


# --- The edit-time hook (Claude Code) ------------------------------------------------------

CLAUDE_SETTINGS = Path(".claude") / "settings.json"
HOOKS_KEY = "hooks"
POST_TOOL_USE = "PostToolUse"
# Bash too: agents often write files through the shell, which no Edit/Write hook sees;
# for those calls the hook checks the files git shows as changed.
EDIT_TOOLS = "Edit|Write|MultiEdit|Bash"
MATCHER_KEY = "matcher"
HOOK_UPDATED = "matcher updated"
HOOK_COMMAND = 'shockharness hook claude-code post-edit --root "$CLAUDE_PROJECT_DIR"'
COMMAND_KEY = "command"
JSON_KINDS = {dict: "object", list: "array"}
HOOK_ADDED = "added"
HOOK_PRESENT = "already present"
HOOK_COMMAND_UPDATED = "command updated"
POLICY_FLAG = "--policy"


def hook_command(lock: Path | None) -> str:
    """The hook's command; with a lock file (``--lock``) it runs under that policy."""
    if lock is None:
        return HOOK_COMMAND
    return f'{HOOK_COMMAND} {POLICY_FLAG} "{lock}"'


def _settings_document(path: Path) -> dict[str, Any]:
    """The project's Claude Code settings, or an empty object when there are none."""
    if not path.exists():
        return {}
    data = read_bytes(path)
    # Boundary (declared in .shockharness.toml): the settings file is external input.
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UsageError(f"Claude Code settings are not UTF-8: {exc}", str(path)) from exc
    # Boundary (declared in .shockharness.toml): the settings file is external input.
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise UsageError(f"Claude Code settings are not valid JSON: {exc}", str(path)) from exc
    if not isinstance(document, dict):
        raise UsageError("Claude Code settings must be a JSON object", str(path))
    return document


def _runs_shockharness(handler: Any) -> bool:
    return (
        isinstance(handler, dict)
        and COMMAND_KEY in handler
        and isinstance(handler[COMMAND_KEY], str)
        and handler[COMMAND_KEY].startswith(HOOK_COMMAND)
    )


def _hook_group(groups: list[Any]) -> dict[str, Any] | None:
    """The PostToolUse group that already runs the hook, if any."""
    for group in groups:
        if not isinstance(group, dict) or HOOKS_KEY not in group:
            continue
        if isinstance(group[HOOKS_KEY], list) and any(
            _runs_shockharness(handler) for handler in group[HOOKS_KEY]
        ):
            return group
    return None


def _member(document: dict[str, Any], key: str, empty: Any, path: Path) -> Any:
    """``document[key]``, created empty when the settings have none yet: a project
    without hooks is a valid state, and the hook is added to it."""
    if key not in document:
        document[key] = empty
    value = document[key]
    if not isinstance(value, type(empty)):
        raise UsageError(
            f"Claude Code settings: {key!r} must be a JSON {JSON_KINDS[type(empty)]}", str(path)
        )
    return value


def _update_group(group: dict[str, Any], command: str) -> str | None:
    """Bring an installed hook group to the current matcher and ``command``; the status,
    or None when it already matches."""
    status = None
    if MATCHER_KEY not in group or group[MATCHER_KEY] != EDIT_TOOLS:
        group[MATCHER_KEY] = EDIT_TOOLS
        status = HOOK_UPDATED
    for handler in group[HOOKS_KEY]:
        if _runs_shockharness(handler) and handler[COMMAND_KEY] != command:
            handler[COMMAND_KEY] = command
            if status is None:
                status = HOOK_COMMAND_UPDATED
    return status


def install_claude_hook(project_root: Path, command: str) -> tuple[Path, str]:
    """Add the post-edit hook running ``command`` to ``.claude/settings.json``: appended
    to any PostToolUse hooks already configured, never replacing them, and only once. A
    hook installed earlier gets the current matcher (Bash included) and ``command`` (with
    or without a lock)."""
    path = project_root / CLAUDE_SETTINGS
    document = _settings_document(path)
    hooks = _member(document, HOOKS_KEY, {}, path)
    groups = _member(hooks, POST_TOOL_USE, [], path)
    existing = _hook_group(groups)
    if existing is None:
        handler = {"type": "command", COMMAND_KEY: command, "timeout": HOOK_TIMEOUT_SECONDS}
        groups.append({MATCHER_KEY: EDIT_TOOLS, HOOKS_KEY: [handler]})
        status = HOOK_ADDED
    else:
        updated = _update_group(existing, command)
        if updated is None:
            return path, HOOK_PRESENT
        status = updated
    text = json.dumps(document, indent=JSON_INDENT) + "\n"
    write_bytes(path, text.encode("utf-8"))
    return path, status


def write_lock(path: Path, text: str) -> None:
    """Write the ``--lock`` policy file (its directory is created)."""
    write_bytes(path, text.encode("utf-8"))
