---
name: write-compliant-code
description: Write new Python or JavaScript that passes the ShockHarness quality gate on the first run. Use when adding or changing executable code in a repository that runs shockharness. Covers clear contracts, no catch outside a declared boundary, no parameter defaults or fallback values, no numeric literal other than 0 or 1, named constants for meaningful 0/1 values, and keeping data, configuration and specification files separate from source.
---

# Write compliant code

ShockHarness (`shockharness check`) is a deterministic static-analysis gate for
Python and JavaScript. Its one idea: unexpected failures, missing information
and unexplained decisions must not silently become apparently valid program
behavior. This skill is for writing code that passes the gate the first time.
Use `fix-violations` for existing findings and `pre-commit-review` before you
commit.

## The contract you are writing to

Three hard policies are on by default in the `strict` profile. Each rule below
is quoted from `shockharness rules explain <ID>`; run that command when you need
the full detection guarantees.

| Rule | What fails | Default |
|---|---|---|
| `MAGIC001` | a numeric literal other than exactly `0` or `1` in executable code (`2`, `-1`, `1.5`, `0x10`, `10n`, a literal inside a Python type annotation) | error |
| `EXC001` | a catch outside an approved boundary: bare `except:`, `except Exception`, an untyped JavaScript `catch (e)`, or any catch in a file no boundary covers | error |
| `EXC002` | a handler that swallows the exception, only logs it, or replaces it without its cause | error |
| `EXC003` | an approved `try` whose body does more than the one operation the boundary sanctions | error |
| `DEF001` | a function parameter default (`def f(a, b=1)`, `function f(a = 1)`), a dataclass field default or `default_factory` | error |
| `DEF002` | `m.get(k, v)`, `getattr(o, a, v)`, `o?.x ?? v`, `const {x = v} = o`; `m.get(k)` with its implicit `None` is a review finding | error |
| `DEF003` | `x or v`, `x \|\| v` used as a value rather than as Boolean logic | review |
| `DEF004` | `x ?? v`, `x if x is not None else v` | error |
| `DEF005` | a handler that returns a default value instead of failing | error |
| `DEF006` | `os.getenv("X", v)`, `process.env.X \|\| v`, `const { X = v } = process.env` | error |
| `SUPP001` / `SUPP002` | a malformed suppression comment / one that silences nothing | error / warning |
| `EXC004` | `return`, `break` or `continue` that leaves a `finally` block | warning |
| `STUB001` / `STUB002` | a stub (`raise NotImplementedError`, an empty body, `throw new Error("not implemented")`) / an import of a mock or test module in production code | warning |
| `ASSERT001` | a Python `assert` used as a runtime check (removed under `-O`) | warning |
| `BOOL001` | `f(x, True, False)`: pass flags by keyword or an options object | review |
| `STATE001` / `IMPORT001` | module state written from functions / a side effect at import time | warning |

A clean report says `gate: PASS (exit 0)`. Exit `1` is a policy violation, `2`
an invalid configuration or invocation, `3` a tool failure or, under
`parse_errors = "fail"`, a file that could not be parsed. Every report also
lists `rules not implemented (not analyzed)`: `MAGIC002` is registered but
produces no findings yet, so a clean run never implies it was checked. The
complexity family (`CPLX001`-`CPLX006`) is advisory: warnings that never fail
a plain `check`; see the `refactor-complexity` skill.

## Principles

1. **Make the contract explicit.** Every value a function needs is a required
   parameter or a validated field of a settings object. Every failure is a
   raised, typed error. If a caller may omit something, the type says so
   (`int | None`) and the code branches on it explicitly, naming what it does.
2. **No catch outside a declared boundary.** A boundary is a
   `[[tool.shockharness.rules.exceptions.boundaries]]` entry in
   `.shockharness.toml` with `path`, `language`, the qualified `exception` and a
   `reason`. Boundaries are where the program meets the outside world: reading
   a file, decoding external input, a network call, a subprocess. Inside the
   boundary the `try` wraps exactly one operation and the handler converts the
   failure into a typed error the caller must handle; it never returns a
   success-shaped value.
3. **No defaults, no fallbacks.** Do not write `b=1`, `.get(k, v)`, `x or v`,
   `x ?? v`, `os.getenv("X", "3")`, `process.env.PORT || 3000`. Read required
   data with indexing (`raw["PORT"]`, `env.PORT` followed by validation) so a
   missing value fails loudly, once, at load time.
4. **No numeric literal other than 0 or 1.** A number in code needs a contract:
   variable policy (timeouts, limits, page sizes) becomes a required,
   validated configuration parameter; invariant mathematics or a published
   protocol value becomes a named constant that cites its source, kept in a
   designated constants module or suppressed inline with the citation as the
   reason. Never move a number into an unexplained constant.
