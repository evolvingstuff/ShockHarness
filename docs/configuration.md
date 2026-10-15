# Configuration

ShockHarness reads exactly one user configuration source, validated against a
closed schema, and layers it over a built-in profile and the bundled strict
defaults. Nothing is read from environment variables. Configuration files are
data and are never executed.

## Where configuration comes from

One **source** applies, chosen in this order (highest first):

| Tier | Source | Notes |
|---|---|---|
| `cli` | `--config PATH` | Must exist and contain `[tool.shockharness]`. |
| `dedicated` | `<root>/.shockharness.toml` **or** `<root>/shockharness.toml` | Either spelling; **both present is an error** naming both files. Wins over `pyproject.toml`; a shadowed `pyproject` table is reported as a config note. |
| `pyproject` | `[tool.shockharness]` in `<root>/pyproject.toml` | Used only when no dedicated file exists. |
| `bundled` | `defaults.toml` inside the package | Always present; the strict profile. |

The effective configuration is then built from four **layers**, lowest first:

```text
bundled defaults  <  built-in profile  <  the source above  <  command-line overrides
```

* The profile layer is the overlay for `profile = "strict" | "recommended" |
  "minimal"` (see Profiles below); `strict` changes nothing.
* The source's own keys override the profile's. Lists replace, tables merge key by key.
* The command-line overrides are exactly `--profile NAME` and
  `--parse-errors fail|warn` (see below); nothing else can be changed from the
  command line.

`<root>` is `--root` (default: the current directory). Targets outside the root
are a usage error, so relative paths in reports are always root-relative.

`shockharness config effective` prints the merged values with a per-key
origin (`bundled`, `profile:<name>`, `cli`/`dedicated`/`pyproject`, or
`cli_override`), the digest, notes, and policy deviations. `shockharness
config validate` exits 0 only when the configuration is valid, prints the
effective profile, and lists every policy deviation; every problem is listed
with its key path.

## Profiles

Three profiles ship inside the package (`shockharness/profiles/*.toml`,
versioned with the tool; no profile is ever fetched remotely). Select one with
`profile = "..."` in the configuration or `--profile` on the command line.

| Profile | What it is | Gate behaviour |
|---|---|---|
| `strict` (default) | The bundled defaults: every rule at its documented severity, `parse_errors = "fail"`, complexity enabled | Hard violations and unparseable files fail |
| `recommended` | `strict`, except: `DEF003` (truthiness fallbacks, already `review` in strict) and `DEF004` (nullish fallbacks) are `review`; `MAGIC001` permits the unary literal `-1` (`allow_unary_negative_one = true`: `indexOf(...) === -1`, `[-1]`, `.at(-1)`) and does not report module-level named constant definitions (`named_constant_definitions = "allow"`); `CPLX005` fan-out fires above 30 distinct call targets instead of 20 (`fan_out_warn = 30`) and as a `review` finding instead of a warning (`fan_out_severity = "review"`), because the units over 20 on real codebases are orchestrators (login, streaming, restore) | As strict minus `DEF004` |
| `minimal` | `MAGIC001`, `EXC001`-`EXC003` and `DEF001`-`DEF006` all capped at `review` (`rules.<section>.severity = "review"`), `named_constant_definitions = "allow"`, `parse_errors = "warn"`, complexity disabled; `SUPP001` still fails | Only malformed suppressions fail; everything is still reported |

Any profile below `strict` prints a `policy deviation` line in every report
(text, JSON `config.deviations`, SARIF run `properties.config_deviations`)
and in `config validate`, followed by one line per key the profile changes.
The report's top-level `effective_profile` names the profile in force.
`shockharness init --profile recommended|minimal` writes a short file that
selects the profile and nothing else: spelling out the strict values would
override the profile layer and undo it.

The per-section severity cap is also available directly:
`rules.magic_numbers.severity`, `rules.exceptions.severity` and
`rules.defaults.severity` accept `"error"` (default) or `"review"`. `"review"`
turns the section's error findings into review findings (reported, never
gating; `DEF005` included for `rules.defaults`); warnings and review findings
are unchanged. Each cap below `"error"` is a reported deviation.

