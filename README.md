# ShockHarness

<p align="center">
  <img src="https://raw.githubusercontent.com/evolvingstuff/ShockHarness/main/docs/assets/hero.webp"
       alt="ShockHarness: a robot agent jolted an instant before pressing Enter on rm -rf /. Constrained agents. Safer code."
       width="480">
</p>

A strict, deterministic static-analysis quality gate for Python, JavaScript and
TypeScript.
Its one idea: unexpected failures, missing information, and unexplained
decisions must not silently become apparently valid program behavior.

Three default-on hard policies:

1. **Exception transparency.** No catch except at narrow, explicitly approved
   external boundaries. No catch-and-continue, no success-shaped fallbacks.
2. **No implicit defaults.** No fallback values for missing required data, no
   function-parameter defaults in strict mode.
3. **No magic numbers.** Every numeric literal in executable code must be
   exactly `0` or `1`. `range(2)` is a violation. The tool invents no exemptions.

Plus a separate, advisory complexity family (`CPLX001`-`CPLX006`: cyclomatic,
cognitive, nesting, NPath, a confidence-classified call graph with cycles and
fan-out, git churn and hotspots). Hard violations are never averaged into a
score; complexity never fails a plain `check`.

ShockHarness complements Ruff and ESLint; it is not a formatter or a general
linter. It runs offline, needs no LLM, and never uploads source.

## Status

Pre-release. Milestones A (skeleton and contracts), B (parsers and
`MAGIC001`), C (exception rules `EXC001`-`EXC003`), D (default and fallback
rules `DEF001`-`DEF006`), F (baselines, revision diff and gate, SARIF
output, git churn and co-change metrics, built-in profiles, the `check`
command, tag-triggered PyPI publishing, a reusable GitHub Actions workflow and
two consumer examples) and G (bundled agent skills, `skills install` /
`skills update` with a manifest, and a skill evaluation corpus) and E
(per-unit complexity metrics with versioned conventions, a call graph whose
edges are `resolved`, `probable` or `unresolved`, module cycles, fan-in/out,
shared-mutable-state notes, hotspots from churn and cognitive complexity, and
per-unit regressions in revision diffs) are implemented, as are the first five
milestones of the advanced guardrails: H1 (an explicit `unknown` finding status
and file roles), H2 (verification integrity: in a revision diff, report test
skips and focus markers, blanket suppressions, neutralized assertions and
looser policy, baselines, workflows or tool settings that a change adds; an
organization `--policy` file the repository cannot loosen; and a fifth agent
skill, `verification-integrity`), H3 (syntax-level guardrails: `return` in
`finally`, stubs and production imports of test doubles, removable asserts,
positional Boolean flags, module state written from functions, side effects at
import time; advisory until their precision is measured) and H4 (async lifecycle:
coroutines and Promises created and dropped, tasks started without an owner,
settled batches whose failures nobody checks; a sixth skill, `async-lifecycle`)
and H5 (API-catalog rules: shell commands from data and ignored exit statuses,
must-use results, type escape hatches, fixed sleeps, unbounded retries, batches
that drop failures, checks that always say yes).
`MAGIC002` is **not yet implemented**; every report lists unimplemented rules under
`rules_not_implemented` so a clean run never implies coverage the tool does
not have. See `STATUS.md` for exact evidence.

Implemented rules:

| ID | What it reports | Default |
|---|---|---|
| `MAGIC001` | numeric literal other than `0`/`1` in executable code | error |
| `EXC001` | catch outside an approved boundary (bare, broad, unresolved, untyped) | error |
| `EXC002` | handler that swallows, only logs, or replaces the exception without its cause | error |
| `EXC003` | approved `try` wrapping more than the one sanctioned operation | error |
| `EXC004` | `return`, `break` or `continue` that leaves a `finally` block, discarding the exception in flight | warning |
| `DEF001` | parameter default, dataclass field default / `default_factory` | error |
| `DEF002` | `m.get(k, v)`, `getattr(o, a, v)`, `o?.x ?? v`, `const {x = v} = o`; `.get(k)` implicit `None` as review | error |
| `DEF003` | `x or v`, `x || v` outside Boolean logic | review |
| `DEF004` | `x ?? v`, `x if x is not None else v` | error |
| `DEF005` | handler that returns a default (literal, module constant, one-return helper) | error |
| `DEF006` | `os.getenv("X", v)`, `process.env.X || v`, `const { X = v } = process.env` | error |
| `SUPP001` / `SUPP002` | malformed / unused suppression comment | error / warning |
| `CPLX001`-`CPLX004` | a unit's cyclomatic, cognitive, nesting or NPath number above its threshold (`docs/complexity.md`) | warning |
| `CPLX005` | module import cycle (one finding per cycle), or fan-out above `fan_out_warn` | warning (fan-out `review` in `recommended`) |
| `CPLX006` | a unit longer than `max_lines_warn` logical lines; module bodies exempt | warning |
| `VERIFY001` | a test skip, xfail or focus marker the change adds (needs `diff`/`gate --base`) | warning |
| `VERIFY002` | a blanket suppression comment the change adds (`# noqa`, `// eslint-disable`, `@ts-ignore`, ...) | warning |
| `VERIFY003` | a looser configuration, files dropped from analysis, baseline growth, a weakened ShockHarness workflow job, loosened ruff/flake8/pytest/coverage/ESLint settings; a key that loosens the `--policy` file (also in `check`) | warning |
| `VERIFY004` | an assertion the change makes unable to fail, or a test it empties | warning |
| `STUB001` | `raise NotImplementedError`, `raise NotImplemented`, an empty function body, `throw new Error("not implemented")` in production code (abstract API exempt) | warning |
| `STUB002` | production code importing a mocking or fake-data library or a module under `tests/`, `fixtures/`, `mocks/` | warning |
| `ASSERT001` | a Python `assert` in production code (removed under `python -O`); type-narrowing asserts allowed | warning |
| `BOOL001` | a `True`/`False` passed positionally to a call with several arguments | review |
| `STATE001` | a module-level mutable binding that functions assign or mutate | warning |
| `IMPORT001` | a process, network request, socket, thread or deletion started at import time | warning |
| `ASYNC001` | a coroutine or Promise created and dropped (an async call as a statement, `void`), across files | warning |
| `ASYNC002` | `asyncio.create_task(...)` with its handle dropped, outside a `TaskGroup` | warning |
| `ASYNC003` | `gather(return_exceptions=True)` / `Promise.allSettled` whose results are not checked for failure | warning |
| `PROCESS001` | a shell command built from data; a subprocess whose exit status nothing checks | warning |
| `RESULT001` | a must-use call used as a statement (`name.strip()`, `sorted(xs)`, `items.map(f)`) | warning |
| `TYPE001` | `Any`, `cast(...)`, `# type: ignore` (Python) | review |
| `SLEEP001` | a fixed sleep where a condition is needed (polling in a loop) | review |
| `RETRY001` | a retry with no limit (endless loop, unbounded `@retry`) | warning |
| `BATCH001` | a loop that drops per-item failures | warning |
| `STUB003` | a check (`is_admin`, `canEdit`) that always returns `True` | review |
| `ROLE001` | a test-role file that production code imports, or that holds no test (in a diff: a file newly classified as a test) | warning / review |

## Install

Requires Python 3.11+. Runtime dependencies are `tree-sitter` and
`tree-sitter-javascript` only. Pin an exact version; releases are tagged and
published to PyPI from `v*` tags (see `docs/releasing.md`).

```bash
pip install "shockharness==0.6.0"          # Python project: put the pin in pyproject.toml
uv tool install "shockharness==0.6.0"      # any project (JavaScript included): isolated tool env
pipx install "shockharness==0.6.0"
```

From a checkout:

```bash
uv pip install -e ".[dev]"
```

## Use

