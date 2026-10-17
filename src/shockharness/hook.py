"""Edit-time feedback for coding agents: ``shockharness hook claude-code post-edit``.

A Claude Code ``PostToolUse`` hook (matcher ``Edit|Write|MultiEdit``) pipes the tool call
as JSON on stdin; the edited file is ``tool_input.file_path``. The file is analyzed under
the project's configuration (with the cache, so a hook run costs one file), and its
findings at or above ``--fail-on`` are written to stderr with exit 2, which Claude Code
shows to the agent while the edit is still in its context. A clean file, a file outside
the project or one the configuration does not include exits 0 and prints nothing.

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
from shockharness.config import EffectiveConfig
from shockharness.constants import HOOK_FEEDBACK
from shockharness.findings import Finding
from shockharness.output.text import finding_lines

AGENT_CLAUDE_CODE = "claude-code"
HOOK_AGENTS = (AGENT_CLAUDE_CODE,)
EVENT_POST_EDIT = "post-edit"
HOOK_EVENTS = (EVENT_POST_EDIT,)
TOOL_INPUT = "tool_input"
FILE_PATH = "file_path"
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


def _message(relative: Path, findings: Sequence[Finding]) -> str:
    lines = [
        f"shockharness: {len(findings)} finding(s) in {relative.as_posix()} after this edit; "
        "fix them now, the intended way (the skills say how); do not suppress, skip or "
        "loosen the configuration to get past them:"
    ]
    lines.extend(finding_lines(findings))
    return "\n".join(lines) + "\n"


def run_post_edit(
    event_text: str,
    root: Path,
    config: EffectiveConfig,
    options: AnalysisOptions,
    fail_on: str,
) -> HookResult:
    event = parse_event(event_text)
    if event.problem != "":
        # Malformed input is a notice to the user, not feedback: the agent did nothing wrong.
        return HookResult(HOOK_NOTICE, event.problem + "\n")
    path = edited_path(event.value)
    if path is None:
        return HookResult(HOOK_CLEAN, "")
    relative = _within(Path(path), root)
    if relative is None:
        return HookResult(HOOK_CLEAN, "")
    report = analyze_paths([root / relative], root, config, options)
    own = [f for f in report.findings if f.path == relative.as_posix()]
    shown = _fed_back(own, fail_on)
    if len(shown) == 0:
        return HookResult(HOOK_CLEAN, "")
    return HookResult(HOOK_FEEDBACK, _message(relative, shown))


def write_result(result: HookResult, stream: Any) -> int:
    if result.message != "":
        stream.write(result.message)
    return result.exit_code


def read_stdin() -> str:
    return sys.stdin.read()