## Command-line overrides

Exactly two configuration keys can be overridden on the command line, on every
command that loads configuration (`check`, `gate`, `diff`, `baseline create`,
`config validate`, `config effective`):

| Flag | Effect |
|---|---|
| `--profile strict\|recommended\|minimal` | Replaces the profile layer. The configuration file's *other* keys still apply on top of it, so `--profile strict` on a repository configured for `minimal` applies the repository's includes, boundaries and overrides under strict severities. |
| `--parse-errors fail\|warn` | Replaces `parse_errors` only. |

Both are recorded with origin `cli_override`, each adds a config note naming
the flag and the value it replaced, both enter the configuration digest, and
any resulting looseness is a policy deviation like any other.

Why only these two: a CI job sometimes needs to ask a stricter or looser
question without editing the repository (a scheduled strict run on a codebase
that gates on `recommended`, or a quick look at what `minimal` would report),
and sometimes needs to decide whether syntax the host interpreter cannot parse
should fail the step. Everything else is policy and belongs in the checked-in
file, where it is reviewed, diffed and digested. A flag per key would let a
pipeline weaken the gate invisibly to anyone reading the repository.

## Schema

All keys are optional in user configuration because the bundled defaults supply
every value. Unknown keys, wrong types, bad enum values, invalid globs, unknown
rule IDs, and unsupported include extensions are **errors**, never warnings.

