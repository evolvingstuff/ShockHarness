# Changelog

All notable changes to ShockHarness. Format follows Keep a Changelog; versions
follow Semantic Versioning. The report `schema_version` is tracked separately.

## [Unreleased]

### Added
- Property contracts, milestone P1a (opt-in, Python; spec v0.5). The family is off by
  default and in every profile.
  - **Declarations:** `requires` / `produces` / `preserves` / `preserves_except`.
  - **Checks:** at call sites against the callee's own declared contract (one hop,
    across files) and at catalog callee sinks (`callee:N`, keyword arguments mapped for
    project callees).
  - **Rules:** `PROP001` (review), `PROP003` (error unless `allow_undeclared`),
    `PROP006` and `PROP007` (review).
  - **Unknown:** every await, generator and `.join` build.
  - **Configuration:** `rules.property_contracts` with `config validate` resolving the
    catalog's references. VERIFY003 covers every key.
  - **Runtime:** the runtime file `src/shockharness/contracts/runtime/contracts.py`
    (identity until `enable("check", static_properties)`; `check` mode; static
    properties counted by `report()`).
  - **Install:** `shockharness contracts install --language python --dest PATH` and
    `--check`, recorded in `.shockharness-contracts.json`. Nothing is published.
  - `RESULT001` permits the four declarations as statements when they resolve to the
    runtime module.
  - Spec v0.6 (decisions 37 and 38):
    - `enable` raises unless its second argument is a list of strings.
    - `PROP005` (review) reports a test bootstrap's `enable(...)` whose literal list is
      not the catalog's `runtime = "static"` set, and a non-literal list is `PROP006`.
    - `shockharness contracts static-properties` prints the list to paste.
    - The §11.1 fixture uses the `produces(preserves(expr, x), "p")` idiom.
- `STATE002` (`rules.module_state`, review, Python): a shared object published before
  it is initialized. A global, or `self.<attr>` outside a constructor, is assigned a
  new object and then has its fields set in the same function, so another thread can
  read it half-built. Severity `rules.module_state.state002_severity`. From MetaList's
  encryption-service race. Measured: exactly MetaList's two pre-fix functions, nothing
  else in about 2,500 files. The cache schema is "20".

### Changed (feedback from MetaList on 0.9.0)
- `ASYNC003`: a `Promise.allSettled(...)` at a script's top level is checked against
  the statements that follow it in its block, as one inside a function is checked
  against the function. A top-level batch checked on the next line, inside a
  top-level `try`, is no longer reported; one that nothing after it checks still is.
  The cache schema is "19".

## [0.9.0] - 2026-10-17

Fewer reasons to work around the gate: the findings of the under-the-gate experiment
(three rounds) and of MetaList. New rules ship at `warning` or `review` (decision 9).

**Upgrading from 0.8.0.** No change makes a passing gate fail:
- **Named constants (decision 36).** MAGIC001 no longer reports the literal of a
  module-level named constant definition (`MAX_PAGES = 8`, `const SETTLE_MS = 400`,
  `CHUNK_BYTES = 64 * 1024`) in any profile. `named_constant_definitions = "allow"` is
  now the strict default too; `"report"` is a tightening. An existing
  `# shockharness: ignore[MAGIC001]` on such a line now matches nothing and is a
  SUPP002 warning: delete the comment and keep the citation as a plain comment.
- **Fewer false alarms.** DEF005 (an entry point's exit status inside a boundary,
  decision 37), DEF002 (an assigned grouping `setdefault`) and BOOL001 (assertion
  arguments) report fewer findings.
- **New findings, never failing the gate.** EXC005 (warning) and MAGIC004 (review) are
  new; they report but never fail.

### Added
- `EXC005` (`rules.exceptions`, warning): a declared catch boundary naming an
  exception that no catch in the files it covers catches, reported at the
  boundary's line in the configuration file. Judged only when every covered file
  was analyzed in the run. From the under-the-gate experiment, where agents
  declared boundaries ahead of the code.
- `MAGIC004` (`rules.magic_numbers`, review, Python, JavaScript and TypeScript): a
  named constant whose name only spells a number (`TWO = 2`, `ONE_HUNDRED = 100`,
  `VALUE_100 = 100`). Severity `rules.magic_numbers.magic004_severity`.

### Changed
- MAGIC001 under `strict`: named constant definitions are allowed (decision 36). The
  `recommended` and `minimal` profiles no longer set the option, since it is the
  default. Measured before the change: 965 MetaList findings, all 35 in
  ShockHarness's own `src`, and 58 in the under-the-gate experiment's agent-written
  builds go away, and no constant name among them only spells a number.
- The skills say a fixed value is a module-level named constant that cites its
  source, with no suppression, never named after its value or disguised. They also
  say:
  * a failed read or write is reported, never dropped;
  * a boundary is declared for the catch being written;
  * a project error never derives from `SystemExit`;
  * test values stay in the test;
  * the `python -O` refusal is only for code that asserts.
- `DEF002`: `x = m.setdefault(k, <empty container>)` whose next statement mutates `x`
  is the grouping idiom, like the chained form, and is not reported.
- `DEF005` (decision 37): inside a declared boundary, an entry point's handler that
  returns a named non-zero exit status (`return EXIT_UNREADABLE`) is not reported.
  The entry point is `main`, a function called under `if __name__ == "__main__":`, or
  one named in `[project.scripts]`. The remediation says not to re-implement a
  library's validation to avoid its exception.
- `BOOL001`: the expected value of an assertion (`assertEqual(x, True)`,
  `assert.equal(v, true)`) is not reported. MetaList had 159 of its 353 findings there.
- ShockHarness's own configuration drops its `constants.py` MAGIC001 override.
- The consumer upgrade check injects a literal in an expression, and the examples
  keep their RFC citations as plain comments.
- The cache schema is "18".

## [0.8.0] - 2026-10-17

The edit-time hook for Claude Code, decisions 34 and 35, MAGIC002, DOM001 and DOM002,
and two more rounds of MetaList feedback. New rules ship at `warning` or `review`
(decision 9).

**Upgrading from 0.7.0.** Two changes can move a gate verdict, and a third changes
new projects:
- **Switching a rule off is now an error (decision 35).** `check` and the edit
  hook compare the configuration file with the accepted one (the merge base with
  `origin/HEAD`, else `HEAD`). Every loosening except a catch boundary naming one
  file is a `VERIFY003` error until a person commits it. In `diff` and `gate
  --base`, the same changes since the base are errors too (they were warnings), so
  a pull request that switches a rule off fails. Set
  `rules.verification.rule_switching_severity = "warning"` for the old behavior;
  that is itself a reported deviation.
- **`DEF002` statement forms (decision 34)**, below.
- `shockharness init` now writes the test exemption (`MAGIC001` and `DEF001` off for
  the test role). Existing configuration files are not changed.

**DEF002 statement forms.** `DEF002` (version 2) now recognizes the `return` statement form of
the membership fallback in Python: `if k in m: return m[k]` followed by
`return v`, and `if k not in m: return v` followed by `return m[k]`. It is an
error under `missing_value_fallbacks = "forbid"`, like `m[k] if k in m else v`,
so a gate that passed can fail. Measured: MetaList 20, ShockHarness's own `src`
8 (fixed in the same change), pip, pytest, hypothesis, build, hatchling and npm
together 1.

### Added
- Spec 21.1 decision 34: `DEF002` follows fallback helpers. A call of a
  module-level function of the same file whose body (after a docstring and
  checks that only raise) is a lookup with a default that is one of its
  parameters (`m.get(k, default)`, `getattr(o, a, default)`, either membership
  form, `try: return m[k]` / `except KeyError: return default`) is reported at
  the call, with the argument as the fallback. New mode
  `rules.defaults.fallback_helpers`, `"review"` in strict for this release.
  MetaList's `_mapping_value_or`, whose 26 literal defaults reset 11 server-kept
  reminder fields on every edit, gives 32 such findings on its pre-fix tree.
  The `fix-violations` skill and DEF002's remediation no longer recommend a
  helper that returns a stand-in for a missing value. The cache schema is "17".
- Spec 21.1 decision 35, from the under-the-gate experiment (round 2):
  - `shockharness init`, and `skills install` in a project with no
    configuration, write the test exemption ShockHarness's own configuration
    has (`roles = ["test"]`, `disable = ["MAGIC001", "DEF001"]`). The skills
    say `init` has done it.
  - `check` and the edit hook report every rule the configuration switches
    off since the accepted configuration (the merge base with `origin/HEAD`,
    else `HEAD`, else what `init` writes) as `VERIFY003`. Every loosening
    counts except a catch boundary naming one file. The new key
    `rules.verification.rule_switching_severity` (default `"error"`) sets the
    severity, so `check` fails until a person commits the change. The hook
    feeds it back as soon as the configuration file changes, whichever tool
    changed it. `coverage.accepted_configuration` says what was compared.
  - `skills install --hook --lock` writes the project's configuration
    (boundaries aside) as a `--policy` file under
    `~/.config/shockharness/locks/` and runs the hook with it.
  - **Behavior change:** in `diff` and `gate --base`, a configuration change
    that switches a rule off is now a `VERIFY003` error (it was a warning, per
    decision 9), so such a pull request fails the gate. Set
    `rule_switching_severity = "warning"` to keep the old behavior; that is
    itself a reported deviation.
