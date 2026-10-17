---
name: async-lifecycle
description: Keep asynchronous work observable in a repository that runs shockharness. Use when writing or changing async Python (asyncio, anyio, trio) or JavaScript (Promises, async functions), when a call to an async function is not awaited, when starting background tasks, when using asyncio.gather(return_exceptions=True) or Promise.allSettled, and when shockharness reports ASYNC001, ASYNC002 or ASYNC003. Explains each finding and the owned, awaited or returned alternatives.
---

# Async lifecycle

An async call that nobody awaits is a promise that nobody keeps. The caller returns
success, the work runs later or never, and its failure surfaces, if at all, as a warning
in a log that no request is attached to. This is a swallowed exception without a
`catch`, and ShockHarness reports it the same way.

The rule for an agent: **every coroutine, task and Promise has an owner that waits for it
and sees its failure.** The owner is the function that awaits it, a caller it is returned
to, or a supervisor that outlives it (a `TaskGroup`, `Promise.all` whose result is
awaited).

## What the findings mean

| Finding | What the code does | Do this instead |
|---|---|---|
| `ASYNC001` | calls an async function (or `fetch`, `asyncio.sleep`, ...) as a statement, or with `void`, and drops the coroutine or Promise | `await` it, `return` it, or hand it to an owner; a top-level JavaScript entry point ends in `.catch(...)` that reports and sets the exit code |
| `ASYNC002` | `asyncio.create_task(...)` / `ensure_future(...)` as a statement: the task's handle is dropped | start it in a `TaskGroup`, or keep the handle and await or cancel it |
| `ASYNC003` | `gather(..., return_exceptions=True)` / `Promise.allSettled` whose results are thrown away or never checked for failure | check every result and raise or report the failures; use plain `gather` / `Promise.all` when the first failure should fail the batch |

`ASYNC001` finds project functions declared `async` across files through the call graph;
a call matched only by name is reported as `unknown`. Without type information an
arbitrary library call is never assumed to return a Promise: only the catalog in
`rules.async_lifecycle` counts. The rules ship at `warning`; a repository that wants them
to gate sets `rules.async_lifecycle.severity = "error"`.

## Commands

```bash
shockharness check .                       # ASYNC findings with the rest
shockharness rules explain ASYNC001
shockharness gate --base origin/main --head HEAD
```

## Examples

Python:

```python
# ASYNC001: save() is async; this line creates a coroutine and drops it. Nothing is saved.
async def handle(record):
    save(record)
    return OK

# Owned: awaited.
async def handle(record):
    await save(record)
    return OK

# ASYNC002: the task can be garbage-collected mid-flight; its exception is never retrieved.
async def handle(user):
    asyncio.create_task(notify(user))
    return OK

# Owned: the group waits for the task and raises its failure.
async def handle(user):
    async with asyncio.TaskGroup() as group:
        group.create_task(notify(user))
    return OK

# ASYNC003: every failure in the batch becomes a value and is thrown away.
async def sync_all(jobs):
    await asyncio.gather(*jobs, return_exceptions=True)

# Inspected: failures are raised together.
async def sync_all(jobs):
    results = await asyncio.gather(*jobs, return_exceptions=True)
    failures = [r for r in results if isinstance(r, Exception)]
    if failures:
        raise ExceptionGroup("sync failed", failures)
```

JavaScript:

```javascript
// ASYNC001: writeRecord is async; the Promise and its rejection are dropped.
export function saveRecord(record) {
  writeRecord(record);
  return true;
}

// Owned: the caller sees the failure.
export async function saveRecord(record) {
  await writeRecord(record);
  return true;
}

// ASYNC001 with void: void does not handle the rejection, it hides it.
void writeRecord(record);

// An entry point that cannot be awaited reports its failure.
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

// ASYNC003: results thrown away.
Promise.allSettled(jobs);

// Inspected: rejected entries are reported.
export async function runAll(jobs) {
  const results = await Promise.allSettled(jobs);
  const failed = results.filter((result) => result.status === "rejected");
  if (failed.length > 0) {
    throw new AggregateError(failed.map((result) => result.reason), "jobs failed");
  }
}
```