```toml
[tool.shockharness]
profile = "strict"                      # "strict" | "recommended" | "minimal"; see Profiles
include = ["**/*.py", "**/*.js", "**/*.mjs", "**/*.cjs"]
exclude = ["**/.git/**", "**/node_modules/**", "**/.venv/**", "**/venv/**",
           "**/dist/**", "**/build/**", "**/generated/**", "**/__pycache__/**"]
parse_errors = "fail"                   # "fail" -> exit 3 on any unparseable file; "warn" -> reported, gate unaffected
unsupported_sources = "warn"            # an included file no adapter parses (.ts, .pyx): "fail" -> exit 3, "warn" -> listed, "ignore" -> counted only ("ignore" in minimal)
follow_symlinks = false                 # never leave the root through a link unless asked

[tool.shockharness.rules.magic_numbers]
enabled = true
severity = "error"                      # "review" caps MAGIC001 at review (reported, never gating; a deviation)
allowed_values = [0, 1]                 # value-based; extra values are reported as deviations
allow_unary_negative_one = false        # -1 fails unless true; -0 always fails (true in recommended)
named_constant_definitions = "report"   # MAX_PAGES = 8 / const SETTLE_MS = 400 at module scope: "report" (strict) or "allow" (recommended, minimal)
exclude_configuration_files = true      # files matching configuration_files skip MAGIC001 (reported per file)
configuration_files = ["conftest.py", "setup.py", "*.config.js", "*.config.mjs", "*.config.cjs",
                       "*.conf.js", "*.conf.cjs", ".eslintrc.js", ".eslintrc.cjs",
                       ".prettierrc.js", ".prettierrc.cjs", "gulpfile.js", "Gruntfile.js"]

[tool.shockharness.rules.magic_strings]   # MAGIC002: registered, not implemented
enabled = true
mode = "review"

[tool.shockharness.rules.exceptions]      # EXC001-EXC003
enabled = true
severity = "error"                        # "review" caps EXC001-EXC003 at review
mode = "boundary_whitelist"               # the only mode
transparent_rethrow = false               # true: handlers that only re-raise pass EXC001 (reported as a deviation)
transparent_guards = []                   # guard callees ("rethrowUnexpectedError"): a handler opening with guard(<caught>) is narrowed by it (each a deviation)
capture_managers = []                     # qualified names of the project's exception-capturing context managers; `with M(T):` is then a catch of T (each a deviation)
boundaries = []                           # see below

[tool.shockharness.rules.defaults]        # DEF001-DEF006; each mode: "forbid" -> error, "review" -> review, "allow" -> off
enabled = true
severity = "error"                        # "review" caps every DEF finding (DEF005 included) at review
function_parameters = "forbid"            # DEF001: parameter defaults, destructured parameter defaults
dataclass_fields = "forbid"               # DEF001: dataclass field defaults and default_factory
missing_value_fallbacks = "forbid"        # DEF002: m.get(k, v), getattr(o, a, v), const {x = v} = o, o?.x ?? v
truthiness_fallbacks = "review"           # DEF003: x or v, x || v (also replace legitimate falsy values)
nullish_fallbacks = "forbid"              # DEF004: x ?? v, x if x is not None else v
configuration_fallbacks = "forbid"        # DEF006: os.getenv("X", v), process.env.X || v
                                          # DEF005 (a handler that returns a default) has no mode: always an error

[tool.shockharness.complexity]            # CPLX001-CPLX005: advisory warnings; see docs/complexity.md
enabled = true                            # false: no metrics, no CPLX findings (reported as a deviation)
cognitive_warn = 15                       # CPLX002: cognitive/1 above this value
cyclomatic_warn = 15                      # CPLX001: cyclomatic/1 above this value
max_nesting_warn = 4                      # CPLX003: nesting/1 above this value
cyclomatic_counts_boolean_operators = true   # cyclomatic/1 counts and/or, &&/||/??, ||= (false: a deviation)
npath_cap = 10000                         # npath/1 saturates here; reported as ">= cap"
npath_warn = 200                          # CPLX004: npath/1 at or above this value, or saturated
fan_out_warn = 20                         # CPLX005: distinct call targets of one unit above this value (30 in recommended)
fan_out_severity = "warning"              # CPLX005 fan-out findings: "warning" or "review" (both advisory; "review" in recommended)
max_lines_warn = 50                       # CPLX006: size/1 logical lines of one unit above this value; module bodies exempt
npath_only_without_cognitive = true       # a unit above cognitive_warn and npath_warn is one CPLX002 finding naming both; false: CPLX002 and CPLX004
abstraction_displacement = false          # experimental, diff mode only; see docs/complexity.md

[tool.shockharness.history]               # local `git log`, file granularity, never gating
enabled = true
horizon_days = 90                         # commits newer than (head commit date - horizon_days)
min_support = 3                           # co-change pairs need at least this many shared commits

[tool.shockharness.gates]
new_hard_violations = "fail"              # "fail" -> exit 1 on any new unsuppressed error finding; "warn" -> exit 0, reported
legacy = "baseline"                       # what a finding matched by a baseline or base revision means; see below
complexity_regressions = "warn"           # diff/gate only: "warn" lists per-unit regressions, "fail" fails the gate, "ignore" says nothing

[[tool.shockharness.overrides]]           # per-path rule disables; every one is a reported deviation
paths = ["tests/**"]
disable = ["MAGIC001"]
reason = "Fixtures encode literal expected outputs"

[[tool.shockharness.rules.exceptions.boundaries]]   # one approved catch site
path = "src/integrations/**"                        # glob, same semantics as include/exclude
language = "python"
exception = "requests.exceptions.Timeout"           # qualified class name; wildcards are rejected
reason = "External network timeout"

[[tool.shockharness.rules.exceptions.boundaries]]   # several classes for one path, one reason
path = "src/proc/**"
language = "python"
exceptions = ["OSError", "ProcessLookupError"]      # exactly one of `exception` / `exceptions` per entry
reason = "The child process may already be gone"
```

## Exception boundaries

A boundary approves catching one exception class (`exception = "..."`) or
several (`exceptions = ["...", "..."]`, 0.2.0) in files matching one glob for
one language, with one reason. It is the only way a catch passes `EXC001`
(apart from a configured transparent guard, below), and every boundary is
listed once in `config.deviations` so the approval is never silent.

* Each entry has exactly one of `exception` and `exceptions`; both, neither,
  or an empty list is a configuration error naming the entry. Every name must
  be a dotted class name (`OSError`, `requests.exceptions.Timeout`,
  `pkg.errors.Upstream`, JavaScript `TimeoutError`). `*`, `|`, and empty
  strings are configuration errors. A bare `except` cannot be approved at all.
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
* Python: a handler that opens with `if not isinstance(exc, T): raise` is
  matched against the boundaries as a catch of `T` (or of each member of a
  tuple), not of the broad type on the `except` line.