- Edit-time feedback for Claude Code: `shockharness hook claude-code post-edit`
  reads a `PostToolUse` tool call on stdin, analyzes the edited file and feeds
  its findings (`--fail-on`, `warning` by default) back to the agent with exit 2.
  `skills install --agent claude --hook` appends the hook to the project's
  `.claude/settings.json` (once, never replacing existing hooks); without
  `--hook`, it offers it.
  The hook skips files that are not source (`pyproject.toml`, `README.md`).
  It also runs after shell commands (matcher `Edit|Write|MultiEdit|Bash`) and
  then checks the source files `git status` shows as changed since its last run:
  agents often write files through the shell. Each run is logged in
  `.shockharness-cache/hook/runs.jsonl`; `skills install --hook` updates an older
  matcher.
- `DOM002` (`rules.dom`, review, JavaScript and TypeScript, opt-in): a pressable
  element attached to `document.body` (directly, or appended into a container a
  function attaches and returns) that matches no selector of the skip lists named
  in `press_exclusions` (`"path:function"`): its presses reach that handler as
  presses outside (decision 32). Skip lists follow constants and helper calls
  through imports. Nothing is reported while `press_exclusions` is empty. New
  keys: `press_exclusions`, `dom002_severity`. The cache schema is "16".

### Changed (MetaList's rule ideas)
- `MAGIC003`: not reported for a name in the new `standard_targets` (`tabIndex`,
  where HTML defines `-1`), nor for a `-1` passed to a callee the same file also
  passes `1` (`move(-1)` beside `move(1)`).
- `RESULT001`: a method of a string literal is recorded as the `str` method, and
  `str.join` is in the Python defaults, so `", ".join(parts)` alone on a line is
  reported. The cache schema is "15".
- Skills: `pre-commit-review` asks that an element attached to `document.body`
  is skipped by every page-level "outside press" handler and pressed by a
  browser test in each mode; `fix-violations` warns that a fallback helper
  (`_mapping_value_or`) is `.get` under another name, and asks whether a type
  checker runs before acting on TYPE001.

### Changed (feedback from MetaList on 0.7.0, second round)
- `RESULT001`: a catalog entry can give the number of positional arguments the
  pure callee takes (`.replace/2-3`, JavaScript `.replace/2`); a call with
  another count is a different method of that name (`location.replace(url)`,
  `Path.replace(p)`, `store.replaceAll({...})`) and is not reported. A call in a
  `try` body with a handler is not reported (`host.encode("idna")` run to
  validate). `.join` left the Python defaults: on a name it was `Thread.join`
  in every case measured. On the 790-file corpus 25 findings became 5.
- `ASYNC001`: a `void` call is not reported when the project registers a global
  unhandled-rejection listener that reports (`window.addEventListener(
  "unhandledrejection", ...)`, `process.on("unhandledRejection", ...)`).
- `GUARD001`: not reported when the callee checks that argument itself among its
  leading statements (`if not isinstance(tags, str): raise TypeError(...)`).
- `STUB003` runs across files: a method of a class some project class extends is
  a hook default and is not reported; an override that repeats an always-yes
  base method is reported as redundant. Bases are resolved through imports.
- `ROLE001`: the default `support_files` cover `**/*fixture*` (singular),
  `**/*helper*`, `**/support/**` and `**/*_support.*`.
- The cache schema is "14".

### Changed (feedback from MetaList on 0.7.0)
- `ASYNC003` does not report a Python `gather(..., return_exceptions=True)` in a
  `finally` / `except` block of a function that cancelled tasks before it (the
  wait for cancellation to finish).
- `PROCESS001` does not report an exit status returned to the caller with the
  result (`return subprocess.run(...)`, or through a returned name).
- `INPUT002` counts a `node:assert` call given the value (`assert(...)`,
  `assert.ok`, `assert.equal`, through nested calls) as a check.
- `ASSERT001` reports an assert once, listing every external source that reaches
  it (it reported one finding per source).
- Dataflow: a method called on a computed receiver (`Path(p).read_text()`,
  `conn.cursor().execute(q)`) now matches `.name` catalog entries. The cache
  schema is "12".

### Added
- `MAGIC002` (`rules.magic_strings`, review, Python, JavaScript and TypeScript):
  a string literal written out at least 3 times in at least 2 files and compared
  (`==`, `in`, `===`, `case`) in at least 2 of them, reported once at its first
  use with the other places (decision 31). Messages of log calls and exceptions,
  docstrings, f-string and template parts, annotations, TypeScript literal types,
  import specifiers and UPPER_SNAKE_CASE definitions are never counted. New keys:
  `roles`, `min_length`, `min_occurrences`, `min_files`, `min_compared_files`,
  `kinds`, `message_callees`, `allowed`. No rule is left unimplemented:
  `coverage.rules_not_implemented` is `[]`, and the text report omits the line
  when the list is empty. The cache schema is "13".
- `DOM001` (`rules.dom`, warning, JavaScript and TypeScript): a delegated event
  handler that tests `event.target instanceof HTMLElement` before
  `event.target.closest(...)`, which silently drops clicks on SVG icons inside
  buttons (decision 27). The cache schema is "11".

## [0.7.0] - 2026-10-17

Milestones H4, H5, H-TS and H6 of specification section 21, ROLE001, the assert
rework, MAGIC003, and feedback rounds from MetaList. Every new rule ships at
`warning` or `review` (decision 9).

**Upgrading from 0.6.0.** Three changes can move a gate verdict:
- TypeScript (`.ts`, `.tsx`, `.mts`, `.cts`) is analyzed by default: a
  TypeScript repository gets its MAGIC001, EXC and DEF findings (errors) instead
  of unsupported-source warnings. Set `include` to the 0.6.0 globs to keep the
  old scope.
- `-1` is allowed by default (`allow_unary_negative_one = true`): fewer MAGIC001
  errors in `strict` and `minimal`.
- A very long Python expression is analyzed instead of crashing (or, on CPython
  3.11, is a parse failure with its reason).

Otherwise: ASSERT001 reports only asserts on external input (fewer warnings);
the CLI refuses to run under `python -O`; existing configurations stay valid;
caches are invalidated automatically (cache schema "10").

### Added (MAGIC003, decision 30)
- `MAGIC003` (`rules.sentinels`, review): a `-1` standing for a value (assigned,
  returned, passed, a dict / object entry), where it often encodes a meaning of
  the program's own (`selected_index = -1`, `sys.exit(-1)`). Subscripts, slices,
  arithmetic, comparisons, UPPER_SNAKE targets and arguments of index callees
  (`range`, `.split`, `.slice`, `.at` ...) are never reported. `values` can add
  `0` or `1`.

### Changed (MAGIC001, feedback from MetaList)
- **`-1` is allowed by default** (`rules.magic_numbers.allow_unary_negative_one =
  true` in every profile; it was true only in `recommended`): Python's last-item
  and all-but-last idioms (`items[-1]`, `text[:-1]`) and JavaScript's
  `indexOf(...) === -1`. On MetaList's code, all 262 findings for it were such
  idioms. A strict project that reported `-1` gets fewer findings; `false` keeps
  the old behavior and is no longer a deviation, while turning it on in a project
  that had it off is a loosening `VERIFY003` reports.

Milestone H6, part two (decision 29): cross-site consistency. Both rules are
review findings (decision 9), so no gate verdict changes.

### Added (H6 part two)
- `PROV001` (`rules.consistency`): a parameter filled with a made-up identifier
  (`uuid4()`, `crypto.randomUUID()`) at one call site while other sites pass an
  identifier the program issued (`store.start_run()`, `createSession()`),
  followed through attributes, `str(...)` and helper functions.
- `GUARD001` (`rules.consistency`): a call made without the check of its
  argument that at least 75 percent of the function's call sites (and at least 3)
  make first (`if has(x): remove(x)`, `if (!has(x)) return;`, `assert has(x)`).
- Dataflow facts record each call's first argument and the guards in effect.
- The cache schema is "9".

### Changed (asserts, decision 28)
- **ASSERT001 version 2 reports only an assert that checks external input**: one
  whose test depends, followed like INPUT001 (across functions too), on request
  data, a configuration read, or `rules.assertions.external_reads` (`sys.argv`,
  `input`, `open`, `json.load`, `requests.get`, ...). Internal invariants are
  never reported; version 1 reported every production assert, which pushed
  agents to delete them. Fewer findings than 0.6.0 wherever asserts state
  invariants.
- New `ASSERT002` (review): production code relies on asserts and no analyzed
  code reads `sys.flags.optimize`; one finding per run asking for a startup
  check. New keys `rules.assertions.assert002_severity` and `external_reads`.
- The CLI refuses to run under `python -O` / `PYTHONOPTIMIZE` (exit 2):
  ShockHarness checks its own invariants with assert.
- The skills encourage asserting internal invariants (write-compliant-code
  principle 9) and say never to delete an assert to satisfy a finding.
- Dataflow: an imported name is now a read wherever the import is (a
  function-level `from flask import request` was a local).

