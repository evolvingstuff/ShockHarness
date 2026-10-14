# Limitations

Stated so that a clean report is never read as more than it is.

## Coverage

* Only `MAGIC001`, `EXC001`, `EXC002`, `EXC003`, `SUPP001`, and `SUPP002`
  produce findings. Every other registered rule is listed in
  `coverage.rules_not_implemented` in each report. A passing gate today means
  "no magic numbers, no unapproved or suppressing catches, no over-wide
  approved try blocks, and no bad suppressions", nothing more.
* Python syntax coverage is exactly the host interpreter's `ast`. Running on
  3.11 cannot parse 3.12-only syntax; such files are parse failures, not clean.
  The report records `coverage.host_python`.
* JavaScript coverage is the pinned `tree-sitter-javascript` grammar (ESM,
  CommonJS, JSX). TypeScript is not analyzed; `.ts`/`.tsx` in `include` is a
  configuration error.
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
  applies but EXC002 does not say whether it hides the failure. DEF005
  (Milestone D) will cross-reference catches with default values.
* EXC003 reports what the `try` body contains, not which line raises. Arguments
  of the one attributed call may contain attribute access and constants that
  cannot raise the boundary exception; nested calls in arguments are counted as
  extra operations and flagged with `approximate` confidence. `finally`,
  `else`, and context-manager `__exit__` are not inspected.
* Python `except*` groups are handled like `except`; the group's contents are
  not inspected.

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

## Not yet built (see the specification)

Default/fallback rules, complexity metrics, call graphs, Git
history features, baselines and diff mode, SARIF output, `.gitignore`
awareness, agent skills and `skills install`. Each of these fails loudly
today: unknown CLI commands are argparse errors (exit 2), `--format sarif` is
refused with exit 2, and `evaluate_gate` rejects a baseline with
`UnsupportedFeatureError`.

## Platform

Tested locally on macOS with CPython 3.11, 3.12, 3.13, and 3.14 (the CI
matrix adds Linux and Windows). The symlink test is skipped on Windows.