**Capture managers** (`rules.exceptions.capture_managers`, 0.2.0). Qualified
class names (`["app.errors.CapturedExceptionContext"]`) of context managers
that catch a declared exception type and expose it after the block.
`with Manager(T1, T2, ...):` is then a catch of `T1` and `T2` (the positional
arguments that name exception types), checked by `EXC001` against the
boundaries exactly like `except (T1, T2):`; a manager with no readable type is
an untyped catch. `contextlib.suppress(...)` is always such a catch and one
that swallows (`EXC002`, unless a boundary approves it). A listed manager
matches by qualified name when its import resolves (exact) and by bare name
when it does not (approximate). Each entry is a reported deviation; an
unlisted manager is an ordinary `with`. See `docs/rules.md`, EXC001.

**Transparent guards** (`rules.exceptions.transparent_guards`, 0.2.0). A list
of guard callees as written (`["rethrowUnexpectedError"]`,
`["errors.rethrow_unexpected"]`): functions that re-raise anything not on
their allowlist and return for expected failures. A handler whose first
statement calls a listed guard with the caught exception as its only argument
is treated as narrowed by the guard: `EXC001` does not report the catch, and
`EXC002` classifies the statements after the guard (a handler with nothing
after it still swallows). Default empty; each guard is a reported policy
deviation. This replaces one `boundaries` entry per exception type per path
for codebases with a house guard; it is not a boundary, so `EXC003` does not
run on guarded catches.

## Default and fallback modes

`rules.defaults` has one switch (`enabled`) for the whole family and one *mode*
per kind of default. `forbid` makes the finding an `error` (fails the gate),
`review` reports it without failing, `allow` turns that kind off. The strict
profile forbids everything except `truthiness_fallbacks`, which is `review`
because `x or v` is also ordinary Boolean logic. A mode looser than the strict
value is listed in `config.deviations`; tightening (`truthiness_fallbacks =
"forbid"`) is not a deviation. `DEF005` has no mode: a handler that returns a
default is always an error; disable the rule by override if a path needs it.

The two *implicit* shapes, `m.get(k)` and `os.getenv("X")` with no fallback, are
`review` under both `forbid` and `review`, and off under `allow`: they may
yield `None` for a missing value, but nothing proves the value was required.

Keys for the one unimplemented rule family (`magic_strings`) are validated
and stored so that a configuration written today keeps working when the rule
lands. They have no effect on findings yet; the report's
`coverage.rules_not_implemented` says so.

## Complexity

`[tool.shockharness.complexity]` drives the advisory family `CPLX001`-`CPLX006`
and the sections `metrics.complexity` (per-unit cyclomatic, cognitive, nesting,
NPath and size numbers, with their versioned conventions and the thresholds
in force) and `metrics.graph` (call graph with `resolved` / `probable` /
`unresolved` edges, module import edges, cycles, fan-in/out, shared mutable
state). Every finding is a `warning` (fan-out findings are `review` under
`fan_out_severity = "review"`); a plain `check` never fails because of
them, and `complexity.enabled = false` (the `minimal` profile) switches the
whole family off and says so in `config.deviations`. Thresholds above the
defaults and `fan_out_severity` are not deviations;
`cyclomatic_counts_boolean_operators = false` is, because the number then
counts fewer decisions than its convention states. `max_lines_warn` (0.2.0)
is `CPLX006`'s threshold on `size/1` logical lines; module bodies are exempt.
`npath_only_without_cognitive` (0.2.0, default `true`) folds `CPLX004` into
`CPLX002` when one unit is above both thresholds, so the text report shows one
line naming both numbers and the JSON report keeps only `CPLX002` for that
unit; `false` reports both. `docs/complexity.md` defines every convention.

## First contact: `check --summary`

