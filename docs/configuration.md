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
| `recommended` | `strict`, except: `DEF003` (truthiness fallbacks, already `review` in strict) and `DEF004` (nullish fallbacks) are `review`; `CPLX005` fan-out fires above 30 distinct call targets instead of 20 (`fan_out_warn = 30`) and as a `review` finding instead of a warning (`fan_out_severity = "review"`), because the units over 20 on real codebases are orchestrators (login, streaming, restore); `DEF001`-`DEF006` findings whose status is `unknown` do not gate (`rules.defaults.fail_on_unknown = false`, 0.5.0) | As strict minus `DEF004` and unknown `DEF*` findings |
| `minimal` | `MAGIC001`, `EXC001`-`EXC003` and `DEF001`-`DEF006` all capped at `review` (`rules.<section>.severity = "review"`), `parse_errors = "warn"`, complexity disabled; `SUPP001` still fails | Only malformed suppressions fail; everything is still reported |

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
    uses: evolvingstuff/ShockHarness/.github/workflows/check.yml@v0.29.0
    with:
      shockharness-version: "0.29.0"
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
                                        # C# (Godot .NET, G1) is opt-in: add "**/*.cs" (see below)
exclude = ["**/.git/**", "**/node_modules/**", "**/.venv/**", "**/venv/**",
           "**/dist/**", "**/build/**", "**/generated/**", "**/__pycache__/**",
           "**/*.d.ts",                 # declaration files hold types only
           "**/.godot/**", "**/bin/**/*.cs", "**/obj/**/*.cs"]   # Godot editor and .NET build output
parse_errors = "fail"                   # "fail" -> exit 3 on any unparseable file; "warn" -> reported, gate unaffected
unsupported_sources = "warn"            # an included file no adapter parses (.pyx, .vue): "fail" -> exit 3, "warn" -> listed, "ignore" -> counted only ("ignore" in minimal)
follow_symlinks = false                 # never leave the root through a link unless asked

[tool.shockharness.cache]
enabled = true                          # the content-hash cache of per-file results (0.3.0); see Cache below
directory = ".shockharness-cache"       # relative to the root; belongs in .gitignore; not part of the config digest

[tool.shockharness.skills]
notify_missing = true                   # check prints one line while an agent works here with no skills installed; see Skills notice below

[tool.shockharness.suppressions]
forbidden = []                          # paths where no inline suppression counts; see Inline suppressions below

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
allow_unary_negative_one = true         # -1 passes (items[-1], indexOf() === -1); false reports it; -0 always fails
named_constant_definitions = "allow"    # MAX_PAGES = 8 / CHUNK_BYTES = 64 * 1024 / const SETTLE_MS = 400 at module scope: not reported (every profile, decision 36); "report" tightens
magic004_severity = "review"            # MAGIC004: a constant whose name only spells a number (TWO = 2)
magic005_severity = "warning"           # MAGIC005: a number spelled otherwise (len("  "), int("30"), indent="  ")
exclude_configuration_files = true      # files the config role's globs match skip MAGIC001 (reported per file)
configuration_files = ["conftest.py", "setup.py", "*.config.js", "*.config.mjs", "*.config.cjs",
                       "*.conf.js", "*.conf.cjs", ".eslintrc.js", ".eslintrc.cjs",
                       ".prettierrc.js", ".prettierrc.cjs", "gulpfile.js", "Gruntfile.js"]
                                        # legacy spelling of file_roles.config (kept through 0.x); see File roles

[tool.shockharness.rules.magic_strings]   # MAGIC002, see "Repeated strings (MAGIC002)"
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
fallback_helpers = "review"               # DEF002: calls of value_or(m, k, v), a helper that is m.get(k, v) (decision 34)
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

