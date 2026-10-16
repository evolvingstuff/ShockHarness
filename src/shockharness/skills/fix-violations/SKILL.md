---
name: fix-violations
description: Repair ShockHarness findings (MAGIC001, EXC001-EXC003, DEF001-DEF006, SUPP001/SUPP002) without masking behavior. Use when shockharness check or gate exits 1, when a CI job running ShockHarness fails, or when asked to clean up magic numbers, broad catches, parameter defaults or fallback values. Covers running the analyzer, finding the intended contract behind each finding, adding a characterization test, changing the code, rerunning tests and analyzer, and the rules for suppressions.
---

# Fix violations

A ShockHarness finding says that code hides a decision: a number with no
contract, a failure turned into a value, a missing value silently replaced.
Fixing it means making the decision explicit, not making the finding go away.
This skill is the corrective workflow; `write-compliant-code` is the
preventive one and `pre-commit-review` is the final check.

## Never do these

- **Never delete a `try`/`except` or `try`/`catch` to satisfy `EXC001`** without
  deciding, and writing down, what the caller must now handle. Removing the
  catch may be right (the failure should propagate) or may hide that a
  boundary is missing from `.shockharness.toml`.
- **Never replace `.get(key, default)` with `[key]` mechanically** to satisfy
  `DEF002`. Indexing turns a silent default into a `KeyError`, which is correct
  only if the key is required. If it is optional, the type must say so and the
  code must branch on absence explicitly.
- **Never add a suppression without a contract review.** A suppression needs an
  exact rule ID and a reason that cites a source (`# shockharness:
  ignore[MAGIC001] reason="RFC 9110 section 15.5.5"`). "Legacy", "TODO" and
  "false positive" are not reasons. A malformed suppression is a `SUPP001`
  error; one that silences nothing is a `SUPP002` warning.
- **Never widen a boundary, loosen a profile or lower a severity to get green.**
  Those are policy changes; propose them with a recorded rationale.
- **Never move a number into an unexplained constant** (`THIRTY = 30`). The
  name must say what the value means and where it comes from.

## Workflow

### 1. Run the analyzer and read the whole report

```bash
shockharness check .                                  # text report, exit 1 on violations
shockharness check . --format json --output report.json
shockharness rules explain EXC003                     # guarantees, limitations, remediation for one rule
```

Each finding line is `path:line:col: RULE severity: message  [evidence]`; an
*unknown* finding reads `RULE severity (unknown): ...` (JSON: `"status":
"unknown"`). The message names the construct, the confidence (`exact`,
`approximate`, `unresolved`) and, for `EXC001`, why no boundary applies.
The `unknown:` trailer line counts unknown findings and names the families
whose `fail_on_unknown` makes them gate. Also read the
`config:` line (profile, deviations) and the `rules not implemented (not
analyzed)` line, so you know what was not checked.

### 2. For each finding, identify the intended contract

Ask what the code promises when the value is absent or the operation fails.