`shockharness check PATH... --summary` prints, instead of every finding, the
shape of the problem: findings by rule and top-level directory (`src/`,
`tests/`, `.` for files at the root) and by severity, the ten files with the
most policy findings (`MAGIC`/`EXC`/`DEF`/`SUPP`, not `CPLX`), complexity
counts (units analyzed, units over each threshold, NPath-saturated units,
import cycles, units over `fan_out_warn`), parse failures and the elapsed
time, followed by the same totals, configuration lines and `gate:` line as
the full report. The exit code is unchanged. The JSON report always carries
the same overview as its `summary` object, whose totals equal
`execution_summary`; `summary.elapsed_seconds` is the one field of a report
that differs between two runs over the same input.

## Adopting ShockHarness on an existing codebase

Four ways to turn the gate on without a red build on day one. They answer
different questions and combine freely; every one is visible in the report.

| Path | Where it lives | What it does | Use it when |
|---|---|---|---|
| **Baseline** (`baseline create`, then `--baseline FILE`) | A reviewed, committed file | Existing findings are legacy and do not gate; anything new fails. Counts and listings are unchanged. | You want the gate to be *real* from the first PR while the backlog is paid down. The usual choice. |
| **`gates.new_hard_violations = "warn"`** | Configuration (`[tool.shockharness.gates]`) | Every run reports hard violations and exits 0; the gate reason says they were downgraded. A policy deviation. | The whole repository has agreed, for now, that the policy is advisory, and that decision should be reviewed and diffed like any other config change. |
| **`profile = "minimal"`** (or `recommended`) | Configuration (`profile`) or `--profile` | Rules still run and report, but their findings are `review` (and syntax failures only warn). A policy deviation with one line per changed key. | First contact: you want to read what the rules would say before deciding anything, or an interim policy where only malformed suppressions fail. |
| **`--exit-zero`** | Command line only, on `check` (and `scan`) and `gate` | The report, severities, verdict text and counts are unchanged; only the process exit code becomes 0 when the verdict is `fail`. Exit 2 (configuration, usage) and exit 3 (tool failure, strict parse failure) are never masked. The report carries `gate.advisory = true`, a `shockharness: advisory run (--exit-zero): gate verdict FAIL reported as exit 0` line in text, and `advisory` in SARIF run properties. | One invocation should not block (a scheduled strict run on a repository that gates on `recommended`, a first SARIF upload, a local dry run) and nobody should have to edit the repository's policy to get that. |

`--exit-zero` is deliberately **not** a configuration key: a checked-in
"never fail" switch already exists as `gates.new_hard_violations = "warn"`,
and it belongs in the repository where it is reviewed, digested and reported
as a deviation. The flag is the per-invocation form of the same decision, and
because it lives in the command line it can never silently become the
repository's policy. It is not a deviation (the policy did not change) but it
is never silent either: a report that exited 0 under the flag says so in every
format.

Typical sequence: start with `--profile minimal` or `--exit-zero` to read the
report; create a baseline and switch to `strict`; use `gate --base <default
branch> --head HEAD` on pull requests; delete the baseline when it is empty.

## Baselines

A baseline is a reviewed JSON file of finding fingerprints. It lets a project
adopt the strict profile with existing debt: findings in the baseline are
*legacy* and do not fail the gate, anything else is *new* and does.

```bash
shockharness baseline create src/ --output .shockharness-baseline.json
# review the file, then commit it
shockharness check src/ --baseline .shockharness-baseline.json
shockharness gate src/ --baseline .shockharness-baseline.json
```

* **Fingerprint.** SHA-256 over the fingerprint version, rule ID, root-relative
  path, enclosing scope (`null` for scope-less findings such as `SUPP002`), the
  evidence line with every whitespace character removed, and an occurrence
  index that distinguishes identical constructs in one file (in source order).
  Moving a line, inserting lines above it, or reformatting whitespace keeps the
  fingerprint; changing the construct, the rule, the scope, or the file changes
  it. Every finding carries its fingerprint in the JSON report
  (`findings[].fingerprint`) and in SARIF (`partialFingerprints`).
