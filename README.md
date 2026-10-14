# ShockHarness

A strict, deterministic static-analysis quality gate for Python and JavaScript.
Its one idea: unexpected failures, missing information, and unexplained
decisions must not silently become apparently valid program behavior.

Three default-on hard policies:

1. **Exception transparency.** No catch except at narrow, explicitly approved
   external boundaries. No catch-and-continue, no success-shaped fallbacks.
2. **No implicit defaults.** No fallback values for missing required data, no
   function-parameter defaults in strict mode.
3. **No magic numbers.** Every numeric literal in executable code must be
   exactly `0` or `1`. `range(2)` is a violation. The tool invents no exemptions.

Plus a separate, advisory complexity family (cyclomatic, cognitive, nesting,
NPath, call graph, churn). Hard violations are never averaged into a score.

ShockHarness complements Ruff and ESLint; it is not a formatter or a general
linter. It runs offline, needs no LLM, and never uploads source.

## Status

Pre-release. Milestones A (skeleton and contracts), B (parsers and
`MAGIC001`), C (exception rules `EXC001`-`EXC003`), D (default and fallback
rules `DEF001`-`DEF006`) and F (baselines, revision diff and gate, SARIF
output, git churn and co-change metrics, built-in profiles, the `check`
command, tag-triggered PyPI publishing, a reusable GitHub Actions workflow and
two consumer examples) are implemented. `MAGIC002`, complexity metrics, the
hotspot score and agent skills are **not yet implemented**; every report lists
unimplemented rules under `rules_not_implemented` so a clean run never implies
coverage the tool does not have. See `STATUS.md` for exact evidence.

Implemented rules:

| ID | What it reports | Default |
|---|---|---|
| `MAGIC001` | numeric literal other than `0`/`1` in executable code | error |
| `EXC001` | catch outside an approved boundary (bare, broad, unresolved, untyped) | error |
| `EXC002` | handler that swallows, only logs, or replaces the exception without its cause | error |
| `EXC003` | approved `try` wrapping more than the one sanctioned operation | error |
| `DEF001` | parameter default, dataclass field default / `default_factory` | error |
| `DEF002` | `m.get(k, v)`, `getattr(o, a, v)`, `o?.x ?? v`, `const {x = v} = o`; `.get(k)` implicit `None` as review | error |
| `DEF003` | `x or v`, `x || v` outside Boolean logic | review |
| `DEF004` | `x ?? v`, `x if x is not None else v` | error |
| `DEF005` | handler that returns a default (literal, module constant, one-return helper) | error |
| `DEF006` | `os.getenv("X", v)`, `process.env.X || v`, `const { X = v } = process.env` | error |
| `SUPP001` / `SUPP002` | malformed / unused suppression comment | error / warning |

## Install

Requires Python 3.11+. Runtime dependencies are `tree-sitter` and
`tree-sitter-javascript` only. Pin an exact version; releases are tagged and
published to PyPI from `v*` tags (see `docs/releasing.md`).

```bash
pip install "shockharness==0.1.0a1"          # Python project: put the pin in pyproject.toml
uv tool install "shockharness==0.1.0a1"      # any project (JavaScript included): isolated tool env
pipx install "shockharness==0.1.0a1"
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
shockharness check src/ --format json --output report.json
shockharness check src/ --format sarif --output report.sarif  # GitHub code scanning
shockharness check src/ --profile minimal                      # try a profile without editing config
shockharness check src/ --parse-errors warn                    # the only other CLI override
shockharness baseline create src/ --output .shockharness-baseline.json
shockharness check src/ --baseline .shockharness-baseline.json # legacy findings do not gate
shockharness diff --base main --head HEAD                      # new / fixed / unchanged, exit 0
shockharness gate --base main --head HEAD                      # exit 1 only on new hard violations
shockharness rules list
shockharness rules explain MAGIC001
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

shockharness 0.1.0: 1 file(s), 1 analyzed, 0 failed; 5 finding(s), 0 suppressed
  by severity: error=5
  rules applied: MAGIC001, EXC001, EXC002, EXC003, DEF001, DEF002, DEF003, DEF004, DEF005, DEF006, SUPP001, SUPP002
  rules not implemented (not analyzed): MAGIC002, CPLX001, CPLX002, CPLX003, CPLX004, CPLX005
gate: FAIL (exit 1)
  5 hard violation(s) and gates.new_hard_violations = "fail"
```

## Profiles

Three built-in profiles ship with the package and are selected with
`profile = "..."` (or `--profile`): **`strict`** (default: every rule at its
documented severity, unparseable files fail), **`recommended`** (strict, but
`DEF003`/`DEF004` fallbacks are `review`), **`minimal`** (`MAGIC001`, `EXC*`
and `DEF*` all capped at `review`, syntax failures warn, complexity off:
everything is reported, nothing but malformed suppressions fails). Precedence
is bundled defaults < profile < repository configuration < `--profile` /
`--parse-errors`. Any profile below `strict` is printed as a policy deviation
in every report, and the report's `effective_profile` names it.

## Configuration

`.shockharness.toml` or `shockharness.toml` (one of them; both is an error) or
a `[tool.shockharness]` table in `pyproject.toml` (the dedicated file wins and
the shadowed table is reported). Unknown keys, bad types, unknown rule IDs,
and invalid globs are errors, never ignored. Every rule can be disabled; every
disable is listed in the report.

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
paths = ["tests/**"]
disable = ["MAGIC001"]
reason = "Fixtures encode literal expected outputs"
```

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
    uses: evolvingstuff/ShockHarness/.github/workflows/check.yml@v0.1.0
    permissions:
      contents: read
      security-events: write
    with:
      shockharness-version: "0.1.0a1"
```

It uploads SARIF to code scanning. Keep the version pin in `pyproject.toml`, a
requirements file or that workflow input, never in a shell string, so
Dependabot can open upgrade PRs; `docs/integration.md` has the full recipe and
a Dependabot snippet, and `examples/python` and `examples/js` are complete
consumers exercised by CI.

See `docs/` for configuration, rules, architecture, integration, releasing,
and limitations.

## Library

```python
from pathlib import Path
from shockharness import analyze_paths
from shockharness.analysis import AnalysisOptions
from shockharness.config import load_config

config = load_config(Path("."), None)
report = analyze_paths([Path("src")], Path("."), config, AnalysisOptions(inline_suppressions=True))
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
ruff check src tests scripts && ruff format --check src tests scripts
shockharness check src tests scripts   # the tool gates its own source
python -m build && python scripts/consumer_upgrade_check.py --dist dist --examples examples
```

ShockHarness runs on itself as a hard CI gate. Its one `MAGIC001` exemption is
`src/shockharness/constants.py`; its declared exception boundaries are listed in
`.shockharness.toml` with reasons and enforced by `EXC001`-`EXC003`: every
`try` in the tool wraps exactly one external call and converts the failure into
a typed diagnostic. `DEF001`-`DEF006` hold too: the tool has no parameter
defaults outside tests, no mapping fallbacks, and no `or`/`is None` defaults.

## License

MIT. See `LICENSE`.