```bash
shockharness version                    # same as --version
shockharness init                       # writes .shockharness.toml (strict profile)
shockharness init --profile recommended # or minimal: a short file selecting the profile
shockharness config validate            # exit 0 if valid; prints the profile and every deviation
shockharness config effective           # merged config with per-key origins
shockharness check src/                 # human-readable report, exit = gate status
shockharness check src/ --summary       # first contact: findings by rule x directory, worst files, complexity counts; same gate line
shockharness check src/ --format json --output report.json
shockharness check src/ --format sarif --output report.sarif  # GitHub code scanning
shockharness check src/ --profile minimal                      # try a profile without editing config
shockharness check src/ --parse-errors warn                    # the only other CLI override
shockharness check src/ --exit-zero                            # advisory: full report, exit 0 on violations
shockharness check src/ --no-cache                             # bypass the content-hash cache (.shockharness-cache/) for one run
shockharness baseline create src/ --output .shockharness-baseline.json
shockharness check src/ --baseline .shockharness-baseline.json # legacy findings do not gate
shockharness diff --base main --head HEAD                      # new / fixed / unchanged, exit 0
shockharness gate --base main --head HEAD                      # exit 1 only on new hard violations
shockharness exceptions src/                                   # every suppression, boundary, override, exclusion and baseline entry, with its source (exit 0)
shockharness rules list
shockharness rules explain MAGIC001
shockharness skills list                                       # the six bundled agent skills
shockharness skills install --agent claude                     # .claude/skills/<name>/SKILL.md + manifest
shockharness skills update --agent claude --check              # exit 1 when a skill is stale or edited
```

`check` is the canonical analysis command; `scan`, the name used before
Milestone F, still works as a hidden alias with identical arguments.

Baselines are reviewed files of stable finding fingerprints (rule, path,
scope, whitespace-free evidence, occurrence index) that survive line moves;
nothing ever updates one automatically. `diff` and `gate` compare the full
trees of two **committed** revisions through local git only (uncommitted
changes are not part of `HEAD`). Every CLI report also carries
`metrics.history`: per-file churn and co-change pairs from local `git log`,
at file granularity, never gating, and explicitly `unavailable` outside a
repository.

Exit codes: `0` gates pass, `1` policy violations, `2` invalid configuration or
invocation, `3` internal error or (with `parse_errors = "fail"`) a file that
could not be parsed. A report is still produced when the gate fails.

Example:

```text
src/client.py:12:11: MAGIC001 error: Numeric literal 30 has no permitted justification in executable code  [timeout = 30]
src/client.py:15:24: DEF001 error: parameter 'port' of connect() has a default value: 5432  [def connect(host, port=5432):]
src/client.py:18:15: DEF006 error: environment variable "RETRIES" falls back to "3"; os.getenv(...) substitutes a fallback when environment variable "RETRIES" is unset (getenv)  [retries = os.getenv("RETRIES", "3")]
src/client.py:24:5: DEF005 error: except handler converts the exception into a fallback value: return None (EXC002 classification return_fallback; the handler is reported once, here)  [except OSError:]
src/client.py:24:5: EXC001 error: except handler of 'OSError' is forbidden: catch of 'OSError' is not approved by any boundary for this file  [except OSError:]

shockharness 0.6.0: 1 file(s), 1 analyzed, 0 failed; 5 finding(s), 0 suppressed
  by severity: error=5
  rules applied: MAGIC001, EXC001, EXC002, EXC003, DEF001, DEF002, DEF003, DEF004, DEF005, DEF006, CPLX001, CPLX002, CPLX003, CPLX004, CPLX005, CPLX006, SUPP001, SUPP002
  rules not implemented (not analyzed): MAGIC002
  complexity: 3 unit(s) in 1 file(s); conventions cyclomatic/1, cognitive/1, nesting/1, npath/1; 0 NPath saturated; advisory (CPLX001-CPLX004 and CPLX006 are warnings)
  graph: call edges 2 resolved, 1 probable, 1 unresolved; module edges 0 resolved, 2 external, 0 unresolved; 0 cycle(s); 0 shared mutable binding(s)
gate: FAIL (exit 1)
  5 hard violation(s) and gates.new_hard_violations = "fail"
```

