# Proposal: a finish-time gate, "the agent cannot stop while its change adds findings"

Status: **proposed** (2026-10-27), waiting for Tom's go-ahead. Nothing is built.
Follows the edit-time hook (`shockharness hook claude-code post-edit`, 4583bee); its
row in `docs/ideas.md` names this as the next step.

## The gap

The edit-time hook reports the findings in each file right after it is edited. It
leaves three gaps:

* **It sees one file at a time.** The cross-file rules see only that file, so new dead
  code, duplicates and broken import and call boundaries surface only in CI (DEAD001,
  DUP001, IMPORT002, CALL001).
* **Its feedback can be ignored.** Exit 2 puts the findings in front of the agent, and
  nothing stops the agent from saying "done" with them still there. The hook reports each
  file content once, so after a reply that leaves them, they are not repeated.
* **It cannot tell new findings from old ones.** In a file with 40 old findings, the
  agent is told about all 40 after every edit, so the 2 it just added are hard to see.

The CI gate (`gate --base B --head HEAD`) answers the right question, "what did this
change add?". It answers it only after a push, when the agent's session is over.

## The change: a Claude Code `Stop` hook

```bash
shockharness hook claude-code stop --root "$CLAUDE_PROJECT_DIR"
```

Claude Code runs a `Stop` hook when the agent is about to end its turn. If the hook
exits 2, the turn goes on and the agent reads stderr as the reason. The hook:

1. **Picks the base.** It uses the commit `HEAD` was at when the session started (see
   "The base" below). `--base REF` sets it explicitly instead, for example
   `--base origin/main`, which means the merge base of that ref and `HEAD`.
2. **Exits fast when nothing changed.** If no source file the configuration includes
   differs from the base (`git diff --name-only` plus untracked files), it exits 0. It
   also exits 0 if the working tree is the same as at the last stop this hook let
   through (content hashes in the hook store, as `post-edit` keeps them). A turn that
   only talked costs one `git` call.
3. **Analyzes both sides.** The working tree is analyzed in place, with the cache. The
   base revision is analyzed from `git archive`, as `diff` does today, and its report is
   kept in the hook store, keyed by commit, configuration digest and ShockHarness version.
   So the base is analyzed once per session, not once per stop.
4. **Gives the CI gate's verdict.** It reports what `gate --base` would fail on:
   * new findings by fingerprint, at the configured `gates` severities, with renames
     followed as `diff` follows them;
   * complexity regressions;
   * policy loosening (VERIFY003), including new inline suppressions and a configuration
     that switches a rule off.

   A stop is blocked exactly when CI would go red, and a stop that lets the work through
   means CI will pass the same tree.
5. **Blocks with the list.** It exits 2, and stderr lists the new findings in the
   `check` format, the first 20 in full plus a count of the rest. The message reads like
   `post-edit`'s: fix them now, the intended way; do not suppress, skip or loosen the
   configuration. It adds one way out: "if a finding needs a decision only the user can
   make, say which and why in your final message, and stop."

### The loop guard

Claude Code stops a run of blocks after eight in a row, but that count restarts
whenever the agent calls a tool. An agent that keeps editing and failing would never
reach it, so the hook needs a guard of its own. It records the set of fingerprints it
last blocked on, per `session_id`, and lets the stop through when either:

* the set is the same as at the last block (`stop_hook_active` is true and nothing was
  fixed), or
* it has blocked `hooks.stop.max_blocks` times this session (default 3).

When it lets a stop through with findings left, it prints a notice the user sees and
the agent does not act on (exit 0 with a `systemMessage`): "stopped with 2 new findings
in this change: …". The person always learns what is left, and the agent is never
trapped. Pressing Esc never runs the hook at all.

### The base

The base is the commit at the start of the session, not the branch point. Two reasons:

* **This repository commits straight to `main`**, and so do several projects that use
  ShockHarness. There, "the merge base with main" is `HEAD` itself, which would hide
  everything the agent has already committed.
* **Commits do not move the base.** An agent that commits mid-session cannot hide its
  findings that way.

The install adds a `SessionStart` hook (`shockharness hook claude-code session-start`)
that records `HEAD` for the session. A session without that record (for example, the
hook was installed mid-session) falls back to the first commit any hook saw for that
`session_id`.

Known limit: when the working tree already had uncommitted changes at the start of the
session, their findings count as the agent's. `SessionStart` notes this in the run log.
Analyzing the working tree at session start would close the gap, but it would delay
every session start by a full analysis (about 20 s on MetaList).

### Install and configuration

* **`skills install --agent claude --stop-hook`** adds the `Stop` and `SessionStart`
  entries to `.claude/settings.json`. Like `--hook`, it appends to hooks already there,
  only once, and accepts `--lock`. The `Stop` entry sets `"timeout": 600`. A stop hook
  that times out lets the agent stop, and the run log records it.
* **It is opt-in, separate from `--hook`**, because it can hold the agent's turn for a
  while, and a project should choose that.
* **A new table `[tool.shockharness.hooks.stop]`** holds `max_blocks` and `shown` (how
  many findings to list in full). Like `cache` and `skills`, it is left out of the
  configuration digest: it tunes the hook, not the policy.
* **No `SubagentStop` hook.** A subagent's work belongs to the main agent's turn, and
  the main agent's `Stop` sees the same working tree. Blocking a subagent halfway
  through would cut off work the main agent has not finished.
* **Claude Code only, at first**, as `post-edit` is today.

## Cost, measured today (0.31.0)

| Step | ShockHarness (1008 files) | MetaList at f999d6cb |
|---|---|---|
| A turn with no source change | one `git diff` and `git status` | same |
| Working tree, warm cache (`check`) | 3.5 s | 21 s |
| Base revision, once per session (no cache, as `diff`) | about 24 s (`diff` of two revisions: 47 s) | not measured; about 2 to 3 minutes estimated from the warm time |

The first stop with a source change in a MetaList session would take a few minutes,
because of the base analysis. Each later stop would take about 20 s. Two ways to cut
the first stop, which are questions below:

* Start the base analysis in the background at `SessionStart`.
* Let the base analysis use the cache. Entries are keyed by path and content, so files
  the agent has not touched would hit.

## What is new in the code

* **`diff` with the working tree as head.** Today `diff` analyzes only committed
  revisions. The working tree side reuses `check`'s analysis, and the comparison
  (fingerprints, renames, complexity, policy snapshot) is shared with `diff_revisions`,
  not copied.
* **Two hook events in `hook.py`:** `stop` and `session-start`, with their state in
  `HookStore`.
* **The install path** in `skills/install.py`, the `hooks.stop` schema, docs (README,
  `docs/configuration.md`), and a spec decision.

## Questions for Tom

1. **The base:** the commit at the start of the session (recommended), or the merge base
   with a named branch, as CI uses?
2. **The threshold:** the CI gate's verdict (recommended), or every new finding,
   including warnings and review findings?
3. **The first-stop cost:** start the base analysis in the background at `SessionStart`,
   let it use the cache, or accept a slow first stop?
4. **The install:** opt-in `--stop-hook` (recommended), or part of `--hook`?
