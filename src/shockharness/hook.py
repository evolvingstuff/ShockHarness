"""Edit-time feedback for coding agents: ``shockharness hook claude-code post-edit``.

A Claude Code ``PostToolUse`` hook (matcher ``Edit|Write|MultiEdit``) pipes the tool call
as JSON on stdin; the edited file is ``tool_input.file_path``. The file is analyzed under
the project's configuration (with the cache, so a hook run costs one file), and its
findings at or above ``--fail-on`` are written to stderr with exit 2, which Claude Code
shows to the agent while the edit is still in its context. A clean file, a file outside
the project, a file that is not source (``pyproject.toml``, ``README.md``) or one the
configuration does not include exits 0 and prints nothing.

Only the edited file is analyzed: the cross-file rules see that file alone, so the gate
(``check`` or ``gate`` in CI) stays the authority.
"""

import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shockharness.analysis import AnalysisOptions
from shockharness.api import analyze_paths
from shockharness.cache.store import cache_settings
from shockharness.config import SUPPORTED_EXTENSIONS, EffectiveConfig
from shockharness.constants import HOOK_FEEDBACK
from shockharness.findings import Finding
from shockharness.history.git import locate_repository, run_git_text
from shockharness.hook_state import HookStore
from shockharness.output.text import finding_lines

AGENT_CLAUDE_CODE = "claude-code"
HOOK_AGENTS = (AGENT_CLAUDE_CODE,)
EVENT_POST_EDIT = "post-edit"
HOOK_EVENTS = (EVENT_POST_EDIT,)
TOOL_INPUT = "tool_input"
TOOL_NAME = "tool_name"
FILE_PATH = "file_path"
# Tools whose input names the file they changed; every other tool (Bash) may change any
# file, so the files git shows as changed are checked instead.
EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit"})
GIT_STATUS = ("status", "--porcelain=v1", "-z", "--no-renames", "--untracked-files=all")
GIT_NUL = "\0"
# A porcelain v1 entry is "XY PATH": two status letters, a space, the path.
GIT_STATUS_WIDTH = len("XY")
GIT_DELETED = "D"
# Claude Code's hook protocol: 0 lets the agent go on, HOOK_FEEDBACK (2) feeds stderr
# back to it, any other code is a notice to the user that the agent does not act on.
HOOK_CLEAN = 0
HOOK_NOTICE = 1
# --fail-on: the severities that are fed back, from the most severe.
SEVERITY_ORDER = ("error", "warning", "review")


@dataclass(frozen=True)
class HookResult:
    exit_code: int
    message: str


@dataclass(frozen=True)
class HookEvent:
    """The hook's stdin: the parsed JSON, or why it is not JSON."""

    value: Any
    problem: str


def parse_event(event_text: str) -> HookEvent:
    try:
        value = json.loads(event_text)
    except json.JSONDecodeError as error:
        return HookEvent(None, f"shockharness hook: the hook input is not JSON ({error.msg})")
    return HookEvent(value, "")


def edited_path(event: Any) -> str | None:
    """The file a Claude Code Edit / Write / MultiEdit call changed; None for a tool call
    without one."""
    if not isinstance(event, Mapping) or TOOL_INPUT not in event:
        return None
    tool_input = event[TOOL_INPUT]
    if not isinstance(tool_input, Mapping) or FILE_PATH not in tool_input:
        return None
    path = tool_input[FILE_PATH]
    if not isinstance(path, str) or path == "":
        return None
    return path


def _within(path: Path, root: Path) -> Path | None:
    """``path`` relative to ``root``, or None when it lies outside."""
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        return None
    return resolved.relative_to(root.resolve())


def _fed_back(findings: Sequence[Finding], fail_on: str) -> list[Finding]:
    severities = SEVERITY_ORDER[: SEVERITY_ORDER.index(fail_on) + 1]
    return [f for f in findings if f.severity in severities and f.suppression is None]


def _message(relative: str, findings: Sequence[Finding]) -> str:
    lines = [
        f"shockharness: {len(findings)} finding(s) in {relative} after this edit; "
        "fix them now, the intended way (the skills say how); do not suppress, skip or "
        "loosen the configuration to get past them:"
    ]
    lines.extend(finding_lines(findings))
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class Candidates:
    """The source files a tool call may have changed (relative to the root), and why
    there are none when there are none."""

    files: tuple[str, ...]
    note: str


def _source(path: Path, root: Path) -> str | None:
    relative = _within(path, root)
    if relative is None or relative.suffix not in SUPPORTED_EXTENSIONS:
        return None  # outside the project, or not a source file
    return relative.as_posix()