* **File.** `schema_version`, `tool_version`, `config_digest`,
  `fingerprint_version`, and `fingerprints` (each with its fingerprint plus
  `rule_id`, `path`, `scope`, `evidence`, `occurrence` so a reviewer can read
  it). Sorted and byte-stable; see `schemas/baseline-v1.schema.json`.
  Suppressed findings are not baselined (they already do not gate). Every
  unsuppressed finding of any severity is.
* **Never automatic.** `baseline create` refuses to overwrite an existing file
  without `--force`, refuses to write anything when analysis did not complete
  (a parse failure under `parse_errors = "fail"`), and no command ever
  rewrites a baseline. Regenerating it is a reviewed, explicit act.
* **`gates.legacy`** decides what a matched finding means:
  * `baseline` (default): the finding is listed with `baseline = "matched"`,
    counted in `gate.hard_violations` and `findings_by_severity`, and excluded
    from the verdict (`gate.new_hard_violations` drives it). Legacy debt stays
    visible in the counts.
  * `ignore`: listed with `baseline = "ignored"` and excluded from the counts
    and the verdict (`gate.baselined` is the only place it is counted).
  * `fail`: the baseline is recorded (`gate.baseline.applied = false`) but not
    applied; every finding counts and fails.
* **Stale entries** (fingerprints the current analysis no longer produces) are
  listed under `gate.baseline.stale` with a gate reason line. They never fail
  the gate; they are the prompt to recreate the baseline. A baseline created
  under a different configuration is applied anyway and noted
  (`gate.baseline.config_digest_matches = false`): fingerprints do not depend
  on the policy, but findings the old policy did not produce are new.

## Revision diff and gate

```bash
shockharness diff --base main --head HEAD [--format text|json|sarif]
shockharness gate --base main --head HEAD
```

Both commands resolve the two revisions with local git only (no remote is
contacted), export each **whole** tree at that commit with `git archive` into
a temporary directory, analyze it completely under the working tree's
configuration, and classify every finding by fingerprint: `new` (head only),
`fixed` (base only), `unchanged` (both). The working tree itself is not
analyzed: **uncommitted changes are not part of `HEAD`**. A dirty working tree
is fine; it is simply not compared. The analysis root may be a subdirectory of
the repository; only that subtree is analyzed at each revision.

`diff` is reporting only and exits 0 (3 if the head tree could not be
analyzed under `parse_errors = "fail"`; 2 for a bad revision or no
repository). `gate` exits 1 only on **new** unsuppressed hard violations;
fixed violations never fail, and unchanged ones are legacy under
`gates.legacy` exactly as baseline matches are (`baseline` or `ignore`: not
gating; `fail`: they count). The report records both refs and their resolved
commit hashes, the configuration digest, and the tool version; see
`schemas/diff-v1.schema.json`. `--baseline` cannot be combined with
`--base/--head`: the base revision is the legacy source of a revision gate.

Both commands also compare every head unit's complexity numbers with the same
unit at base. `metrics.complexity.regressions` lists the units that are above
a `CPLX001`-`CPLX004` threshold at head and grew since base (a unit absent at
base counts as grown from nothing). `gates.complexity_regressions` decides what
that means: `"warn"` (default) adds a gate reason, `"fail"` fails the gate with
exit 1, `"ignore"` says nothing. It is the only way complexity ever reaches a
verdict, and it never applies to a plain `check`. With
`complexity.abstraction_displacement = true` the diff also fills
`metrics.graph.abstraction_displacement` (experimental; see
`docs/complexity.md`).

## History

`[tool.shockharness.history]` controls `metrics.history` in every CLI report
(`check`, `diff`, `gate`). It reads `git log` locally for the analyzed files at
the analyzed revision (`HEAD` for `check`, the head commit for `diff`/`gate`)
and reports, at **file granularity**: per file the number of commits, distinct
authors, first and last change (author dates); `cochange` pairs of analyzed
files that appear in the same commits with `support` (shared commits) and a
directional `confidence` (support over each file's own commit count), for
pairs with `support >= min_support`. The horizon is anchored on the head
commit's committer date, not on the wall clock, so the metrics for a commit are
reproducible. `hotspots` scores each analyzed file as `log1p(churn) *
normalized_complexity` (the file's summed cognitive complexity over the
largest such sum; `hotspots_formula` repeats this), sorted by score; it is
`null` with a `hotspots_reason` when history or complexity is unavailable.

The section never gates. When git cannot be run, the root is not inside a
repository, or the revision is unknown, `status` is `"unavailable"` with the
reason; with `enabled = false` it is `"disabled"`; a report produced by the
library's `analyze_paths` alone is `"not_collected"` (use
`shockharness.api.with_history`). It is never silently empty.

