---
name: property-contracts
description: Declare and keep property contracts (requires / produces / preserves) in a repository that enables rules.property_contracts. Use when a value must carry a fact the code cannot see in it (normalized, redacted, sanitized HTML, a validated path), when shockharness reports PROP001-PROP008, when writing the catalog, a predicate or a test bootstrap that calls enable, and when the repository runs at enforcement = "complete". Explains how to choose properties, where each declaration goes, the runtime modes, and the sorry count.
---

# Property contracts

Some facts about a value are not visible in the value: this series is normalized, this
note is redacted, this markup is safe to assign to the page. A property contract writes
the fact into the code. Calls of four functions from the project's own copy of the
runtime file, each returning its first argument, declare them; ShockHarness checks every
path to the place that needs the fact. The full guide is `docs/property-contracts.md` in
the ShockHarness repository, and the design is its
`docs/shockharness_property_contracts_spec.md`.

## The declarations

| Call | Where | Means |
|---|---|---|
| `requires(x, "p", ...)` | first in the body, before any other use of the parameter | the caller must pass `x` carrying `p` |
| `requires(x)` | first in the body | considered: `x` needs nothing (counts toward the sorry count) |
| `produces(value, "p", ...)` | at the point `p` is really established, usually `return produces(...)` | `value` now carries `p` |
| `preserves(result, source)` | `return preserves(expr, x)` | `result` carries what `source` carried |
| `preserves_except(result, source, "p", ...)` | the same, less some properties | |

Every operation the analysis cannot credit destroys every property (arithmetic, a
rebuilt dict, a library call). The idiom for "computed from `x`, still everything `x`
was, plus `p`" is `return produces(preserves(expr, x), "p")`.

A generic wrapper (`head(x, n)`, `first(items)`) that returns `preserves(result, x)`
on a parameter that requires nothing passes on whatever each caller's argument carried.
`return x` alone carries nothing; say `preserves`.

## What the findings mean

| Finding | What to do |
|---|---|
| `PROP001` | Route the value through the property's declared producer. If something the analyzer cannot see really establishes it, add `produces(x, "p")` there and a test that exercises that point. **Never remove a `requires` to satisfy it.** An unknown `PROP001` means a call the analysis cannot follow (a method on a value, a registry lookup, a call deeper than `max_depth`): call the function directly, or declare at the point the property is established. |
| `PROP002` | Only the catalog's producers may produce the property: call the producer, or ask for this function to be added to the catalog. |
| `PROP003` | Fix the spelling, or add the property to the catalog with its description, producers and runtime level. |
| `PROP004` | Establish the property on every return, or accept that the result does not carry it. |
| `PROP005` | Paste `shockharness contracts static-properties` into the bootstrap's `enable(...)`, or register the missing predicate. |
| `PROP006` | Write each property as a string literal and pass the arguments positionally. |
| `PROP007` | Move the `requires` to the top of the body. |
| `PROP008` | State the parameter's `requires` and the return's `produces`/`preserves`. If the code and the spec do not tell you what the contract is, stop and ask. |

If you cannot determine the contract from the code and the spec, **stop and report it**
rather than guessing. A property is a design decision, not a fix.

## Choosing properties

- A property is a fact that is **not observable from the value** and that later code
  depends on: `redacted`, `validated_path`, `cloud_disclosable`. "Is a list" is a type,
  not a property.
- Use one property per pipeline step that later code relies on. Name it for what was
  established, in `lower_snake_case`.
- Give it `producers` when only one function may establish it (the sanitizer, the
  privacy evaluator), and a `reason` on every sink.
- Strings and numbers cannot carry runtime state: their properties are
  `runtime = "static"`. Objects can be `"check"`; a property with a cheap, pure
  predicate can be `"verify"`.

## Examples

Python, non-compliant: the result of an inline computation is passed on as if
normalized, and `fit`'s requirement was deleted to make the finding go away.

```python
def fit(series):
    return train(series)            # was: requires(series, "normalized")

def pipeline(raw):
    return fit((raw - raw.mean()) / raw.std())
```

Python, compliant:

```python
from app.contracts import preserves, produces, requires

def normalize(x):
    requires(x, "numeric")
    return produces(preserves((x - x.mean()) / x.std(), x), "normalized")

def fit(series):
    requires(series, "normalized", "numeric")
    return train(series)

def pipeline(raw):
    requires(raw, "numeric")
    return fit(normalize(raw))
```

JavaScript, non-compliant then compliant (an `innerHTML` sink requiring
`sanitized_html`):

```javascript
el.innerHTML = `<b>${tag}</b>`;                       // PROP001: tag is not escaped

import { escapeHtml } from "./html.js";
el.innerHTML = `<b>${escapeHtml(tag)}</b>`;           // composed from escaped parts
```

TypeScript is read as JavaScript; annotations are ignored:

```typescript
export function redact(note: Note): Note {
  requires(note, "decrypted");
  return produces(stripPrivate(note), "redacted");
}
```

## The runtime and `enable`

The runtime file is identity-only until test code calls `enable` once, before any
declaration has run. Production never calls it, and no environment variable turns it on.

- **Python tests:** `conftest.py` calls `enable("check", [...])` before importing the
  application. The list is the catalog's static properties; paste
  `shockharness contracts static-properties`.
