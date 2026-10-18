# Limitations

Stated so that a clean report is never read as more than it is.

## Coverage

* Only the error-severity rules (`MAGIC001`, `EXC001`-`EXC003`, `DEF001`-`DEF006`
  outside their review shapes, `SUPP001`) fail a gate under the defaults. A passing
  gate means "no magic numbers, no unapproved or suppressing catches, no
  over-wide approved try blocks, no recognized default or fallback shapes, and no
  bad suppressions", nothing more: the complexity family and every guardrail
  rule are advisory (warning or review) and a passing gate says nothing about
  them.
* Python syntax coverage is exactly the host interpreter's `ast`. Running on
  3.11 cannot parse 3.12-only syntax; such files are parse failures, not clean.
  The same holds for a tree the host's parser cannot build: on CPython 3.11 an
  expression a few thousand terms long raises `RecursionError` inside `ast.parse`
  and the file is a parse failure (`RecursionError: nested too deeply ...`);
  3.12 and later parse it. The report records `coverage.host_python`.
* JavaScript coverage is the pinned `tree-sitter-javascript` grammar (ESM,
  CommonJS, JSX). TypeScript coverage (H-TS) is the pinned
  `tree-sitter-typescript` grammar (`.ts`, `.mts`, `.cts`; `.tsx` with its TSX
  grammar), read by the JavaScript extractors; see TypeScript below. A file
  that an `include` pattern matches but no adapter parses (`.vue`, `.svelte`,
  `.pyx`) is an *unsupported source*: `unsupported_sources` (`warn` in `strict`
  and `recommended`: listed under `coverage.unsupported_sources` with a warning
  line; `fail`: an analysis failure and exit 3; `ignore` in `minimal`) is how a
  project notices that a file left the policy. An `include` pattern that names
  an unsupported extension literally (`**/*.vue`) is still a configuration
  error.
* Only UTF-8 (with or without BOM) sources are read. Other encodings are a
  `decode_error` file status. Python's PEP 263 coding declarations are not honored.
* File roles (H1) are labels from path globs, not from file contents: a test
  helper outside the test globs is `production`, a generated file outside the
  generated globs is analyzed as written by hand. Roles never exclude a file from
  analysis; `exclude` does that.
* The `unknown` status (H1) covers what the inventory in `docs/rules.md` lists
  and nothing more. Some shapes whose verdict also rests on missing information
  are not yet unknown findings: a capture manager with one readable exception
  type and further unreadable positional arguments (`suppress(OSError, *more)`)
  is judged by the readable type alone, and a unit whose unresolved calls could
  push it over `fan_out_warn` gets no CPLX005 finding (the resolved count is
  below the threshold). Turning these into findings would add findings, so it is
  left to a later milestone.

## MAGIC001

* Strings and regular-expression literals are not inspected. `"30"`, `'42'`,
  `/\d{3}/` and `` `value 7` `` are not findings.
* Numbers produced at runtime (`int("30")`, `Number("5")`) are not detected.
* `NaN`, `Infinity`, `math.pi`, `Math.PI` are identifiers, not literals.
* The rule flags literals; it does not judge whether a named constant is
  justified. `ITERATIONS = 2` is a finding.
* JavaScript legacy octal (`017`) is decoded as octal. Strict-mode JavaScript
  rejects it, but the grammar accepts it, so the value is reported as 15.

## EXC001-EXC003

* Context managers are catches only when they are `contextlib.suppress` or a
  manager listed in `rules.exceptions.capture_managers`; a manager whose
  `__exit__` swallows but is not listed is an ordinary `with`.
* A promise rejection handler passed by reference is classified only when the
  reference is a function defined at the top level of the same module; an
  imported or computed handler is unresolved and fails closed.

* Exception identity resolution is static and best effort. It follows builtins,
  module-level imports (exact), relative imports, module-level classes and
  nested imports (approximate). It does not follow star imports, runtime
  rebinding, or names bound by `exec`/`globals()`; those are `unresolved` and
  fail closed, never guessed. An import inside a function that shadows a
  module-level import is not scoped: the last binding seen wins.
* Class hierarchies are unknown. A boundary for `OSError` does not approve
  `FileNotFoundError`; a catch of a broad library base (`requests.RequestException`)
  is flagged only for lacking a boundary, not as broad.
