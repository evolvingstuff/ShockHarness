# STATUS

Implementation log for ShockHarness, kept per the specification's completion
protocol (section 15). Every claim below was produced by running the command
shown; nothing is reported as passing that was not run.

## Milestone A: skeleton + contracts — DONE (2026-10-14)

Delivered: `pyproject.toml` (hatchling, Python 3.11+, MIT), `LICENSE`,
`README.md`, `CHANGELOG.md`, GitHub Actions matrix (ubuntu/macos/windows x
3.11-3.14 plus a wheel build job), `.pre-commit-hooks.yaml`, configuration
schema with full shape and semantic validation, precedence
(`--config` > `.shockharness.toml` > `pyproject.toml` > bundled defaults),
rule registry with every specified rule ID and implementation status,
diagnostic/report models, `schemas/report-v1.schema.json`, CLI `scan`,
`config validate`, `config effective`, `rules list`, `rules explain`, `init`,
exit-code contract (0/1/2/3), text and JSON renderers, library API
(`analyze_source`, `analyze_paths`, `evaluate_gate`).

## Milestone B: parsers + MAGIC001 — DONE (2026-10-14)

Delivered: Python adapter (`ast` + `tokenize`, iterative traversal, byte to
character columns, scope names, annotation marking), JavaScript adapter
(tree-sitter, any `ERROR`/`MISSING` node is a parse failure, iterative
traversal, JSX/template/BigInt/legacy-octal/separators), `MAGIC001` (value-based
0/1, folded unary sign, `-0` flagged, annotations flagged), `SUPP001`/`SUPP002`
inline suppression rules, per-path overrides with recorded origin,
configuration-file exemption with recorded reason, golden fixture corpus (26
files, expectations reviewed by hand), property/metamorphic/fuzz tests, CLI
tests, self-compliance test.

Acceptance criterion from the spec, verified by
`tests/cli/test_cli.py::test_milestone_b_acceptance_python_and_js`:
`range(2)` fails in Python; `for (let i = 0; i < 2; i++)` fails in JS; both
pass with `rules.magic_numbers.enabled = false` and the JSON report records
the disable under `coverage.rules_disabled_globally`, `config.deviations`, and
every file's `rules_disabled`.

Milestones A and B were built in one pass because `scan` cannot be exercised
end to end without a parser and a rule; they are committed together.

## Evidence (all run 2026-10-14 on macOS arm64)

```text
$ ruff check src tests && ruff format --check src tests
All checks passed!
48 files already formatted

$ pytest -q                      # CPython 3.14.7
224 passed in 1.45s
$ pytest -q                      # CPython 3.13.1
224 passed in 1.65s
$ pytest -q                      # CPython 3.12.8
224 passed in 1.63s
$ pytest -q                      # CPython 3.11.11
224 passed in 1.39s

$ shockharness scan src tests    # self-compliance, all four interpreters
gate: PASS (exit 0)

$ shockharness config validate
shockharness: configuration is valid (dedicated: .../.shockharness.toml)

$ python -m build
Successfully built shockharness-0.1.0.tar.gz and shockharness-0.1.0-py3-none-any.whl

$ uv venv clean --python 3.12 && uv pip install dist/shockharness-0.1.0-py3-none-any.whl
$ clean/bin/shockharness --version
shockharness 0.1.0
$ clean/bin/shockharness scan src/b.js --format json     # smoke corpus, 8 findings, gate fail
```

Sample text output on a mixed smoke corpus (Python file with violations and
suppressions, JS file, one unparseable file):

