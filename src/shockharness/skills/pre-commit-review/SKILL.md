---
name: pre-commit-review
description: Review a change against the ShockHarness quality gate before committing or opening a pull request. Use when asked to review, check, verify or sign off a diff in a repository that runs shockharness, or before any commit there. Runs shockharness gate or check, reports unsupported analysis, suppressions, policy deviations and remaining warnings, runs the project's tests, and never claims a pass without having run the commands.
---

# Pre-commit review

The review has one rule: **never claim a pass you did not run.** Every
statement in the review quotes the command and the lines of output that back
it. A report that says "looks compliant" without the gate's own `gate: PASS
(exit 0)` line is not a review.

## Commands

Run from the repository root, in this order.

```bash
git status --short                                   # what is about to be committed
shockharness config validate                         # exit 0; profile and every policy deviation
shockharness check .                                 # working tree, full configured scope
shockharness gate --base origin/main --head HEAD     # committed revisions only: exit 1 on NEW hard violations
pytest -q                                            # or the project's test command: node --test, npm test
```

Use the repository's default branch in `--base` (`main`, `master`, `develop`).
`gate` compares two **committed** revisions through local git; uncommitted
changes are not part of `HEAD`, so run `check .` for the working tree and
`gate` after committing (or on the CI run of the pull request). If the
repository uses a baseline, add `--baseline .shockharness-baseline.json` to
`check`. If the repository exposes `shockharness` only through a tool runner,
prefix the commands accordingly (`uvx --from 'shockharness==<pin>'
shockharness ...`).

Exit codes: `0` pass, `1` policy violations, `2` invalid configuration or
invocation, `3` tool failure or, under `parse_errors = "fail"`, a file that
could not be parsed. Exit `2` and `3` are review blockers of their own: they
mean nothing was verified.

## What to report, in this order

1. **Unsupported analysis.** Quote the `rules not implemented (not analyzed)`
   line (`MAGIC002`) and the `N failed` count
   of files that could not be analyzed. A clean gate covers only the rules
   that ran and the files that parsed. Name any file reported as a parse
   failure or excluded by configuration when it is part of the change.
2. **Policy deviations.** Quote the `config:` line and every `policy
   deviation` line from `config validate`: a profile below `strict`, a loosened
   mode, a severity cap, each declared exception boundary, each
   `[[overrides]]` entry. The review says whether the change added or widened
   one, and whether its `reason` holds.
3. **Suppressions.** Quote the `N suppressed` count and list each suppression
   the change adds or touches, with its rule ID and reason. Check that the rule
   ID exists (`shockharness rules list`), the reason cites a source, and the
   finding it silences is the one intended (`--no-inline-suppressions` shows
   every finding including suppressed ones). An unused suppression is a
   `SUPP002` warning and should be deleted.
4. **Remaining findings and warnings.** List every `error`, `warning` and
   `review` finding in the changed files with its line, including the `review`
   findings that do not gate (`DEF003`, the implicit `None` of `.get(k)`,
   `approximate` confidences) and the complexity warnings (`CPLX001`-`CPLX006`,
   never gating; `gate --base/--head` lists per-unit regressions under
   `complexity regressions against base`). For each, say whether it is addressed, accepted
   with a stated contract, or left for a follow-up with a named owner.
5. **Tests.** Quote the test runner's summary line (`N passed`, or `node
   --test`'s `# pass N` / `# fail N`). A change that removes a default,
   a catch or a fallback must come with a characterization test for the new
   contract (see `fix-violations`); say which test that is.
6. **Verdict.** `PASS` only when `check .` (and `gate`, when run) exited `0`,
   the tests passed, and items 1-4 contain nothing unresolved. Otherwise
   `BLOCKED` with the first blocking item.

## Review template

```text
Scope: <files changed>
Config: shockharness config validate -> exit 0; profile strict; deviations: <quoted lines or "none">
Analyzer: shockharness check . -> exit <n>
  <quoted summary lines: files, findings by severity, suppressed, rules not implemented>
  <quoted gate line>
Gate vs base: shockharness gate --base origin/main --head HEAD -> exit <n>; <quoted '<n> new, <n> fixed, <n> unchanged finding(s)' line>
Suppressions in this change: <rule ID, file:line, reason> or none
Remaining findings in changed files: <list> or none
Tests: <command> -> <quoted summary line>
Verdict: PASS | BLOCKED (<first blocking item>)
```

## Examples

### A review that passes