### Changed (feedback)
- STUB001: a JavaScript error message is a TODO placeholder only when it opens
  with `TODO` in capitals or `todo` followed by `:` or `(`; `"Todo toggle
  missing"` (a name) no longer is. `rules.stubs.markers` match only a comment
  line that opens with the marker, not the word inside a sentence.
- IMPORT001 does not apply to scripts run directly: a file whose first line is a
  shebang, or one the new `rules.import_effects.script_files` (`scripts/**`,
  `bin/**`; adding a glob is a deviation) matches that no analyzed file imports.
  The exemption is listed in `files[].rules_disabled` (origin `script`).

### Fixed
- A Python file with a very long expression (about 1000 terms or more, such as a
  long string concatenation) crashed the analysis with an internal error (exit
  3): the H3 stub collector recursed once per tree level. It now walks with an
  explicit stack. On CPython 3.11, where `ast.parse` itself cannot build such a
  tree inside the tool, the file is a parse failure with the reason, governed by
  `parse_errors` like any unparseable file. 0.6.0 is affected.

Milestone H6, part one (specification section 21, decision 26): external input.
Both rules are advisory (decision 9), so no gate verdict changes.

### Added (H6)
- Dataflow facts: each function's value dependencies (`ModuleFacts.dataflow`),
  for Python, JavaScript and TypeScript.
- `INPUT001` (`rules.input`, warning): request data (Flask, Django/Starlette,
  Express/Koa, Lambda events) that reaches a shell, `eval`, deserialization, a
  file path, a query, a redirect or an outbound URL without a validator,
  followed through assignments, string building and calls, and across project
  functions through the call graph (`max_depth`, 3 crossings). The message names
  the source, its location and the functions crossed.
- `INPUT002` (`rules.input.input002_severity`, review): `os.getenv("X")`,
  `os.environ.get("X")` or `process.env.X` passed on, returned or stored without
  any check in the function.
- A sink entry that is not `"callee:N"` is a configuration error.

### Changed (H6)
- The cache schema is "8".

Milestone H-TS of specification section 21 (decision 25): TypeScript.

### Added (H-TS)
- TypeScript is a third language: `.ts`, `.mts`, `.cts` and `.tsx` are parsed
  with `tree-sitter-typescript` (a new runtime dependency, pinned
  `>=0.23.2,<0.24`, approved in decision 8) and analyzed by every JavaScript
  rule: magic numbers (literal types are reported as annotations), exceptions,
  defaults (typed and `constructor(private x = v)` parameters), complexity and
  the call graph, H2-H5 and ROLE001. `report.files[].language` and
  `coverage.languages` gain `"typescript"` (an additive enum value in
  `report-v1.schema.json`).
- `TYPE001` for TypeScript: `any`, type assertions (`x as T`, `<T>x`; not
  `as const`), non-null assertions (`x!`, new `rules.types.report_non_null`,
  switching it off is a deviation) and `@ts-ignore` / `@ts-expect-error` /
  `@ts-nocheck` (under `report_type_ignore`).
- Type-only imports and exports (`import type`, `{ type X }`, `export type ...
  from`) are erased: no import fact and no module edge, so a type-only cycle is
  not a cycle and ROLE001 ignores type-only imports of test files.
  `import x = require("m")` is a module import. A `./m.js` specifier resolves to
  `m.ts` / `m.tsx` (`.mjs` to `.mts`, `.cjs` to `.cts`) when no `m.js` is
  analyzed.

### Changed (H-TS)
- **The default `include` adds `**/*.ts`, `**/*.tsx`, `**/*.mts` and
  `**/*.cts`, and the default `exclude` adds `**/*.d.ts`.** A TypeScript
  repository on the defaults is now analyzed instead of listing its files as
  unsupported sources, so its gate verdict can change (MAGIC001, EXC001-EXC003
  and DEF001-DEF006 are errors). To keep the previous scope, set `include` to
  `["**/*.py", "**/*.js", "**/*.mjs", "**/*.cjs"]`. Python and JavaScript
  verdicts are unchanged.
- The default test role adds `**/*.test.ts`, `**/*.spec.ts`, `**/*.test.tsx`,
  `**/*.spec.tsx`, `**/*.test.mts`, `**/*.spec.mts`; the default config role
  (and the legacy `configuration_files`) adds `*.config.ts`, `*.config.mts`,
  `*.config.cts`.
- A JavaScript exception boundary also covers TypeScript files; a TypeScript
  boundary (`language = "typescript"`) covers TypeScript only.
- The cache schema is "7".

### Fixed (H-TS)
- JavaScript: a function's parenthesized parameters are now its locals (they
  were not, so mutating a parameter that shadows a module binding counted as a
  write to that binding).
### Added (ROLE001, spec 21.1 decision 24)
- `ROLE001` (`rules.role_integrity`, category `policy_integrity`): a
  production-role file that imports a test-role file through the module graph
  (warning, exact: shipped code shielded from the production rules), and a
  test-role file with no test case that matches none of `support_files`
  (`empty_test_severity`, review by default).
- `VERIFY003` also reports, in a revision diff, a file the base classified as
  production that the head classifies as test (a new `file_roles` glob, or a
  move under one).

Milestone H5 of specification section 21: API-catalog rules. Seven new rules
ship at `warning` or `review` (decision 9), so no gate verdict changes; the
golden corpus has no H5 findings, and the 0.3.0 regression runs with them off.

### Added (H5)
- `PROCESS001` (`rules.processes`): a shell command built from data (f-string,
  template, `+`, `%`, `.format`) run through a shell; `subprocess.run` without
  `check=True`, `subprocess.call`, `os.system`, `child_process.spawnSync` whose
  exit status is thrown away or never read.
- `RESULT001` (`rules.results`, production and test): a must-use call used as a
  statement (`sorted(xs)`, `name.strip()`, `items.map(f)`); method entries are
  approximate.
- `TYPE001` (`rules.types`, review, Python): `Any` in annotations, `cast(...)`,
  `# type: ignore`, each switchable.
- `SLEEP001` (`rules.sleep`, review): fixed sleeps, marked as polling in loops.
- `RETRY001` (`rules.retry`): endless retry loops whose handler never gives up;
  unbounded `tenacity` / `retrying` / `backoff` decorators.
- `BATCH001` (`rules.batches`): loops whose per-item handler only passes,
  continues or logs.
- `STUB003` (`rules.stubs.stub003_severity`, review): a check named
  `is_*`/`can_*`/`validate*`/... that always returns `True`.

### Changed (H5)
- The cache schema is "6".
- This repository's own configuration sets `rules.types.report_any = false`
  (its configuration and report values are dynamic TOML/JSON data); casts and
  `type: ignore` stay reported.

Milestone H4 of specification section 21: async lifecycle. Three new rules ship
at `warning` (decision 9), so no gate verdict changes; the golden corpus has no
async findings, and the 0.3.0 regression runs with them off.

### Added
- `ASYNC001` (Python, JavaScript): a coroutine or Promise created and dropped:
  a call that is a whole statement, or a JavaScript `void` call, whose callee is
  a configured coroutine/Promise API (`asyncio.sleep`, `fetch`, `fs/promises`
  ...) resolved through the file's imports, or a project function declared
  `async`, resolved across files by the call graph (a probable edge is
  `unknown`).
- `ASYNC002` (Python): `create_task(...)` / `ensure_future(...)` with the task's
  handle dropped, unless a configured supervisor (`asyncio.TaskGroup`,
  `anyio.create_task_group`, `trio.open_nursery`) bound the receiver.
- `ASYNC003` (Python, JavaScript): `gather(..., return_exceptions=True)` and
  `Promise.allSettled` whose results are thrown away or never checked for
  failure in the enclosing function.
- `[tool.shockharness.rules.async_lifecycle]`: `enabled`, `severity`, `roles`
  (production and test), `fail_on_unknown`, `python_coroutine_apis`,
  `javascript_promise_apis`, `supervisors`; every loosening is a policy
  deviation.
- A sixth bundled skill, `async-lifecycle`.

### Changed
- The cache schema is "5" (async facts are cached).
- With ASYNC001 active, units are measured and the call graph is built even
  when `complexity.enabled = false` (neither is reported then).

### Schema
- Report shapes are unchanged (`schema_version` "1"): the new rule IDs appear in
  `coverage.rules_implemented`, findings and SARIF rules, in category
  `contract_integrity`; `gate.unknown_gating_families` can name
  `async_lifecycle`.

## [0.6.0] - 2026-10-16

Milestone H3 of specification section 21: syntax-level guardrails. Seven new
rules ship at `warning` (`BOOL001` at `review`) until their precision is measured
(decision 9), so no gate verdict changes: with the new rules switched off, the
golden corpus keeps its 0.3.0 verdicts under every profile, and with them on no
gate status, exit code or hard-violation count changes (both pinned in
`tests/unit/test_profile_regression.py`).

### Added
- `EXC004` (`rules.exceptions`, every role): `return`, `break` or `continue` that
  leaves a `finally` block, discarding the exception in flight. Python and
  JavaScript, including labeled jumps.
