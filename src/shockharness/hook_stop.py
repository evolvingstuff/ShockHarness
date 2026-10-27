"""The finish-time gate: ``shockharness hook claude-code stop`` (docs/proposal-stop-hook.md).

A Claude Code ``Stop`` hook runs when the agent is about to end its turn. This one runs
the CI gate's comparison (``gating.diff.diff_working_tree``) between the commit the
session started from and the working tree, and exits 2 with the new hard violations on
stderr while the gate would fail, so the agent keeps working instead of saying "done".

* **The base** is the commit ``HEAD`` was at when the session started, recorded by the
  ``session-start`` event (or, without it, by the first hook run of the session), so a
  commit made during the session does not hide what the session added. ``--base REF``
  uses the merge base of ``REF`` and ``HEAD`` instead.
* **Fast paths:** no file differs from the base, or the working tree is as it was at the
  last stop the hook let through, and the hook exits 0 after two git calls.
* **The loop guard** is the hook's own, since Claude Code's cap on blocks in a row
  restarts after every tool call: while the agent continues because of this hook, a stop
  whose new violations are the ones it was last blocked on, or one after
  ``hooks.stop.max_blocks`` blocks, is let through with a notice to the user (exit 1),
  naming what is left.
"""

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shockharness import gate as gate_module
from shockharness.analysis import AnalysisOptions
from shockharness.cache.store import cache_directory, cache_settings
from shockharness.config import EffectiveConfig
from shockharness.constants import EXIT_OK, HOOK_FEEDBACK
from shockharness.findings import Finding
from shockharness.gating.diff import STATUS_NEW, DiffReport, diff_working_tree, hard_violation
from shockharness.history.git import RepositoryLocation, locate_repository, run_git_text
from shockharness.hook import (
    BASE_PREFIX,
    HOOK_CLEAN,
    HOOK_NOTICE,
    HookResult,
    parse_event,
    remembered_base,
    session_of,
)
from shockharness.hook_state import HookStore
from shockharness.output.text import finding_lines

STOP_HOOK_ACTIVE = "stop_hook_active"
# State keys per session, beside the edit hook's file hashes.
BLOCKS_PREFIX = "stop-blocks:"  # blocks in a row while the agent continues
BLOCKED_ON_PREFIX = "stop-blocked-on:"  # digest of what the last block named
PASSED_PREFIX = "stop-passed:"  # digest of the changed files at the last stop let through
HOOKS_KEY = "hooks"
STOP_KEY = "stop"
GIT_NUL = "\0"
DELETED = "deleted"  # a changed file's hash when it is gone from the working tree
SHORT_COMMIT = 12
COMPLEXITY = "complexity"  # metrics.complexity.regressions of a diff
REGRESSIONS = "regressions"


@dataclass(frozen=True)
class StopSettings:
    max_blocks: int
    shown: int


def stop_settings(config: EffectiveConfig) -> StopSettings:
    table = config.values[HOOKS_KEY][STOP_KEY]
    return StopSettings(max_blocks=int(table["max_blocks"]), shown=int(table["shown"]))


def run_session_start(event_text: str, root: Path, config: EffectiveConfig) -> HookResult:
    """Record ``HEAD`` as the session's base. Prints nothing: a ``SessionStart`` hook's
    output would join the agent's context."""
    event = parse_event(event_text)
    store = HookStore(root / str(cache_settings(config)["directory"]))
    if event.problem != "":
        return _notice(store, event.problem, {"event": "session-start"})
    state = store.load_state()
    recorded = remembered_base(root, event.value, state)
    if len(recorded) > 0:
        store.save_state({**state, **recorded})
    note = _dirty_note(root)
    store.log_run({"event": "session-start", "recorded": sorted(recorded.values()), "note": note})
    return HookResult(HOOK_CLEAN, "")


def _dirty_note(root: Path) -> str:
    """A note when the session starts with uncommitted changes: their findings will count
    as the session's."""
    text, error = run_git_text(root, ["status", "--porcelain=v1", "-z", "--", "."])
    if text is None:
        return f"the working tree could not be listed: {error}"
    if text == "":
        return ""
    return "the working tree had uncommitted changes when the session started"


def _base(
    root: Path, base_ref: str | None, session: str, state: Mapping[str, str]
) -> tuple[str | None, str]:
    """(the base commit, or None, and why there is none)."""
    if base_ref is not None:
        text, error = run_git_text(root, ["merge-base", base_ref, "HEAD"])
        if text is None:
            return None, f"--base {base_ref}: {error}"
        return text.strip(), ""
    key = BASE_PREFIX + session
    if key not in state:
        return None, "the session has no recorded base commit"
    return state[key], ""