## Profiles

Three built-in profiles ship with the package and are selected with
`profile = "..."` (or `--profile`): **`strict`** (default: every rule at its
documented severity, unparseable files fail), **`recommended`** (strict, but
`DEF003`/`DEF004` fallbacks are `review`, `-1` and module-level named constant
definitions such as `MAX_PAGES = 8` pass `MAGIC001`, fan-out is `review`
above 30, and `DEF*` findings the analyzer could not establish (`unknown`) are
reported without gating; included files no adapter parses are warned about, as
in strict),
**`minimal`** (`MAGIC001`, `EXC*` and `DEF*` all capped at `review`,
syntax failures warn, complexity off: everything is reported, nothing but
malformed suppressions fails). Precedence
is bundled defaults < profile < repository configuration < `--profile` /
`--parse-errors`. Any profile below `strict` is printed as a policy deviation
in every report, and the report's `effective_profile` names it.

## Adopting ShockHarness

This section is written for a coding agent (or a person) that was told to set
up ShockHarness in a repository and is reading it over HTTP. It is complete on
its own: nothing here depends on another page, and the detailed documents are
linked with absolute URLs at the end. Run every command from the repository
root.

### Step 1: install a pinned version

The version is always an exact pin; nothing updates to `latest`. Pick one:

```bash
uv tool install 'shockharness==0.6.0'                    # isolated tool environment; any repository, JavaScript included
uvx --from 'shockharness==0.6.0' shockharness version     # one-off run, nothing installed
pip install 'shockharness==0.6.0'                        # Python project: keep the pin in pyproject.toml (a dev extra) or requirements-dev.txt
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
    uses: evolvingstuff/ShockHarness/.github/workflows/check.yml@v0.6.0
    permissions:
      contents: read
      security-events: write
    with:
      shockharness-version: "0.6.0"
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
| Install | `shockharness version` | `shockharness 0.6.0` |
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

## Configuration

`.shockharness.toml` or `shockharness.toml` (one of them; both is an error) or
a `[tool.shockharness]` table in `pyproject.toml` (the dedicated file wins and
the shadowed table is reported). Unknown keys, bad types, unknown rule IDs,
and invalid globs are errors, never ignored. Every rule can be disabled; every
disable is listed in the report. Per-file results are cached under
`.shockharness-cache/` (add it to `.gitignore`; `cache.enabled = false` or
`--no-cache` turns it off; a warm run only redoes the cross-file work).

```toml
[tool.shockharness]
profile = "strict"
include = ["src/**/*.py", "src/**/*.js"]
exclude = ["**/node_modules/**", "**/.venv/**"]
parse_errors = "fail"

[tool.shockharness.rules.magic_numbers]
enabled = true
allowed_values = [0, 1]
allow_unary_negative_one = false