[[tool.shockharness.rules.exceptions.boundaries]]   # C# (G2): the type as qualified as you like;
path = "src/Game/SaveSystem.cs"                     # it matches a catch's written type by its
language = "csharp"                                 # last segments (IOException)
exception = "System.IO.IOException"
reason = "Save files live on the player's disk"
```

**C# is opt-in (G1).** The default `include` does not list `**/*.cs`, so upgrading never
starts analyzing a project's C# files on its own: only numbers, complexity, suppression
comments, exceptions and defaults run on C# so far (`coverage.rules_not_applicable.csharp`
lists the rest), and strict MAGIC001 would fail a gate that passed before. A project turns C# on by
listing it in its own `include` (the list replaces the default, so repeat the other
languages it uses):

```toml
[tool.shockharness]
include = ["**/*.py", "**/*.cs"]
```

The default `exclude` already leaves out `.godot/` and .NET build output (`bin/**/*.cs`,
`obj/**/*.cs`). To leave third-party Godot plugins out too, set `exclude` to the default
list plus `"addons/**"`.

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
| `generated` | `**/generated/**`, `**/*_pb2.py`, `**/*.min.js`, `**/*.g.cs`, `**/*.Designer.cs` |
| `vendor` | `**/vendor/**`, `**/third_party/**` |
| `config` | `conftest.py`, `setup.py`, `*.config.js`, `*.config.mjs`, `*.config.cjs`, `*.conf.js`, `*.conf.cjs`, `.eslintrc.js`, `.eslintrc.cjs`, `.prettierrc.js`, `.prettierrc.cjs`, `gulpfile.js`, `Gruntfile.js` |
| `test` | `tests/**`, `test/**`, `**/__tests__/**`, `**/test_*.py`, `**/*_test.py`, `**/*.test.js`, `**/*.spec.js`, `**/*.test.mjs`, `**/*.spec.mjs`, `**/*Tests.cs`, `**/*.Tests/**`, `**/conftest.py` |
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
rule_switching_severity = "error" # a configuration change that switches a rule off
```

`VERIFY001`-`VERIFY004` compare the head revision of a `diff` or `gate
--base/--head` with its base revision and report what the change **added**:
test skip and focus markers, blanket suppression comments, a looser policy
(configuration, files dropped from analysis, baselines, workflows, other tools'
settings), and assertions made unable to fail. A plain `check` has no base and
reports them as not applicable, except two parts of `VERIFY003`: the `--policy`
attempts, and every rule the configuration switches off since the **accepted
configuration** (below). See `docs/rules.md` for every pattern.

**Switching a rule off needs a person (spec 21.1 decision 35).** Every
configuration loosening except a catch boundary naming one file switches a rule
off: an `[[overrides]]` entry, a disabled rule family, a lowered severity or gate
mode, a raised threshold, a new `exclude` pattern, a looser profile, an allowed
value, a boundary whose `path` is a glob. `check` and the edit hook compare the
working configuration file with the accepted one: the configuration at the merge
base of `HEAD` and `origin/HEAD`, else at `HEAD`, else (no commit yet, or that
revision has no ShockHarness configuration) what `shockharness init` writes for
the configured profile. Each rule switched off is a `VERIFY003` finding at
`rule_switching_severity`, the stricter of the working and accepted values;
committing the change (on a branch, merging it) accepts it. In `diff` and `gate
--base` the same changes since the base revision get that severity too, so with
the default `"error"` a pull request that switches a rule off fails. Outside a
git repository nothing can be accepted, so nothing is compared;
`coverage.accepted_configuration` and a `VERIFY003:` line in the text report say
what was compared or why not. `shockharness init` (and `skills install` in a
project with no configuration) writes the test exemption
(`roles = ["test"]`, `disable = ["MAGIC001", "DEF001"]`), so a new project does
not need to add it.

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | `false` turns the four rules off (a policy deviation) |
| `severity` | `"warning"` | the severity of every VERIFY finding. `"error"` makes them gate like any hard violation; that tightens the policy and is not a deviation. `"review"` lowers them further and is a deviation |
| `fail_on_unknown` | `false` | whether an `unknown` VERIFY finding (the base version could not be analyzed, or rename detection failed) gates according to its severity |
| `allowed_skip_reasons` | `[]` | exact reason strings that make an added Python skip acceptable (JavaScript skips carry no reason). Each entry is listed as a policy deviation |
| `report_narrow_suppressions` | `false` | `VERIFY002` always reports blanket suppressions; with `true` it also reports added suppressions that name specific rule codes |
| `rule_switching_severity` | `"error"` | the severity of `VERIFY003` findings for a configuration change that switches a rule off (above). Lowering it is a deviation and is itself reported at the accepted configuration's severity |

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