* JavaScript has no static exception types. The `instanceof` guard convention is
  a documented proof obligation on the handler, not a type proof: a boundary for
  `TimeoutError` approves whatever `TimeoutError` is bound to at runtime.
  `err.name === "..."`, `||`-joined guards, `switch (err.constructor)` and
  `catch ({ message })` are untyped and fail.
* Promise rejection handlers are inspected only when written inline;
  `.catch(handleError)` is opaque and fails closed. Rejections handled through
  `Promise.allSettled`, `.then(undefined, h)` with a non-function, or event
  listeners are not catches to this tool.
* EXC002 classifies handler shapes, not semantics. A handler that returns a
  variable, calls a helper, or has several statements is "other": EXC001 still
  applies but EXC002 does not say whether it hides the failure. DEF005 follows
  the returned value one step (module constants, one-return helpers); anything
  further is not traced.
* EXC003 reports what the `try` body contains, not which line raises. Arguments
  of the one attributed call may contain attribute access and constants that
  cannot raise the boundary exception; nested calls in arguments are counted as
  extra operations and flagged with `approximate` confidence. `finally`,
  `else`, and context-manager `__exit__` are not inspected.
* Python `except*` groups are handled like `except`; the group's contents are
  not inspected.

## DEF001-DEF006

* The rules are syntactic. They report value-substituting *expressions* and,
  since decision 34, the two `return` statement forms of a Python membership
  fallback (`if k in m: return m[k]` then `return v`, and the `not in` order).
  Other statement spellings (`if x is None: x = v`, `if k not in m: m[k] = v`,
  an `else:` branch, a JavaScript `if (o.has(k)) return o.get(k);`) are not
  inspected; rewriting an expression into one of them silences the rule without
  changing behaviour, and the policy relies on review for that.
* Fallback helpers are found by the shape of a module-level function and
  followed only to calls by name in the same file: a helper imported from
  another module, a method, or a helper whose default is computed from a
  parameter (`default or []`) is not followed.
* Types are not inferred. `.get`, `.setdefault` and `.pop` are matched by
  method name; the receiver is "known" only when the module binds or annotates
  it as a mapping, and then only by name, not by scope. An HTTP client's
  `session.get(url, params)` is an approximate DEF002 error;
  `session.get("path")` is an approximate review finding; `session.get(url)`
  is not reported at all.
* The implicit `None` of `m.get(k)` / `os.getenv("X")` is suppressed only when
  the same expression compares the result with `None` or feeds a reported
  `or`. A check on the next statement (`if raw is None: raise`) is not seen,
  so that pattern still produces a review finding.
* `or`/`||` operands that are Boolean *variables* (`return ok || done`) look
  like values and produce approximate review findings; only syntactic Boolean
  logic (comparisons, `not`, `and`) is excluded.
* Constant-shapedness is a naming heuristic: `DEFAULT_TIMEOUT` is treated as a
  constant because of its spelling. DEF005 never uses that heuristic alone: an
  `UPPER_CASE` name a handler returns is traced only when the module binds it.
* Dataclass detection is by decorator name (`dataclass`,
  `dataclasses.dataclass`); attrs, pydantic, `NamedTuple` and `TypedDict`
  defaults are not recognized. Python class attributes outside dataclasses and
  JavaScript class field initializers are not parameter defaults.
* JavaScript: a bare `process.env.X` or `o.x` read is not a finding because
  every absent property is `undefined`; object spread merging
  (`{ ...defaults, ...options }`), `Object.assign`, and `Map.prototype.get`
  without `??` are not recognized. Promise rejection handlers are covered by
  their literal body only (`.catch(() => null)`), not by traces.
* Environment reads through wrappers (`settings.env("X", 3)`, dotenv helpers)
  are not recognized; `os.environ.pop("X")` with one argument is not a finding.
* Rebinding is not followed: `DEFAULT = {}` traced by DEF005 may have been
  reassigned at runtime.

## Suppressions

* Only the single-line, same-line form is recognized. A suppression on the
  line above does nothing and is reported as unused.
* A suppression for a disabled or unimplemented rule is reported as unused.

## Positions

* A lone `\r` is treated as a line break for Python, matching `ast`. tree-sitter
  counts rows by `\n` only, so JavaScript files that use bare `\r` line breaks may
  report shifted line numbers. CRLF is handled correctly in both.