## When fire-and-forget is intended

Sometimes work should outlive the request: a metrics flush, a cache warm-up. That is a
design decision, so make the owner explicit: a long-lived supervisor object that keeps
the tasks, logs their exceptions, and is shut down cleanly; or a job queue. Register a
custom supervisor in `rules.async_lifecycle.supervisors` (a policy deviation, so review
sees it). Do not silence the finding with `void` or by assigning the task to `_`.

## Checklist

- [ ] Every call to an async function is awaited, returned, or handed to an owner.
- [ ] Every task is started in a `TaskGroup` (or nursery), or its handle is kept and awaited or cancelled.
- [ ] Every `gather(return_exceptions=True)` / `Promise.allSettled` result is checked for failures, or the batch is returned to a caller that checks it.
- [ ] No `void` on a Promise; top-level entry points end in a `.catch` that reports and sets the exit code.
- [ ] Tests await what they call: an unawaited coroutine in a test makes it pass without checking anything.

## Adopting ShockHarness

This section is written for a coding agent (or a person) that was told to set
up ShockHarness in a repository and is reading it over HTTP. It is complete on
its own: nothing here depends on another page, and the detailed documents are
linked with absolute URLs at the end. Run every command from the repository
root.

### Step 1: install a pinned version

The version is always an exact pin; nothing updates to `latest`. Pick one:

```bash
uv tool install 'shockharness==0.7.0'                    # isolated tool environment; any repository, JavaScript included
uvx --from 'shockharness==0.7.0' shockharness version     # one-off run, nothing installed
pip install 'shockharness==0.7.0'                        # Python project: keep the pin in pyproject.toml (a dev extra) or requirements-dev.txt
```

The analyzer needs Python 3.11 or newer to run; the analyzed code may be
Python, JavaScript or TypeScript. Its only runtime dependencies are `tree-sitter`,
`tree-sitter-javascript` and `tree-sitter-typescript`. The pin that CI installs must live where an updater
can read it (`pyproject.toml`, a requirements file, or the workflow input in
step 4), never only inside a shell command.

### Step 2: write the policy file

```bash
shockharness init                 # writes .shockharness.toml: strict profile, every default spelled out
shockharness config validate      # exit 0; prints the profile and every policy deviation
```

Commit `.shockharness.toml`. Adjust `include` and `exclude` so only source is
analyzed. Tests may stay included; exempt them from `MAGIC001` and `DEF001`
with an `[[tool.shockharness.overrides]]` entry that carries a `reason`, as
the tool's own configuration does.

### Step 3: first run, and the four onboarding paths for an existing codebase

```bash
shockharness check .              # exit 0 pass, 1 violations, 2 invalid configuration, 3 tool failure or unparseable file
```

A codebase that predates the policy will have findings. Choose one of four
paths. All four are visible in every report, so none of them hides anything.

| Path | Command or configuration | Use it when |
|---|---|---|
| Baseline | `shockharness baseline create . --output .shockharness-baseline.json`, review and commit the file, then run `shockharness check . --baseline .shockharness-baseline.json` | You want a real gate from the first pull request: legacy findings stay listed but do not gate, new ones fail. The usual choice. |
| `profile = "minimal"` | `profile = "minimal"` in `.shockharness.toml`, or `shockharness check . --profile minimal` for one run | First contact: every rule runs and reports at `review`; only malformed suppressions fail. |
| `gates.new_hard_violations = "warn"` | `[tool.shockharness.gates]` with `new_hard_violations = "warn"` in `.shockharness.toml` | The repository has agreed that the policy is advisory for now, and that decision should be reviewed and diffed like any configuration change. It is reported as a deviation. |
| `--exit-zero` | `shockharness check . --exit-zero` | One invocation must not block (a dry run, a first SARIF upload, a scheduled strict run) and the repository's policy must not change for it. Exit 1 becomes 0; exit 2 and 3 are never masked; the report says `advisory`. |