- **A server under a browser suite:** a test-only entry script calls `enable` and then
  starts the server exactly as the production entry does.
- **A browser:** a test-entry page whose first module script calls `enable`, or an
  init script (Playwright `addInitScript`) that sets
  `globalThis.__shockharnessContracts = { mode: "check", static: [...] }`. In Node, call
  `enable` and then `await import(...)` the application.
- `enable("verify", [...])` also runs predicates. Register each one once, at startup, in
  the catalog's `registration_module`: `register("normalized", predicate, "mean 0, sd
  1")`. A predicate is pure, does not change the value, and keeps its tolerances in named
  constants.

## Commands

```bash
shockharness contracts install --language python --dest app/contracts.py
shockharness contracts install --language javascript --dest static/js/vendor/shockharness-contracts.js
shockharness contracts install --check          # CI: an edited or stale copy fails
shockharness contracts static-properties        # the list enable(...) takes
shockharness check .
shockharness exceptions .                       # includes the sorry count under complete
shockharness rules explain PROP001
```

## `complete` and the sorry count

With `enforcement = "complete"` (or a path in `complete_paths`), every parameter of every
module-level function and method needs a `requires`, and every return a `produces` or
`preserves` (PROP008). `requires(x)` with no property is the honest answer for a
parameter that needs nothing. `shockharness exceptions .` lists each one: the project's
sorry count, read by reviewers like suppressions. Do not add `requires(x)` to silence
PROP008 when the parameter does need something; that hides the contract the level exists
to expose.

## Checklist

- [ ] Each property is a fact the value cannot show, named for what was established, in the catalog with its `runtime` level.
- [ ] Each `requires` is first in its function; each `produces` is where the property is really established, with a test that exercises that point.
- [ ] No `requires` was removed, and no `produces` added without justification, to satisfy a finding.
- [ ] Pass-through helpers say `preserves(result, x)`; nothing relies on `return x` carrying a property.
- [ ] The test bootstrap calls `enable` once with the list `shockharness contracts static-properties` prints; production never calls it.
- [ ] Predicates are pure, registered once in the registration module, with named tolerances.
- [ ] `shockharness check .` passes, and under `complete` every `requires(x)` in `shockharness exceptions .` is a real decision.

## Adopting ShockHarness

This section is written for a coding agent (or a person) that was told to set
up ShockHarness in a repository and is reading it over HTTP. It is complete on
its own: nothing here depends on another page, and the detailed documents are
linked with absolute URLs at the end. Run every command from the repository
root.

### Step 1: install a pinned version

The version is always an exact pin; nothing updates to `latest`. Pick one:

```bash
uv tool install 'shockharness==0.15.0'                    # isolated tool environment; any repository, JavaScript included
uvx --from 'shockharness==0.15.0' shockharness version     # one-off run, nothing installed
pip install 'shockharness==0.15.0'                        # Python project: keep the pin in pyproject.toml (a dev extra) or requirements-dev.txt
```

The analyzer needs Python 3.11 or newer to run; the analyzed code may be
Python, JavaScript or TypeScript. Its only runtime dependencies are `tree-sitter`,
`tree-sitter-javascript` and `tree-sitter-typescript`. The pin that CI installs must live where an updater
can read it (`pyproject.toml`, a requirements file, or the workflow input in
step 4), never only inside a shell command.

### Step 2: write the policy file

```bash
shockharness init                 # writes .shockharness.toml: strict profile, every default spelled out, tests exempt
shockharness config validate      # exit 0; prints the profile and every policy deviation
```

Commit `.shockharness.toml` and adjust `include`/`exclude` so only source is
analyzed; `init` already exempts tests from `MAGIC001` and `DEF001`. Never
switch a rule off to get past a finding (an override, a disabled rule, a lower
severity, a wider `exclude`): that is the user's decision, and `check` and the
hook report it as `VERIFY003` until a person commits it. A catch boundary
naming one file is the remedy `EXC001` asks for and needs no sign-off.

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
    uses: evolvingstuff/ShockHarness/.github/workflows/check.yml@v0.15.0
    permissions:
      contents: read
      security-events: write
    with:
      shockharness-version: "0.15.0"
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

Six skills ship inside the package (`shockharness skills list` names them).

```bash
shockharness skills install --agent claude                              # .claude/skills/<name>/SKILL.md in this repository
shockharness skills install --agent claude --hook                       # also: findings after every edit (.claude/settings.json)
shockharness skills install --agent claude --hook --lock                # also: a lock file the project's configuration cannot loosen
shockharness skills install --agent codex                               # .agents/skills/<name>/SKILL.md in this repository
shockharness skills install --agent generic --project docs/agent-skills # any agent; prints the line to add to AGENTS.md
shockharness skills update --agent claude --check                       # exit 1 when an installed skill is stale or edited
```

Add `--user` to install into `~/.claude/skills` or `~/.agents/skills`
instead. `install` writes `.shockharness.toml` (as `init` does) when the project
has none, and never overwrites a file without `--force`. A manifest,
`.shockharness-skills.json`, records a SHA-256 per file: `skills update`
rewrites unedited files and reports edited ones as conflicts. Put `skills
update --check` in CI to detect drift after an upgrade.

### Step 6: verify

Each command's output confirms one step.

| Step | Command | Output that confirms it |
|---|---|---|
| Install | `shockharness version` | `shockharness 0.15.0` |
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