| Finding | Question | Typical answer |
|---|---|---|
| `MAGIC001` | Why this number? Who decides it? | Variable policy: a required, validated configuration parameter. Invariant or protocol value: a named constant with a cited source, in a designated constants module or with an inline suppression quoting the source. |
| `DEF001` | May the caller really omit this argument? | Usually no: make it required and update the callers. If yes: the type is `T \| None`, and the body branches on `None` by name. |
| `DEF002`, `DEF004`, `DEF003` | Is the key or value required? Is absence a normal state? | Required: index it, let `KeyError`/`TypeError` surface at load time, or validate once at the boundary. Absence is a normal state (an empty view has no root entry, an unused tag has no posting): branch explicitly (`if "x" in raw:`) with a comment, or call a small named helper whose name says what absence means (`posting_or_empty`); do not force an index there, that turns a normal state into a crash. From outside (configuration, a request): validate where it enters. |
| `DEF006` | Where is configuration validated? | In one load function that reads required keys, validates them and raises on a missing or invalid value. Nothing downstream reads the environment. |
| `EXC001`, `EXC003` | Is this really an external boundary? | External (file, network, subprocess, decoding external input): declare a boundary with `path`, `language`, qualified `exception`, `reason`; keep one operation inside the `try`; re-raise a typed error with `from exc`. Internal: remove the catch and fix the cause or let it propagate. |
| `EXC002`, `DEF005` | What should the caller see when this fails? | A typed error. Not `None`, not `[]`, not a logged line and a continue. |
| `SUPP001`, `SUPP002` | Is the suppression still justified? | Fix the comment syntax, or delete a suppression that no longer silences anything. |
| `EXC004` | Should the exception really disappear? | No: move the `return` after the `try`; keep `finally` to cleanup. If it must be discarded, catch the type at a declared boundary. |
| `STUB001` | What should this do? | Implement it, delete the unused entry point, or stop and say the behavior is underspecified. Never write a plausible fake. An abstract method is `@abstractmethod` on an ABC or a `Protocol`. |
| `STUB002` | Why does production depend on a test double? | Invert it: production defines the interface, tests inject the double. A real production module under `tests/` moves. |
| `ASSERT001` | Must this check survive `python -O`? | Yes for input, permissions and state: `if not ok: raise ValueError(...)`. A type-narrowing `assert x is not None` is allowed. |
| `BOOL001` | What does the flag switch? | Pass it by keyword (`escape=True`) or in an options object; a flag that selects behavior may be two functions. |
| `STATE001` | Who owns this state? Does it need to change at all? | A fixed table becomes a `tuple`/`frozenset`/`Object.freeze`d value (`write-compliant-code`, principle 8). Otherwise an object the caller creates and passes in, or a new value returned. A deliberate cache goes in `[[rules.module_state.allowed]]` with its reason. |
| `IMPORT001` | Who asked for this effect? | Move it into a function the entry point calls (`main()`, a factory, `start()`). |

An **unknown** finding means the rule could not establish the property, not
that the code is fine or that it is wrong. Treat it as a request for the
missing information, and supply it:

| Unknown finding | What could not be determined | Supply it by |
|---|---|---|
| `EXC001`, an exception type that does not resolve | which class the handler catches | Import the exception class by name (`from pkg.errors import FetchError`), or catch the class directly instead of a variable, call or subscript; then declare the boundary for that qualified name if the catch is a real boundary |
| `EXC001`, an opaque promise rejection handler | whether the handler checks the error class and rethrows the rest | Write the handler inline, or define it at the top level of the same module, with the `instanceof` guard and rethrow |
| `EXC001`, a `with` whose capture manager cannot be established, or a manager with no readable exception type | which exceptions the block captures | Construct the manager in the `with` itself (`with Manager(TimeoutError):`), pass the exception classes as plain arguments, and list the manager in `rules.exceptions.capture_managers` |
| `DEF002` on a receiver not proven a mapping | whether `.get(k, v)` is a mapping fallback at all | Annotate or construct the receiver as a mapping (`table: dict[str, int] = {}`), after which the finding is a plain violation to fix as above; if the receiver is not a mapping (an HTTP client), restructure the call (keyword arguments) or suppress with a reason naming the receiver's real type |

Never suppress an unknown finding without stating what could not be
determined and why it is acceptable: the reason must name the missing fact
(`reason="session is requests.Session; .get(url, params) is an HTTP call, not a
mapping fallback"`). Never set `fail_on_unknown = false` to get green; it is a
policy deviation like any other loosening.

### 3. Add a characterization test first

Before changing the code, write a test that pins the behavior you intend:
the missing key raises, the invalid value raises with a clear message, the
timeout surfaces as the typed error, the explicit page size is honored. Run
it; it should fail on the current code when the current behavior is wrong, or
pass when you are only removing an implicit path. Either way it protects the
contract through the change.

### 4. Change the code

Make the smallest change that states the contract. Update every caller that
relied on the default. Prefer a required settings object loaded once over
threading new parameters through many signatures.

### 5. Rerun tests and analyzer

```bash
pytest -q                       # or: node --test
shockharness check .
```

Both must pass. Then, if the repository gates pull requests:

```bash
shockharness gate --base origin/main --head HEAD    # after committing; exit 1 only on new hard violations
```

## Worked examples

### Python: `MAGIC001` + `DEF001` + `DEF006`

Finding lines:

```text
src/app/pages.py:3:36: DEF001 error: parameter 'page_size' of paginate() has a default value: 10  [def paginate(items, page_size=10):]
src/app/pages.py:3:36: MAGIC001 error: Numeric literal 10 has no permitted justification in executable code  [def paginate(items, page_size=10):]
src/app/settings.py:6:19: DEF006 error: environment variable "PAGE_SIZE" falls back to "10"; os.getenv(...) substitutes a fallback when environment variable "PAGE_SIZE" is unset (getenv)  [page_size = int(os.getenv("PAGE_SIZE", "10"))]
```