def _edited_files(event: Any, root: Path) -> Candidates:
    path = edited_path(event)
    if path is None:
        return Candidates((), "the edit names no file")
    relative = _source(Path(path), root)
    if relative is None:
        return Candidates((), "not a source file of the project")
    return Candidates((relative,), "")


def _status_paths(text: str) -> list[str]:
    """Paths of ``git status --porcelain=v1 -z --no-renames`` entries not deleted."""
    found: list[str] = []
    for entry in text.split(GIT_NUL):
        status, path = entry[:GIT_STATUS_WIDTH], entry[GIT_STATUS_WIDTH + 1 :]
        if path != "" and GIT_DELETED not in status:
            found.append(path)
    return found


def _shell_files(root: Path) -> Candidates:
    """Files a shell command may have changed: the source files git shows as modified,
    added or untracked. Without git, shell edits cannot be seen."""
    location, error = locate_repository(root)
    if location is None:
        return Candidates((), f"shell edits are not checked: {error}")
    text, error = run_git_text(root, [*GIT_STATUS, "--", "."])
    if text is None:
        return Candidates((), f"shell edits are not checked: {error}")
    sources = [_source(location.toplevel / path, root) for path in _status_paths(text)]
    return Candidates(tuple(sorted({s for s in sources if s is not None})), "")


def _candidates(event: Any, root: Path) -> Candidates:
    tool = ""
    if isinstance(event, Mapping) and TOOL_NAME in event:
        tool = str(event[TOOL_NAME])
    if tool in EDIT_TOOLS:
        return _edited_files(event, root)
    return _shell_files(root)


def _changed(
    root: Path, files: Sequence[str], state: Mapping[str, str], store: HookStore
) -> dict[str, str]:
    """The files whose content differs from what the hook last analyzed, with their hash."""
    hashes = {name: store.content_hash(root / name) for name in files}
    return {
        name: digest
        for name, digest in hashes.items()
        if digest is not None and (name not in state or state[name] != digest)
    }


def _feedback(
    root: Path,
    files: Sequence[str],
    config: EffectiveConfig,
    options: AnalysisOptions,
    fail_on: str,
) -> tuple[str, int]:
    """The message for the files' findings at ``fail_on`` or worse, and their count."""
    report = analyze_paths([root / name for name in files], root, config, options)
    parts: list[str] = []
    count = 0
    for name in files:
        shown = _fed_back([f for f in report.findings if f.path == name], fail_on)
        if len(shown) > 0:
            parts.append(_message(name, shown))
            count += len(shown)
    return "".join(parts), count


def run_post_edit(
    event_text: str,
    root: Path,
    config: EffectiveConfig,
    options: AnalysisOptions,
    fail_on: str,
) -> HookResult:
    event = parse_event(event_text)
    store = HookStore(root / str(cache_settings(config)["directory"]))
    if event.problem != "":
        # Malformed input is a notice to the user, not feedback: the agent did nothing wrong.
        record = {"tool": "", "files": [], "findings": 0, "exit": HOOK_NOTICE}
        store.log_run({**record, "note": event.problem})
        return HookResult(HOOK_NOTICE, event.problem + "\n")
    tool = ""
    if isinstance(event.value, Mapping) and TOOL_NAME in event.value:
        tool = str(event.value[TOOL_NAME])
    candidates = _candidates(event.value, root)
    state = store.load_state()
    changed = _changed(root, candidates.files, state, store)
    message, count = "", 0
    if len(changed) > 0:
        message, count = _feedback(root, sorted(changed), config, options, fail_on)
        store.save_state({**state, **changed})
    return _finish(store, tool, sorted(changed), count, message, candidates.note)


def _finish(
    store: HookStore, tool: str, files: list[str], count: int, message: str, note: str
) -> HookResult:
    """Log the run; feedback for the agent first, then a notice when the hook's own
    files could not be kept (the user sees it, the agent does not act on it)."""
    exit_code = HOOK_CLEAN
    if count > 0:
        exit_code = HOOK_FEEDBACK
    record = {"tool": tool, "files": files, "findings": count, "exit": exit_code, "note": note}
    logged = store.log_run(record)
    if exit_code == HOOK_CLEAN and (not logged or len(store.problems) > 0):
        return HookResult(HOOK_NOTICE, f"shockharness hook: {'; '.join(store.problems)}\n")
    return HookResult(exit_code, message)


def write_result(result: HookResult, stream: Any) -> int:
    if result.message != "":
        stream.write(result.message)
    return result.exit_code


def read_stdin() -> str:
    return sys.stdin.read()