- `STUB001` (`rules.stubs`): `raise NotImplementedError`, `raise NotImplemented`,
  a function whose body is only `pass`/`...`/a docstring, `throw new
  XError("not implemented")`; abstract API (`@abstractmethod`, `@overload`,
  `ABC`/`Protocol`/`ABCMeta` classes) exempt; optional comment `markers`.
- `STUB002` (`rules.stubs`): production imports of mocking or fake-data libraries
  (`mock_modules`) or of modules under test path segments (`test_path_segments`).
- `ASSERT001` (`rules.assertions`, Python): `assert` in production code;
  type-narrowing asserts allowed by default (`allow_type_narrowing`).
- `BOOL001` (`rules.boolean_arguments`, review): a Boolean literal passed
  positionally to a call with several arguments; `allowed_callees`.
- `STATE001` (`rules.module_state`): a module-level mutable binding written by a
  function, method or arrow; `[[allowed]]` entries with a reason.
- `IMPORT001` (`rules.import_effects`): configured side-effecting calls
  (processes, network, sockets, threads, deletion, `fetch`, `setInterval`)
  executed at import time, resolved through the file's own imports.
- `write-compliant-code` principle 8, "prefer immutable values": frozen
  records, tuples and frozensets, `Object.freeze`, new values preferred over
  mutated inputs (discouraged, not forbidden; local variables may be mutated
  freely); STATE001's remediation
  and `fix-violations` point at it.