[tool.shockharness.rules.assertions]       # ASSERT001, ASSERT002
enabled = true
severity = "warning"                       # ASSERT001: an assert on external input
assert002_severity = "review"              # ASSERT002: asserts relied on, -O not refused
roles = ["production"]
allow_type_narrowing = true
external_reads = ["sys.argv", "sys.stdin", "input", "os.environ.*", "open", ".read_text", ...]   # "x.*": below x only

[tool.shockharness.rules.boolean_arguments]  # BOOL001
enabled = true
severity = "review"
roles = ["production"]
allowed_callees = ["get", "getattr", "setattr", "setdefault", "pop", "next",
                   "SetShaderParameter", "Set", "SetDeferred", "Call", "Rpc", "EmitSignal", ...]   # Godot (G2)

[tool.shockharness.rules.module_state]     # STATE001, STATE002, STATE003
enabled = true
severity = "warning"
roles = ["production"]
allowed = []                               # [[...allowed]] path, name, reason
state002_severity = "review"               # STATE002: published before initialized
state003_severity = "review"               # STATE003: read outside the lock its writes hold

[tool.shockharness.rules.import_effects]   # IMPORT001
enabled = true
severity = "warning"
roles = ["production"]
python_operations = ["subprocess.run", "os.system", "socket.socket", "requests.get", ...]
javascript_operations = ["child_process.exec", "fs.rmSync", "fetch", "setInterval", ...]
script_files = ["scripts/**", "bin/**"]    # scripts IMPORT001 skips when nothing imports them
```

The full lists are in the bundled `defaults.toml` (`shockharness config
effective` prints them). `EXC004` belongs to `rules.exceptions` (its `enabled`
switch and `severity` cap) and applies to every role.

| Key | Meaning | Policy deviation when |
|---|---|---|
| `severity` | the severity of every finding of the section's rules, as in `rules.verification`: `warning` by default (`review` for BOOL001, decision 9), `error` to gate | lowered to `review` |
| `roles` | the file roles the rules apply to; a rule is not applied to (and not listed in `rules_applied` of) a file of another role | a default role is removed |
| `markers` | STUB001 also reports comment lines that open with one of these words | never (adding tightens) |
| `test_path_segments`, `mock_modules` | what STUB002 treats as test code | an entry is removed |
| `allow_type_narrowing` | ASSERT001 never reports an assert that only narrows types | never (`false` tightens) |
| `external_reads` | what ASSERT001 treats as external input, beyond `rules.input`'s sources and configuration reads | an entry is removed |
| `allowed_callees` | BOOL001 skips calls whose last callee segment is listed | an entry is added |
| `allowed` | STATE001 skips `name` in files matching `path` | always, one line per entry, with its `reason` |
| `python_operations`, `javascript_operations` | the qualified callees IMPORT001 reports at import time | an entry is removed |
| `script_files` | globs of scripts IMPORT001 skips when no analyzed file imports them (a shebang file is always skipped) | a glob is added |

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
[tool.shockharness.rules.async_lifecycle]   # ASYNC001-ASYNC004
enabled = true
severity = "warning"                        # "warning" | "error" | "review"
roles = ["production", "test"]
fail_on_unknown = false                     # ASYNC001 through a probable call-graph edge
python_coroutine_apis = ["asyncio.sleep", "asyncio.wait_for", "asyncio.gather", ...]
javascript_promise_apis = ["fetch", "fs/promises.readFile", ...]
supervisors = ["asyncio.TaskGroup", "anyio.create_task_group", "trio.open_nursery"]
gates = ["navigator.locks.request:last"]   # ASYNC004: calls holding a gate while their callback runs
```

`gates` (ASYNC004) lists the calls that hold a gate, a command queue or a lock, while
their callback runs: `callee:index` with the callback's argument index, or
`callee:last`. A project adds its own queue (`gates = ["navigator.locks.request:last",
"CommandGate.run:1"]`); the callee is matched as written.

`severity` and `roles` work as in the H3 tables. Removing a role or a catalog
entry (a gate included), adding a supervisor, or lowering the severity to `review` is a policy
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
csharp_must_use = ["Mathf.Clamp", ".Trim", ".Normalized", ".Where", ...]   # C# since G2
# C# since G3: rules.async_lifecycle.csharp_task_apis, rules.import_effects.csharp_operations,
# rules.processes.csharp_process_apis, rules.sentinels.csharp_index_callees

