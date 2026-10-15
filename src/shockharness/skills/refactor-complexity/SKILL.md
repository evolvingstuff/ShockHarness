---
name: refactor-complexity
description: Reduce real complexity in Python or JavaScript code that ShockHarness gates, without gaming metrics. Use when asked to simplify, untangle or refactor a function or module, when review calls code hard to follow, or when preparing for ShockHarness complexity rules. Covers finding repeated cognitive work and coupling, recording call structure and behavior tests before and after, and keeping the refactor compliant with MAGIC001, EXC001-EXC003 and DEF001-DEF006.
---

# Refactor complexity

ShockHarness treats complexity as a separate, advisory family, never averaged
into the hard gate. **The complexity rules `CPLX001` (cyclomatic), `CPLX002`
(cognitive), `CPLX003` (nesting depth), `CPLX004` (NPath) and `CPLX005`
(coupling and cycles) are registered but not implemented**: `shockharness
rules list` shows them as `planned`, and every report lists them under `rules
not implemented (not analyzed)`. They arrive in Milestone E. Until then the
tool gives you no complexity number and no call graph; this skill tells you
how to refactor well without one, and how not to chase a metric once one
exists.

## What complexity means here

Not a count. Complexity is **repeated cognitive work**: a reader has to hold
the same condition, the same unit conversion, or the same error-handling shape
in mind in several places, and **coupling**: a change in one place forces a
change somewhere a reader could not predict. Both are what the planned rules
approximate; both can be addressed directly today.

Signs worth acting on:

- The same `if` guard or the same chain of `and`/`&&` tests appears in more
  than one function.
- A function reads configuration, validates it, performs I/O and formats the
  result, so no test can exercise one of those without the others.
- A nested branch exists only to handle an absent value that should have been
  required at load time (`DEF001`-`DEF006` territory).
- A `try` wraps several operations so that one handler has to guess which of
  them failed (`EXC003` territory).
- Two modules import each other, or a module reaches into another's internals
  to get a number it should have been given.

Signs that are not complexity: a long but linear function with one job; a
`match`/`switch` over a closed enumeration; a table of constants.

## What metric gaming looks like

Do not:

- Split a function into `step1`, `step2`, `step3` helpers that share mutable
  state through arguments or module globals. The reader now holds the same
  state across three places.
- Replace nested `if` with early `return None` or `continue` that hides an
  invalid state instead of raising.
- Move a branch into a lambda or a dict dispatch merely to lower a nesting
  count.
- Collapse conditions into one `and`/`or` expression that nobody can read, or
  turn an explicit `if x is None: raise` into `x or default` (that is a
  `DEF003` finding and a behavior change).
- Catch an exception to flatten control flow (`EXC001`), or introduce a default
  parameter so a helper has fewer call sites to update (`DEF001`).

Every one of these makes the code easier for a counter and harder for a
reader. When Milestone E ships, a before/after number that improved while
behavior tests shrank is a red flag, not a success.

## Workflow

### 1. Record the current structure

The tool does not yet produce a call graph, so write it down by hand before
touching anything: which functions in the module call which, which modules
import this one, and which external effects (I/O, environment, time, random)
each function has. A short list in the pull-request description is enough.

```text
load_report(path) -> read_text(path), parse(text), summarize(rows)
summarize(rows)   -> format_row(row)            # pure
main(argv)        -> load_report, print          # process boundary
```

### 2. Pin behavior with tests before changing code

Write or extend tests that exercise the observable behavior of every function
you will touch, including the failure paths: a missing key raises, a malformed
input raises a typed error, the explicit page size is honored. Run them green
on the current code. These are the before tests; they must still pass,
unchanged, after the refactor. If a test has to change, the refactor changed
behavior; say so explicitly and get it reviewed as such.

### 3. Refactor toward one decision per place

- **Hoist validation to a load step.** Read configuration once into a settings
  object with required, validated fields. Downstream functions take the object
  and never re-check it. This deletes most defensive nesting without hiding
  anything.
- **Extract the repeated condition into a named predicate** when the same
  test appears twice, and give it a test of its own.
- **Separate effects from computation.** A pure function that takes data and
  returns data is testable in isolation; the I/O wrapper around it stays thin
  and is where a declared exception boundary lives (one operation per `try`).
- **Break import cycles by moving the shared thing** (a type, a constant) into
  a module both sides depend on, rather than by lazy imports inside functions.
- **Keep the gate's rules.** No new numeric literal other than `0` or `1`, no
  default parameter on the extracted helper, no catch outside a declared
  boundary, no `or`/`??` fallback introduced to simplify a branch.

### 4. Run the gate and the tests, then compare