- Each new section has `enabled`, `severity` (`warning`/`error`/`review`, the
  findings' severity) and `roles` (default `["production"]`); every loosening
  of them is a policy deviation, reported by VERIFY003 and protected by
  `--policy`.

### Changed
- The tool's own code: six `assert`s that checked real invariants raise
  explicitly; `schema.Field` is an `ABC` with abstract methods; the codec's type
  hint cache uses `functools.cache` instead of a module-level dict.
- The content-hash cache schema is "4" (guardrail facts are cached); earlier
  caches are invalidated.

### Schema
- Report shapes are unchanged (`schema_version` "1"); the new rule IDs appear in
  `coverage.rules_implemented`, findings and SARIF rules, and the new categories
  map `STUB*`, `ASSERT001`, `IMPORT001` to `contract_integrity` and `BOOL001`,
  `STATE001` to `structural`.
- Configuration: the five `rules.*` tables above.

## [0.5.0] - 2026-10-16

Feedback round F4 (`docs/shockharness-suggestions-4.md`, from agents running
ShockHarness on a real project; spec 21.1 decisions 12, 13 and 18). Verdicts are
unchanged except where listed under Changed; `tests/unit/test_profile_regression.py`
pins each intended difference against the 0.3.0 snapshot.

### Added
- `shockharness exceptions PATH...`: one read-only list of every inline
  suppression (rules, reason, used or unused), every malformed one, every policy
  deviation and `exclude` pattern with the file and line (or profile, policy
  file or command line) it comes from, the `--policy` attempts, and with
  `--baseline` the baseline's entries per rule and per file. Text or JSON
  (`schemas/exceptions-v1.schema.json`, `report_kind = "exceptions"`); exit 0,
  or 2 on an invalid configuration; never gates.
- `DEF002` kind `discarded_removal`: `m.pop(k, None)` as a statement is a
  `review` finding in every profile whose message asks whether `del` is right.
- Skills: a "propose a rule" step in `fix-violations` and `pre-commit-review`;
  output validation (principle 7) in `write-compliant-code`; a worked
  "absence is a normal state" example in Python and JavaScript.
- Docs: Python 3.10 projects (run the gate as its own job on 3.11+), empty
  trees, and the checks a layered checker should keep until H3-H-TS land.

### Changed
- `DEF002` no longer reports a `.get(...)` call that is itself a decorator
  (`@router.get("/x")`); a `None`-fallback lookup assigned to a name whose next
  statement is an `if` without `else` that only raises when the name is `None`,
  falsy, not callable or not an instance; or `m.setdefault(k, <empty
  container>)` whose result is immediately mutated (the grouping idiom). In the
  golden corpus this removes one review finding (`def_mapping_get.py:47`).
- `DEF002` remediation names three cases: the key must exist (index it), absence
  is a normal state (explicit `if k in m:` or a named helper), or the value comes
  from outside (validate where it enters).
- The `recommended` profile sets `rules.defaults.fail_on_unknown = false`:
  `DEF*` findings the analyzer could not establish are reported and do not gate.
  `strict` is unchanged. A `fail_on_unknown = false` is now a policy deviation
  whenever `strict` says `true`, whether a profile or the repository sets it.

### Schema
- New `schemas/exceptions-v1.schema.json` for `shockharness exceptions --format json`.
- Check, diff and baseline report shapes are unchanged (`schema_version` "1").
  The new `discarded_removal` kind is a fact kind; findings show it only through
  their message.

## [0.4.0] - 2026-10-16

Milestone H2 part 2 of specification section 21: `VERIFY003` reports a change
that loosens the policy that judges it (configuration, files dropped from
analysis, baselines, workflows, other tools' settings); `--policy FILE` adds an
organization floor the repository cannot loosen; a fifth agent skill,
`verification-integrity`. A plain `check` without `--policy` keeps its 0.3.0
verdict.

Milestone H2 part 1 of specification section 21: verification integrity.
`VERIFY001`, `VERIFY002` and `VERIFY004` compare a head revision with its base
in `diff` and `gate --base/--head` and report what the change added to weaken
its own checks. They ship at `warning` (spec 21.1 decision 9) and change no
existing verdict: a plain `check` reports them as not applicable.

Milestone H1 of specification section 21: the `unknown` finding status with
per-family `fail_on_unknown`, and file roles. Every existing test, the golden
corpus under all three profiles and the self-gate keep their 0.3.0 verdicts
and exit codes (pinned by `tests/unit/test_profile_regression.py`).

### Added
- `VERIFY003` (looser policy), in `diff` and `gate --base/--head`: a new
  policy deviation, an ordered setting moved to its looser end (gate modes,
  `unsupported_sources`, `parse_errors`, VERIFY severity, fan-out severity), a
  raised complexity threshold, a narrower `include` or wider `exclude`; files
  the base analyzed that the head configuration no longer does; fingerprints
  added to a ShockHarness baseline; in a GitHub Actions job that runs
  ShockHarness, the job removed, `continue-on-error: true`, `if: false`,
  `--exit-zero`, `--profile minimal|recommended`, `--parse-errors warn` or an
  older version pin; codes added to ruff/flake8 ignore, per-file-ignores and
  exclude lists or removed from ruff `select`, deselecting pytest `addopts`,
  removed `testpaths`, coverage `omit`/`exclude_lines`, a lowered or removed
  `fail_under`, an ESLint rule turned down or removed (JSON `.eslintrc`). An
  unreadable or unparseable file makes its comparison `unknown`.
- `--policy FILE` on every command that loads configuration: a
  `[tool.shockharness]` file that must live outside the analysis root, layered
  between the profile and the repository's configuration. A repository key
  that would loosen a key the policy sets is dropped (the policy's value
  applies), noted, and reported as `VERIFY003`, in a plain `check` too.
- In a revision diff the VERIFY rules use the stricter of the run's and the
  base revision's `rules.verification` (strictest of base): a change cannot
  disable, lower or exempt the rules that report it.
- The reusable workflow `check.yml` takes `policy-repository`, `policy-ref`,
  `policy-path` and a `policy-token` secret, clones the policy into
  `$RUNNER_TEMP` and passes `--policy`.
- A fifth bundled skill, `verification-integrity`: fix the cause instead of
  skipping, suppressing or loosening, and what each VERIFY finding means.
- `VERIFY001` (added test skip, expected-failure or focus marker: pytest and
  unittest markers, `pytestmark`, `pytest.skip` / `self.skipTest` in a test
  body; `describe` / `it` / `test` with `.skip` / `.only`, `x*` and `f*`
  spellings), `VERIFY002` (added blanket suppression comment: `noqa`,
  `type: ignore`, `pylint: disable`, `pragma: no cover`, `mypy:
  ignore-errors`, `eslint-disable*`, `@ts-ignore` / `@ts-expect-error` /
  `@ts-nocheck`, `istanbul` / `c8` / `v8 ignore`, `shockharness: ignore`;
  narrow ones on request), `VERIFY004` (added tautological assertion, a test
  whose assertions all disappeared, a test whose body became empty). Only
  additions are reported; what existed at base is debt. Renames detected by
  git are followed. A file whose base version could not be analyzed, or whose
  rename status could not be established, yields `unknown` findings. Test-role
  files for VERIFY001/004; every role except generated and vendor for VERIFY002.
- `[tool.shockharness.rules.verification]`: `enabled`, `severity`
  (`"warning"` default in every profile, `"error"`, `"review"`),
  `fail_on_unknown` (default `false`), `allowed_skip_reasons`,
  `report_narrow_suppressions`. `severity = "review"` and each allowed skip
  reason are policy deviations; `severity = "error"` tightens and is not.
- Finding categories: `policy_integrity` (VERIFY), `contract_integrity`
  (MAGIC, EXC, DEF, SUPP), `structural` (CPLX). The text output of `diff` and
  `gate` lists policy-integrity findings first under their own heading and
  prints a `verification:` line; `check` lists the rules that need a base
  revision on their own line instead of under "rules applied".
- Every finding has a `status`: `violation` (the rule established the property
  and it does not hold) or `unknown` (the rule could not establish it).
  Severity is unchanged and orthogonal. Unknown today: `EXC001` on a catch
  whose only obstacles are exception types that do not resolve, on a promise
  rejection handler that references a function the module does not define, on
  a `with` whose capture-manager binding cannot be established and on a capture
  manager with no readable exception type; `DEF002` on `m.get(k, v)`,
  `m.setdefault(k, v)`, `m.pop(k, v)` and `m.get(k)` whose receiver is not
  proven a mapping. A bare `except`, an untyped JavaScript `catch` and an
  inline untyped rejection handler stay `violation`, as does a catch naming
  one resolved type that no boundary approves. The inventory is in
  `docs/rules.md` (Finding status) and kept as a test
  (`tests/unit/test_unknown_inventory.py`) that fails when a new place
  produces an unresolved state or a finding without a recorded decision.
- `fail_on_unknown` (boolean) per rule family, in the family's own table:
  `rules.exceptions` and `rules.defaults` default to `true` (both families
  have always failed closed on these findings), `rules.magic_numbers` and
  `complexity` to `false` (they produce no unknown findings). `true`: unknown
  findings gate by severity exactly as before. `false`: they are reported,
  counted in `gate.unknown`, add to no other count, never fail the gate, and a
  gate reason says how many were reported only. Setting a family to `false`
  where its profile says `true` is a policy deviation.
- File roles: every file gets exactly one of `generated`, `vendor`,
  `config`, `test`, `docs` (the first whose `[tool.shockharness.file_roles]`
  globs match, in that order) or `production`. Documented defaults: test =
  `tests/**`, `test/**`, `**/__tests__/**`, `**/test_*.py`, `**/*_test.py`,
  `**/*.test.js`, `**/*.spec.js`, `**/*.test.mjs`, `**/*.spec.mjs`,
  `**/conftest.py`; config = the 0.3.0 `configuration_files` list; generated =
  `**/generated/**`, `**/*_pb2.py`, `**/*.min.js`; vendor = `**/vendor/**`,
  `**/third_party/**`; docs = `docs/**`. Roles never change which files are
  discovered or analyzed.
- `[[tool.shockharness.overrides]]` accepts `roles = ["test"]` instead of
  `paths` (exactly one of the two per entry, validated), reported as a policy
  deviation (`... for file role(s) test: <reason>`) and with origin
  `overrides[i]` like a path override.
- The text report marks unknown findings (`EXC001 error (unknown): ...`) and
  prints an `unknown:` trailer line with the count and the families that gate
  on it.

### Changed
- The `verification:` line of `diff` and `gate` text output reads
  `RULES against base X: N source file(s) compared (...); M policy file(s) and
  K baseline(s) checked; severity S`, and `policy:` lines name the
  `--policy` file and each attempt before the policy deviations.
- `coverage.rules_not_implemented` is `["MAGIC002"]`.
- A `shockharness: ignore[...]` comment naming a VERIFY rule is a `SUPP001`
  error and suppresses nothing: a change cannot excuse its own weakening of
  the checks inline (spec 21.1 decision 5).
- The content-hash cache schema is "3" (verification facts are cached with the
  other per-file facts); caches written by earlier builds are invalidated.
- The MAGIC001 configuration-file exemption is expressed on the config role:
  `exclude_configuration_files = true` exempts files whose role is `config`
  (and a `generated`/`vendor` file a config glob also matches, which was exempt
  in 0.3.0). The `rules_disabled` reason now names the config role pattern;
  the origin is still `configuration_file`. `rules.magic_numbers.configuration_files`
  is the legacy spelling of `file_roles.config` (kept through 0.x): set alone
  it replaces the config role's globs as it replaced the exempt list before;
  set together with `file_roles.config` the lists are merged. A config note
  says which.
- The cache schema is `"2"` (entries carry finding status and file role); a
  0.3.0 cache directory is invalidated and rebuilt on the first run.
- This repository's own `tests/**` override is now `roles = ["test"]`, and its
  `file_roles.config` is empty (its one `conftest.py` is test code).

### Schema
All additive under report `schema_version` "1" (the new properties are
optional in `schemas/report-v1.schema.json`, so 0.3.0 reports still validate):
- H2 part 2: `config.policy` (`path`, `digest`, `keys`; `null` without
  `--policy`) and `config.policy_attempts` (`key`, `policy_value`,
  `attempted_value`, `reasons`) in reports and diff reports;
  `coverage.verification.policy` (`configuration`, `workflows_checked`,
  `workflows_note`, `files_compared`, `baselines`, `read_errors`) and
  `coverage.verification.policy_attempts` in diff reports; `VERIFY003` in
  `coverage.rules_implemented` and `rules_needing_base_revision`. The
  configuration origin `policy` in `config effective`.
- H2: `findings[].category` (`policy_integrity` | `contract_integrity` |
  `structural`), in reports, diff reports and SARIF `properties.category`;
  `coverage.rules_needing_base_revision`; `coverage.verification`
  (`status` `not_applicable` | `analyzed` | `disabled`, and in a diff the base
  commit, files compared, new, renamed and unanalyzable-base counts, rename
  detection state, severity and settings); `summary.by_category`; diff
  `summary.new_policy_integrity`; SARIF rule `properties.category` and
  `properties.needs_base_revision`.
- `findings[].status` (`violation` | `unknown`).
- `files[].role` and `files[].role_pattern` (the deciding glob, `null` for
  production).
- `coverage.roles`: files per role, every role listed.
- `summary.by_status` (both statuses listed) and `summary.by_role` (findings
  per role of their file, every role listed).
- `gate.unknown` and `gate.unknown_gating_families`.
- SARIF results: `properties.status`; `level` still comes from the severity.
- Diff reports (`schemas/diff-v1.schema.json`): `findings[].finding_status`
  (a diff finding's `status` keeps meaning new/fixed/unchanged), and
  `gate.unknown` / `gate.unknown_gating_families`.
- Configuration: `rules.verification` table (H2); `file_roles` table; `fail_on_unknown` in
  `rules.magic_numbers`, `rules.exceptions`, `rules.defaults` and
  `complexity`; `overrides[].roles`; `overrides[].paths` is no longer required
  (one of `paths`/`roles` is).

## [0.3.0] - 2026-10-15

The third feedback round, from `docs/shockharness-suggestions-3.md`
(the same 906-file codebase run with 0.2.0). All five items are below; the
content-hash cache (item 3, deferred from the first brief's item 6) is the
largest.

### Added
- The content-hash cache of per-file results. Parse facts, rule findings and
  per-unit complexity metrics are stored under `cache.directory` (default
  `.shockharness-cache/` under the analysis root; `cache.enabled` default
  true; `--no-cache` on `check`/`scan`/`gate PATH...` bypasses reading and
  writing for one run). The key is the tool version, the effective
  configuration digest, the host (interpreter and JavaScript grammar), the
  language and the SHA-256 of the file's bytes; any difference is a miss, a
  header difference invalidates everything. Cross-file work (call graph,
  cycles, suppressions, fingerprints, baseline matching, diffs, history) is
  always recomputed; `baseline create` and revision diffs never read the
  cache. Entries are JSON (never pickles), written atomically; a corrupt,
  unreadable or schema-mismatched index or entry is counted and described
  once under `coverage.cache` and ignored. `coverage.cache` (`status`,
  `directory`, `reason`, `hits`, `misses`, `invalidated`, `errors`,
  `problems`) is the one report block that differs between a cold and a warm
  run; the text output prints a `cache:` line. On this repository a warm run
  takes a fifth of a cold one. Library API: `AnalysisOptions` gains a
  required `cache` field (`CACHE_CONFIGURED` | `CACHE_BYPASSED`),
  `analyze_files` a `cache` argument and `build_report` the coverage block.
  The `cache` table is excluded from the configuration digest, so toggling or
  moving the cache keeps baselines valid. The directory is skipped by
  discovery like `.git`, listed in the repository's and both examples'
  `.gitignore`, and documented in `docs/configuration.md`, Cache.
- `EXC001`/`EXC002` resolve a capture manager bound to a name: `capture =
  CapturedExceptionContext(T); with capture:` (81 of the 82 captures in that
  codebase) and `s = suppress(T); with s:` are the same catch as the inline
  form, resolved to the most recent binding of the name in the same function
  or module body. The confidence is `exact` when nothing stands between the
  assignment and the `with`, `approximate` when the assignment sits in a
  branch or loop the `with` is not inside (or the name is also a parameter or
  a comprehension target), and `unresolved` (an untyped catch, never the older
  binding) when the name was rebound in between, is bound by `with ... as`, or
  is bound to a listed manager only in another scope. A name never bound to a
  listed manager is an ordinary `with`. IR: `ManagerFact` now carries a
  `ManagerCall` (inline form) or a `NameResolution` (bound form).
- `rules.magic_numbers.named_constant_definitions = "allow"` accepts literal
  arithmetic as the value of a module-level constant: `CHUNK_BYTES = 64 *
  1024`, `const MAX_MS = 30 * 60 * 1000;` (numeric literals, unary `+`/`-`,
  parentheses, `+ - * / // % **`; JavaScript the same set). Any name, call,
  attribute, subscript or non-numeric literal in the expression keeps every
  literal reported; `"report"` is unchanged. Specification section 5 and
  section 19 (decision 16) record it.
- `EXC002`'s message for a handler that consists only of a transparent guard
  call (`catch (error) { rethrowUnexpectedError(error); }`) ends with the
  three remedies: handle the expected error after the guard, log it and
  continue with a stated reason, or suppress the finding with a reason. No
  behaviour change.

### Schema
- Report schema 1 gains `coverage.cache` (required), the `cache` table joins
  the configuration schema, and `config_digest` no longer covers the `cache`
  table. No existing field changed.

### Changed
- Glob patterns: a leading `/` or `./` anchors the pattern to the analysis
  root. `/main.py` and `./main.py` match only the root-level `main.py`;
  `/src/*.py` matches `src/a.py` but not `src/sub/a.py` or `other/src/a.py`.
  Patterns without either prefix keep their semantics (no slash: basename
  anywhere; with a slash: whole relative path). This changes `./pattern` from
  "the same as `pattern`" to "root-anchored", and `config validate` now
  accepts a leading `/` (it was an error). `include`, `exclude`,
  `overrides[].paths`, `rules.magic_numbers.configuration_files` and boundary
  paths all honour the anchor.

## [0.2.0] - 2026-10-14

The feedback round after the first run of 0.1.0 on a 906-file codebase
(`docs/shockharness-suggestions.md`): precision, noise and adoption cost.
Items 1-5 and 7-9 of that document are implemented here; item 6 (a
content-hash cache) is deferred to a later release.

### Added
- `rules.magic_numbers.named_constant_definitions` (`"report"` | `"allow"`):
  a numeric literal that is the whole value of a module-level named constant
  definition (`MAX_PAGES = 8`, `_WAIT: Final = 10.0`, `const SETTLE_MS = 400;`,
  `export const N = -3;`) is marked by both adapters
  (`NumericLiteral.constant_definition`). `strict` keeps `"report"`, so the
  specification's reading (a named constant is not automatically justified)
  is unchanged there; `recommended` and `minimal` use `"allow"`. `"allow"` is
  a reported policy deviation. Containers, expressions, chained targets, class
  and function bodies and definitions nested in module-level blocks are
  reported either way. Specification sections 5 and 19 record the decision.
- `CPLX006` unit size: a warning when a unit's `size/1` logical line count is
  above `complexity.max_lines_warn` (default 50 in every profile); module
  bodies are exempt. Registered with full metadata, part of
  `rules_applied`/`rules_disabled`, revision diffs and the summary.
- `complexity.npath_only_without_cognitive` (default `true`): a unit above
  both `cognitive_warn` and `npath_warn` is one `CPLX002` finding whose
  message carries the NPath number; `false` restores the separate `CPLX004`.
  A unit above the NPath threshold alone is still `CPLX004`.
- `rules.exceptions.transparent_guards`: guard callees
  (`["rethrowUnexpectedError"]`) that re-raise anything unexpected. A handler
  whose first statement calls a listed guard with the caught exception as its
  only argument is narrowed by it: `EXC001` does not report the catch and
  `EXC002` classifies the statements after the guard (nothing after it still
  swallows; a literal return after it is `EXC002`'s, not `DEF005`'s). Each
  guard is a reported deviation. `CatchFact` gains `guard_call`, `guard_body`
  and `narrowed_from`.
- Python `isinstance` guards: `except Exception as exc:` whose first statement
  is `if not isinstance(exc, T): raise` (or a tuple) is checked by `EXC001` as
  a catch of `T`; the message says what it was narrowed from.
- Boundaries may list several classes for one path with one reason:
  `exceptions = ["OSError", "ProcessLookupError"]` alongside the single
  `exception = "..."` form; exactly one of the two per entry is validated, and
  the entry is one deviation line naming every class. `EXC003` is unchanged.
- `check --summary` (also on `scan` and `gate PATH...`): a first-contact
  overview (findings by rule and top-level directory and by severity, the ten
  files with the most policy findings, complexity counts, parse failures,
  elapsed time) followed by the unchanged totals and `gate:` line.
- `complexity.fan_out_severity` (`"warning"` | `"review"`): the severity of
  `CPLX005` fan-out findings; both are advisory, so neither is a deviation.

Second batch, from `docs/shockharness-suggestions-2.md` (coverage gaps found
against the project's own linter); items 1-4 are implemented, item 5 (a
plugin API) is a design note for later:

- `EXC001`/`EXC002` see exception capture through context managers:
  `with contextlib.suppress(T, ...):` (either import spelling) is a catch of
  `T` that swallows, and `rules.exceptions.capture_managers` lists a
  project's own managers by qualified name (`with M(T, ...):` is a catch of
  the exception types passed positionally; exact when the import resolves,
  approximate by bare name when it does not; no readable type is an untyped
  catch). Findings sit on the `with` line with the kind `context manager`,
  boundaries approve them like `except` handlers, an approved `suppress` is
  not an `EXC002` swallow, and every configured manager is a reported
  deviation. New IR fact `ManagerFact` (`ModuleFacts.managers`) and catch kind
  `context manager`.
- `DEF002` covers `next(iterator, default)` and
  `collections.defaultdict(factory)` through any import spelling (new kinds
  `next_default` and `defaultdict`); `d.pop(key, default)` and
  `d.setdefault(key, default)` were already covered and now have dedicated
  tests. `DEF001` covers pydantic model fields (a class whose base resolves to
  `pydantic.BaseModel`): `x: int = v`, `Field(default=v)`, `Field(v)`,
  `Field(default_factory=f)` under `dataclass_fields`, with `pydantic field`
  messages; `Field(...)`, `Field()` and `= ...` are required fields.
- Promise rejection handlers: a handler given as a reference to a function
  defined at the top level of the same module is classified by that
  function's body; other references stay unresolved; an expression-bodied
  arrow that only logs is `logging_only`; a bare `log(...)` call counts as
  logging in JavaScript. Swallowing, rethrowing (with `transparent_rethrow`),
  `.finally(fn)` and `async` `try`/`catch` already behaved as the brief asks
  and are pinned by tests.
- `unsupported_sources` (top level; `"fail"` | `"warn"` | `"ignore"`; `warn`
  in `strict` and `recommended`, `ignore` in `minimal`): what an included file
  no adapter can parse means. `fail` makes each one an analysis failure (file
  status `unsupported_source`, language `unsupported`, exit 3); `warn` lists
  them under `coverage.unsupported_sources` with a `warning:` line; `ignore`
  only counts them (a reported deviation). `coverage.discovery` gains
  `unsupported_sources`; `coverage` gains `unsupported_sources_policy` and
  `unsupported_sources` (additive, `schema_version` stays `"1"`).

### Changed
- `CPLX005` reports one finding per import cycle instead of one per member,
  anchored on the lexically first member at its import into the cycle (stable
  fingerprint when unrelated modules are added), naming the language and the
  size, listing up to eight members and noting that Python cycles fail at
  import time while ES-module cycles are usually resolved at call time.
  `metrics.graph.cycles` is unchanged. The text report lists import cycles as
  a group after the per-file findings, Python cycles first.
- `recommended` profile: `magic_numbers.allow_unary_negative_one = true`,
  `magic_numbers.named_constant_definitions = "allow"`,
  `complexity.fan_out_warn = 30`, `complexity.fan_out_severity = "review"`
  (plus the existing `DEF004` at review). `strict` is unchanged. `minimal`
  adds `named_constant_definitions = "allow"`.
- `DEF001`: new tests pin that annotated class attributes of undecorated and
  ORM-style classes are not dataclass fields and that `dataclasses.dataclass`
  (with or without arguments) is recognized; no behaviour change.
- The text report's complexity line reads `CPLX001-CPLX004 and CPLX006 are
  warnings`; documentation and skills name `CPLX001`-`CPLX006`.

### Schema
- `schema_version` stays `"1"`: every change is additive. The report gains a
  top-level `summary` object (`schemas/report-v1.schema.json` describes it:
  `files`, `files_analyzed`, `parse_failures`, `findings`, `suppressed`,
  `by_severity`, `by_rule`, `by_directory`, `by_rule_and_directory`,
  `policy_families`, `top_files_limit`, `top_files`, `complexity`); its
  totals equal `execution_summary`. Elapsed time is printed by the text
  summary only, never in JSON, so reports stay byte-identical across runs
  (the pre-release 0.2.0 build briefly put it in JSON, which made the
  determinism tests flaky on CI). `metrics.complexity.thresholds` gains
  `max_lines_warn`. `CPLX006` appears in `coverage.rules_implemented` and in
  every file's `rules_applied`/`rules_disabled`. Boundary entries in
  `config.values` may carry `exceptions` instead of `exception`. Second batch:
  `files[].status` may be `unsupported_source` and `files[].language`
  `unsupported` (only under `unsupported_sources = "fail"`); `coverage` gains
  `unsupported_sources_policy` and `unsupported_sources`;
  `coverage.discovery` gains `unsupported_sources`.

## [0.1.0] - 2026-10-14

First stable release. Every milestone of the specification (A through G) is
implemented: the three default-on hard policies (`MAGIC001`, `EXC001`-`EXC003`,
`DEF001`-`DEF006`), inline suppressions, baselines, revision diff and gate,
SARIF, git history metrics, advisory complexity metrics and call graph
(`CPLX001`-`CPLX005`), three profiles, the `check` command, `--exit-zero`,
tag-triggered publishing, a reusable GitHub Actions workflow, consumer
examples, four agent skills with `skills install`/`update`, and the eval
corpus. From this release the CLI surface, exit codes, rule IDs and report
`schema_version` 1 are stable; changes to them are documented here first.

### Fixed
- Skills: `SKILL.md` content is normalized to LF when read from the package, so
  frontmatter checks, installs and manifest hashes are identical on checkouts
  that use CRLF (Windows runners with `core.autocrlf`). A `.gitattributes` now
  pins LF on checkout for every text file in the repository.
- History metrics: commit dates are now normalized to one ISO 8601 spelling
  (`+00:00`) regardless of the host's git version. Git 2.45+ prints UTC as `Z`,
  which made `metrics.history` differ between machines and broke two tests on
  CI runners with newer git than the development machine.
- Dependabot no longer proposes minor or major `tree-sitter` bumps; the 0.25
  pin is deliberate (0.26.0 segfaults on CPython 3.14).

### Added
- Milestone E: complexity metrics, call graph, hotspots. `CPLX001`-`CPLX005`
  are implemented as advisory warnings that never fail a plain `check`. Every
  module body, class body, function, method, lambda and arrow is a *unit*
  measured on its own (nested units are excluded from their parent) with
  versioned conventions stated in every message and in
  `metrics.complexity.conventions`: `cyclomatic/1` (boolean operators counted
  under `complexity.cyclomatic_counts_boolean_operators`, optional chaining
  never), `cognitive/1` (published-style nesting and interruption increments,
  explicitly not a SonarSource score, Python/JavaScript parity enforced by a
  table and a Hypothesis property), `nesting/1`, `npath/1` (bounded by
  `complexity.npath_cap`, reported as `>= cap` when saturated, never
  enumerated) and `size/1`. New keys `npath_cap`, `npath_warn`, `fan_out_warn`,
  `cyclomatic_counts_boolean_operators`, `abstraction_displacement`;
  `cyclomatic_counts_boolean_operators = false` is a reported deviation.
  `docs/complexity.md` defines everything.
- `metrics.graph`: a call graph whose edges are `resolved` (direct call of a
  module-level, nested or imported definition), `probable` (module alias
  attribute, `self`/`this` method the class defines, static class call,
  function passed as an argument) or `unresolved` (computed callee, unknown
  receiver, unbound name, undefined `self` attribute); counts per confidence,
  fan-in/fan-out per unit (builtins excluded, unresolved never counted),
  module import edges for Python (absolute and relative, canonical
  package-rooted names, never suffix matching) and JavaScript (`import`,
  `export ... from`, `export *`, `require`), strongly connected components
  as `cycles`, and `shared_mutable_state` notes. `CPLX005` fires per cycle
  member and on fan-out above `fan_out_warn`.
- `metrics.history.hotspots`: `log1p(churn) * normalized_complexity` per file
  (summed cognitive complexity over the repository maximum), with
  `hotspots_formula`; `null` with a reason when history or complexity is
  unavailable.
- Revision diffs list `metrics.complexity.regressions` (head units above a
  threshold whose value grew since base) and honour
  `gates.complexity_regressions` (`warn` default, `fail`, `ignore`);
  `gate.complexity_regressions` and `summary.complexity_regressions` are new
  fields. `complexity.abstraction_displacement = true` adds the experimental
  `metrics.graph.abstraction_displacement` (every entry approximate).
- The analysis pipeline now has a cross-file phase between the per-file rules
  and suppressions, so graph findings are suppressible and fingerprinted;
  `build_report` takes the metrics, `collect_history` takes the complexity
  section, `gate.evaluate` takes the regression count. Report and diff schemas
  gain the new sections (additive); SARIF carries CPLX results.
- The `refactor-complexity` skill now quotes the real rules, thresholds,
  report fields and commands.
- Milestone G: four vendor-neutral agent skills shipped as package data
  (`shockharness/skills/<name>/SKILL.md`, open Agent Skills format with
  `name`/`description` frontmatter): `write-compliant-code`,
  `fix-violations`, `refactor-complexity`, `pre-commit-review`. Each has
  compliant and non-compliant Python and JavaScript examples, exact CLI
  invocations, a corrective workflow, a checklist, and an "Adopting
  ShockHarness" section identical to the README's (enforced by a test).
  `refactor-complexity` states that `CPLX001`-`CPLX005` are not implemented.
- `shockharness skills list|show|install|update`. `install --agent
  claude|codex|generic [--project PATH] [--user] [--force]` writes the skills
  (claude: `.claude/skills`, codex: `.agents/skills`, generic: `--project DIR`
  itself plus a printed `AGENTS.md` pointer line) and a manifest
  `.shockharness-skills.json` (schema version 1: agent, package version,
  SHA-256 per file); it refuses to overwrite without `--force` (exit 2) and
  touches nothing outside the destination. `update` rewrites files whose hash
  still equals the manifest, restores missing ones, adds new skills, reports
  removed ones, leaves edited files alone and reports each as a conflict with
  the remediation (exit 1 while a conflict remains); `update --check` writes
  nothing and exits 1 on any drift. Three new declared exception boundaries in
  `skills/install.py` (`OSError`, `UnicodeDecodeError`,
  `json.JSONDecodeError`).
- Skill evaluation corpus under `evals/`: eight paired tasks (four Python,
  four JavaScript) with prompt, starting files, behavioral tests, expected
  outcome and a clean reference solution; `evals/run_evals.py` (standard
  library only, one declared `MAGIC001` override) scores candidate directories
  by unsuppressed findings per rule, test exit code and suppressions added,
  and writes a JSON scorecard. CI scores the reference solutions and
  round-trips `skills install` / `update --check` for all three agents on
  ubuntu. The sdist carries `evals/`.
- README "Adopting ShockHarness": a self-contained guide for an agent reading
  the README over HTTP (pinned `uv tool install` / `uvx` / `pip` forms,
  `init`, the four onboarding paths, direct and reusable CI steps with the
  Dependabot snippet, `skills install`, and a verification table), with
  absolute links only. `docs/skills.md` is new; `docs/integration.md` gains a
  skills section.
- `--exit-zero` on `check` (and the `scan` alias) and `gate`: an advisory
  run. The report, severities, gate verdict text and every count are
  unchanged; only the process exit code is 0 where the verdict would have
  returned 1. Exit 2 (configuration, usage) and exit 3 (tool failure, strict
  parse failure) are never masked. The run is visible as `gate.advisory`
  (JSON and diff reports, both schemas, additive), a `shockharness: advisory
  run (--exit-zero): gate verdict FAIL reported as exit 0` line in text, and
  the `advisory` SARIF run property; the SARIF invocation `exitCode` is the
  process exit code while `properties.gate.exit_code` keeps the verdict's.
  Deliberately a CLI-only flag, not a configuration key: the configuration
  form is `gates.new_hard_violations = "warn"`. `docs/configuration.md` gains
  "Adopting ShockHarness on an existing codebase" comparing the four onboarding
  paths (baseline, `gates.new_hard_violations = "warn"`, `profile =
  "minimal"`, `--exit-zero`).
- Milestone F (distribution half). `shockharness check` is the canonical
  analysis command (identical arguments and behaviour to `scan`, which stays as
  a hidden alias); `shockharness version` prints the same string as
  `--version`.
- Built-in profiles shipped as package data (`shockharness/profiles/*.toml`),
  selected with `profile = "strict" | "recommended" | "minimal"`: `strict` is
  the bundled defaults; `recommended` reports `DEF003`/`DEF004` at review;
  `minimal` caps `MAGIC001`, `EXC001`-`EXC003` and `DEF001`-`DEF006` at
  review, sets `parse_errors = "warn"` and disables complexity. Precedence:
  bundled defaults < profile < repository configuration < command-line
  overrides. Every profile below `strict` is a policy deviation in every
  report and in `config validate`; `config effective` records profile keys
  with origin `profile:<name>`.
- `rules.magic_numbers.severity`, `rules.exceptions.severity`,
  `rules.defaults.severity` (`"error"` | `"review"`): a per-section cap that
  turns error findings into review findings; each cap is a reported deviation.
- The only two command-line overrides, on every configuration-loading command:
  `--profile NAME` (replaces the profile layer; the repository's other keys
  still apply) and `--parse-errors fail|warn`. Both are recorded with origin
  `cli_override`, noted in the report, and part of the configuration digest.
- `shockharness.toml` is accepted alongside `.shockharness.toml` at the
  dedicated tier; both present in one root is a configuration error naming
  both files.
- `init --profile recommended|minimal` writes a short file selecting the profile.
- Release automation: `.github/workflows/publish.yml` (tag `v*` -> full CI
  workflow -> build wheel and sdist -> tag equals `version.py` -> PyPI trusted
  publishing with `id-token: write`, environment `pypi`, no stored token);
  `docs/releasing.md` with the one-time PyPI steps and the per-release steps.
- Reusable consumer workflow `.github/workflows/check.yml` (`workflow_call`;
  inputs `shockharness-version` (required), `config`, `base`,
  `python-version`; SARIF upload to code scanning; permissions
  `contents: read`, `security-events: write` only); `.github/dependabot.yml`
  for this repository; `docs/integration.md` (pinning to a tag and to a SHA,
  Dependabot snippet, where the pin may live).
- Consumer examples `examples/python` (dev dependency pinned to `0.1.0a1`)
  and `examples/js` (analyzer in an isolated tool environment, never an npm
  dependency), each with a policy file, a workflow and one deliberate
  suppressed finding; `scripts/consumer_upgrade_check.py` (stdlib only)
  copies each into a throwaway git repository, installs the wheel built from
  the checkout, and asserts `check` exits 0, then 1 after one injected
  violation, and `gate --base HEAD~1 --head HEAD` exits 1; run by CI on ubuntu.
- `effective_profile` is also in SARIF run properties, next to
  `config_deviations`.
- Milestone F (analysis half): stable finding fingerprints (`findings[].fingerprint`;
  rule ID, path, enclosing scope, whitespace-free evidence, occurrence index)
  that survive line moves and reformatting; `shockharness baseline create PATH...
  --output FILE` writing a reviewed, byte-stable baseline
  (`schemas/baseline-v1.schema.json`) that is never updated automatically;
  `--baseline FILE` on `scan` and `gate` with `gates.legacy` semantics
  (`baseline`: matched findings listed and counted but not gating; `ignore`:
  listed, not counted; `fail`: baseline recorded but not applied); stale
  baseline entries reported under `gate.baseline.stale`; `evaluate_gate` and
  `apply_baseline` in the library API.
- `shockharness diff --base REF --head REF` (reporting only) and
  `shockharness gate --base REF --head REF` (exit 1 only on new hard
  violations): both revisions resolved and exported with local git only, full
  trees analyzed, findings classified new / fixed / unchanged by fingerprint,
  provenance (both commits, config digest, tool version) in the report
  (`schemas/diff-v1.schema.json`).
- SARIF 2.1.0 output (`--format sarif`) for `scan`, `diff`, and `gate`: one
  run, every registered rule with full descriptions, results with level mapping
  (error, warning, review/note -> note), root-relative URIs, exclusive end
  columns, `partialFingerprints` carrying the baseline fingerprint, in-source
  suppressions, and `baselineState` when a baseline or base revision applies.
- `metrics.history` in every CLI report: per-file commit count, author count,
  first and last change, and co-change pairs with support and directional
  confidence, read from local `git log` over `history.horizon_days` anchored
  on the head commit date; `history.enabled`, `history.horizon_days`,
  `history.min_support` configuration keys; explicit `unavailable`,
  `disabled`, and `not_collected` statuses with reasons; `hotspots` is `null`
  with a reason until Milestone E provides complexity.
- Six declared exception boundaries: reading a baseline file (`OSError`,
  `UnicodeDecodeError`, `json.JSONDecodeError`) and the git subprocess
  (`subprocess.CalledProcessError`, `OSError`, `UnicodeDecodeError`).

### Changed
- **`policy_profile` is renamed to `effective_profile`** in the JSON report,
  the diff report, both JSON schemas and SARIF run properties (specification
  section 20, decision 13). `schema_version` stays `"1"`: no tagged release
  has shipped the old field (0.1.0a1 was published only to claim the name and
  predates the schema's first tagged release), so the rename is made before
  schema v1 is published rather than versioned around.
- The text report's `config:` line names the effective profile; `config
  validate` prints it.
- CI, the pre-commit hook, the README and the docs invoke `shockharness
  check`; the self-gate and Ruff also cover `scripts/`.
- Report schema (still `schema_version` 1, additive): `findings[].fingerprint`,
  `findings[].baseline`, `gate.baselined`, `gate.new_hard_violations`,
  `gate.baseline`, `execution_summary.baselined`, `metrics.history`. The gate
  verdict is driven by `new_hard_violations`; without a baseline it equals
  `hard_violations` as before.
- `--format sarif` no longer exits 2; `evaluate_gate` no longer raises
  `UnsupportedFeatureError` for a baseline (it rejects anything that is not a
  `Baseline` with a `UsageError`).

## [0.1.0a1] - 2026-10-14

First public alpha, published to PyPI to claim the `shockharness` name.
Contains Milestones A through D: MAGIC001, EXC001-EXC003, DEF001-DEF006,
SUPP001/SUPP002, configuration validation, text and JSON reports, and the
`scan`, `config`, `rules`, and `init` commands. No baselines, diff, SARIF,
complexity metrics, or skills yet; see `coverage.rules_not_implemented` in
every report.

Everything listed under "Added" below shipped in this version.

### Added
- Milestone A: package skeleton, MIT license, configuration schema with full
  shape and semantic validation, precedence (`--config` > `.shockharness.toml` >
  `pyproject.toml` > bundled defaults), rule registry with every specified rule
  ID, diagnostic and report models, `scan`, `config validate`, `config effective`,
  `rules list`, `rules explain`, `init`, exit-code contract, GitHub Actions matrix.
- Milestone B: Python (`ast`) and JavaScript (tree-sitter) adapters with
  byte-to-character column mapping, explicit parse-failure propagation,
  `MAGIC001` (value-based 0/1, folded unary sign, annotations flagged),
  `SUPP001`/`SUPP002` inline suppression checks, per-path overrides,
  configuration-file exemption, JSON report (`schema_version` 1) and text output.
- Milestone C: catch facts in the IR (exception identities with
  exact/approximate/unresolved confidence, handler body classification,
  try-body operation attribution) for Python `except`/`except*` and JavaScript
  `catch`, `.catch(handler)`, `.then(ok, handler)`; `EXC001` forbidden catch
  (boundary whitelist, fail-closed on bare/unresolved identities, JavaScript
  instanceof-guard convention), `EXC002` suppressed or converted exception,
  `EXC003` broad try scope; `rules.exceptions.transparent_rethrow` (default
  false); boundary `exception` names validated as dotted class names; every
  boundary and `transparent_rethrow` reported under `config.deviations`.
- Milestone D: default facts in the IR (`DefaultFact`: family, kind, subject,
  fallback, constant-shapedness, syntactic context, confidence) extracted by
  `ir/python_defaults.py` and `ir/javascript_defaults.py`; `DEF001` parameter
  and dataclass-field defaults, `DEF002` mapping/attribute/property fallbacks
  (plus the implicit `None` of `.get(key)` as a review finding), `DEF003`
  truthiness fallbacks (review by default; Boolean logic excluded), `DEF004`
  nullish fallbacks, `DEF005` exception-to-default (literal returns and
  one-step static traces to module constants and one-return helpers), `DEF006`
  configuration fallbacks (`os.getenv`/`os.environ`/`process.env` in every
  spelling); new `rules.defaults` keys `dataclass_fields`, `nullish_fallbacks`,
  `configuration_fallbacks` (all `forbid`); loosened modes reported under
  `config.deviations`; 13 golden fixtures and 25 unit tests; `safe_autofix` is
  false for every finding.

### Changed
- `EXC002` no longer reports the `return_fallback` classification while `DEF005`
  is active: the handler is reported once, as `DEF005`, with the EXC002
  classification named in the message. Disabling `DEF005` restores the EXC002
  finding. Golden expectations for the eleven affected handlers changed rule ID
  only.
- The tool's own code was brought under `DEF002`/`DEF004`: three `setdefault`
  accumulators became explicit membership checks, the report's
  `discovery`/`explicit_targets_excluded` fields are built with an explicit
  branch, and nineteen `x if x is not None else v` expressions on parser fields
  became either explicit branches (genuinely optional values: import aliases,
  `from . import`, source segments) or assertions of grammar invariants (fields
  tree-sitter and `ast` always populate). A Python `SyntaxError` position is now
  recorded only when the interpreter reports both a line and a column; before,
  a missing column was silently replaced by column 1.
- The arities that distinguish `getattr(o, a, v)` and `m.get(k, v)` from plain
  lookups are named in `constants.py`.
- The tool's own boundaries were narrowed to satisfy `EXC003`: config decoding
  and TOML parsing are two `try` blocks, analyzed-file decoding is bound before
  the result is returned, and comment tokenization materializes the token list
  in the one protected call. Behaviour is unchanged.

### Dependencies
- `tree-sitter` 0.25.x (MIT) and `tree-sitter-javascript` 0.25.x (MIT). Pinned
  as a tested pair; language ABI 15. `tree-sitter` 0.26.0 is excluded: with
  CPython 3.14 it segfaults when walking trees nested deeper than about 200
  levels (CPython 3.13 with 0.26.0 and CPython 3.14 with 0.25.2 are both fine).
  The 300-deep nesting test in `tests/unit/test_javascript_adapter.py` guards this.