[tool.shockharness.rules.types]       # TYPE001, review; Python, TypeScript and C# (G4)
report_any = true                     # Any / any / dynamic
report_cast = true                    # cast(...); x as T, <T>x (not as const)
report_non_null = true                # x! (TypeScript, C#; not C#'s null! or default!)
report_type_ignore = true             # # type: ignore; @ts-ignore, @ts-expect-error, @ts-nocheck;
                                      # #nullable disable, #pragma warning disable CS86xx
annotated_share = 0.5                 # TYPE002: this share of production functions annotated...
min_annotated_functions = 20          # ...and at least this many, with no type checker configured
type002_severity = "review"           # TYPE002's severity (C#: a .csproj with Nullable off)

[tool.shockharness.rules.sleep]       # SLEEP001, review
python_sleep_apis = ["time.sleep", "asyncio.sleep", "trio.sleep", "anyio.sleep"]
csharp_sleep_apis = ["Thread.Sleep", "Task.Delay", "OS.DelayMsec", "OS.DelayUsec", "AwaitMillis"]

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
support_files = ["**/conftest.py", "**/__init__.py", "**/fixtures/**", "**/support/**", "**/*fixture*", "**/*helper*", "**/*_support.*", ...]
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

## Cross-site consistency (PROV001, GUARD001)

```toml
[tool.shockharness.rules.consistency]
enabled = true
severity = "review"
roles = ["production"]
python_fabricators = ["uuid.uuid4", "uuid.uuid1", "secrets.token_hex", "secrets.token_urlsafe"]
javascript_fabricators = ["crypto.randomUUID", "uuid.v4", "uuid.v1", "nanoid.nanoid"]
issuer_prefixes = ["start", "create", "new", "register", "open", "begin", "issue", "allocate", "insert"]
guard_min_sites = 3
guard_min_percent = 75
```

Removing a fabricator or an issuer word, and raising either GUARD001 threshold,
are policy deviations. Values are followed across at most
`rules.input.max_depth` function boundaries, as for INPUT001.

## Sentinels (MAGIC003)

```toml
[tool.shockharness.rules.sentinels]
enabled = true
severity = "review"
roles = ["production"]
values = [-1]                     # adding 0 or 1 is possible, and noisy
python_index_callees = ["range", "slice", "itertools.islice", ".pop", ".insert", ".split", ...]
javascript_index_callees = [".slice", ".at", ".splice", ".substr", ".indexOf", ...]
standard_targets = ["tabIndex"]   # names whose -1 a platform standard defines
```

Removing a value or a role, and adding an index callee or a standard target, are
policy deviations.

## Repeated strings (MAGIC002)

```toml
[tool.shockharness.rules.magic_strings]
enabled = true
mode = "review"                   # "fail": the findings are errors
roles = ["production"]
min_length = 4                    # characters, whitespace aside
min_occurrences = 3
min_files = 2
min_compared_files = 2            # files where the value is compared (==, in, ===, case)
kinds = ["argument", "subscript", "compare", "value"]   # "key" and "jsx" are opt-in
message_callees = ["debug", "info", "warning", "warn", "error", "exception", ...]
allowed = ["utf-8", "utf8", "__main__", "strict", "replace", "ignore", "ascii"]
```

Raising a threshold, removing a role or a kind, and adding a message callee or
an allowed value are policy deviations; `mode = "fail"` back to `"review"` is a
loosening `VERIFY003` reports in a diff.

## Delegated handlers, floating controls and text positions (DOM001, DOM002, DOM003)

```toml
[tool.shockharness.rules.dom]
enabled = true
severity = "warning"              # DOM001
roles = ["production"]
classes = ["HTMLElement"]
# DOM002: the functions holding the skip lists of press handlers that act on presses
# outside, as "path:function"; empty (the default) reports nothing.
press_exclusions = ["app/static/js/events/mouse-events.js:isOutsideEditExclusion"]
dom002_severity = "review"
dom003_severity = "review"        # DOM003: selections saved as text positions
```

DOM003 has no other setting: it applies to the section's roles, at `dom003_severity`
(`review`, since whether the content can hold anything but text is not known). Lowering it
is a VERIFY003 loosening.

An entry that is not `path:function` is a configuration error; one whose
function is not found in an analyzed file is an `unknown` DOM002 finding.

