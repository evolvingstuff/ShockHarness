# Limitations

Stated so that a clean report is never read as more than it is.

## Coverage

* Only `MAGIC001`, `EXC001`-`EXC003`, `DEF001`-`DEF006`, `CPLX001`-`CPLX006`,
  `SUPP001`, and `SUPP002` produce findings; `MAGIC002` is listed in
  `coverage.rules_not_implemented` in each report. A passing gate today means
  "no magic numbers, no unapproved or suppressing catches, no over-wide
  approved try blocks, no recognized default or fallback shapes, and no bad
  suppressions", nothing more: the complexity family is advisory and a
  passing gate says nothing about it.
* Python syntax coverage is exactly the host interpreter's `ast`. Running on
  3.11 cannot parse 3.12-only syntax; such files are parse failures, not clean.
  The report records `coverage.host_python`.
* JavaScript coverage is the pinned `tree-sitter-javascript` grammar (ESM,
  CommonJS, JSX). **TypeScript is not analyzed.** A `.ts`/`.tsx` file that an
  `include` pattern matches is an *unsupported source*: `unsupported_sources`
  (`warn` in `strict` and `recommended`: listed under
  `coverage.unsupported_sources` with a warning line; `fail`: an analysis
  failure and exit 3; `ignore` in `minimal`) is how a project notices that a
  file left the policy. An `include` pattern that names an unsupported
  extension literally (`**/*.ts`) is still a configuration error.
* Only UTF-8 (with or without BOM) sources are read. Other encodings are a
  `decode_error` file status. Python's PEP 263 coding declarations are not honored.

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

* The rules are syntactic. They report value-substituting *expressions*; a
  default spelled as a statement (`if x is None: x = v`, `if k not in m:
  m[k] = v`) is not inspected. Rewriting an expression into that form silences
  the rule without changing behaviour; the policy relies on review for that.
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
  and `self`/`this` attributes the class body does not define (inherited,
  assigned, decorated, dynamic) are never guessed. Inheritance, decorators
  that rebind, `__getattr__`, star imports, `exec`/`eval`, runtime rebinding,
  event handlers and callbacks registered elsewhere are not followed. A
  `probable` edge says the binding was not proven (a module alias may be
  rebound; `self.m()` may be overridden).
* Module edges resolve only among the analyzed files. A Python module's name
  starts at the first package (`__init__.py`) on its path; files outside any
  package answer to their basename. Namespace packages, `sys.path` tricks,
  `importlib`, and JavaScript path aliases, bundler resolution, `package.json`
  `exports`, TypeScript sources and JSON imports are not understood: those
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

## Not yet built (see the specification)

`MAGIC002`, per-function churn and rename following, change-impact radius,
data flow, and `.gitignore` awareness. Unknown CLI commands are argparse
errors (exit 2). Profiles exist but are limited to the three built-in
ones (no user-defined or remote profiles), and the only command-line overrides
are `--profile` and `--parse-errors`. The publish workflow and the reusable
consumer workflow have not yet run on GitHub: the first `v*` tag exercises
them (see `docs/releasing.md`), and the example workflows reference the tag
`v0.2.0`, which exists only after that release.

## Platform

Tested locally on macOS with CPython 3.11, 3.12, 3.13, and 3.14 (the CI
matrix adds Linux and Windows). The symlink test is skipped on Windows.