Contract: the page size is operator policy, so it is a required, validated
setting; the function takes it explicitly. Characterization test:

```python
def test_page_size_is_required() -> None:
    with pytest.raises(KeyError):
        load_settings({})
    with pytest.raises(ValueError, match="PAGE_SIZE"):
        load_settings({"PAGE_SIZE": "0"})
    assert paginate(["a", "b", "c"], load_settings({"PAGE_SIZE": "2"}).page_size) == [["a", "b"], ["c"]]
```

Fix:

```python
def load_settings(raw: Mapping[str, str]) -> Settings:
    page_size = int(raw["PAGE_SIZE"])
    if page_size < 1:
        raise ValueError(f"PAGE_SIZE must be at least 1, got {page_size}")
    return Settings(page_size=page_size)

def paginate(items: list[str], page_size: int) -> list[list[str]]:
    if page_size < 1:
        raise ValueError(f"page_size must be at least 1, got {page_size}")
    return [items[start : start + page_size] for start in range(0, len(items), page_size)]
```

### Python: `EXC001` + `DEF005` at a real boundary

```text
src/app/store.py:9:5: DEF005 error: except handler converts the exception into a fallback value: return {} (EXC002 classification return_fallback; the handler is reported once, here)  [except json.JSONDecodeError:]
src/app/store.py:9:5: EXC001 error: except handler of 'json.JSONDecodeError' is forbidden: catch of 'json.JSONDecodeError' is not approved by any boundary for this file  [except json.JSONDecodeError:]
```

Decoding a file is external input, so a boundary is legitimate. Declare it:

```toml
[[tool.shockharness.rules.exceptions.boundaries]]
path = "src/app/store.py"
language = "python"
exception = "json.JSONDecodeError"
reason = "Store file content is external input; malformed JSON becomes a typed StoreError"
```

Keep one operation inside the `try` (`EXC003`) and raise a typed error with its
cause instead of returning `{}`:

```python
def load_store(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    # Boundary (declared in .shockharness.toml): decoding external input.
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StoreError(f"{path}: malformed store file: {exc}") from exc
    if not isinstance(data, dict):
        raise StoreError(f"{path}: store must be a JSON object")
    return data
```

Characterization test: a malformed file raises `StoreError` whose message
names the path; a valid file loads.

### JavaScript: `DEF002` + `MAGIC001` + untyped `catch`

```text
src/config.js:2:19: DEF002 error: env.REQUEST_TIMEOUT_MS falls back to 2500; '??' substitutes a fallback when the property or lookup result is null or undefined  [const timeout = env.REQUEST_TIMEOUT_MS ?? 2500;]
src/config.js:2:45: MAGIC001 error: Numeric literal 2500 has no permitted justification in executable code  [const timeout = env.REQUEST_TIMEOUT_MS ?? 2500;]
src/http.js:4:5: DEF005 error: catch clause converts the exception into a fallback value: return null; (EXC002 classification return_fallback; the handler is reported once, here)  [} catch (err) {]
src/http.js:4:5: EXC001 error: catch clause is forbidden: untyped catch binds every error; a JavaScript catch passes only inside an approved boundary whose error class the handler checks with instanceof and otherwise rethrows  [} catch (err) {]
```

(`env.X ?? v` on a parameter is `DEF002`; the same fallback written as
`process.env.X ?? v` is `DEF006`.)

Fix the configuration read so the value is required and validated once:

```javascript
export function loadConfig(env) {
  const raw = env.REQUEST_TIMEOUT_MS;
  const timeout = Number(raw);
  if (!Number.isFinite(timeout) || timeout <= 0) {
    throw new TypeError(`REQUEST_TIMEOUT_MS must be a positive number, got ${raw}`);
  }
  return Object.freeze({ requestTimeoutMs: timeout });
}
```

Decide the failure contract for `fetchJson`. If the caller should see the
failure, remove the catch:

```javascript
export async function fetchJson(url) {
  const response = await fetch(url);
  return response.json();
}
```

If a specific failure is a boundary, declare it with an error class and use
the guard convention (`if (!(err instanceof TimeoutError)) throw err;` as the
first statement) and re-throw a typed error; never return `null`.

Characterization test (`node --test`):