Removing a class or a role is a policy deviation; adding a narrower class
(`HTMLButtonElement`) reports those filters too.

## Dead code (DEAD001, DEAD002)

Opt-in (spec 21.1 decision 38): off is the default in every profile and is not a
deviation. The judgment is project-wide, so it is made only when the run analyzed every
file `include` selects and none failed to parse; a run over a path, and the edit hook,
report nothing.

```toml
[tool.shockharness.rules.dead_code]
enabled = false                  # true turns the two rules on
roles = ["production"]           # where dead functions are reported; test and config
                                 # files are the roots of DEAD002, never reported
# Functions reached in ways the analysis cannot see, as globs over
# "path::qualified.name": a getattr with a computed name, a function only an HTML
# page or a template calls.
entry_points = ["app/db/migrations.py::_migration_*", "app/static/js/main.js::on*"]
severity = "review"              # DEAD001
dead002_severity = "review"
```

The files a `rules.property_contracts.runtime_module` entry names by path are libraries:
their functions are not judged. While the family is on, turning it off, adding an entry
point or removing a role is a VERIFY003 loosening, and so is lowering either severity.
looseness.

## Duplicated helpers (DUP001, DUP002)

Opt-in (spec 21.1 decision 39): off is the default in every profile and is not a
deviation. Like the dead-code rules, the judgment is made only when the run analyzed every
included file.

```toml
[tool.shockharness.rules.duplicates]
enabled = false                  # true turns the two rules on
roles = ["production"]           # the files whose functions are compared
min_statements = 3               # the smallest function compared (at least 3)
min_tokens = 25                  # ... and its fewest syntax tokens
similarity = 0.85                # DUP002: how alike two versions must be (difflib ratio)
severity = "review"              # DUP001
dup002_severity = "review"
```

While the family is on, turning it off or removing a role is a VERIFY003 loosening, and so
is raising `min_statements`, `min_tokens` or `similarity`, or lowering either severity.

## Godot names (GODOT001-GODOT005)

Spec 21.1 decision 51; C# only, and only for files under a `project.godot`. On by
default: C# itself is opt-in (`include` must list `**/*.cs`).

```toml
[tool.shockharness.rules.godot_names]
enabled = true
severity = "warning"           # GODOT001 (input actions), GODOT003 (connections), GODOT005 (signals)
roles = ["production"]
godot002_severity = "review"   # node paths: a node added at run time is not in the scene file
godot004_severity = "review"   # groups: a group a GDScript or an addon adds is not seen
```

Switching the section off, removing a role or lowering a severity is a policy deviation,
like the H3 tables.

## Import boundaries (IMPORT002)