On pull requests prefer `shockharness gate --base origin/main --head HEAD`
(use the repository's default branch; both revisions must be committed): it
exits 1 only on hard violations that are new relative to the base.

### Step 4: CI

Direct invocation works on any CI system. Install the pin from the manifest,
then run the analyzer; a report is written even when the gate fails:

```yaml
- run: pip install -e ".[dev]"      # the pin lives in pyproject.toml; a JavaScript repository uses the reusable workflow below instead
- run: shockharness check . --format sarif --output shockharness.sarif
```

On GitHub, call the reusable workflow. Pin its ref to a release tag or a full
commit SHA. The analyzer version is the `shockharness-version` input, not the
ref; the two are separate pins:

```yaml
name: ShockHarness
on:
  pull_request:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  shockharness:
    uses: evolvingstuff/ShockHarness/.github/workflows/check.yml@v0.7.0
    permissions:
      contents: read
      security-events: write
    with:
      shockharness-version: "0.7.0"
      base: ${{ github.event_name == 'pull_request' && github.event.pull_request.base.sha || '' }}
```

Add `.github/dependabot.yml` so both pins get upgrade pull requests. Dependabot
bumps the `uses:` ref and any `pyproject.toml` or requirements pin; it does not
rewrite the `shockharness-version` input, so bump that by hand in the same
pull request:

```yaml
version: 2
updates:
  - package-ecosystem: pip
    directory: /
    schedule:
      interval: weekly
  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: weekly
```

### Step 5: install the agent skills

Four skills ship inside the package: `write-compliant-code`,
`fix-violations`, `refactor-complexity` and `pre-commit-review`.

```bash
shockharness skills install --agent claude                              # .claude/skills/<name>/SKILL.md in this repository
shockharness skills install --agent claude --hook                       # also: findings after every edit (.claude/settings.json)
shockharness skills install --agent codex                               # .agents/skills/<name>/SKILL.md in this repository
shockharness skills install --agent generic --project docs/agent-skills # any agent; prints the line to add to AGENTS.md
shockharness skills update --agent claude --check                       # exit 1 when an installed skill is stale or edited
```

Add `--user` to install into the per-user directory (`~/.claude/skills` or
`~/.agents/skills`) instead of the repository. `install` never overwrites an
existing file unless `--force` is given. A manifest,
`.shockharness-skills.json`, is written next to the skills and records the
package version and a SHA-256 per file; `skills update` rewrites unedited
files, leaves edited files alone and reports each as a conflict with the
remediation. Put `skills update --check` in CI to detect drift after an
upgrade.

### Step 6: verify

Each command's output confirms one step.

| Step | Command | Output that confirms it |
|---|---|---|
| Install | `shockharness version` | `shockharness 0.7.0` |
| Policy | `shockharness config validate` | a line starting `shockharness: configuration is valid` naming `profile strict`, exit 0 |
| Analysis | `shockharness check .` | a report whose last lines start with `gate: PASS (exit 0)` or `gate: FAIL (exit 1)`; exit 2 or 3 means the setup is wrong, not the code |
| Baseline, if used | `shockharness check . --baseline .shockharness-baseline.json` | `gate: PASS (exit 0)` followed by `N legacy finding(s) matched the baseline` |
| Pull-request gate | `shockharness gate --base origin/main --head HEAD` | `gate: PASS (exit 0)` with new, fixed and unchanged counts |
| Skills | `shockharness skills update --agent claude --check` | a line ending `up to date`, exit 0 |
| CI | the workflow run | the `shockharness` job green; findings under the repository's Security tab when SARIF is uploaded |

Detailed documents: configuration
https://github.com/evolvingstuff/ShockHarness/blob/main/docs/configuration.md,
rules https://github.com/evolvingstuff/ShockHarness/blob/main/docs/rules.md,
CI and Dependabot
https://github.com/evolvingstuff/ShockHarness/blob/main/docs/integration.md,
skills https://github.com/evolvingstuff/ShockHarness/blob/main/docs/skills.md,
limitations
https://github.com/evolvingstuff/ShockHarness/blob/main/docs/limitations.md.