```bash
pytest -q                                           # or: node --test
shockharness check .                                # must still end in gate: PASS (exit 0)
shockharness gate --base origin/main --head HEAD    # after committing: no new hard violations
```

Then write the after structure next to the before structure from step 1 and
check that every edge you removed was a real dependency and every edge you
added is one a reader would expect.

## Examples

### Python: repeated guard and mixed effects

Before:

```python
def report(path: Path, raw_env: Mapping[str, str]) -> str:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() != "" and not line.startswith("#"):
            fields = line.split(",")
            if len(fields) == int(raw_env["COLUMNS"]):
                rows.append(fields)
    out = []
    for fields in rows:
        if len(fields) == int(raw_env["COLUMNS"]):
            out.append(" | ".join(fields))
    return "\n".join(out)
```

After (same tests, same behavior, one decision per place):

```python
@dataclass(frozen=True)
class ReportSettings:
    columns: int

def load_report_settings(raw_env: Mapping[str, str]) -> ReportSettings:
    columns = int(raw_env["COLUMNS"])
    if columns < 1:
        raise ValueError(f"COLUMNS must be at least 1, got {columns}")
    return ReportSettings(columns=columns)

def is_data_line(line: str) -> bool:
    return line.strip() != "" and not line.startswith("#")

def parse_rows(text: str, settings: ReportSettings) -> list[list[str]]:
    rows = [line.split(",") for line in text.splitlines() if is_data_line(line)]
    return [fields for fields in rows if len(fields) == settings.columns]

def render(rows: list[list[str]]) -> str:
    return "\n".join(" | ".join(fields) for fields in rows)

def report(path: Path, settings: ReportSettings) -> str:
    return render(parse_rows(path.read_text(encoding="utf-8"), settings))
```

The environment is read once, the predicate has a name and a test, the pure
functions are testable without a file, and no default, fallback, catch or
numeric literal was introduced.

### JavaScript: nested absence handling

Before:

```javascript
export function price(order, config) {
  let total = 0;
  for (const item of order.items) {
    if (item.quantity !== undefined) {
      if (item.unitPrice !== undefined) {
        total += item.quantity * item.unitPrice;
      } else {
        total += item.quantity * (config.defaultUnitPrice ?? 0);   // DEF002 and a hidden policy
      }
    }
  }
  return total;
}
```

After: absent fields are rejected where the order is built, so pricing has
one path:

```javascript
export function validateItem(item) {
  if (!Number.isInteger(item.quantity) || item.quantity < 0) {
    throw new TypeError(`quantity must be a non-negative integer, got ${item.quantity}`);
  }
  if (!Number.isFinite(item.unitPrice) || item.unitPrice < 0) {
    throw new TypeError(`unitPrice must be a non-negative number, got ${item.unitPrice}`);
  }
  return Object.freeze({ quantity: item.quantity, unitPrice: item.unitPrice });
}

export function price(items) {
  return items.reduce((total, item) => total + item.quantity * item.unitPrice, 0);
}
```

The before tests for valid orders still pass; a new test pins that an item
without a price is rejected instead of silently priced at zero.

## Checklist

- [ ] Before structure (callers, callees, effects) written down; after structure compared against it.
- [ ] Behavior tests, including failure paths, green before and unchanged after; any changed test called out as a behavior change.
- [ ] Each extracted helper has one job, no default parameters, no shared mutable state.
- [ ] Validation hoisted to one load step; no absence handling left in computation.
- [ ] No new catch outside a declared boundary; no `or`/`??`/`.get(k, v)` introduced; no numeric literal other than `0`/`1`.
- [ ] `shockharness check .` passes and the report still lists `CPLX001`-`CPLX005` as not implemented; no complexity number was claimed.

## Adopting ShockHarness

This section is written for a coding agent (or a person) that was told to set
up ShockHarness in a repository and is reading it over HTTP. It is complete on
its own: nothing here depends on another page, and the detailed documents are
linked with absolute URLs at the end. Run every command from the repository
root.

### Step 1: install a pinned version

The version is always an exact pin; nothing updates to `latest`. Pick one:

```bash
uv tool install 'shockharness==0.1.0a1'                    # isolated tool environment; any repository, JavaScript included
uvx --from 'shockharness==0.1.0a1' shockharness version     # one-off run, nothing installed
pip install 'shockharness==0.1.0a1'                        # Python project: keep the pin in pyproject.toml (a dev extra) or requirements-dev.txt
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
    uses: evolvingstuff/ShockHarness/.github/workflows/check.yml@v0.1.0
    permissions:
      contents: read
      security-events: write
    with:
      shockharness-version: "0.1.0a1"
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
| Install | `shockharness version` | `shockharness 0.1.0a1` |
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