* Columns are 1-based character columns; editors that count UTF-16 code units
  (some IDEs) will differ on lines containing astral-plane characters such as emoji.

## Baselines and revision diff

* A fingerprint is built from the rule, path, enclosing scope, and the evidence
  line without whitespace. Two identical constructs in one file are told apart
  by an occurrence index in source order, so inserting a third identical
  construct *before* existing ones renumbers them and makes them look new.
  Renaming a file, a function, or changing the literal makes the finding new.
* A baseline does not freeze the policy. Fingerprints do not depend on the
  configuration; a stricter configuration produces new findings that are not
  in the baseline (the digest mismatch is reported, not refused).
* `diff` and `gate --base/--head` compare **committed trees only**. The
  working tree, the index, and untracked files are not analyzed; `--head HEAD`
  means the last commit. Trees are exported with `git archive`, which honours
  `export-ignore` attributes: a file excluded that way is absent from both
  sides. Symlinks inside the exported tree are extracted only where the host
  Python's `tarfile` data filter allows them.
* A file that failed to parse at the base revision contributes no findings
  there, so every finding in it at head is `new`. Parse failures at head follow
  `parse_errors`; at base they are only recorded.
* Both revisions are analyzed under the working tree's configuration (one
  digest for the whole report). The configuration committed at either revision
  is not consulted.

## Git history