[[tool.shockharness.overrides]]
roles = ["test"]          # or paths = ["tests/**"]; exactly one of the two
disable = ["MAGIC001"]
reason = "Fixtures encode literal expected outputs"
```

Every file gets one **role** (`generated`, `vendor`, `config`, `test`, `docs`,
else `production`) from the `[tool.shockharness.file_roles]` globs, first match
in that order; the defaults cover `tests/**`, `**/test_*.py`, `**/*.test.js`,
`docs/**`, `**/vendor/**` and the like. Roles label files in the report and
scope overrides and the MAGIC001 configuration-file exemption; they never
change what is analyzed. Every finding has a `status`: `violation`, or
`unknown` when the rule could not establish the property (an exception type
that does not resolve, a `.get(k, v)` on a receiver not proven a mapping).
`fail_on_unknown` per rule family decides whether unknown findings gate; the
exceptions and defaults families keep failing closed by default. See
[docs/configuration.md](docs/configuration.md#file-roles).

Inline suppressions need an exact rule ID and a reason, on the same line:

```python
status = 404  # shockharness: ignore[MAGIC001] reason="RFC 9110 section 15.5.5"
```

A malformed suppression is a `SUPP001` error; one that silences nothing is a
`SUPP002` warning. `--no-inline-suppressions` disables them for centrally
governed policies.

## CI

Direct invocation works on any CI system: install the pin, run
`shockharness check .` (or `gate --base <base> --head HEAD` on pull requests).
GitHub users can call the reusable workflow, pinned to a tag or a full commit
SHA; the analyzer version is the `shockharness-version` input, not the ref:

```yaml
jobs:
  shockharness:
    uses: evolvingstuff/ShockHarness/.github/workflows/check.yml@v0.6.0
    permissions:
      contents: read
      security-events: write
    with:
      shockharness-version: "0.6.0"
```

It uploads SARIF to code scanning. Keep the version pin in `pyproject.toml`, a
requirements file or that workflow input, never in a shell string, so
Dependabot can open upgrade PRs; `docs/integration.md` has the full recipe and
a Dependabot snippet, and `examples/python` and `examples/js` are complete
consumers exercised by CI. Restoring `.shockharness-cache/` between jobs is
optional and safe: an entry from another tool version, configuration or
interpreter is invalidated, never used.

A project tested on Python 3.10 runs the gate as its own job on 3.11+
([integration.md, section 4](docs/integration.md#4-ci)); an empty tree passes
with `0 file(s)` ([integration.md, section 3](docs/integration.md#3-run-it));
and [limitations.md](docs/limitations.md#empty-trees-and-checks-a-layered-checker-may-still-need)
lists the checks a layered checker should keep until the planned milestones
land. `shockharness exceptions` is the reviewer's view of every exception the
code and configuration make ([configuration.md](docs/configuration.md#reporting-of-policy-changes)).

See `docs/` for configuration, rules, complexity conventions, architecture,
integration, skills, releasing, and limitations; `evals/` holds the skill
evaluation corpus. Every JSON report carries `metrics.complexity` (per-unit
numbers, conventions, thresholds, per-file totals), `metrics.graph` (edges
with confidence, module edges, cycles, fan-in/out, shared mutable state) and
`metrics.history` (churn, co-change, hotspots); none of them gates.

## Library

```python
from pathlib import Path
from shockharness import analyze_paths
from shockharness.analysis import CACHE_CONFIGURED, AnalysisOptions
from shockharness.config import load_config

config = load_config(Path("."), None)
options = AnalysisOptions(inline_suppressions=True, cache=CACHE_CONFIGURED)  # or CACHE_BYPASSED
report = analyze_paths([Path("src")], Path("."), config, options)
print(report.gate.status, len(report.findings))

# Optional: apply a reviewed baseline and attach git history metrics.
from shockharness.api import apply_baseline, with_history
from shockharness.gating.baseline import load_baseline

report = apply_baseline(report, load_baseline(Path(".shockharness-baseline.json")), config)
report = with_history(report, Path("."), "HEAD", config)
```

## Development

```bash
uv pip install -e ".[dev]"
pytest -q
ruff check src tests scripts evals && ruff format --check src tests scripts evals
shockharness check src tests scripts evals   # the tool gates its own source
python -m build && python scripts/consumer_upgrade_check.py --dist dist --examples examples
python evals/run_evals.py --reference   # the skill eval corpus: every reference solution scores clean
```

ShockHarness runs on itself as a hard CI gate. Its one `MAGIC001` exemption is
`src/shockharness/constants.py`; its declared exception boundaries are listed in
`.shockharness.toml` with reasons and enforced by `EXC001`-`EXC003`: every
`try` in the tool wraps exactly one external call and converts the failure into
a typed diagnostic. `DEF001`-`DEF006` hold too: the tool has no parameter
defaults outside tests, no mapping fallbacks, and no `or`/`is None` defaults.

## License

MIT. See `LICENSE`.
