# Configuration

ShockHarness reads exactly one user configuration source, validated against a
closed schema, and merges it over the bundled strict defaults. Nothing is read
from environment variables. Configuration files are data and are never executed.

## Where configuration comes from

Precedence, highest first:

| Tier | Source | Notes |
|---|---|---|
| `cli` | `--config PATH` | Must exist and contain `[tool.shockharness]`. |
| `dedicated` | `<root>/.shockharness.toml` | Wins over `pyproject.toml`; a shadowed `pyproject` table is reported as a config note. |
| `pyproject` | `[tool.shockharness]` in `<root>/pyproject.toml` | Used only when no dedicated file exists. |
| `bundled` | `defaults.toml` inside the package | Always present; the strict profile. |

`<root>` is `--root` (default: the current directory). Targets outside the root
are a usage error, so relative paths in reports are always root-relative.

`shockharness config effective` prints the merged values with a per-key origin
tier, the digest, notes, and policy deviations. `shockharness config validate`
exits 0 only when the configuration is valid; every problem is listed with its
key path.

## Schema

All keys are optional in user configuration because the bundled defaults supply
every value. Unknown keys, wrong types, bad enum values, invalid globs, unknown
rule IDs, and unsupported include extensions are **errors**, never warnings.

```toml
[tool.shockharness]
profile = "strict"                      # only "strict" exists today
include = ["**/*.py", "**/*.js", "**/*.mjs", "**/*.cjs"]
exclude = ["**/.git/**", "**/node_modules/**", "**/.venv/**", "**/venv/**",
           "**/dist/**", "**/build/**", "**/generated/**", "**/__pycache__/**"]
parse_errors = "fail"                   # "fail" -> exit 3 on any unparseable file; "warn" -> reported, gate unaffected
follow_symlinks = false                 # never leave the root through a link unless asked

[tool.shockharness.rules.magic_numbers]
enabled = true
allowed_values = [0, 1]                 # value-based; extra values are reported as deviations
allow_unary_negative_one = false        # -1 fails unless true; -0 always fails
exclude_configuration_files = true      # files matching configuration_files skip MAGIC001 (reported per file)
configuration_files = ["conftest.py", "setup.py", "*.config.js", "*.config.mjs", "*.config.cjs",
                       "*.conf.js", "*.conf.cjs", ".eslintrc.js", ".eslintrc.cjs",
                       ".prettierrc.js", ".prettierrc.cjs", "gulpfile.js", "Gruntfile.js"]

[tool.shockharness.rules.magic_strings]   # MAGIC002: registered, not implemented
enabled = true
mode = "review"

[tool.shockharness.rules.exceptions]      # EXC001-EXC003
enabled = true
mode = "boundary_whitelist"               # the only mode
transparent_rethrow = false               # true: handlers that only re-raise pass EXC001 (reported as a deviation)
boundaries = []                           # see below

[tool.shockharness.rules.defaults]        # DEF001-DEF006: registered, not implemented
enabled = true
function_parameters = "forbid"
missing_value_fallbacks = "forbid"
truthiness_fallbacks = "review"

[tool.shockharness.complexity]            # CPLX001-CPLX005: registered, not implemented
enabled = true
cognitive_warn = 15
cyclomatic_warn = 15
max_nesting_warn = 4

[tool.shockharness.gates]
new_hard_violations = "fail"              # "fail" -> exit 1 on any unsuppressed error finding; "warn" -> exit 0, reported
legacy = "baseline"                       # baselines arrive in Milestone F
complexity_regressions = "warn"

[[tool.shockharness.overrides]]           # per-path rule disables; every one is a reported deviation
paths = ["tests/**"]
disable = ["MAGIC001"]
reason = "Fixtures encode literal expected outputs"

[[tool.shockharness.rules.exceptions.boundaries]]   # one approved catch site
path = "src/integrations/**"                        # glob, same semantics as include/exclude
language = "python"
exception = "requests.exceptions.Timeout"           # qualified class name; wildcards are rejected
reason = "External network timeout"
```

## Exception boundaries

A boundary approves catching **one** exception class in files matching one glob
for one language. It is the only way a catch passes `EXC001`, and every boundary
is listed in `config.deviations` so the approval is never silent.

* `exception` must be a dotted class name (`OSError`,
  `requests.exceptions.Timeout`, `pkg.errors.Upstream`, JavaScript
  `TimeoutError`). `*`, `|`, and empty strings are configuration errors. A bare
  `except` cannot be approved at all.
* The name is compared with the identity the analyzer resolved for the handler
  (see `docs/rules.md`): exact identities must match exactly; approximate ones
  (relative imports, classes defined in the analyzed module, JavaScript guards)
  match by dotted suffix.
* A tuple handler needs a matching boundary for each member; several boundaries
  may apply to one file.
* Class hierarchies are not consulted: approve the class you catch.
* JavaScript: the boundary alone is not enough. The handler must open with an
  `instanceof` guard for that class that re-throws everything else.
* Approving a catch does not exempt it from `EXC002` (what the handler does) or
  `EXC003` (what the `try` body wraps).

Keys for unimplemented rule families are validated and stored so that a
configuration written today keeps working when the rules land. They have no
effect on findings yet; the report's `coverage.rules_not_implemented` says so.

## Glob semantics

* Forward slashes only; patterns are relative to the root.
* `**` matches zero or more whole path segments and must be a segment by itself (`**/`, `/**`).
* `*` matches within one segment, `?` one character, `[abc]`/`[!abc]` a class.
* A pattern with no `/` matches the file's **basename** anywhere in the tree (`*.py`).
  A pattern containing `/` matches the whole relative path (`src/**/*.py`).
* Directories matching an exclude pattern of the form `<glob>/**` are pruned and not walked.

## Targets

`shockharness scan PATH...` accepts files and directories. Directories are
walked (sorted, deterministic) and filtered by `include` then `exclude`. A file
named explicitly is analyzed even if `include` does not match it; if `exclude`
matches it, it is listed under `coverage.explicit_targets_excluded` rather than
silently dropped. An explicit file with an unsupported extension is a usage
error (exit 2). `.git` directories are always skipped.

## Inline suppressions

```python
status = 404  # shockharness: ignore[MAGIC001] reason="RFC 9110 section 15.5.5"
```
```javascript
const status = 404; // shockharness: ignore[MAGIC001] reason="RFC 9110 section 15.5.5"
const other = 500;  /* shockharness: ignore[MAGIC001] reason="RFC 9110 section 15.6" */
```

* Same line as the construct. Several IDs: `ignore[MAGIC001, DEF001]`.
* Reason is mandatory and non-empty. Rule IDs must exist.
* A malformed, unknown-rule, or reason-less suppression is a `SUPP001` error and suppresses nothing.
* A suppression that silences nothing is a `SUPP002` warning.
* Suppressed findings stay in the report with their `suppression` filled in; only the gate ignores them.
* `--no-inline-suppressions` ignores every suppression and reports each as `SUPP001`.

## Reporting of policy changes

Everything that loosens the strict profile is surfaced, never silent:

* `config.deviations` lists disabled rules, extra `allowed_values`,
  `allow_unary_negative_one`, `parse_errors = "warn"`, `transparent_rethrow`,
  every exception boundary, and every override, each with its reason.
* `files[].rules_disabled` lists, per file, which rules did not run and why
  (`config`, `overrides[i]`, or `configuration_file`).
* `coverage.rules_not_implemented` lists rules that exist in the registry but produce nothing yet.
* `config_digest` is a SHA-256 of the effective configuration so two reports can be compared.
