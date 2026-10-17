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

The effective configuration is then built from these **layers**, lowest first:

```text
bundled defaults  <  built-in profile  <  --policy file  <  the source above  <  command-line overrides
```

The `--policy` layer is present only with `--policy FILE` (see [The policy
tier](#the-policy-tier)); the source above cannot loosen a key it sets.

* The profile layer is the overlay for `profile = "strict" | "recommended" |
  "minimal"` (see Profiles below); `strict` changes nothing.
* The source's own keys override the profile's. Lists replace, tables merge key by key.
* The command-line overrides are exactly `--profile NAME` and
  `--parse-errors fail|warn` (see below); nothing else can be changed from the
  command line.
* After the layers are merged, a `rules.magic_numbers.configuration_files` list
  set by the source is folded into `file_roles.config` (see File roles). No
  other key is derived from another.

`<root>` is `--root` (default: the current directory). Targets outside the root
are a usage error, so relative paths in reports are always root-relative.

`shockharness config effective` prints the merged values with a per-key
origin (`bundled`, `profile:<name>`, `policy`, `cli`/`dedicated`/`pyproject`, or
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
| `recommended` | `strict`, except: `DEF003` (truthiness fallbacks, already `review` in strict) and `DEF004` (nullish fallbacks) are `review`; `MAGIC001` permits the unary literal `-1` (`allow_unary_negative_one = true`: `indexOf(...) === -1`, `[-1]`, `.at(-1)`) and does not report module-level named constant definitions (`named_constant_definitions = "allow"`); `CPLX005` fan-out fires above 30 distinct call targets instead of 20 (`fan_out_warn = 30`) and as a `review` finding instead of a warning (`fan_out_severity = "review"`), because the units over 20 on real codebases are orchestrators (login, streaming, restore); `DEF001`-`DEF006` findings whose status is `unknown` do not gate (`rules.defaults.fail_on_unknown = false`, 0.5.0) | As strict minus `DEF004` and unknown `DEF*` findings |
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

## The policy tier

```bash
shockharness check . --policy /path/outside/the/repo/shockharness-policy.toml
shockharness gate --base origin/main --head HEAD --policy "$RUNNER_TEMP/policy/shockharness-policy.toml"
```

`--policy FILE` (on every command that loads configuration) names an
organization's policy: a file with a `[tool.shockharness]` table, validated
like any configuration. It is a floor the repository cannot lower:

* **It must live outside the analysis root.** A policy the change under review
  can edit protects nothing, so a file inside `--root` is a configuration error
  (exit 2). Check it out from a separate, protected repository.
* **It sits between the profile and the repository's configuration.** Its keys
  replace the profile's. A `profile` key in it selects the profile unless the
  repository selects a stricter one.
* **The repository may tighten a policy key, never loosen it.** A repository
  key that would loosen a key the policy sets (by the same test VERIFY003 uses:
  a new deviation, an ordered setting moved to its looser end, a raised
  threshold, a narrower include or wider exclude) is dropped, the policy's value
  applies, and the attempt is recorded in `config.policy_attempts`, as a config
  note, and as a `VERIFY003` finding at the key's line, in a plain `check` as
  well as in `diff` and `gate`. A list is one key: a repository `exclude` that
  adds a pattern to the policy's list is an attempt, and the policy's list
  applies.
* **Command-line overrides stay on top.** `--profile` and `--parse-errors`
  belong to whoever runs the command; a `--profile` looser than the policy's
  adds a config note, and a workflow that adds such a flag to a ShockHarness
  job is a `VERIFY003` finding.

The report's `config.policy` names the file, the SHA-256 digest of its
canonical JSON (formatting and comments do not change it) and every key it
sets; the text output prints the same as `policy:` lines before the policy
deviations. Its values enter `config_digest` like any other layer.

In CI, the reusable workflow (0.4.0 and later) fetches the policy from its own
repository so it is never inside the workspace:

```yaml
jobs:
  shockharness:
    uses: evolvingstuff/ShockHarness/.github/workflows/check.yml@v0.6.0
    with:
      shockharness-version: "0.6.0"
      base: ${{ github.event.pull_request.base.sha }}
      policy-repository: my-org/engineering-policy   # cloned into $RUNNER_TEMP
      policy-ref: main                               # a branch or tag
      policy-path: shockharness-policy.toml          # the default
    secrets:
      policy-token: ${{ secrets.POLICY_READ_TOKEN }} # only for a private repository
```

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
include = ["**/*.py", "**/*.js", "**/*.mjs", "**/*.cjs",
           "**/*.ts", "**/*.tsx", "**/*.mts", "**/*.cts"]   # TypeScript since H-TS
exclude = ["**/.git/**", "**/node_modules/**", "**/.venv/**", "**/venv/**",
           "**/dist/**", "**/build/**", "**/generated/**", "**/__pycache__/**",
           "**/*.d.ts"]                 # declaration files hold types only
parse_errors = "fail"                   # "fail" -> exit 3 on any unparseable file; "warn" -> reported, gate unaffected
unsupported_sources = "warn"            # an included file no adapter parses (.pyx, .vue): "fail" -> exit 3, "warn" -> listed, "ignore" -> counted only ("ignore" in minimal)
follow_symlinks = false                 # never leave the root through a link unless asked

[tool.shockharness.cache]
enabled = true                          # the content-hash cache of per-file results (0.3.0); see Cache below
directory = ".shockharness-cache"       # relative to the root; belongs in .gitignore; not part of the config digest

[tool.shockharness.file_roles]          # H1: one role per file, first match wins in this order; see File roles
generated = ["**/generated/**", "**/*_pb2.py", "**/*.min.js"]
vendor = ["**/vendor/**", "**/third_party/**"]
config = ["conftest.py", "setup.py", "*.config.js", "*.config.mjs", "*.config.cjs",
          "*.conf.js", "*.conf.cjs", ".eslintrc.js", ".eslintrc.cjs",
          ".prettierrc.js", ".prettierrc.cjs", "gulpfile.js", "Gruntfile.js"]
test = ["tests/**", "test/**", "**/__tests__/**", "**/test_*.py", "**/*_test.py",
        "**/*.test.js", "**/*.spec.js", "**/*.test.mjs", "**/*.spec.mjs", "**/conftest.py"]
docs = ["docs/**"]                      # anything else is production (examples/ included)

[tool.shockharness.rules.magic_numbers]
enabled = true
severity = "error"                      # "review" caps MAGIC001 at review (reported, never gating; a deviation)
fail_on_unknown = false                 # H1: whether unknown findings gate (MAGIC001 produces none today); see Unknown findings
allowed_values = [0, 1]                 # value-based; extra values are reported as deviations
allow_unary_negative_one = false        # -1 fails unless true; -0 always fails (true in recommended)
named_constant_definitions = "report"   # MAX_PAGES = 8 / CHUNK_BYTES = 64 * 1024 / const SETTLE_MS = 400 at module scope: "report" (strict) or "allow" (recommended, minimal)
exclude_configuration_files = true      # files the config role's globs match skip MAGIC001 (reported per file)
configuration_files = ["conftest.py", "setup.py", "*.config.js", "*.config.mjs", "*.config.cjs",
                       "*.conf.js", "*.conf.cjs", ".eslintrc.js", ".eslintrc.cjs",
                       ".prettierrc.js", ".prettierrc.cjs", "gulpfile.js", "Gruntfile.js"]
                                        # legacy spelling of file_roles.config (kept through 0.x); see File roles

[tool.shockharness.rules.magic_strings]   # MAGIC002: registered, not implemented
enabled = true
mode = "review"

[tool.shockharness.rules.exceptions]      # EXC001-EXC003
enabled = true
severity = "error"                        # "review" caps EXC001-EXC003 at review
mode = "boundary_whitelist"               # the only mode
fail_on_unknown = true                    # H1: unresolved identities, opaque handlers fail closed as always (false: a deviation)
transparent_rethrow = false               # true: handlers that only re-raise pass EXC001 (reported as a deviation)
transparent_guards = []                   # guard callees ("rethrowUnexpectedError"): a handler opening with guard(<caught>) is narrowed by it (each a deviation)
capture_managers = []                     # qualified names of the project's exception-capturing context managers; `with M(T):` is then a catch of T (each a deviation)
boundaries = []                           # see below

[tool.shockharness.rules.defaults]        # DEF001-DEF006; each mode: "forbid" -> error, "review" -> review, "allow" -> off
enabled = true
severity = "error"                        # "review" caps every DEF finding (DEF005 included) at review
fail_on_unknown = true                    # H1: DEF002 on a receiver not proven a mapping keeps gating (false: a deviation)
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
fail_on_unknown = false                   # H1: CPLX findings are never unknown today, and advisory either way

[tool.shockharness.history]               # local `git log`, file granularity, never gating
enabled = true
horizon_days = 90                         # commits newer than (head commit date - horizon_days)
min_support = 3                           # co-change pairs need at least this many shared commits

[tool.shockharness.gates]
new_hard_violations = "fail"              # "fail" -> exit 1 on any new unsuppressed error finding; "warn" -> exit 0, reported
legacy = "baseline"                       # what a finding matched by a baseline or base revision means; see below
complexity_regressions = "warn"           # diff/gate only: "warn" lists per-unit regressions, "fail" fails the gate, "ignore" says nothing

[[tool.shockharness.overrides]]           # per-path or per-role rule disables; every one is a reported deviation
roles = ["test"]                          # H1: by file role; or paths = ["tests/**"]; exactly one of the two
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

## File roles

Every analyzed file (and every failed one) gets exactly one **role**:
`generated`, `vendor`, `config`, `test`, `docs` or `production`. The role is
the first of `generated`, `vendor`, `config`, `test`, `docs` whose
`[tool.shockharness.file_roles]` globs match the file's path, in that order;
a file nothing matches is `production`. The globs follow the
[glob semantics](#glob-semantics) below, root anchors included (`/manual.py`).
A list set in your configuration replaces the default list for that role;
the other roles keep theirs.

| Role | Default globs |
|---|---|
| `generated` | `**/generated/**`, `**/*_pb2.py`, `**/*.min.js` |
| `vendor` | `**/vendor/**`, `**/third_party/**` |
| `config` | `conftest.py`, `setup.py`, `*.config.js`, `*.config.mjs`, `*.config.cjs`, `*.conf.js`, `*.conf.cjs`, `.eslintrc.js`, `.eslintrc.cjs`, `.prettierrc.js`, `.prettierrc.cjs`, `gulpfile.js`, `Gruntfile.js` |
| `test` | `tests/**`, `test/**`, `**/__tests__/**`, `**/test_*.py`, `**/*_test.py`, `**/*.test.js`, `**/*.spec.js`, `**/*.test.mjs`, `**/*.spec.mjs`, `**/conftest.py` |
| `docs` | `docs/**` |
| `production` | everything else, `examples/` included |

Precedence decides overlaps: `third_party/setup.py` is `vendor`,
`tests/conftest.py` is `config` (the config role lists `conftest.py`, and
config precedes test; `**/conftest.py` in the test role applies when you leave
`conftest.py` out of the config role), `docs/test_x.py` is `test`. The default
`exclude` already drops `**/generated/**`, so that glob only matters if you
include generated directories.

Roles **never change which files are discovered or analyzed**: a `docs/` or
`vendor/` file that `include` matches is analyzed under every rule like any
other. They do three things:

* **Label.** Each file in the report carries `role` and `role_pattern` (the
  glob that decided it, `null` for production); `coverage.roles` counts files
  per role and `summary.by_role` counts findings per role (every role listed).
* **Scope overrides.** An `[[tool.shockharness.overrides]]` entry may name
  `roles = ["test"]` instead of `paths = [...]` (exactly one of the two, each
  a non-empty list; `roles` takes any of the six roles). It disables its rules
  for every file of those roles, is reported as a policy deviation
  (`overrides[i] disables MAGIC001, DEF001 for file role(s) test: <reason>`)
  and appears in `files[].rules_disabled` with origin `overrides[i]`, exactly
  like a path override.
* **The MAGIC001 configuration-file exemption.** With
  `rules.magic_numbers.exclude_configuration_files = true` (the default), a
  file whose role is `config` skips MAGIC001, recorded in
  `files[].rules_disabled` with origin `configuration_file`. A `generated` or
  `vendor` file that a config glob also matches keeps the exemption it had in
  0.3.0 (the reason says its role took precedence).

`rules.magic_numbers.configuration_files` is the **legacy spelling** of
`file_roles.config` and stays supported through 0.x. Its default equals the
config role's default. When your configuration sets it and not
`file_roles.config`, it replaces the config role's globs, exactly as it
replaced the exempt list in 0.3.0; when you set both, the two lists are merged
(`file_roles.config` first, duplicates dropped). Either way a `config note`
line says so, and `config effective` shows the resulting `file_roles.config`
with the origin of the legacy key.

## Unknown findings

Every finding has a `status`: `violation` (the rule established the property
it checks, and it does not hold) or `unknown` (the rule could not establish it:
an exception type that does not resolve, a promise rejection handler or a
capture-manager binding whose behaviour cannot be read, a `.get(k, v)` whose
receiver is not proven a mapping). Status is orthogonal to severity, which keeps
its meaning; the inventory of what is unknown is in [rules.md](rules.md#finding-status).

`fail_on_unknown` (boolean) decides per rule family whether unknown findings
gate. It lives in the family's own table: `rules.magic_numbers`,
`rules.exceptions`, `rules.defaults` and `complexity`.

| Family | Default | Why |
|---|---|---|
| `rules.exceptions` | `true` | EXC001 has always failed closed on unresolved types and opaque handlers |
| `rules.async_lifecycle` | `false` | ASYNC001 through a probable call-graph edge (the async callee matched by name only) |
| `rules.defaults` | `true` (`false` in `recommended`) | DEF002 on a receiver not proven a mapping has always failed the gate under `strict`; `recommended` reports it without gating, so a guess about a receiver's type cannot fail that gate |
| `rules.magic_numbers` | `false` | MAGIC001 is exact; it produces no unknown findings |
| `complexity` | `false` | CPLX001-CPLX006 measure what was resolved; advisory either way |

With `true`, an unknown finding gates by its severity exactly like a
violation. With `false`, it is reported and counted in `gate.unknown`, adds to
no other gate count and never fails the gate; a gate reason says how many were
reported only. `gate.unknown` counts every unsuppressed, non-ignored unknown
finding either way, `gate.unknown_gating_families` lists the families set to
`true`, and the text trailer prints both (`unknown: N finding(s) the rules could
not establish; fail_on_unknown families: exceptions, defaults`). Of the
built-in profiles only `recommended` changes one (`rules.defaults`, 0.5.0).
Setting a family to `false` where `strict` says `true` is a policy deviation,
whether a profile or the repository sets it; setting one to `true` is not.

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
unlisted manager is an ordinary `with`. Since 0.3.0 a manager bound to a name
first (`capture = Manager(T); with capture:`, or `s = suppress(T); with s:`) is
resolved to that assignment within the same function or module body: `exact`
when nothing stands between them, `approximate` when the assignment sits in a
branch or loop the `with` is not inside (or the name is also a parameter or a
comprehension target), and an `unresolved` untyped catch when the name was
rebound in between, is bound by `with ... as`, or is bound to a listed manager
only in another scope. See `docs/rules.md`, EXC001, for the table.

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
`execution_summary`. The elapsed time is printed in text output only, so the
JSON report stays byte-identical across runs over the same input.

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

## Verification integrity

```toml
[tool.shockharness.rules.verification]
enabled = true
severity = "warning"              # "warning" | "error" | "review"
fail_on_unknown = false
allowed_skip_reasons = []         # e.g. ["POSIX signals only"]
report_narrow_suppressions = false
```

`VERIFY001`-`VERIFY004` compare the head revision of a `diff` or `gate
--base/--head` with its base revision and report what the change **added**:
test skip and focus markers, blanket suppression comments, a looser policy
(configuration, files dropped from analysis, baselines, workflows, other tools'
settings), and assertions made unable to fail. A plain `check` has no base and
reports them as not applicable, except the `--policy` attempts of `VERIFY003`.
See `docs/rules.md` for every pattern.

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | `false` turns the four rules off (a policy deviation) |
| `severity` | `"warning"` | the severity of every VERIFY finding. `"error"` makes them gate like any hard violation; that tightens the policy and is not a deviation. `"review"` lowers them further and is a deviation |
| `fail_on_unknown` | `false` | whether an `unknown` VERIFY finding (the base version could not be analyzed, or rename detection failed) gates according to its severity |
| `allowed_skip_reasons` | `[]` | exact reason strings that make an added Python skip acceptable (JavaScript skips carry no reason). Each entry is listed as a policy deviation |
| `report_narrow_suppressions` | `false` | `VERIFY002` always reports blanket suppressions; with `true` it also reports added suppressions that name specific rule codes |

The bundled default is the same in all three profiles: specification section
21.1 decision 9 keeps new rules at `warning` until their precision has been
measured. A repository that wants agents stopped, not just told, sets
`severity = "error"`.

**Strictest of base.** In a revision diff the rules run with the stricter of
this table as the run sees it and the base revision's committed table:
`enabled` and `fail_on_unknown` and `report_narrow_suppressions` are true if
either side says so, `severity` is the stricter one, and
`allowed_skip_reasons` keeps only the reasons both list. A change cannot switch
off or lower the rules that report it; the loosening is a `VERIFY003` finding
and takes effect once it is merged.

VERIFY findings cannot be suppressed inline: `shockharness: ignore[VERIFY001]`
is a `SUPP001` error. Exceptions belong in this table or in an `[[overrides]]`
entry by path or role, where review sees them.

**Trust model.** A local CLI cannot stop someone with write access from editing
the configuration that would report them, or from not running the tool.
Verification integrity is enforceable when the gate runs in CI as a required
check on protected branches, and changes to `.shockharness.toml`, workflow
files and baselines need review (CODEOWNERS). `VERIFY003` reports such policy
changes themselves, and `--policy` keeps the organization's floor out of the
repository's reach.

## Syntax-level guardrails (H3)

```toml
[tool.shockharness.rules.stubs]            # STUB001, STUB002
enabled = true
severity = "warning"                       # "warning" | "error" | "review"
roles = ["production"]
markers = []                               # e.g. ["TODO", "FIXME"]
test_path_segments = ["tests", "test", "__tests__", "fixtures", "mocks", "__mocks__", "conftest"]
mock_modules = ["unittest.mock", "mock", "pytest", "pytest_mock", "faker", "freezegun",
                "responses", "sinon", "jest", "@jest/globals", "jest-mock", "vitest",
                "@faker-js/faker", "msw", "nock"]

[tool.shockharness.rules.assertions]       # ASSERT001
enabled = true
severity = "warning"
roles = ["production"]
allow_type_narrowing = true

[tool.shockharness.rules.boolean_arguments]  # BOOL001
enabled = true
severity = "review"
roles = ["production"]
allowed_callees = ["get", "getattr", "setattr", "setdefault", "pop", "next"]

[tool.shockharness.rules.module_state]     # STATE001
enabled = true
severity = "warning"
roles = ["production"]
allowed = []                               # [[...allowed]] path, name, reason

[tool.shockharness.rules.import_effects]   # IMPORT001
enabled = true
severity = "warning"
roles = ["production"]
python_operations = ["subprocess.run", "os.system", "socket.socket", "requests.get", ...]
javascript_operations = ["child_process.exec", "fs.rmSync", "fetch", "setInterval", ...]
```

The full lists are in the bundled `defaults.toml` (`shockharness config
effective` prints them). `EXC004` belongs to `rules.exceptions` (its `enabled`
switch and `severity` cap) and applies to every role.

| Key | Meaning | Policy deviation when |
|---|---|---|
| `severity` | the severity of every finding of the section's rules, as in `rules.verification`: `warning` by default (`review` for BOOL001, decision 9), `error` to gate | lowered to `review` |
| `roles` | the file roles the rules apply to; a rule is not applied to (and not listed in `rules_applied` of) a file of another role | a default role is removed |
| `markers` | STUB001 also reports comments containing one of these whole words | never (adding tightens) |
| `test_path_segments`, `mock_modules` | what STUB002 treats as test code | an entry is removed |
| `allow_type_narrowing` | ASSERT001 skips asserts that only narrow types | never (`false` tightens) |
| `allowed_callees` | BOOL001 skips calls whose last callee segment is listed | an entry is added |
| `allowed` | STATE001 skips `name` in files matching `path` | always, one line per entry, with its `reason` |
| `python_operations`, `javascript_operations` | the qualified callees IMPORT001 reports at import time | an entry is removed |

The same loosenings are what `VERIFY003` reports in a revision diff and what a
`--policy` file protects.

```toml
[[tool.shockharness.rules.module_state.allowed]]
path = "src/app/cache.py"
name = "_MEMO"
reason = "process-wide memo; read-mostly, guarded by _LOCK"
```

## Async lifecycle (H4)

```toml
[tool.shockharness.rules.async_lifecycle]   # ASYNC001-ASYNC003
enabled = true
severity = "warning"                        # "warning" | "error" | "review"
roles = ["production", "test"]
fail_on_unknown = false                     # ASYNC001 through a probable call-graph edge
python_coroutine_apis = ["asyncio.sleep", "asyncio.wait_for", "asyncio.gather", ...]
javascript_promise_apis = ["fetch", "fs/promises.readFile", ...]
supervisors = ["asyncio.TaskGroup", "anyio.create_task_group", "trio.open_nursery"]
```

`severity` and `roles` work as in the H3 tables. Removing a role or a catalog
entry, adding a supervisor, or lowering the severity to `review` is a policy
deviation (and therefore reported by `VERIFY003` and protected by `--policy`).
`fail_on_unknown = true` makes `unknown` ASYNC001 findings gate by their
severity. A custom supervisor (a long-lived object that keeps its tasks and logs
their failures) is declared in `supervisors`:

```toml
[tool.shockharness.rules.async_lifecycle]
supervisors = ["asyncio.TaskGroup", "anyio.create_task_group", "trio.open_nursery", "app.jobs.Supervisor"]
```

## API-catalog rules (H5)

```toml
[tool.shockharness.rules.processes]   # PROCESS001
enabled = true
severity = "warning"
roles = ["production"]
python_process_apis = ["subprocess.run", "subprocess.call", "os.system", ...]
javascript_process_apis = ["child_process.exec", "child_process.spawnSync", ...]

[tool.shockharness.rules.results]     # RESULT001
roles = ["production", "test"]
python_must_use = ["sorted", "copy.deepcopy", ".strip", ".replace", ...]
javascript_must_use = ["structuredClone", ".map", ".filter", ".trim", ...]

[tool.shockharness.rules.types]       # TYPE001, review; Python and TypeScript
report_any = true                     # Any / any
report_cast = true                    # cast(...); x as T, <T>x (not as const)
report_non_null = true                # x! (TypeScript)
report_type_ignore = true             # # type: ignore; @ts-ignore, @ts-expect-error, @ts-nocheck

[tool.shockharness.rules.sleep]       # SLEEP001, review
python_sleep_apis = ["time.sleep", "asyncio.sleep", "trio.sleep", "anyio.sleep"]

[tool.shockharness.rules.retry]       # RETRY001
retry_decorators = ["tenacity.retry", "retrying.retry", "backoff.on_exception", "backoff.on_predicate"]

[tool.shockharness.rules.batches]     # BATCH001

[tool.shockharness.rules.stubs]
stub003_severity = "review"           # STUB003
```

Every section has `enabled`, `severity` and `roles` as in the H3 tables (the
defaults: `warning`, or `review` for `types` and `sleep`; production only, or
production and test for `results`). Removing a role or a catalog entry,
switching a TYPE001 kind off, or lowering a severity to `review` is a policy
deviation, reported by VERIFY003 and protected by `--policy`. Adding entries
tightens: a project lists its own wrappers (`app.shell.run`, `app.retry`) so the
rules see them. The full default lists are in `defaults.toml`.

## Role integrity (ROLE001)

```toml
[tool.shockharness.rules.role_integrity]
enabled = true
severity = "warning"              # a production file importing a test-role file
empty_test_severity = "review"    # a test-role file with no test case
support_files = ["**/conftest.py", "**/__init__.py", "**/fixtures/**", "**/helpers/**", "**/*helpers*", ...]
```

Lowering either severity to `review` (or below the default), and adding a
`support_files` glob, is a policy deviation, so `VERIFY003` reports it and
`--policy` can pin it. A file that is genuinely test support but matches none of
the defaults goes in `support_files`; a file that production code imports does
not belong in the test role at all.

## External input (INPUT001, INPUT002)

```toml
[tool.shockharness.rules.input]
enabled = true
severity = "warning"              # INPUT001
input002_severity = "review"      # INPUT002
roles = ["production"]
max_depth = 3                     # function boundaries INPUT001 follows a value across
python_sources = ["flask.request.args", "flask.request.form", "request.GET", ...]
javascript_sources = ["req.body", "req.query", "ctx.request.body", "event.body", ...]
python_sinks = ["subprocess.run:0", "os.system:0", "eval:0", "open:0", ".execute:0", ...]
javascript_sinks = ["child_process.exec:0", "eval:0", "fs.readFile:0", ".query:0", ...]
python_validators = ["int", "float", "uuid.UUID", "shlex.quote", ".model_validate", ...]
javascript_validators = ["Number", "parseInt", ".safeParse", ".parse"]
python_config_reads = ["os.getenv", "os.environ.get"]
javascript_config_reads = ["process.env"]
```

A sink entry is `"callee:N"`, the callee's argument N counted from 0 (anything
else is a configuration error); `".name"` (sinks and validators) is a method of
that name on any receiver. Removing a source, sink or configuration read,
adding a validator, lowering either severity, and lowering `max_depth` are
policy deviations. A project adds its own wrappers: a request helper as a
source (`"app.http.query"`), a shell helper as a sink (`"app.shell.run:0"`),
its own validator (`"app.validate.command"`). Command-line programs that take
arguments from untrusted callers add `"sys.argv"`, `"input"` or
`"process.argv"`.

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
reads `.py`, `.js`, `.mjs`, `.cjs`, `.ts`, `.tsx`, `.mts` and `.cts`; a `.pyx`,
`.vue`, `.svelte` or `.ipynb` file in an included tree is otherwise silently
outside the policy.

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

## Cache

Per-file results (parse facts, rule findings, per-unit complexity metrics) are
cached under `cache.directory` (default `.shockharness-cache/`; a relative path
resolves against the analysis root, an absolute path is used as is). Add the
directory to `.gitignore`; it is safe to delete at any time and carries a
`CACHEDIR.TAG` so backup tools skip it. `cache.enabled = false` turns the cache
off; `--no-cache` on `check` (`scan`) and `gate PATH...` bypasses reading and
writing for one run. `baseline create` and revision diffs (`diff`,
`gate --base/--head`) never read it; `analyze_source` has no root and no cache.

**Key.** An entry is used only when every part of its key is equal: the tool
version, the effective configuration digest, the host (interpreter version and
implementation, JavaScript grammar version: parse facts depend on both), the
language, and the SHA-256 of the file's bytes. The `cache` table itself is not
part of the configuration digest, so moving or disabling the cache changes
neither the digest a baseline records nor the key. Everything cross-file (the
call graph and its cycles, suppressions and fingerprints, baseline matching,
diffs, history) is recomputed on every run; a hit yields byte-identical
findings and metrics for that file.

**Layout.** `index.json` holds the key header; `entries/<ab>/<sha256 of the
path>.json` holds one JSON entry per file (never a pickle; nothing read from the
cache is executed). Writes go through a temporary file in the same directory
and an atomic rename. A header that differs (another tool version,
configuration or host) invalidates every entry. An unreadable, corrupt or
schema-mismatched index or entry never fails the run and never yields a
partial result: it is counted, described once, ignored, and the file is
analyzed afresh; a corrupt index rebuilds the cache.

**Reporting.** `coverage.cache` carries `status` (`enabled`, `disabled`,
`bypassed`), `directory`, `reason`, the counters `hits`, `misses`,
`invalidated`, `errors`, and the distinct `problems`. It is the one block of
the JSON report that legitimately differs between a cold and a warm run over
the same tree; a determinism comparison (two runs byte-identical) must drop it,
as the tool's own tests do. The text output prints one `cache:` line and a
`warning: cache:` line per problem.

```text
$ shockharness check .                  # cold: every file analyzed and stored
  cache: .shockharness-cache: 0 hit(s), 906 miss(es), 0 invalidated, 0 error(s)
$ shockharness check .                  # warm: only cross-file work runs
  cache: .shockharness-cache: 906 hit(s), 0 miss(es), 0 invalidated, 0 error(s)
```

On a CI runner, restoring `.shockharness-cache/` between jobs (keyed by the
tool version and the configuration file) turns a full run into the cross-file
phase; a cache from another interpreter or tool version is simply invalidated.

## Glob semantics

* Forward slashes only; patterns are relative to the root.
* `**` matches zero or more whole path segments and must be a segment by itself (`**/`, `/**`).
* `*` matches within one segment, `?` one character, `[abc]`/`[!abc]` a class.
* A pattern with no `/` matches the file's **basename** anywhere in the tree (`*.py`,
  `main.py` matches `main.py` and `build/main.py`). A pattern containing `/` matches
  the whole relative path (`src/**/*.py`).
* A leading `/` or `./` **anchors the pattern to the root** (0.3.0): `/main.py` and
  `./main.py` match only the root-level `main.py`; `/src/*.py` matches `src/a.py` but
  not `src/sub/a.py` or `other/src/a.py`. The anchor applies wherever a glob is
  accepted: `include`, `exclude`, `overrides[].paths`, `file_roles.*`,
  `rules.magic_numbers.configuration_files` and boundary `path`s. Before 0.3.0 a
  leading `/` was a configuration error and `./` was stripped (`./main.py` meant
  `main.py`); a configuration that relied on `./pattern` matching nested files
  must drop the `./`.
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
  than the strict profile, every `fail_on_unknown = false` where the profile
  says `true`, and every override (path or role), each with its reason. The same list is in the text report, SARIF
  run properties, and `config validate`.
* `effective_profile` (top level, next to `tool_version` and `schema_version`)
  names the profile in force, including one selected with `--profile`.
* `files[].rules_disabled` lists, per file, which rules did not run and why
  (`config`, `overrides[i]`, or `configuration_file`).
* `coverage.rules_not_implemented` lists rules that exist in the registry but produce nothing yet.
* `shockharness exceptions PATH...` (0.5.0) lists all of it in one place for a
  human reader: every inline suppression with its reason and whether it silences
  anything, every malformed one, every line above with the configuration file
  and line (or the profile, policy file or command line) it comes from, every
  `exclude` pattern the configuration sets, the `--policy` attempts and, with
  `--baseline`, the baseline's entries per rule and per file. Text or JSON
  (`schemas/exceptions-v1.schema.json`); read-only, exit `0` (or `2` on an
  invalid configuration), never gating.
* `config_digest` is a SHA-256 of the effective configuration so two reports can be compared.
* `config.policy` and `config.policy_attempts` name the `--policy` file and
  every repository key that tried to loosen it; each attempt is also a
  `VERIFY003` finding.
* In a revision diff, `VERIFY003` reports every loosening the change itself
  makes to the configuration, baselines, workflows and other tools' settings.