def _changed_paths(
    location: RepositoryLocation, base: str, cache: str
) -> tuple[list[str] | None, str]:
    """Paths (relative to the repository) that differ from ``base`` in the working tree,
    untracked ones included, under the analysis root; none in the cache directory
    (``cache``, relative to the repository), which holds the hook's own files and may
    not be ignored by git."""
    pathspec = location.prefix if location.prefix != "" else "."
    tracked, error = run_git_text(
        location.toplevel, ["diff", "--name-only", "-z", "--no-renames", base, "--", pathspec]
    )
    if tracked is None:
        return None, str(error)
    untracked, error = run_git_text(
        location.toplevel, ["ls-files", "--others", "--exclude-standard", "-z", "--", pathspec]
    )
    if untracked is None:
        return None, str(error)
    paths = {p for p in (tracked + untracked).split(GIT_NUL) if p != "" and not p.startswith(cache)}
    return sorted(paths), ""


def _change_digest(
    root: Path, base: str, config: EffectiveConfig, store: HookStore
) -> tuple[str | None, str]:
    """A digest of every file the working tree changed since ``base`` and its content;
    None with an empty reason when nothing changed, None with the reason when git failed."""
    location, error = locate_repository(root)
    if location is None:
        return None, f"no git repository: {error}"
    cache = cache_directory(root, config).resolve()
    excluded = GIT_NUL  # no path starts with it: a cache outside the repository
    if cache.is_relative_to(location.toplevel.resolve()):
        excluded = cache.relative_to(location.toplevel.resolve()).as_posix() + "/"
    paths, error = _changed_paths(location, base, excluded)
    if paths is None:
        return None, f"the changed files could not be listed: {error}"
    if len(paths) == 0:
        return None, ""
    digest = hashlib.sha256()
    for path in paths:
        file = location.toplevel / path
        content = DELETED
        if file.exists():
            content = str(store.content_hash(file))
        digest.update(f"{path}{GIT_NUL}{content}{GIT_NUL}".encode())
    return digest.hexdigest(), ""


def run_stop(
    event_text: str,
    root: Path,
    config: EffectiveConfig,
    options: AnalysisOptions,
    base_ref: str | None,
) -> HookResult:
    event = parse_event(event_text)
    store = HookStore(root / str(cache_settings(config)["directory"]))
    if event.problem != "":
        return _notice(store, event.problem, {"event": "stop"})
    session = session_of(event.value)
    state = store.load_state()
    recorded = remembered_base(root, event.value, state)
    state = {**state, **recorded}
    base, why = _base(root, base_ref, session, state)
    if base is None:
        return _notice(store, f"shockharness stop hook: no base: {why}", {"event": "stop"})
    changes, why = _change_digest(root, base, config, store)
    record = {"event": "stop", "base": base}
    if changes is None:
        store.save_state(state)
        if why != "":
            return _notice(store, f"shockharness stop hook: {why}", record)
        return _clean(store, {**record, "note": "nothing changed since the base"})
    passed = PASSED_PREFIX + session
    if passed in state and state[passed] == changes:
        store.save_state(state)
        return _clean(store, {**record, "note": "as at the last stop let through"})
    diff = diff_working_tree(root, base, config, options)
    stop = Stop(session, base, changes, _continuing(event.value), stop_settings(config))
    return _verdict(store, state, stop, diff)


def _continuing(event: Any) -> bool:
    """Whether the agent is going on because a stop hook blocked its last stop."""
    return (
        isinstance(event, Mapping) and STOP_HOOK_ACTIVE in event and event[STOP_HOOK_ACTIVE] is True
    )


@dataclass(frozen=True)
class Stop:
    session: str
    base: str
    changes: str  # the digest of the changed files
    continuing: bool
    settings: StopSettings