* File granularity only. Per-function attribution, rename following
  (`--no-renames`: a renamed file's history starts at the rename), and merge
  commits (which list no files in `git log --name-only`) are not handled.
* Author counts are distinct author e-mail addresses as recorded by git; no
  identity merging. The addresses themselves are not written to the report.
* Co-change pairs are counted per commit; a commit touching more than fifty
  analyzed files is excluded from pairing (and counted in
  `commits_excluded_from_cochange`) because a sweep says nothing about which
  files belong together.
* `commits_considered` is bounded by `git log --since`, which git evaluates on
  committer dates and which can stop a traversal early in histories with
  out-of-order dates; the result is deterministic for a given head commit.
* The hotspot score needs both history and complexity. Outside a repository,
  without git, or with `complexity.enabled = false` it is `null` with
  `hotspots_reason` naming the missing input; a file that failed to parse has
  churn but no score. It is file-level: a file with one hot function and ten
  cold ones scores as one file.

## Complexity metrics and the call graph

* The conventions are the tool's own (`docs/complexity.md`), versioned and
  stated in every message. `cognitive/1` follows the published description of
  cognitive complexity but is not a SonarSource score: nested units are
  measured separately, comprehension `for` clauses do not count, and operator
  runs are counted per parenthesized group. Numbers are not comparable with
  other tools, only with earlier runs of this one.
* A unit's numbers exclude nested units. Extracting code that sits two or more
  decision levels deep lowers the file's summed cognitive score by the nesting
  increments it no longer pays; the graph records the new edge but no score
  says whether the extraction helped a reader.
* NPath is an estimate: infeasible paths are counted, loops count as one
  branch, early returns prune nothing, and the value is clamped at
  `npath_cap` (reported as `>= cap`).
* The call graph is static and best effort. `unresolved` edges are honest
  gaps, not errors: computed callees (`o[k]()`, `getattr(o, n)()`, `f()()`),
  method calls on parameters, locals and other values of unknown type,
  unbound names (JavaScript globals outside the fixed builtin list included),
  and `self`/`this` attributes neither the class nor its analyzed bases define
  (assigned, decorated, dynamic) are never guessed. A method through an exact
  receiver resolves (`docs/proposal-receivers.md`, R1 for Python, R2 for
  JavaScript), on a closed world: a subclass outside the analyzed files that
  overrides the method is not seen, and a JavaScript object literal's method
  that another module reassigns is not seen either. Decorators that rebind,
  `__getattr__`, star imports, `exec`/`eval`, runtime rebinding, event
  handlers and callbacks registered elsewhere are not followed. A `probable`
  edge says the binding was not proven (a JavaScript default import's
  attribute is looked up as a module member; `self.m()` / `this.m()` is
  overridden in an analyzed subclass; `this` in an object literal's method
  depends on the call).
* Module edges resolve only among the analyzed files. A Python module's name
  starts at the first package (`__init__.py`) on its path; files outside any
  package answer to their basename. Namespace packages, `sys.path` tricks,
  `importlib`, and JavaScript path aliases (tsconfig `paths` and `baseUrl`
  included), bundler resolution, `package.json` `exports` and JSON imports are
  not understood: those
  edges are `external` or `unresolved`, and a cycle through them is not
  detected.
* Fan-out counts distinct targets of resolved and probable edges; builtins
  are excluded, unresolved calls are reported but never counted, so a unit
  built on dynamic dispatch has a low fan-out and a high unresolved count.
* Shared mutable state is a module-local heuristic: writes through aliases,
  through other modules, through `nonlocal`, or by functions that received
  the container as an argument are not seen; shadowing is tracked only by
  name within one unit.
* Abstraction displacement is experimental and off by default; it follows
  resolved edges only and marks every entry approximate.
* Regressions in a revision diff match units by `path::name` key: a renamed
  or moved unit is a new unit (its base value is taken as nothing), so a
  rename of an already-complex function shows up as a regression once.

## SARIF

* One run per document. `baselineState` is present only when a baseline file
  or base revision was applied; otherwise consumers see no state at all rather
  than a guessed one. Fixed findings of a diff appear as `absent` results with
  their base-revision locations.
* URIs are root-relative with `uriBaseId = "%SRCROOT%"`; the absolute root is
  not written so the document is byte-identical across machines.

## Skills

* `skills install` knows three destinations (`claude`, `codex`, `generic`);
  the Claude and Codex paths were verified against each vendor's documentation
  on 2026-10-14 and are a one-line table entry each in
  `src/shockharness/skills/adapters.py`. A vendor that moves its skills
  directory needs a new release of this package (or `--agent generic
  --project <dir>` in the meantime).
* The frontmatter parser reads the subset of YAML the shipped skills use
  (single-line `key: value` fields between two `---` lines); it is not a YAML
  parser and is applied only to the shipped files.
* `skills update` detects edits by hash; it does not merge. An edited file is
  left alone and reported, and the shipped version is available with
  `skills show`. `skills install --force` is the only command that overwrites
  an edited skill.
* The eval runner scores analyzer findings, the task's tests and added
  suppressions. It does not run agents, does not score review accuracy
  (`pre-commit-review` verdicts are compared by hand), and needs `node` on
  `PATH` for the JavaScript tasks (a missing `node` is reported as a test
  failure, never as a pass).
* The "Adopting ShockHarness" section embedded in every skill pins the
  package version of the skill's own release, so an installed skill may name
  an older version than the latest on PyPI until `skills update` is run.

## VERIFY001-VERIFY004

* They need a base revision. A plain `check` reports them as not applicable;
  only `diff` and `gate --base/--head` run them.
* Syntax, not intent. A skip inside a conditional branch of a test body, a
  skip applied by a fixture or a conftest hook, a test deselected by runner
  configuration (`-k`, `addopts`, `testPathIgnorePatterns`) and an ignore list
  in a tool's configuration file are not seen by `VERIFY001`; `VERIFY003`
  reports the configuration changes it knows (below).
* `VERIFY004` knows patterns, not semantics: an assertion weakened to one that
  is merely unlikely to fail (`assert len(x) >= 0`, a loosened tolerance) is
  not judged. Assertions are counted syntactically; a test that moved its
  checks into a helper whose name does not start with `assert` or `expect`
  looks as if it lost them.
* Matching is by file (following git's rename detection) and by test name. A
  renamed test function or a file git does not recognise as renamed makes its
  existing markers and suppressions look added. A file whose base version could
  not be analyzed yields `unknown` findings.
* JavaScript skips carry no reason, so `allowed_skip_reasons` applies to Python
  markers only. `@ts-expect-error` is classified as a blanket suppression
  because it names no code.
* A local CLI cannot stop someone with write access from editing the
  configuration that would report them, or from not running the tool. The
  rules are enforceable when `gate` runs in CI as a required check on protected
  branches and policy files need review (spec section 21.1 decision 5).

* `VERIFY003` reads workflows as text, without a YAML parser: flow-style
  mappings, anchors and aliases, matrix-generated jobs and steps defined in a
  composite action or another reusable workflow are not interpreted, and a job
  renamed in the same change looks like a removed job plus a new one. Workflows
  are checked only when the analysis root is the repository's top level.
* `VERIFY003` compares the tool configuration files at the analysis root only,
  and only the settings listed in `docs/rules.md`. Not read: ESLint flat config
  (`eslint.config.js`), `package.json` `eslintConfig`, a YAML `.eslintrc`
  (reported as `unknown`), mypy, pyright, tsconfig, Jest/Vitest configuration,
  `conftest.py` hooks, and nested configuration files in subdirectories.
* Baseline growth is detected for files whose name contains `baseline` and that
  parse as ShockHarness baselines. A baseline passed with `--baseline` under
  another name is not compared.
* The policy floor protects the keys the policy file sets, compared with the
  same loosening test as `VERIFY003`. A key the policy does not set is the
  repository's to change. Command-line `--profile` and `--parse-errors` are not
  bound by the policy; a workflow that adds them is reported instead.

## EXC004, STUB001, STUB002, ASSERT001, BOOL001, STATE001, IMPORT001 (H3)

* They ship at `warning` (`BOOL001` at `review`) and never gate by default: their
  precision has not been measured on a reviewed corpus yet (spec 21.1 decision 9).
* Syntax, not intent. `STUB001` does not recognize an abstract API written
  without `ABC`, `Protocol` or `@abstractmethod`, and cannot tell a plausible
  fake (`return True`) from an implementation (that is the planned `STUB003`).
  `ASSERT001` knows external input only through its catalogs (data read from the
  project's own storage is an invariant to it); `ASSERT002` accepts any read of
  `sys.flags.optimize` as the guard and may not see one outside a partial run.
  `BOOL001` does not resolve the callee, so a flag whose meaning is obvious from
  the function name is reported too.
* `STUB002` matches import names, not files: a production package named
  `fixtures` is reported, and a mock reached through a re-export is not.
* `STATE001` is per file: writes through another module (`other.CACHE.append`)
  or an alias are not seen.
* `IMPORT001` recognizes only the configured qualified operations, resolved
  through the file's own imports; framework calls on objects (`app.run()`,
  `server.listen()`) and effects reached through a function called at import
  time are not reported. A local function that shadows a global such as `fetch`
  is still matched. The script exemption trusts a shebang even in a file that
  is also imported, and decides "nothing imports it" from resolved module edges
  among the analyzed files only (a `runpy` or subprocess invocation is not an
  import).
* JavaScript has no removable `assert`, so `ASSERT001` is Python only; empty
  JavaScript functions are not `STUB001` findings.

## ASYNC001-ASYNC003 (H4)

* They ship at `warning` and never gate by default (decision 9). An `ASYNC001`
  finding through a `probable` call-graph edge is `unknown` and gates only with
  `rules.async_lifecycle.fail_on_unknown = true`.
* `ASYNC001` sees a call that is a whole statement (or `void`). A coroutine or
  Promise stored in a variable and never awaited, passed to a function that
  drops it, or created inside an expression is not tracked. Without type
  information an arbitrary library call is not assumed to return a Promise:
  only the configured catalog and project functions declared `async` count.
  A function that returns a Promise without being declared `async` is not
  recognized. A global unhandled-rejection listener exempts every `void` call
  of the project, whatever the listener does beyond `preventDefault()`; a
  listener registered through a helper, or on an object other than `window`,
  `self`, `globalThis` or `process`, is not seen.
* `ASYNC002` recognizes a supervisor only by the `with`/`async with` that bound
  the receiver in the same function; a `TaskGroup` passed in as a parameter is
  not recognized, so `group.create_task(...)` there is reported (approximate).
  A task kept in a set or given a done-callback is not reported, and whether
  that owner retrieves its exception is not checked.
* `ASYNC003` recognizes inspection anywhere in the enclosing function, not
  traced to the batch's own results; a helper in another function that inspects
  them is not followed.
* Framework background-job queues, event emitters and callback APIs are not
  modeled.

## PROCESS001, RESULT001, TYPE001, SLEEP001, RETRY001, BATCH001, STUB003 (H5)

* Advisory until measured (decision 9); `TYPE001`, `SLEEP001` and `STUB003` ship
  at `review` because the pattern is often deliberate.
* Catalogs, not types: a callee counts only when it resolves through the file's
  imports to a listed name; a wrapper the project wrote is invisible until it is
  listed. `RESULT001`'s method entries match any receiver by name and argument
  count: a project method with the same name and count as a pure one
  (`rich`'s in-place `Text.rstrip()`) is still reported, and a must-use call in a
  `try` with a handler is never reported, whether or not it can raise.
* `STUB003` matches classes by name, not through imports: two classes of one
  name in different modules are treated as one.
* `PROCESS001` does not trace whether interpolated data can contain shell syntax
  (H6), counts a status read anywhere in the function as checking it, and does
  not judge `Popen` / `spawn` exit handling.
* `RETRY001` sees bounds only in the handler or the decorator; a timeout around
  the loop is not seen. `BATCH001` does not check whether recorded failures are
  ever reported. `SLEEP001` cannot tell pacing from synchronization.
* `TYPE001` lists escapes where they are written: an `any` inside a type alias
  is reported at the alias, not at each use; an assertion to the type a value
  already has is still reported; `unknown`, `object` and `Function` are not
  escapes. `// eslint-disable` of a `@typescript-eslint` rule is SUPP001/SUPP002's.

## TypeScript

* No type information is used: rules read the syntax, as for JavaScript. A
  call on a typed receiver (`client: Client` then `client.send()`) resolves no
  better than in JavaScript, and type annotations never narrow a finding.
* `import type`, `export type ... from` and `{ type X }` specifiers are erased
  (no import fact, no module edge), as the compiler erases them; a module that
  `verbatimModuleSyntax` keeps for its side effects is not modelled.
  `import x = require("m")` is a module import; `export =` and `import A = N.B`
  aliases are not followed.
* A `./m.js` (`.mjs`, `.cjs`) specifier resolves to `m.ts` / `m.tsx` (`.mts`,
  `.cts`) when no JavaScript file of that name is analyzed, as TypeScript's
  `node16` resolution does.
* Namespaces (`namespace N {}`) and `declare module` blocks are read as code,
  but their members are not module bindings, so `N.f()` does not resolve; enum
  declarations are not bindings either, and their member values are executable
  code for MAGIC001.
* Overload signatures, abstract members and interface members have no body and
  are not units. Decorators are code: their arguments are scanned.
* Declaration files (`**/*.d.ts`) are excluded by default; listing one
  explicitly analyzes it like any TypeScript file.

## ROLE001

* Only resolved module edges count: an import the module graph cannot resolve
  (a computed specifier, a re-export it does not follow) is not seen.
* A helper that only tests import but that holds real logic is not judged; the
  empty-test check recognizes test cases syntactically (the VERIFY test-case
  facts) and support files by glob.
* The diff side compares roles of files that exist at both revisions (renames
  followed); a new file added directly under `tests/` is not a reclassification.

## INPUT001-INPUT002 (H6)

* No path sensitivity and no guards: a check before the sink
  (`if not cmd.isalnum(): raise`) is not seen; only a catalog validator cleans
  a value, and it cleans it for every sink (`shlex.quote` makes a value clean
  for a SQL query too).
* Values are followed through locals, arguments and return values only: an
  attribute (`self.cmd = ...`), a module-level variable read in another
  function, a closure, a callback or a dynamically dispatched call breaks the
  chain. A method call resolves only as far as the call graph resolves it
  (`self.m(...)` is probable; `Runner().go(...)` is not resolved).
* A call the analysis cannot resolve passes everything on: `len(body)` would be
  tainted if `len` were not a validator. Constructors of project classes pass
  their arguments on rather than following `__init__`.
* Sources rooted at parameters match by name (`req.body` in any function
  whose parameter is called `req`); method-name sinks (`.execute`, `.query`)
  and validators (`.parse`) match any receiver.
* INPUT002 cannot tell a required variable from an optional one; a check in
  another function (a later `validate_config()`) is not seen, and destructuring
  `const { X } = process.env` is not followed.
* Code nested deeper than 100 statements or expressions is not followed (the
  unit's facts are marked truncated); long operator chains are flattened and
  never count against that depth.

## PROV001, GUARD001 (H6 part two)

* Intent is not known: a parameter that legitimately takes a new identifier or
  an existing one is reported, and so is a call whose guard is unnecessary at
  that site (the caller already knows the value is present).
* Issuers are recognized by name; an identifier that arrives as the caller's own
  parameter is not classified.
* A guard is a call on the same argument text: a check through another variable
  or attribute, a `try`/`except` around the call, a guard in the caller's caller,
  or a comparison that is not a call (`if key in table:`) is not seen.
* Only call sites the call graph resolves to one project function are compared;
  method calls on objects the graph cannot type are not.
* A callee's own check counts only among its leading statements and only on the
  parameter the first argument binds; a check further down is not seen.

## MAGIC003

* Whether a number means something is not known: plain arithmetic written as a
  value (`step = -1`, a direction passed to a project function, an index passed
  to a project method) is reported too, and a sentinel built at run time
  (`-len(x)`) is not seen.
* Index callees are matched by name (`.pop` on any receiver); a project method
  that takes an index needs adding to the catalog.

## DOM002

* Opt-in: whether a handler really acts on presses outside is the project's
  statement in `press_exclusions`; nothing is guessed.
* Vanilla DOM only: jQuery (`$("body").append`), portals and framework rendering
  are not read, and an element reached through an object property
  (`document.body.append(state.overlay)`) is not followed.
* Names given to an element outside the function that builds it, attribute and
  pseudo selectors, and helpers reached through anything but a plain call are not
  seen; whether a modal can open while the handler's mode is active is not known.

## MAGIC002

* Equal strings are grouped by value only: two copies that mean different
  things (a column name and a CLI word) are reported together, and two spellings
  of one meaning (`"Pending"`, `"pending"`) are not linked.
* Strings built at run time, f-string and template parts, and the values of
  UPPER_SNAKE_CASE definitions are not seen; a status kept in a lowercase module
  variable is counted like any other value.
* A message is recognized by its callee's last name (`message_callees`, or a
  name ending in `Error` / `Exception` / `Warning`); a message passed through a
  project helper is counted.

## DOM001

* Syntax only: a guard through a helper (`isHtml(target)`), a target stored on
  an object, or `closest()` reached through another variable is not seen, and
  only a test in the function's own body (not in a nested block) is considered.

## Empty trees, and checks a layered checker may still need

* A tree with no analyzable files passes: `check` reports `0 file(s)` and exits
  `0`. `unsupported_sources` is about files that are present but unsupported,
  not about the absence of files.
* For projects that run their own checker alongside ShockHarness, what is
  covered today: `contextlib.suppress` (a catch that swallows: `EXC001`,
  `EXC002`), JavaScript `.catch(...)` rejection handlers (`EXC001`, `EXC002`,
  `DEF005`), every `except`/`catch` outside a declared boundary, and since H3
  `return`/`break`/`continue` in a `finally` block (`EXC004`, at `warning`
  until measured), and since H4 `asyncio.gather(..., return_exceptions=True)`
  and `Promise.allSettled` whose results are never inspected (`ASYNC003`),
  dropped coroutines and Promises (`ASYNC001`) and tasks started without an
  owner (`ASYNC002`), and since H5 `subprocess` calls whose exit status is
  ignored and shell commands built from data (`PROCESS001`), and since H-TS
  all of it for TypeScript too, with its type escapes (`TYPE001`), and since
  H6 request data reaching a shell, query, file path or redirect unvalidated
  (`INPUT001`), unchecked optional configuration reads (`INPUT002`), made-up
  identifiers where issued ones are expected (`PROV001`) and calls left
  unguarded where the other callers check (`GUARD001`).

## Not yet built (see the specification)

The
remaining advanced-guardrail rules of specification section 21, per-function
churn and rename following, change-impact radius,
and `.gitignore` awareness. Unknown CLI commands are argparse
errors (exit 2). Profiles exist but are limited to the three built-in
ones (no user-defined or remote profiles), and the only command-line overrides
are `--profile` and `--parse-errors`. The publish workflow and the reusable
consumer workflow have not yet run on GitHub: the first `v*` tag exercises
them (see `docs/releasing.md`), and the example workflows reference the tag
`v0.12.0`, which exists only after that release.

## Platform

Tested locally on macOS with CPython 3.11, 3.12, 3.13, and 3.14 (the CI
matrix adds Linux and Windows). The symlink test is skipped on Windows.