```javascript
test("config is required", () => {
  assert.equal(loadConfig({ REQUEST_TIMEOUT_MS: "2500" }).requestTimeoutMs, 2500);
  assert.throws(() => loadConfig({}), TypeError);
});
```

### Python and JavaScript: `DEF002` where absence is a normal state

A tag that no note carries has no posting. Indexing would raise for a
legitimate state; a fallback would hide a typo in the tag. Say what absence
means, once, in a helper:

```python
def posting_or_empty(index: dict[str, list[str]], tag: str) -> list[str]:
    # A tag that no note carries has no posting; absence is a normal state here.
    if tag in index:
        return index[tag]
    return []
```

```javascript
export function postingOrEmpty(index, tag) {
  // A tag that no note carries has no posting; absence is a normal state here.
  if (index.has(tag)) {
    return index.get(tag);
  }
  return [];
}
```

Removing an entry that may be absent reads the same way: `cache.pop(key, None)`
as a statement is a `DEF002` review finding of kind `discarded_removal`. If the
key is always present, write `del cache[key]` so a missing key fails; if absence
is normal, write `if key in cache: del cache[key]` and say why.

## Propose a rule

When you find a bug that ShockHarness did not report, write down the rule
that would have caught it, even if you fix the bug right away. A rule over a
syntactic pattern is better than a heuristic. Note:

- the pattern, as a minimal triggering example in the language it occurred in;
- why it is a bug (what the program did instead of failing);
- the proposed rule, and how it decides (which call, which argument, which
  missing check);
- the false positives you expect, and what would keep the rule quiet on them.

Put the note wherever the project collects tooling feedback (an issue, a
notes file the maintainers read). Do not edit the analyzer, its configuration
or a baseline to act on it.

## When a suppression is the right fix

Only for a value whose meaning comes from an authority outside the codebase
and whose literal form is the clearest representation: an HTTP status, a
well-known port, a unit conversion defined by a standard. Cite the source:

```python
NOT_FOUND = 404  # shockharness: ignore[MAGIC001] reason="RFC 9110 section 15.5.5"
```

```javascript
export const NOT_FOUND = 404; // shockharness: ignore[MAGIC001] reason="RFC 9110 section 15.5.5"
```

The suppression sits on the same line as the finding, names exactly one rule
ID that exists (`shockharness rules list`), and carries a quoted reason. The
finding remains in every report, marked suppressed; the count of suppressions
is part of the report, and reviewers read it.

## Checklist

- [ ] The full report was read, including `config:` deviations and the rules not analyzed.
- [ ] Each finding has a stated contract (required value, typed error, optional branch, cited constant).
- [ ] Each unknown finding was answered by supplying the missing information (resolvable import, inline or module-level handler, configured manager, typed receiver), or suppressed with a reason that names what could not be determined.
- [ ] A characterization test exists for each changed contract and runs green.
- [ ] No `try`/`except` was deleted, no `.get` replaced with indexing, no suppression added without the contract decision written in the commit or review.
- [ ] Any new boundary has `path`, `language`, qualified `exception` and a `reason`, and its `try` wraps one operation.
- [ ] Every suppression has an exact rule ID and a reason that cites a source.
- [ ] Tests and `shockharness check .` both pass; `gate --base <default branch> --head HEAD` passes after committing.
- [ ] Any bug found along the way that ShockHarness did not report has a written rule proposal (pattern, why it is a bug, the rule, expected false positives).

## Adopting ShockHarness

This section is written for a coding agent (or a person) that was told to set
up ShockHarness in a repository and is reading it over HTTP. It is complete on
its own: nothing here depends on another page, and the detailed documents are
linked with absolute URLs at the end. Run every command from the repository
root.

### Step 1: install a pinned version

The version is always an exact pin; nothing updates to `latest`. Pick one:

```bash
uv tool install 'shockharness==0.5.0'                    # isolated tool environment; any repository, JavaScript included
uvx --from 'shockharness==0.5.0' shockharness version     # one-off run, nothing installed
pip install 'shockharness==0.5.0'                        # Python project: keep the pin in pyproject.toml (a dev extra) or requirements-dev.txt
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
    uses: evolvingstuff/ShockHarness/.github/workflows/check.yml@v0.5.0
    permissions:
      contents: read
      security-events: write
    with:
      shockharness-version: "0.5.0"
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
| Install | `shockharness version` | `shockharness 0.5.0` |
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