5. **Name a 0 or 1 that carries meaning.** The rule permits `0` and `1`, it does
   not recommend them. An exit code, a sentinel, a flag, a first page, a
   protocol value: give it a name (`EXIT_OK = 0`, `FIRST_PAGE = 1`). Plain
   arithmetic identity stays literal: `i + 1`, `len(x) - 1`, `range(0, n)`,
   `x ** 0`, `start = 0`.
6. **Separate source from data, configuration and specification.** Numbers
   belong in `.toml`, `.json`, `.env.example`, a schema, or a constants module
   that is declared as such. In the tool's own repository the single
   `MAGIC001` exemption is `src/shockharness/constants.py`, declared as an
   `[[tool.shockharness.overrides]]` entry with a reason. Build-tool
   configuration files (`conftest.py`, `*.config.js`, `.eslintrc.js`, listed
   under `rules.magic_numbers.configuration_files`) are exempt from `MAGIC001`
   and the report says so per file.
7. **Validate what you return, not only what you receive.** When a function's
   contract promises something about its result (non-empty, sorted, within a
   range, exactly the expected keys), check it before returning and raise on
   violation. The check states the promise in code, and a broken promise fails
   where it is broken instead of in a caller. Never turn the check into a
   fallback (`return result or []`).

   ```python
   def page_of(items: list[str], page: int, size: int) -> list[str]:
       if page < FIRST_PAGE or size < 1:
           raise ValueError(f"page {page} of size {size} is not a valid page")
       result = items[(page - FIRST_PAGE) * size : page * size]
       if len(result) > size:
           raise AssertionError(f"page holds {len(result)} items, more than {size}")
       return result
   ```

   ```javascript
   export function sortedIds(records) {
     const ids = records.map((record) => record.id).sort();
     if (new Set(ids).size !== ids.length) {
       throw new Error("record ids are not unique");
     }
     return ids;
   }
   ```
8. **Prefer immutable values.** A value nobody can change needs no owner, cannot
   be altered behind a caller's back, and makes the order of calls irrelevant.
   Build data once and hand it on: `@dataclass(frozen=True)` for records,
   `tuple` and `frozenset` (or a `Mapping` you never write to) for collections,
   `Object.freeze` and `const` in JavaScript. When a function needs a changed
   value, prefer returning a new one (`dataclasses.replace`, a new tuple,
   `{...obj, x}`) over mutating its input. Mutating local variables, and objects
   the function itself created, is fine: a list built up in a loop, a dict
   filled before it is returned. Mutating what other code can also see (a
   function's inputs, shared values, module-level state that functions write,
   which is `STATE001`) is discouraged rather than forbidden: when it is the
   clearer design, say so in the function's name or docstring.

   ```python
   from dataclasses import dataclass, replace


   @dataclass(frozen=True)
   class Order:
       items: tuple[str, ...]
       paid: bool


   def with_item(order: Order, item: str) -> Order:
       return replace(order, items=(*order.items, item))  # the caller's order is unchanged


   ALLOWED_CURRENCIES = frozenset({"EUR", "USD"})
   ```

   ```javascript
   export const ALLOWED_CURRENCIES = Object.freeze(["EUR", "USD"]);

   export function withItem(order, item) {
     return Object.freeze({ ...order, items: [...order.items, item] });
   }
   ```

   Fine: `totals = {}` filled in a loop and returned. Discouraged: `def
   add_item(order, item): order.items.append(item)`, which changes every holder
   of `order`, and `function markPaid(order) { order.paid = true; }`, which a
   caller cannot see coming from the call site.

## Examples

### Python

Non-compliant (five findings):

```python
import os

def fetch(url, timeout=30):                      # DEF001 (timeout=30), MAGIC001 (30)
    retries = int(os.getenv("RETRIES", "3"))     # DEF006
    try:
        return client.get(url, timeout=timeout)
    except Exception:                            # EXC001 broad catch, no boundary
        return None                              # DEF005 exception-to-default
```

Compliant:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class HttpSettings:
    timeout_seconds: float
    retries: int

def load_http_settings(raw: Mapping[str, str]) -> HttpSettings:
    """Build settings from a mapping such as os.environ; a missing key raises KeyError."""
    timeout = float(raw["REQUEST_TIMEOUT_SECONDS"])
    retries = int(raw["RETRIES"])
    if timeout <= 0:
        raise ValueError(f"REQUEST_TIMEOUT_SECONDS must be positive, got {timeout}")
    if retries < 0:
        raise ValueError(f"RETRIES must not be negative, got {retries}")
    return HttpSettings(timeout_seconds=timeout, retries=retries)

def fetch(client: Client, url: str, settings: HttpSettings) -> Response:
    return client.get(url, timeout=settings.timeout_seconds)   # a failure propagates, typed, to the caller