```text
Scope: src/app/settings.py, src/app/pages.py, tests/test_pages.py
Config: shockharness config validate -> exit 0; profile strict; deviations: tests/** disables MAGIC001, DEF001 (reason: fixtures encode literal expected outputs)
Analyzer: shockharness check . -> exit 0
  shockharness 0.2.0: 7 file(s), 7 analyzed, 0 failed; 1 finding(s), 1 suppressed
  rules not implemented (not analyzed): MAGIC002
  gate: PASS (exit 0)
Gate vs base: shockharness gate --base origin/main --head HEAD -> exit 0; 0 new, 2 fixed, 1 unchanged finding(s)
Suppressions in this change: none (the existing MAGIC001 suppression on src/app/http.py:9, RFC 9110 section 15.5.5, is unchanged)
Remaining findings in changed files: none
Tests: pytest -q -> 14 passed in 0.31s
Verdict: PASS
```

### A review that blocks

```text
Scope: src/client.js
Config: shockharness config validate -> exit 0; profile strict; deviations: none
Analyzer: shockharness check . -> exit 1
  src/client.js:12:5: DEF005 error: catch clause converts the exception into a fallback value: return null; (EXC002 classification return_fallback; the handler is reported once, here)  [} catch (err) {]
  src/client.js:12:5: EXC001 error: catch clause is forbidden: untyped catch binds every error; a JavaScript catch passes only inside an approved boundary whose error class the handler checks with instanceof and otherwise rethrows  [} catch (err) {]
  shockharness 0.2.0: 3 file(s), 3 analyzed, 0 failed; 2 finding(s), 0 suppressed
  rules not implemented (not analyzed): MAGIC002
  gate: FAIL (exit 1)
Gate vs base: not run (working tree uncommitted)
Suppressions in this change: none
Remaining findings in changed files: DEF005 and EXC001 at src/client.js:12; the failure of fetch() is turned into null
Tests: node --test -> # pass 6 / # fail 0 (no test covers the failure path)
Verdict: BLOCKED (EXC001/DEF005: decide the failure contract; see fix-violations)
```

### Python and JavaScript snippets the review should catch

```python
limit = options.get("limit", 100)          # DEF002 + MAGIC001: required value? validated where?
except Exception:                           # EXC001: broad catch outside a boundary
    log.warning("ignored")                  # EXC002: logging-only handler
```

```javascript
const port = process.env.PORT || 3000;      // DEF006 + MAGIC001
export function paginate(items, size = 10)  // DEF001 + MAGIC001
```

And what passes: a required, validated settings object; a `try` inside a
declared boundary that wraps one operation and re-throws a typed error; a
cited inline suppression for a protocol constant:

```python
NOT_FOUND = 404  # shockharness: ignore[MAGIC001] reason="RFC 9110 section 15.5.5"
```

## Checklist

- [ ] `config validate`, `check .` (with `--baseline` if the repository uses one) and the tests were actually run; exit codes quoted.
- [ ] `gate --base <default branch> --head HEAD` run on committed revisions, or explicitly marked "not run" with the reason.
- [ ] Unsupported analysis quoted: rules not implemented, files not analyzed.
- [ ] Every policy deviation quoted; any new boundary or override reviewed for its reason.
- [ ] Every suppression in the change listed with rule ID and cited reason; unused ones deleted.
- [ ] Every remaining finding in changed files listed with a disposition.
- [ ] Characterization tests named for every removed default, catch or fallback.
- [ ] Verdict is `PASS` only with `gate: PASS (exit 0)` and a green test summary in the quoted output.

## Adopting ShockHarness

This section is written for a coding agent (or a person) that was told to set
up ShockHarness in a repository and is reading it over HTTP. It is complete on
its own: nothing here depends on another page, and the detailed documents are
linked with absolute URLs at the end. Run every command from the repository
root.

### Step 1: install a pinned version

The version is always an exact pin; nothing updates to `latest`. Pick one:

```bash
uv tool install 'shockharness==0.2.0'                    # isolated tool environment; any repository, JavaScript included
uvx --from 'shockharness==0.2.0' shockharness version     # one-off run, nothing installed
pip install 'shockharness==0.2.0'                        # Python project: keep the pin in pyproject.toml (a dev extra) or requirements-dev.txt
```

The analyzer needs Python 3.11 or newer to run; the analyzed code may be
Python or JavaScript. Its only runtime dependencies are `tree-sitter` and
`tree-sitter-javascript`. The pin that CI installs must live where an updater
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
    uses: evolvingstuff/ShockHarness/.github/workflows/check.yml@v0.2.0
    permissions:
      contents: read
      security-events: write
    with:
      shockharness-version: "0.2.0"
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
| Install | `shockharness version` | `shockharness 0.2.0` |
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