```text
src/a.py:2:11: MAGIC001 error: Numeric literal 30 has no permitted justification in executable code  [TIMEOUT = 30]
src/a.py:8:5: MAGIC001 error: Numeric literal 0x1F has no permitted justification in executable code  [w = 0x1F  # shockharness: ignore[MAGIC001] reason="RFC 1234 flag mask"]  (suppressed: RFC 1234 flag mask)
src/a.py:9:8: SUPP001 error: malformed suppression; expected shockharness: ignore[RULEID] reason="..."  [q = 7  # shockharness: ignore[MAGIC001]]
src/b.js:3:13: MAGIC001 error: Numeric literal -0 has no permitted justification in executable code  [const neg = -0; const el = <A size={2} b="3"/>;]
src/c.py:1:12: parse_error: SyntaxError: invalid syntax

shockharness 0.1.0: 3 file(s), 2 analyzed, 1 failed; 19 finding(s), 2 suppressed
  rules applied: MAGIC001, SUPP001, SUPP002
  rules not implemented (not analyzed): MAGIC002, EXC001, EXC002, EXC003, DEF001, ...
  analysis status: failed
gate: ERROR (exit 3)
  1 file(s) could not be analyzed and parse_errors = "fail"
```

## Failures observed during development (and what was done)

1. **Bundled defaults misplaced `overrides`** under `[gates]`; the first `scan`
   exited 3 with a traceback via the process boundary. Fixed; a test now
   asserts the bundled defaults' shape.
2. **Self-gate caught a real violation**: `match.group(2)` in
   `suppressions.py`. Replaced with named groups. The gate works on its author.
3. **Segmentation fault**: py-tree-sitter 0.26.0 on CPython 3.14 crashes when
   walking trees nested deeper than about 200 levels (CPython 3.13 with 0.26.0
   and CPython 3.14 with 0.25.2 are fine). Runtime pin is now
   `tree-sitter>=0.25.1,<0.26`; the 300-deep test guards the regression.
4. **Fuzzer found an undeclared boundary**: CPython's `tokenize` raises
   `UnicodeDecodeError` for `\r` followed by a multibyte character even when
   `ast.parse` succeeds. Now caught at the declared Python-adapter boundary and
   reported as a parse failure.
5. **IR literal order** from the Python adapter was reversed (stack traversal).
   IR literals and comments are now sorted by span in both adapters.
6. **Ruff reformatted two fixtures** before `tests/fixtures` was excluded from
   it, shifting golden lines. Fixtures restored; regenerated expectations
   diffed byte-identical against the reviewed set.

## Milestone C: exception rules EXC001-EXC003 — DONE (2026-10-14)

Delivered: catch facts in the IR (`ir/model.py`: `CatchFact`,
`ExceptionIdentity` with exact/approximate/unresolved confidence, `HandlerBody`
classification, `TryStatement` attribution), Python extractor
(`ir/python_catches.py`: module symbol table over builtins, absolute and
relative imports, aliases, module-level classes, nested and guarded imports;
`except`/`except*`; handler classification empty / logging-only /
return-fallback / reraise / raise-chained / raise-other / other), JavaScript
extractor (`ir/javascript_catches.py`: `catch` clauses, `.catch(handler)`,
`.then(ok, handler)`, the two `instanceof` guard forms, opaque handlers),
`rules/exceptions.py` (EXC001 boundary whitelist that fails closed on bare,
unresolved, and dynamic identities; EXC002 on the four suppressing shapes even
inside a boundary; EXC003 one-statement/one-operation try bodies, reported on
the offending statement), `rules.exceptions.transparent_rethrow` (default
false, reported as a deviation), boundary `exception` validated as a dotted
class name (wildcards rejected), every boundary listed in `config.deviations`,
registry metadata for the three rules, 19 new golden fixtures (expectations
regenerated and reviewed row by row; the golden test now accepts per-fixture
`rules.exceptions` settings so boundary cases are covered), unit tests for
identity resolution confidence and for every rule verdict, a CLI acceptance
test, and documentation.

Decisions recorded here (not in the specification):

* **JavaScript convention.** A `catch` is approved only inside a boundary whose
  `exception` names an error class *and* whose handler opens with
  `if (!(err instanceof C)) throw err;` (or the block form, or
  `if (err instanceof C) {...} else { throw err; }`). `exception = "*"` is a
  configuration error. `err.name === "..."` and `||`-joined guards are untyped.
  The guarded identity is `approximate`: nothing proves what `C` is bound to.