Spec 21.1 decision 44. Modules some files must never import, declared per project: no entry
by default, so IMPORT002 reports nothing (and is not recorded in a file's `rules_applied`)
until a project adds one. `importers`, `allowed_names` and `reason` are required; an entry
names what it forbids with `imported` (project files, by path), `modules` (other modules, by
name) or both, and may exempt files with `allowed_importers`.

```toml
[tool.shockharness.rules.import_boundaries]
enabled = true
severity = "error"               # "warning" or "review" report without gating

[[tool.shockharness.rules.import_boundaries.forbidden]]
importers = ["/app/main.py", "/app/db/migrations.py"]    # the files the entry binds (globs)
imported = ["/app/services/backup_service.py"]           # the files they may not import (globs)
allowed_names = []               # names they may still import from it; [] allows none
reason = "a migration can never touch a backup"

[[tool.shockharness.rules.import_boundaries.forbidden]]
importers = ["/app/services/auth_service.py"]
imported = ["/app/services/backup_service.py"]
allowed_names = ["create_timestamped_backup"]
reason = "authentication may only take a new backup"

[[tool.shockharness.rules.import_boundaries.forbidden]]
importers = ["/app/**"]
allowed_importers = ["/app/services/public_http.py"]   # bound files exempt from the entry (globs)
modules = ["httpx", "urllib.request", "http.client", "socket"]  # other modules, by name
allowed_names = []
reason = "network calls go through public_http"
```

`modules` names a module as code imports it and covers everything below it: Python
`cryptography.hazmat` matches `cryptography.hazmat.primitives` and `from cryptography import
hazmat`, not `import cryptography`; a JavaScript package matches its paths (`fs` matches
`fs/promises`), a scoped package is one name (`@anthropic-ai/sdk`), and `node:fs` and `fs`
are the same. Only imports that do not resolve to an analyzed file are matched by name; a
project file is named by its path under `imported`. A relative specifier (`./x`, `.errors`)
is a configuration error.

Both sides are path globs (see Glob semantics), matched against the importing file and the
file the import resolves to, so one entry covers `from app.services.backup_service import
x`, `import app.services.backup_service`, `from app.services import backup_service`, a
relative import and a JavaScript path alike. With `allowed_names` set, an import of the
whole module (`import m`, `from pkg import m`, `import * as m`, a bare `require`, a star or
side-effect import) is reported, since it takes every name; a JavaScript default import is
the name `default`.

Removing an entry, narrowing its globs, dropping a module, exempting another file or adding
an allowed name is a VERIFY003 loosening (an entry is kept when some new entry binds at
least the same importers, exempts no other file, forbids at least the same files and
modules and allows no other name), and so is lowering the severity. Turning the
section off is a deviation.

## Call boundaries (CALL001)

Calls some files must never make, declared per project: no entry by default, so CALL001
reports nothing (and is not recorded in a file's `rules_applied`) until a project adds one.
`callers`, `calls` and `reason` are required; `allowed_callers` exempts files.

```toml
[tool.shockharness.rules.call_boundaries]
enabled = true
severity = "error"                    # "warning" or "review" report without gating

[[tool.shockharness.rules.call_boundaries.forbidden]]
callers = ["/app/**"]                                  # the files the entry binds (globs)
allowed_callers = ["/app/storage/encrypted_writer.py"] # bound files exempt from it (globs)
calls = ["@disk_writes"]                               # what they may not call
reason = "plaintext never touches disk"

[[tool.shockharness.rules.call_boundaries.forbidden]]
callers = ["/app/static/js/**"]
allowed_callers = ["/app/static/js/modules/api-client.js"]
calls = ["@network"]
reason = "the browser talks to the server through one client"
```

A call is a qualified name and everything below it (`shutil`, `os.replace`, `fetch`,
`fs/promises.writeFile`), a method on any receiver (`.write_text`), either with
`/mode=write` (only a literal write mode counts), or a catalog. `@disk_writes` and
`@network` expand to the section's `python_disk_writes` / `javascript_disk_writes` /
`python_network` / `javascript_network` lists for the file's language; `shockharness
config effective` prints them. Removing a name from a catalog is a policy deviation.
Removing an entry, dropping a call, exempting another file or narrowing `callers` is a
VERIFY003 loosening (an entry is kept when some new entry binds at least the same callers,
exempts no other file and forbids at least the same calls). `docs/rules.md` has the
matching rules.

## Property contracts (PROP001, PROP003, PROP005, PROP006, PROP007)

Opt-in (`docs/shockharness_property_contracts_spec.md`, milestones P1a, P1b and P2,
Python and JavaScript; the adopter's guide is `docs/property-contracts.md`). Off is
the default in every profile and is not a deviation. The rules are described in
`docs/rules.md`.

```toml
[tool.shockharness.rules.property_contracts]
enabled = false                    # true turns the family on for this repository
roles = ["production"]             # the file roles checked
fail_on_unknown = false            # whether unknown PROP001 findings gate
runtime_module = []                # where `shockharness contracts install` put the file:
                                   # "app/contracts.py" (a project path, flat or src layout;
                                   # it may be excluded from analysis) or a package name
allow_undeclared = false           # PROP003 is error; true: review, and the name counts
enforcement = "declared"           # "declared" | "complete": PROP008, every parameter and return declared
complete_paths = []                # globs where "complete" applies while the rest stays "declared"
max_depth = 3                      # calls a result is followed through; deeper is unknown
                                   # (raising it is never a loosening, decision 47)
runtime_mode_required = "check"    # "off" | "check" | "verify": with "verify", PROP005
                                   # checks registration_module registers every predicate
registration_module = ""           # app.predicates or static/js/predicates.js; "" none

[tool.shockharness.rules.property_contracts.severities]
PROP001 = "review"
PROP002 = "review"
PROP003 = "error"
PROP004 = "review"
PROP005 = "review"
PROP006 = "review"
PROP007 = "review"
PROP008 = "review"

[[tool.shockharness.rules.property_contracts.properties]]
name = "cloud_disclosable"         # lower_snake_case, listed once
description = "content the privacy evaluator permits to leave the machine"
producers = ["app.privacy.evaluate"]   # dotted references to project functions; [] = any
runtime = "static"                 # "static" | "check" | "verify": what the runtime checks

[[tool.shockharness.rules.property_contracts.properties]]
name = "sanitized_html"
description = "markup that may be assigned to the page"
producers = ["static/js/sanitize.js:sanitize"]   # JavaScript: path:export
runtime = "static"
literal_satisfies = true           # optional: "" and "<hr>" carry it by themselves

[[tool.shockharness.rules.property_contracts.compositions]]
language = "javascript"            # "python": "fstring" | "concat" | "format" | "join"
operation = "template_literal"     # "javascript": "template_literal" | "concat" | "join"
inputs_require = ["escaped_html"]  # every non-literal part must carry these
produces = "sanitized_html"
reason = "constant markup around escaped text is safe markup"

[[tool.shockharness.rules.property_contracts.sinks]]
language = "javascript"
target = "innerHTML"               # an assignment: <any>.innerHTML = value ("headers[]": a subscript)
requires = ["sanitized_html"]
reason = "unsanitized markup reaching the page is the XSS path"

[[tool.shockharness.rules.property_contracts.sinks]]
language = "python"
callee = "app.cloud.send_messages:0"   # a project or library callee; the argument by position
requires = ["cloud_disclosable"]       # catalog properties
reason = "nothing reaches the provider without the privacy evaluator"
producer = "app.privacy.evaluate"      # optional; the finding names it
```

**Checks.** These are configuration errors (exit 2) whenever the configuration is
loaded:

* a sink with both or neither of `callee` and `target`; a malformed `callee` (not
  `<reference>:<N>`) or `target`;
* a sink or composition naming a property the catalog does not list;
* a composition operation the language does not have;
* a duplicate or badly spelled property name;
* an enabled family with no `runtime_module`;
* `runtime_mode_required = "verify"` with no `registration_module`. When the family is enabled, `config validate` and every
analysis also resolve each Python reference against the project's files:

* every producer must be a function of the project: a dotted Python reference, or a
  JavaScript `path:export` that the file exports (re-exports followed);
* a sink callee in a project module or file must exist there;
* a sink callee in no project module is a library callee and is accepted: Python
  `json.dumps`, JavaScript `dompurify:sanitize` or a global such as `fetch`.

An unresolved reference is a configuration error that names the key.

**The runtime file.** `shockharness contracts install --language python --dest
app/contracts.py` copies the runtime into the project. `--language javascript --dest
static/js/vendor/shockharness-contracts.js` copies the ES module and writes
`shockharness-contracts.d.ts` beside it (`.mjs` gets `.d.mts`). In a browser, where the
page's modules run before a harness could call `enable`, there are two options. A
test-entry page can call it in a module script before the application's. An init script
(Playwright's `addInitScript`, Puppeteer's `evaluateOnNewDocument`) can set
`globalThis.__shockharnessContracts = { mode: "check", static: [...] }`; the module
reads that once at load, treats it as `enable`, and deletes it. `--project DIR` names the root
(default: the current directory). The copy is recorded in `.shockharness-contracts.json`,
in the manifest format `skills install` writes. An edited copy, or a file this manifest
did not write, is never replaced without `--force`.
`shockharness contracts install --check` writes nothing and exits 1 when a recorded copy
is edited, missing or older than the shipped runtime. Nothing is published to any package
registry, and the project depends on its own copy, not on `shockharness`. Test code calls
`enable("check", static_properties)` once, before any declaration has run. The second
argument is a list of the properties marked `runtime = "static"`: it is required, and is
`[]` when there are none. `shockharness contracts static-properties [--root DIR]` prints
it in the form to paste. PROP005 reports a bootstrap whose literal list disagrees with
the catalog. `enable("verify", [...])` also runs the predicates the project
registers with `register(name, predicate, description)`. Until then, and in production, every declaration
is the identity.

Every key is covered by VERIFY003 (see `docs/rules.md`).

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

## Skills notice

`skills.notify_missing` (default `true`): while the project has a configuration of its
own and a coding agent's files are in it (`.claude/` or `CLAUDE.md` for Claude Code,
`.agents/` or `AGENTS.md` for Codex and the other agents that read `AGENTS.md`) with no
ShockHarness skills installed for that agent, `check` prints one line on stderr naming
the `skills install` command (docs/skills.md). `false` records that the repository wants
no skills and stops the line. Like the `cache` table, the `skills` table is not part of
the configuration digest: it cannot change a result.

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
diffs, history) is recomputed on every run, with one exception below; a hit
yields byte-identical findings and metrics for that file.

**The property-contracts phase** is the one cross-file phase the cache covers
(first for an unchanged tree only, now file by file; see CHANGELOG.md). It is
the most expensive, and it only runs when `rules.property_contracts.enabled` is true.
Each checked file's findings are kept with what they depended on, and reused while all
of it is unchanged:
* the header (tool version, configuration digest, host);
* the file's text, and which contract rules and `complete` scope apply to it;
* every name its analysis resolved, which must resolve to the same file;
* the text of every module it depended on, analyzed or read from disk, including
  modules reached only through a callee's result the analysis had already computed for
  another file;
* every JavaScript path it looked for, which must still exist or still be missing;
* when an override check ran for it, the classes of every analyzed module (their names,
  bases and methods).

Every other file is computed afresh, and with it only what its findings need. On
MetaList (981 files, contracts on) an edit to one file recomputes 3 to 7 files. A
change to a class (a new subclass, a renamed method) recomputes the files that ran an
override check, about 200 there.

**Layout.** `index.json` holds the key header; `entries/<ab>/<sha256 of the
path>.json` holds one JSON entry per file, and `contracts.json` the last
contracts phase (never a pickle; nothing read from the cache is executed). Writes go through a temporary file in the same directory
and an atomic rename. A header that differs (another tool version,
configuration or host) invalidates every entry. An unreadable, corrupt or
schema-mismatched index or entry never fails the run and never yields a
partial result: it is counted, described once, ignored, and the file is
analyzed afresh; a corrupt index rebuilds the cache.

**Reporting.** `coverage.cache` carries `status` (`enabled`, `disabled`,
`bypassed`), `directory`, `reason`, the counters `hits`, `misses`,
`invalidated`, `errors`, the distinct `problems`, and `contracts`: `off` (the
phase did not run, or the cache is not open), `hit` (every checked file reused its
entry), `stale` (some did) or `miss` (none did), with `contracts_reused` of
`contracts_files`. It is the one block of
the JSON report that legitimately differs between a cold and a warm run over
the same tree; a determinism comparison (two runs byte-identical) must drop it,
as the tool's own tests do. The text output prints one `cache:` line and a
`warning: cache:` line per problem.

```text
$ shockharness check .                  # cold: every file analyzed and stored
  cache: .shockharness-cache: 0 hit(s), 906 miss(es), 0 invalidated, 0 error(s)
$ shockharness check .                  # warm: only cross-file work runs
  cache: .shockharness-cache: 906 hit(s), 0 miss(es), 0 invalidated, 0 error(s)
  cache: property contracts: reused for every file (981 of 981 files)
$ shockharness check .                  # after an edit to one file
  cache: property contracts: reused where nothing they depend on changed (974 of 981 files)
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
* `suppressions.forbidden` does the same for chosen paths, from the configuration: for
  code whose findings are resolved by a change and never silenced, such as regression
  cases. Each entry needs `paths` (globs) and a `reason`, which the `SUPP001` message
  quotes with the matching glob.

  ```toml
  [[tool.shockharness.suppressions.forbidden]]
  paths = ["tests/regression/adversarial/**"]
  reason = "a regression case is resolved by a code change"
  ```

  A ban tightens the policy, so it is not a deviation. Removing an entry, or dropping a
  path from it, is a `VERIFY003` loosening (an entry is kept when some new entry still
  lists all its paths).

## Reporting of policy changes

Everything that loosens the strict profile is surfaced, never silent:

* `config.deviations` lists the profile when it is below `strict`, disabled
  rules (complexity included), `cyclomatic_counts_boolean_operators = false`,
  every `rules.<section>.severity = "review"`
  cap, extra `allowed_values`, `allow_unary_negative_one`, `parse_errors = "warn"`,
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