## Unsupported sources

`unsupported_sources` (top level, next to `parse_errors`; 0.2.0) decides what
a file that `include` matches but no adapter can parse means. ShockHarness
reads `.py`, `.js`, `.mjs` and `.cjs`; a `.ts`, `.tsx`, `.pyx` or `.ipynb`
file in an included tree is otherwise silently outside the policy.

| Value | Effect |
|---|---|
| `fail` | each such file is an analysis failure: status `unsupported_source`, counted in `coverage.files_failed`, `analysis_status = "failed"`, gate `ERROR` and exit 3, like an unparseable file under `parse_errors = "fail"` |
| `warn` (strict and recommended) | the files are listed under `coverage.unsupported_sources` with a `warning:` line in the text report; the gate is unaffected |
| `ignore` (minimal) | only `coverage.discovery.unsupported_sources` counts them; nothing is listed. A reported deviation under every profile |

Files that `include` does not match, that `exclude` drops, or that sit in a
pruned directory are never affected; `coverage.discovery.unsupported_extension`
still counts every unparseable file the walk saw. An explicit target with an
unsupported extension stays a usage error (exit 2). `fail` is stricter than
the profile default and is not a deviation.

## Glob semantics

* Forward slashes only; patterns are relative to the root.
* `**` matches zero or more whole path segments and must be a segment by itself (`**/`, `/**`).
* `*` matches within one segment, `?` one character, `[abc]`/`[!abc]` a class.
* A pattern with no `/` matches the file's **basename** anywhere in the tree (`*.py`).
  A pattern containing `/` matches the whole relative path (`src/**/*.py`).
* Directories matching an exclude pattern of the form `<glob>/**` are pruned and not walked.

## Targets

`shockharness check PATH...` accepts files and directories (`scan` is a hidden alias with identical arguments). Directories are
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

* Same line as the construct. Several IDs: `ignore[MAGIC001, DEF001]`. A multi-line
  construct is suppressed on the line where the finding is reported (its start).
* Reason is mandatory and non-empty. Rule IDs must exist.
* A malformed, unknown-rule, or reason-less suppression is a `SUPP001` error and suppresses nothing.
* A suppression that silences nothing is a `SUPP002` warning.
* Suppressed findings stay in the report with their `suppression` filled in; only the gate ignores them.
* `--no-inline-suppressions` ignores every suppression and reports each as `SUPP001`.

## Reporting of policy changes

Everything that loosens the strict profile is surfaced, never silent:

* `config.deviations` lists the profile when it is below `strict`, disabled
  rules (complexity included), `cyclomatic_counts_boolean_operators = false`,
  every `rules.<section>.severity = "review"`
  cap, extra `allowed_values`, `allow_unary_negative_one`,
  `named_constant_definitions = "allow"`, `parse_errors = "warn"`,
  `unsupported_sources = "ignore"`, `transparent_rethrow`, every transparent
  guard, every capture manager, every exception boundary
  (once, listing every class it approves), every `rules.defaults` mode looser
  than the strict profile, and every override, each with its reason. The same list is in the text report, SARIF
  run properties, and `config validate`.
* `effective_profile` (top level, next to `tool_version` and `schema_version`)
  names the profile in force, including one selected with `--profile`.
* `files[].rules_disabled` lists, per file, which rules did not run and why
  (`config`, `overrides[i]`, or `configuration_file`).
* `coverage.rules_not_implemented` lists rules that exist in the registry but produce nothing yet.
* `config_digest` is a SHA-256 of the effective configuration so two reports can be compared.