* **Approximate matching.** Relative imports (`.errors.X`), classes defined in
  the analyzed module (`src.pkg.m.X`), nested imports, and JavaScript guards
  match a boundary by dotted suffix in either direction. Exact identities must
  match exactly.
* **`transparent_rethrow`** also lets a bare `except: raise` pass: it changes
  nothing about the flow. `raise X from err` is a conversion and is never
  transparent.
* **EXC003 counts operations**, not just statements: `parse(session.get(url))`
  under a Timeout boundary is flagged with `approximate` confidence because the
  handler would also catch a Timeout raised by `parse`. Import statements are
  attributable operations (optional-dependency boundaries).
* **EXC002 `other`.** A handler that returns a variable or has several
  non-logging statements is not classified; EXC001 still applies. DEF005 will
  cross-reference catches with defaults.

Acceptance criterion from the spec (Milestone C), verified by
`tests/cli/test_cli.py::test_milestone_c_acceptance_exceptions`: the same
narrow `requests.exceptions.Timeout` handler passes in `src/net/` (boundary)
and fails in `src/core/` (no boundary); `except Exception: return None` fails
EXC001 and EXC002; `except Mystery` is an EXC001 finding with
`confidence = "unresolved"` saying the name could not be resolved; a
boundary-approved handler around two statements fails EXC003 on the second
statement.

### Dogfooding: what the rule found in the tool

With `.shockharness.toml` unchanged, the first self-scan failed with four
EXC003 findings. All were real over-wide boundaries and were fixed in code;
no boundary was added or widened:

1. `analysis.py` `_read_source` returned `raw.decode("utf-8-sig"), None, None`
   from inside the `UnicodeDecodeError` try (a tuple, not a call). Now the
   decode is bound in the try and the tuple is built after it.
2. `config.py` `_read_toml` had `tomllib.loads(raw_bytes.decode("utf-8"))`
   under two handlers, so the TOML boundary also caught decode errors and vice
   versa. Now two try blocks, one call each.
3. `ir/python.py` `_comments` wrapped a whole `for` loop (tokenize, build
   `Comment` facts, append) under the tokenizer boundary. Now `list(tokens)` is
   the one protected call; facts are built outside it. The pre-existing
   `(tokenize.TokenError, SyntaxError, ValueError)` tuple handler is approved
   member by member by boundaries 5-7.

Behaviour is unchanged (all Milestone B tests still pass); the gate is green on
all four interpreters.

### Evidence (all run 2026-10-14 on macOS arm64)

```text
$ ruff check src tests && ruff format --check src tests
All checks passed!
52 files already formatted

$ pytest -q                      # CPython 3.14.7
325 passed in 1.65s
$ pytest -q                      # CPython 3.13.1
325 passed in 1.79s
$ pytest -q                      # CPython 3.12.8
325 passed in 1.65s
$ pytest -q                      # CPython 3.11.11
325 passed in 1.89s

$ shockharness scan src tests    # self-compliance, all four interpreters
gate: PASS (exit 0)

$ shockharness config validate
shockharness: configuration is valid (dedicated: .../.shockharness.toml)
  policy deviation: rules.exceptions.boundaries[0] approves catching OSError in src/shockharness/config.py (python): ...
  ... (11 boundaries, 2 overrides)

$ python -m build
Successfully built shockharness-0.1.0.tar.gz and shockharness-0.1.0-py3-none-any.whl
```

Sample text output on a smoke corpus (`src/net/client.py` with a narrow
approved handler, a two-statement try, a broad catch, and an unknown name;
`src/net/client.js` with a guarded catch and a logging-only `.catch`; boundaries
for `requests.exceptions.Timeout` and `TimeoutError` on `src/net/**`). The
narrow Python handler and the guarded JavaScript catch produce nothing:

```text
src/net/client.js:9:12: EXC001 error: promise .catch handler is forbidden: rejection handler binds every rejection; it passes only inside an approved boundary whose error class the handler checks with instanceof and otherwise rethrows  [fetch(url).catch((err) => { console.error(err); });]
src/net/client.js:9:12: EXC002 error: promise .catch handler only logs the exception; logging is not handling  [fetch(url).catch((err) => { console.error(err); });]
src/net/client.py:15:9: EXC003 error: approved except handler protects 2 statements; a boundary may wrap only the one sanctioned external operation (approved by boundaries[0] (requests.exceptions.Timeout: External HTTP call may time out))  [data = response.json()]
src/net/client.py:24:5: EXC001 error: except handler of 'Exception' is forbidden: broad catch of 'Exception' is not approved by any boundary for this file  [except Exception:]
src/net/client.py:24:5: EXC002 error: except handler converts the exception into a fallback value: return None  [except Exception:]
src/net/client.py:31:5: EXC001 error: except handler of 'Mystery' is forbidden: 'Mystery' could not be resolved to a known exception (not a builtin, an import, or a class defined in this module); strict mode fails closed  [except Mystery as exc:]

shockharness 0.1.0: 2 file(s), 2 analyzed, 0 failed; 6 finding(s), 0 suppressed
  by severity: error=6
  rules applied: MAGIC001, EXC001, EXC002, EXC003, SUPP001, SUPP002
  rules not implemented (not analyzed): MAGIC002, DEF001, DEF002, DEF003, DEF004, DEF005, DEF006, CPLX001, CPLX002, CPLX003, CPLX004, CPLX005
  policy deviation: rules.exceptions.boundaries[0] approves catching requests.exceptions.Timeout in src/net/** (python): External HTTP call may time out
  policy deviation: rules.exceptions.boundaries[1] approves catching TimeoutError in src/net/** (javascript): External HTTP call may time out
  analysis status: complete
gate: FAIL (exit 1)
  6 hard violation(s) and gates.new_hard_violations = "fail"
```

### Failures observed during development (and what was done)

1. **Self-gate found four over-wide boundaries** in the tool (listed above).
   Code narrowed; policy untouched.
2. **Golden generator tokens**: regenerating `expected.json` with a fixed
   40-character message prefix would have rewritten three hand-shortened
   Milestone B tokens. The generator now keeps a reviewed token when it still
   matches the message; the 23 Milestone B entries are byte-identical.
3. **`from .. import errors`** produced `...errors.X` (three dots). Fixed the
   relative-prefix join; covered by
   `test_relative_local_and_nested_bindings_are_approximate`.
4. **`x = new Client(u)`** in a JavaScript try body was "not a call" because
   the statement is an assignment expression; the attribution now unwraps
   assignments. Covered by `test_try_statement_attribution_in_javascript`.
5. Four unit-test expectations were wrong on first run (line numbers,
   operation counts, and `except` being a valid identifier that the boundary
   name check correctly accepts); the tests were corrected, not the code.

## Known limitations

See `docs/limitations.md`. Headline: only MAGIC001, EXC001-EXC003,
SUPP001/SUPP002 produce findings; exception identity resolution is static and
best effort (star imports, runtime rebinding, class hierarchies are not
followed; unresolved names fail closed); the JavaScript guard convention is a
proof obligation, not a type proof; rejection handlers passed by reference are
opaque; EXC002 does not classify handlers that return variables; Python syntax
coverage equals the host interpreter; UTF-8 only; JS bare-`\r` line breaks may
shift line numbers; `.gitignore` is not consulted; SARIF, baselines, diff mode,
Git features, and skills are not built.

## Next tasks

- **Milestone C (exceptions)**: `EXC001`-`EXC003` for Python (`ast.Try`,
  `ast.TryStar`, handler type resolution via import/symbol table with
  confidence) and JavaScript (`catch` clauses, `.catch()` handlers), boundary
  matching against `rules.exceptions.boundaries`, broad-try detection. The
  repository's own `.shockharness.toml` already declares its boundaries so the
  self-gate will exercise the rule immediately.
- Decide `.gitignore` handling (spec: only if configured) and `-0` policy wording in docs if challenged.
- CI has not run yet (nothing pushed). The matrix is defined; first push will show Linux/Windows results.