def _verdict(store: HookStore, state: dict[str, str], stop: Stop, diff: DiffReport) -> HookResult:
    """Exit 0 when the gate passes, exit 2 with what it fails on, or exit 1 (a notice to
    the user) when the loop guard lets a failing stop through."""
    record: dict[str, Any] = {"event": "stop", "base": stop.base, "gate": diff.gate.status}
    blocks_key = BLOCKS_PREFIX + stop.session
    if gate_module.process_exit_code(diff.gate) == EXIT_OK:
        store.save_state({**state, PASSED_PREFIX + stop.session: stop.changes, blocks_key: "0"})
        return _clean(store, record)
    found = _new_violations(diff)
    blocked_on = _blocked_digest(found, diff.gate.reasons)
    blocks = 0
    if stop.continuing and blocks_key in state:
        blocks = int(state[blocks_key])
    last_key = BLOCKED_ON_PREFIX + stop.session
    unchanged = stop.continuing and last_key in state and state[last_key] == blocked_on
    details = [f"{f.rule_id} {f.path}:{f.span.line}" for f in found]
    record = {**record, "findings": len(found), "details": details, "blocks": blocks}
    if unchanged or blocks >= stop.settings.max_blocks:
        store.save_state({**state, blocks_key: "0"})
        message = _left_message(stop, diff, found, blocks, unchanged)
        return _notice(store, message, record)
    store.save_state({**state, blocks_key: str(blocks + 1), last_key: blocked_on})
    store.log_run({**record, "exit": HOOK_FEEDBACK})
    return HookResult(HOOK_FEEDBACK, _block_message(stop, diff, found))


def _new_violations(diff: DiffReport) -> list[Finding]:
    gating = gate_module.unknown_gating_sections(diff.config)
    return [
        entry.finding
        for entry in diff.findings
        if entry.status == STATUS_NEW and hard_violation(entry.finding, gating)
    ]


def _blocked_digest(found: Sequence[Finding], reasons: Sequence[str]) -> str:
    """What a block named: its findings' fingerprints and the gate's reasons."""
    parts = sorted(str(f.fingerprint) for f in found)
    return hashlib.sha256(GIT_NUL.join([*parts, *reasons]).encode()).hexdigest()


def _listed(diff: DiffReport, found: Sequence[Finding], shown: int) -> list[str]:
    """Why the gate fails (its first reason; the others are notes), the new violations,
    the first ``shown`` in full, and the complexity regressions when they fail it."""
    lines = [f"  {reason}" for reason in diff.gate.reasons[:1]]
    lines.extend(finding_lines(found[:shown]))
    if len(found) > shown:
        lines.append(f"  ... and {len(found) - shown} more")
    if diff.config.values["gates"]["complexity_regressions"] == gate_module.REGRESSIONS_FAIL:
        lines.extend(_regression_line(r) for r in diff.metrics[COMPLEXITY][REGRESSIONS])
    return lines


def _regression_line(regression: Mapping[str, Any]) -> str:
    base = regression["base"]
    if base is None:
        base = "new"
    return (
        f"{regression['path']}:{regression['span']['line']}: {regression['rule_id']} "
        f"{regression['name']}: {regression['metric']} {base} -> {regression['head']}, "
        f"threshold {regression['threshold']}"
    )


def _block_message(stop: Stop, diff: DiffReport, found: Sequence[Finding]) -> str:
    lines = [
        f"shockharness: this change is not finished: against {stop.base[:SHORT_COMMIT]}, "
        "the commit this session started from, the gate fails:",
        *_listed(diff, found, stop.settings.shown),
        "Fix them now, the intended way (the skills say how); do not suppress, skip or "
        "loosen the configuration to get past them. If one needs a decision only the user "
        "can make, say which and why in your final message, and stop.",
    ]
    return "\n".join(lines) + "\n"


def _left_message(
    stop: Stop, diff: DiffReport, found: Sequence[Finding], blocks: int, unchanged: bool
) -> str:
    why = f"after {blocks} block(s)"
    if unchanged:
        why = "with nothing fixed since the last block"
    lines = [
        f"shockharness stop hook: the agent stopped {why}; against "
        f"{stop.base[:SHORT_COMMIT]} the gate still fails:",
        *_listed(diff, found, stop.settings.shown),
    ]
    return "\n".join(lines) + "\n"


def _clean(store: HookStore, record: Mapping[str, Any]) -> HookResult:
    logged = store.log_run({**record, "exit": HOOK_CLEAN})
    if not logged or len(store.problems) > 0:
        return HookResult(HOOK_NOTICE, f"shockharness hook: {'; '.join(store.problems)}\n")
    return HookResult(HOOK_CLEAN, "")


def _notice(store: HookStore, message: str, record: Mapping[str, Any]) -> HookResult:
    """A notice to the user (exit 1): the stop goes ahead and the agent does not act on it."""
    store.log_run({**record, "exit": HOOK_NOTICE, "note": message.strip()})
    return HookResult(HOOK_NOTICE, message.rstrip("\n") + "\n")