```

If `client.get` must be caught (a network boundary), declare it and keep the
`try` to that single call:

```toml
[[tool.shockharness.rules.exceptions.boundaries]]
path = "src/app/http.py"
language = "python"
exception = "requests.exceptions.Timeout"
reason = "Network I/O; a timeout becomes a typed FetchError the caller handles"
```

```python
def fetch(client: Client, url: str, settings: HttpSettings) -> Response:
    # Boundary (declared in .shockharness.toml): one network call.
    try:
        response = client.get(url, timeout=settings.timeout_seconds)
    except requests.exceptions.Timeout as exc:
        raise FetchError(url, settings.timeout_seconds) from exc
    return response
```

A meaningful 0 or 1 gets a name even though the rule allows it:

```python
EXIT_OK = 0
EXIT_VIOLATIONS = 1

def main(argv: Sequence[str]) -> int:
    if run(argv):
        return EXIT_OK
    return EXIT_VIOLATIONS
```

### JavaScript

Non-compliant:

```javascript
export function loadConfig(env = process.env) {            // DEF001
  const port = Number(env.PORT || 3000);                    // DEF006, MAGIC001
  const { retries = 3 } = env;                              // DEF006, MAGIC001
  return { port, retries };
}

export async function fetchJson(url) {
  try {
    const response = await fetch(url);
    return await response.json();                           // EXC003 if a boundary existed: two operations
  } catch (err) {                                           // EXC001 untyped catch
    return null;                                            // DEF005
  }
}
```

Compliant:

```javascript
export function loadConfig(env) {
  const port = Number(env.PORT);
  if (!Number.isInteger(port) || port <= 0) {
    throw new TypeError(`PORT must be a positive integer, got ${env.PORT}`);
  }
  const retries = Number(env.RETRIES);
  if (!Number.isInteger(retries) || retries < 0) {
    throw new TypeError(`RETRIES must be a non-negative integer, got ${env.RETRIES}`);
  }
  return Object.freeze({ port, retries });
}

export async function fetchJson(url) {
  const response = await fetch(url);        // a rejection propagates to the caller
  return response.json();
}
```

A JavaScript `catch` has no type, so the convention for an approved boundary
is a guard that re-throws everything else as the handler's first statement:

```javascript
// Boundary (declared in .shockharness.toml, exception = "TimeoutError"): one call.
try {
  return await fetchWithTimeout(url, config.requestTimeoutMs);
} catch (err) {
  if (!(err instanceof TimeoutError)) throw err;
  throw new FetchError(url, err);
}
```

A protocol constant with an authoritative source may be suppressed inline, on
the same line, with an exact rule ID and a reason:

```javascript
export const NOT_FOUND = 404; // shockharness: ignore[MAGIC001] reason="RFC 9110 section 15.5.5"
```

The finding stays in every report with the suppression attached; only the
gate ignores it. A suppression with no rule ID, or a reason-less one, is a
`SUPP001` error; one that silences nothing is a `SUPP002` warning.

## Workflow

1. Before writing, read the repository's `.shockharness.toml`: which profile
   is active, which boundaries exist, which paths are overridden and why. Do
   not add a boundary or an override to make your code pass; propose it with a
   reason and let the review decide.
2. Write the contract first: required parameters, a validated settings
   object, typed errors. Then the code.
3. Run the analyzer on what you touched, then on the whole configured scope:

   ```bash
   shockharness check path/to/changed_file.py
   shockharness check .
   shockharness rules explain DEF002        # when a finding's message is not enough
   ```

4. Run the project's tests. A clean gate is not a working program.
5. For each remaining finding follow `fix-violations`; for the commit follow
   `pre-commit-review`.

## Checklist

- [ ] Every value the code needs is a required parameter or a validated settings field; no `=` default in a signature, no `.get(k, v)`, `or`, `??`, `getenv("X", v)`.
- [ ] No `try`/`catch` outside a boundary declared in `.shockharness.toml`; each approved `try` wraps one operation and re-raises a typed error with its cause.
- [ ] No numeric literal other than `0` or `1`; each number lives in configuration or a cited, named constant.
- [ ] Each `0` or `1` that means something (exit code, sentinel, flag) has a name.
- [ ] Data, configuration and specification live in data files or a declared constants module, not in executable source.
- [ ] `shockharness check .` ends in `gate: PASS (exit 0)` and the tests pass.
- [ ] Any suppression has an exact rule ID and a reason that cites a source.
- [ ] Each function whose result carries a promise (non-empty, sorted, bounded, a known key set) checks it before returning and raises on violation.
- [ ] Records are frozen and collections immutable where nothing needs to change them; functions prefer returning new values to mutating their inputs (local variables may be mutated freely), and any input they do mutate is named as such.

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
