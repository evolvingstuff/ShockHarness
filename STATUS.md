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

## Milestone D: default and fallback rules DEF001-DEF006 — DONE (2026-10-14)

Delivered: default facts in the IR (`ir/model.py`: `DefaultFact` with family,
kind, subject, fallback text, constant-shapedness, syntactic context,
exact/approximate confidence, and a one-line explanation), Python extractor
(`ir/python_defaults.py`: parameter and keyword-only and lambda defaults,
`typing.overload` `...` excluded; dataclass fields with `default` and
`default_factory` as distinct kinds, `ClassVar` excluded; `.get`/`.setdefault`/
`.pop` with a fallback, `getattr` with three arguments, membership ternaries,
`.get(key)` implicit `None`; `or` outside Boolean tests with context tracking
through assignment/return/argument/test positions; `is None` ternaries with
propagation and plain choices excluded; `os.getenv`/`os.environ` in every
import spelling; DEF005 traces to module constants, empty constructors and
one-return helpers), JavaScript extractor (`ir/javascript_defaults.py`:
function/arrow/method/constructor parameter defaults, destructuring defaults in
parameters, declarations, for-of loops and assignment patterns, rest parameters
excluded; `||`, `||=`, `??`, `??=`, `x ? x : v`, null/undefined/`typeof`
ternaries, membership and `hasOwnProperty`/`Object.hasOwn` ternaries;
`process.env` in member, subscript, destructuring and operator forms; DEF005
traces including `const` arrow helpers with expression bodies),
`rules/defaults.py` (mode to severity: forbid -> error, review -> review,
allow -> off; implicit shapes always review unless allowed; DEF005 always
error), three new configuration keys (`dataclass_fields`, `nullish_fallbacks`,
`configuration_fallbacks`, all `forbid`) in `schema.py`, `defaults.toml`,
`.shockharness.toml` and `docs/configuration.md`, loosened modes reported in
`config.deviations`, registry metadata for the six rules, 13 golden fixtures
(expectations regenerated and reviewed row by row; every pre-existing row is
unchanged except the eleven `EXC002` `return_fallback` rows that became
`DEF005`), 25 unit tests in `tests/unit/test_defaults.py`, and documentation.

Decisions recorded here (not in the specification):

* **DEF005 replaces EXC002 for `return_fallback`.** Both rules describe one
  handler; counting it twice would double a gate failure. While DEF005 is
  active, EXC002 skips `return_fallback` and DEF005 reports it with the EXC002
  classification named in the message. Disabling DEF005 (override or
  `rules.defaults.enabled = false`) restores the EXC002 finding, so nothing is
  lost under any configuration. Tested both ways.
* **Dataclass field defaults are forbidden** (`dataclass_fields = "forbid"`):
  a field default is a parameter default on the generated `__init__`.
  `default_factory` is recorded as its own kind so reports can tell them apart.
  Configurable independently of `function_parameters`.
* **Destructuring defaults** split by position: in parameters they are DEF001,
  in declarations/loops/assignments DEF002, and from `process.env` DEF006.
  `??` splits on its left operand: a property or lookup is DEF002, a plain
  identifier DEF004. Environment reads always win (DEF006 claims the `or`,
  `??`, ternary and implicit-`None` shapes so a file is not told twice).
* **Boolean logic is not a fallback.** An `or`/`||` with any operand that is a
  comparison, `and`/`&&`, `not`/`!`, a Boolean constant, or (Python) an
  `isinstance`-style builtin call is skipped. Boolean *variables* cannot be
  told from values and remain approximate review findings.
* **Implicit `.get(key)`** is reported (review) when the receiver is a known
  mapping, or when the receiver is unknown and the key is a string literal;
  `client.get(url)` is not reported because nothing says it is a lookup.
  A result that is awaited or compared with `None` in the same expression is
  not reported either. A check on the following statement is not seen.
* **DEF005 traces, never guesses.** Only module-level bindings to
  constant-shaped values and module-level one-return helpers are followed.
  Imported names and `UPPER_CASE` names the module does not bind are not
  DEF005 findings (see dogfooding below).
* **Confidence**: `exact` when the fallback is constant-shaped (literal,
  container of literals, `UPPER_CASE` name/attribute, empty constructor) and
  the shape is unambiguous; `approximate` when the receiver type is unknown or
  the right operand of `or` is not a constant. Approximate findings keep the
  configured severity: under `forbid` they fail the gate, as EXC001's
  `unresolved` identities do.
* **Statement-level defaults** (`if x is None: x = v`) are out of scope by
  design and documented as such; the rules target value-substituting
  expressions.

### Dogfooding: what the rules found in the tool

The first self-scan reported 38 findings. Two groups were rule imprecision,
fixed in the rules; the rest were real and fixed in the code. No policy was
loosened: `.shockharness.toml` gained only the three new keys at `forbid`.

Rule precision (fixed in the rule, recorded here because it changed detection):

1. `DEF003` flagged `return name in LOGGING_EXACT or LOGGING_CALL.match(name)
   is not None` and four similar Boolean chains. An `or` whose operands are
   comparisons is logic, not substitution. Boolean operands now exclude the
   `or` (both languages).
2. `DEF005` flagged the CLI's process boundary (`except ShockHarnessError:
   ... return EXIT_INVALID_CONFIG`) through a naming-convention heuristic:
   "an `UPPER_CASE` name the module does not bind is probably a constant".
   An exit code returned from the sanctioned process boundary is not a
   success-shaped default, and a name's casing is not a static trace. The
   heuristic was removed; DEF005 now traces only module-bound constants and
   helpers. Imported defaults are a documented limitation.

Code (fixed in the code, behaviour unchanged unless stated):

3. `DEF002`: three `dict.setdefault(key, accumulator)` calls (`report.py` x2,
   `suppressions.py`) became explicit `if key not in d: d[key] = ...`.
4. `DEF002`: three `m[k] if k in m else v` ternaries in `tests/conftest.py`
   and `tests/unit/test_gate_and_report.py` became explicit branches.
5. `DEF004`: nineteen `x if x is not None else v` expressions. Thirteen were on
   tree-sitter/`ast` fields that the grammar always populates (`name` of a
   named scope, `constructor` of `new`, `function` of a call, `body` of
   `try`/`catch`, `object`/`property` of a member expression, `operator` of a
   binary expression, `end_lineno`/`end_col_offset` of parsed nodes); these
   now assert the invariant, so an unexpected tree fails visibly (exit 3)
   instead of being papered over. Six were genuinely optional values (import
   `as` names, `from . import`, `get_source_segment` returning `None`, the
   report's missing discovery step, my own fact texts) and became explicit
   branches. One changed behaviour: a Python `SyntaxError` with a line but no
   column used to get column 1; it now gets no span (CPython always supplies
   both, so no test moved).
6. `MAGIC001`: my own `range(n - 1, -1, -1)` in the new JavaScript walker was
   caught by the gate and became `reversed(list(enumerate(...)))`; the
   lookup arities `2`/`3` moved to `constants.py`.

Acceptance criterion from the spec (Milestone D): representative Python and
JavaScript examples produce exact diagnostics for all six rules (golden
fixtures `def_*.py` / `def_*.js`, 164 reviewed rows, and the smoke corpus
below), and every finding has `safe_autofix = false`
(`tests/unit/test_defaults.py::test_every_fixture_finding_is_a_suggestion`).

### Evidence (all run 2026-10-14 on macOS arm64)

```text
$ ruff check src tests && ruff format --check src tests
All checks passed!
56 files already formatted

$ pytest -q                      # CPython 3.14.7
363 passed in 2.18s
$ pytest -q                      # CPython 3.13.1
363 passed in 2.02s
$ pytest -q                      # CPython 3.12.8
363 passed in 1.97s
$ pytest -q                      # CPython 3.11.11
363 passed in 2.46s

$ shockharness scan src tests    # self-compliance, all four interpreters
gate: PASS (exit 0)

$ shockharness config validate
shockharness: configuration is valid (dedicated: .../.shockharness.toml)
  ... (13 policy deviations: 11 boundaries, 2 overrides; no rules.defaults deviation)

$ python -m build
Successfully built shockharness-0.1.0.tar.gz and shockharness-0.1.0-py3-none-any.whl
```

Sample text output on a smoke corpus (`src/app/settings.py`: a dataclass with
defaults, a function with defaults, `os.getenv` with a fallback, `.get` with
and without a fallback, `or`, an `is None` ternary, and a handler returning
`None`; `src/app/client.js`: `process.env` in two spellings, destructured
parameter defaults, `??` on an identifier and on an optional chain, `||`, and
a handler returning `null`), bundled strict defaults:

```text
src/app/client.js:1:14: DEF006 error: environment variable HOST falls back to "localhost"; '||' replaces an unset or empty environment variable HOST with a fallback  [const host = process.env.HOST || "localhost";]
src/app/client.js:2:16: DEF006 error: destructuring default for 'PORT' in a destructuring of process.env: "3000"  [const { PORT = "3000" } = process.env;]
src/app/client.js:4:42: DEF001 error: destructuring default for 'retries' in parameters: 3  [export function connect(url, { retries = 3, timeout } = {}) {]
src/app/client.js:4:42: MAGIC001 error: Numeric literal 3 has no permitted justification in executable code  [export function connect(url, { retries = 3, timeout } = {}) {]
src/app/client.js:4:57: DEF001 error: parameter '{ retries = 3, timeout }' of connect has a default value: {}  [export function connect(url, { retries = 3, timeout } = {}) {]
src/app/client.js:5:17: DEF004 error: timeout falls back to 30 when null or undefined; '??' substitutes a fallback when the left operand is null or undefined  [const limit = timeout ?? 30;]
src/app/client.js:5:28: MAGIC001 error: Numeric literal 30 has no permitted justification in executable code  [const limit = timeout ?? 30;]
src/app/client.js:6:17: DEF003 review: url.label falls back to "default" when falsy; '||' substitutes a constant for every falsy value of the left operand (undefined, null, 0, '', NaN, false alike)  [const label = url.label || "default";]
src/app/client.js:7:16: DEF002 error: options?.mode falls back to "fast"; '??' substitutes a fallback when the property or lookup result is null or undefined  [const mode = options?.mode ?? "fast";]
src/app/client.js:10:5: DEF005 error: catch clause converts the exception into a fallback value: return null; (EXC002 classification return_fallback; the handler is reported once, here)  [} catch (err) {]
src/app/client.js:10:5: EXC001 error: catch clause is forbidden: untyped catch binds every error; a JavaScript catch passes only inside an approved boundary whose error class the handler checks with instanceof and otherwise rethrows  [} catch (err) {]
src/app/settings.py:8:17: DEF001 error: dataclass field 'port' of Settings has a default value: 5432  [port: int = 5432]
src/app/settings.py:8:17: MAGIC001 error: Numeric literal 5432 has no permitted justification in executable code  [port: int = 5432]
src/app/settings.py:9:40: DEF001 error: dataclass field 'tags' of Settings has a default_factory: list  [tags: list = field(default_factory=list)]
src/app/settings.py:12:24: DEF001 error: parameter 'port' of connect() has a default value: 5432  [def connect(host, port=5432, timeout=None):]
src/app/settings.py:12:24: MAGIC001 error: Numeric literal 5432 has no permitted justification in executable code  [def connect(host, port=5432, timeout=None):]
src/app/settings.py:12:38: DEF001 error: parameter 'timeout' of connect() has a default value: None  [def connect(host, port=5432, timeout=None):]
src/app/settings.py:13:15: DEF006 error: environment variable "RETRIES" falls back to "3"; os.getenv(...) substitutes a fallback when environment variable "RETRIES" is unset (getenv)  [retries = os.getenv("RETRIES", "3")]
src/app/settings.py:15:15: DEF002 error: options["verbose"] falls back to False when the key is missing; .get(key, fallback) substitutes the fallback for a missing key; the receiver's type is not established, so this is approximate  [verbose = options.get("verbose", False)]
src/app/settings.py:16:13: DEF003 review: options.get("label") falls back to "default" when falsy; 'or' substitutes a constant for every falsy value of the left operand (None, 0, '', empty containers alike)  [label = options.get("label") or "default"]
src/app/settings.py:17:13: DEF004 error: timeout falls back to 30 when None; conditional expression on 'is None' substitutes a value when the subject is missing  [limit = timeout if timeout is not None else 30]
src/app/settings.py:17:49: MAGIC001 error: Numeric literal 30 has no permitted justification in executable code  [limit = timeout if timeout is not None else 30]
src/app/settings.py:20:5: DEF005 error: except handler converts the exception into a fallback value: return None (EXC002 classification return_fallback; the handler is reported once, here)  [except OSError:]
src/app/settings.py:20:5: EXC001 error: except handler of 'OSError' is forbidden: catch of 'OSError' is not approved by any boundary for this file  [except OSError:]

shockharness 0.1.0: 2 file(s), 2 analyzed, 0 failed; 24 finding(s), 0 suppressed
  by severity: error=22, review=2
  rules applied: MAGIC001, EXC001, EXC002, EXC003, DEF001, DEF002, DEF003, DEF004, DEF005, DEF006, SUPP001, SUPP002
  rules not implemented (not analyzed): MAGIC002, CPLX001, CPLX002, CPLX003, CPLX004, CPLX005
  config note: no project configuration found; bundled strict defaults apply
  analysis status: complete
gate: FAIL (exit 1)
  22 hard violation(s) and gates.new_hard_violations = "fail"
```

### Failures observed during development (and what was done)

1. **Self-gate: 38 findings on the tool** (listed above). Two rule-precision
   fixes, 26 code fixes, no policy change.
2. **The gate caught new code twice more** while I was writing it: a `-1` in
   my JavaScript walker (MAGIC001) and an `"a loop" if right is None else ...`
   in the for-of extractor I added after the first clean scan (DEF004; the
   grammar always supplies the iterable, so it is asserted). The gate works on
   its author, again.
3. **`session.get(url)` noise.** The first implicit-`None` design reported every
   one-argument `.get` call as a review finding, which put a `DEF002` row on
   every HTTP-client line in the Milestone C tests and acceptance corpus.
   Narrowed as described under decisions; the exception tests now filter to
   their own family so a future default rule cannot silently change them.
4. **Four hand-counted columns and one confidence** in the new unit tests were
   wrong on first run (`process.env.FALLBACK` is constant-shaped by the
   `UPPER_CASE` rule, so `exact`); the tests were corrected, not the code.
5. **Golden review** surfaced one gap: `for (const { id, label = "none" } of
   rows)` produced nothing. tree-sitter puts the pattern directly on the
   `for_in_statement`, not in a declarator; handled, fixture row added. Also
   added the `({ x = v } = o)` assignment-pattern form while there.

## Known limitations

See `docs/limitations.md`. Headline: only MAGIC001, EXC001-EXC003,
DEF001-DEF006, SUPP001/SUPP002 produce findings; exception identity resolution
is static and best effort (star imports, runtime rebinding, class hierarchies
are not followed; unresolved names fail closed); the JavaScript guard convention
is a proof obligation, not a type proof; rejection handlers passed by reference
are opaque; the default rules are syntactic (statement-level defaults are not
inspected, mapping receivers are known by name only, Boolean variables look
like values, DEF005 traces one step within the module, bare `process.env.X`
reads are not findings); Python syntax coverage equals the host interpreter;
UTF-8 only; JS bare-`\r` line breaks may shift line numbers; `.gitignore` is
not consulted; SARIF, baselines, diff mode, Git features, and skills are not
built.

## Next tasks

- **Milestone E (complexity + graph)**: `CPLX001`-`CPLX005` per-function
  cyclomatic/cognitive/nesting, approximate NPath, call graph with
  unresolved-edge reports; separate advisory family, never averaged into the
  gate.
- Consider a flow-sensitive refinement for the implicit-`None` review finding
  (a `.get(k)` whose result is checked against `None` on the next statement),
  and scope-aware mapping knowledge, if the review noise proves costly.
- Decide `.gitignore` handling (spec: only if configured) and `-0` policy wording in docs if challenged.
- Milestone F part 2 (profiles, `check`, release automation) is recorded below; the first `v*` tag exercises `publish.yml` for real.
- CI verified 2026-10-14 on the first push (run 1 at https://github.com/evolvingstuff/ShockHarness/actions/runs/38646310534): all 13 jobs green, ubuntu/macos/windows x Python 3.11-3.14 plus the wheel build job.

## Milestone F part 1: baselines, diff gate, SARIF, git history — DONE (2026-10-14)

Scope per section 20 decision 6 (F before E), split in two sessions. This is
the analysis half. The distribution half (profiles, `check` rename, `version`
subcommand, release workflows, consumer examples, `effective_profile`) is a
separate follow-on session and is **not** in this commit.

Delivered: finding fingerprints (`gating/baseline.py`: rule ID, root-relative
path, enclosing scope or `null`, whitespace-free evidence, occurrence index;
assigned in `analysis.py` once a file's findings are sorted, so
`analyze_source` results carry them too), baseline files
(`schemas/baseline-v1.schema.json`; `baseline create PATH... --output FILE
[--force]`), `--baseline FILE` on `scan` and `gate PATH...` with the three
`gates.legacy` modes, stale-entry reporting, `apply_baseline` /
`evaluate_gate` / `with_history` in `api.py`, revision diff (`gating/diff.py`:
local `git rev-parse` + `git archive` into a temporary directory per revision,
full-tree analysis, new / fixed / unchanged by fingerprint;
`schemas/diff-v1.schema.json`), `diff` (reporting only) and `gate --base
--head` (exit 1 only on new hard violations) commands, SARIF 2.1.0 output
(`output/sarif.py`) for `scan`, `diff`, `gate`, git history metrics
(`history/git.py` subprocess wrapper, `history/hotspots.py` churn,
`history/cochange.py` pairs) under `metrics.history` with `history.enabled`,
`history.horizon_days`, `history.min_support` keys in `schema.py`,
`defaults.toml` and the docs, six new declared boundaries in
`.shockharness.toml`, 46 new tests, and documentation (`docs/configuration.md`
baselines / diff / history sections, `docs/limitations.md`,
`docs/architecture.md`, README, CHANGELOG, report schema).

Decisions recorded here (not in the specification or the brief):

* **Fingerprint material** is a JSON array `[fingerprint_version, rule_id,
  path, scope-or-null, evidence-without-whitespace, occurrence]` hashed with
  SHA-256. The message is deliberately *not* included so wording changes
  between tool versions do not invalidate baselines; the rule ID and the
  evidence identify the construct. A scope-less finding (SUPP001/SUPP002) hashes
  `null`, not a substitute string: the first draft used `"" if scope is None`
  and the self-gate flagged it as DEF004, which was the right call.
* **Occurrence index** is per file and per identity, in source order. Inserting
  an identical construct *before* existing ones renumbers them; documented as
  a limitation. Within one report fingerprints are unique (asserted in
  `diff_revisions`).
* **`baseline` vs `ignore`.** The brief describes both as "listed, not
  gating". The implemented difference: `baseline` keeps matched findings in
  `hard_violations` / `findings_by_severity` and adds `new_hard_violations`,
  which drives the verdict, so legacy debt stays visible in the counts;
  `ignore` removes matched findings from every count except `gate.baselined`.
  Markers: `baseline = "matched"` / `"ignored"`. `fail` records the baseline
  (`gate.baseline.applied = false`) and applies nothing.
* **Stale entries** are a gate reason plus `gate.baseline.stale` (full
  entries), not a finding: a finding needs a rule ID and a span, and a stale
  entry has neither. They never change the verdict.
* **Config digest mismatch** is noted (`config_digest_matches = false` and a
  note), not refused: fingerprints are policy-independent, and refusing would
  make every policy tightening require a new baseline before the first run.
* **What goes into a baseline:** every unsuppressed finding of any severity.
  Suppressed findings already do not gate and are left out so that removing a
  suppression surfaces the finding again.
* **`baseline create` refuses** an existing file without `--force` and refuses
  to write when analysis did not complete (gate status `error`): a baseline
  from a partial analysis would silently legitimise whatever the failed files
  contain.
* **`gate` has two forms**: `gate --base REF --head REF` (the spec's) and
  `gate PATH... [--baseline FILE]` (a working-tree gate with the same verdict
  as `scan`; it exists because the brief says `--baseline` applies to `gate`).
  `--baseline` with `--base/--head` is a usage error: the base revision is the
  legacy source of a revision gate, and two legacy sources would need two
  `gate.baseline` records.
* **Diff export** uses `git archive --format=tar` read through `tarfile`
  (with `data_filter` where the host Python has it), not `git worktree add`,
  so the user's `.git` is never modified. `git archive` runs at the toplevel
  so a subdirectory `--root` works (`git rev-parse --show-prefix`); it honours
  `export-ignore`, which is documented.
* **Head parse failure** under `parse_errors = "fail"` makes `diff` exit 3,
  not 0: the tool could not analyze, which is a tool failure in the brief's
  sense. Base parse failures are recorded only; such a file's head findings are
  all `new`.
* **Both revisions use the working tree's configuration** (one digest). The
  committed configuration at either revision is not consulted, so the diff
  compares code, not policy.
* **History horizon** is anchored on the head commit's committer date
  (`until`), not the wall clock, so `metrics.history` for a commit is
  reproducible (tested by running it twice). `--since` bounds the git walk; the
  cutoff is re-applied in Python on committer dates so the semantics are the
  tool's, not git's.
* **Churn dates** are author dates (`first_change`, `last_change`); authors are
  counted as distinct author e-mails and never written to the report.
  `--no-renames`: a rename restarts a file's history. Merge commits list no
  files and count for nothing. A commit touching more than fifty analyzed
  files (`COCHANGE_MAX_FILES_PER_COMMIT`) is excluded from pairing and counted.
* **`analyze_paths` stays pure** (no git) and reports `metrics.history.status
  = "not_collected"` with the reason; the CLI attaches history through
  `with_history`. Library consumers opt in.
* **Boundaries beyond the brief.** The brief named git as the only new
  try/except site. Reading a user-supplied baseline file is the same class of
  boundary as reading a configuration file, so `gating/baseline.py` declares
  `OSError`, `UnicodeDecodeError`, `json.JSONDecodeError`, each converting to a
  `UsageError` (exit 2). The git wrapper declares
  `subprocess.CalledProcessError`, `OSError`, `UnicodeDecodeError`; each
  handler returns a `GitResult` error (data), never a value that looks like
  success. Six boundaries were added and none was widened; the existing
  `cli.py` `OSError` reason now also names the baseline file.
* **SARIF choices**: `uriBaseId = "%SRCROOT%"` with no `originalUriBaseIds`
  so the document carries no machine-specific absolute path; `baselineState`
  only when a baseline or base revision was applied; fixed diff findings as
  `absent` results at their base location; `columnKind =
  "unicodeCodePoints"` (our columns are character columns); suppressed
  findings keep their level and carry an `inSource` suppression; every
  registered rule (implemented or not) is in `rules` with
  `properties.implemented`.
* **Report schema** stays `schema_version` 1; every addition is a new key
  (`findings[].fingerprint`, `findings[].baseline`, `gate.baselined`,
  `gate.new_hard_violations`, `gate.baseline`, `execution_summary.baselined`,
  `metrics.history`). `policy_profile` is untouched; the rename to
  `effective_profile` belongs to part 2 (section 20 decision 13).

Acceptance (brief's "done when"), verified by
`tests/cli/test_cli.py::test_baseline_create_then_scan_with_baseline`
(`baseline create` then `scan --baseline` passes with the legacy findings
listed as `baseline: matched`, fails on one new finding),
`tests/cli/test_cli.py::test_gate_between_two_commits` (two-commit repository
with a dirty working tree: `gate --base c1 --head HEAD` exits 1 on the one new
violation and reports both commits, the digest and the tool version; `gate
--base c1 --head c3` with only fixed violations exits 0; `diff` exits 0),
`tests/unit/test_sarif.py` (structural check against the required SARIF 2.1.0
keys, level mapping, fingerprints, suppressions, baseline states),
`tests/unit/test_history.py` (temporary repository churn and co-change, and
`unavailable` for a non-repository directory, an absent git binary, and an
unknown revision).

### Dogfooding: what the gate found in the new code

Three real findings on the first self-scan, all fixed in code; no policy was
loosened beyond declaring the six boundaries the brief asked for (plus the
three baseline-file ones recorded above):

1. `MAGIC001`: `key[2]` to pull the scope out of the identity tuple. Replaced
   by tuple unpacking.
2. `DEF004`: `NO_SCOPE if finding.scope is None else finding.scope` in the
   fingerprint. Replaced by JSON-encoding the identity so `null` is its own
   value; `BaselineEntry.scope` became `str | None`.
3. `EXC001` x6 before the boundaries were declared: exactly the six sites the
   brief anticipated, each wrapping one call (`subprocess.run`, `bytes.decode`,
   `path.read_bytes`, `json.loads`). `EXC003` had nothing to say.

Ruff additionally wanted a context manager around `tarfile.open` and three
line wraps.

### Evidence (all run 2026-10-14 on macOS arm64)

```text
$ ruff check src tests && ruff format --check src tests
All checks passed!
67 files already formatted

$ pytest -q                      # CPython 3.14.7
409 passed in 4.50s
$ pytest -q                      # CPython 3.13.1
409 passed in 4.08s
$ pytest -q                      # CPython 3.12.8
409 passed in 4.09s
$ pytest -q                      # CPython 3.11.11
409 passed in 4.65s

$ shockharness scan src tests    # self-compliance, all four interpreters
  history: 8 commit(s) in 90 day(s) before 2026-10-14T15:18:14-07:00 (file granularity); 66 co-change pair(s) with support >= 3; hotspots: not computed: the hotspot score (log1p(churn) * normalized complexity) needs the complexity metrics of Milestone E, which are not implemented
  analysis status: complete
gate: PASS (exit 0)

$ shockharness config validate
shockharness: configuration is valid (dedicated: .../.shockharness.toml)
  ... (19 policy deviations: 17 boundaries, 2 overrides)

$ shockharness scan src tests --format sarif | jq '.runs[0] | {rules: (.tool.driver.rules|length), results: (.results|length)}'
{"rules": 18, "results": 0}

$ python -m build
Successfully built shockharness-0.1.0a1.tar.gz and shockharness-0.1.0a1-py3-none-any.whl
```

Smoke corpus: a two-commit repository (`c1`: `x = 2` and `return 3` in
`src/a.py`, `const y = 4` in `src/b.js`; `c2`: two lines inserted above `x = 2`,
`return 3` -> `return 5`, `b.js` deleted, `src/c.js` with `const z = 7` added)
plus an uncommitted `src/dirty.py` with `dirty = 9`:

```text
$ shockharness baseline create src --output base.json
shockharness: wrote base.json with 4 fingerprint(s) from 3 file(s) (config digest 776d6504...); review it before committing it

$ shockharness scan src --baseline base.json
src/a.py:3:5: MAGIC001 error: Numeric literal 2 has no permitted justification in executable code  [x = 2]  (baseline: matched)
src/a.py:5:12: MAGIC001 error: Numeric literal 5 has no permitted justification in executable code  [return 5]  (baseline: matched)
src/c.js:1:11: MAGIC001 error: Numeric literal 7 has no permitted justification in executable code  [const z = 7;]  (baseline: matched)
src/dirty.py:1:9: MAGIC001 error: Numeric literal 9 has no permitted justification in executable code  [dirty = 9]  (baseline: matched)
...
gate: PASS (exit 0)
  4 legacy finding(s) matched the baseline (4 hard) and do not fail the gate (gates.legacy = "baseline"); they are still counted

$ shockharness gate --base HEAD~1 --head HEAD
fixed: src/a.py:3:12: MAGIC001 error: Numeric literal 3 has no permitted justification in executable code  [return 3]
new: src/a.py:5:12: MAGIC001 error: Numeric literal 5 has no permitted justification in executable code  [return 5]
fixed: src/b.js:1:11: MAGIC001 error: Numeric literal 4 has no permitted justification in executable code  [const y = 4;]
new: src/c.js:1:11: MAGIC001 error: Numeric literal 7 has no permitted justification in executable code  [const z = 7;]

shockharness 0.1.0a1 diff: base HEAD~1 (a56894b07dc4) -> head HEAD (0a06daf5a821); 2 new, 2 fixed, 1 unchanged finding(s)
  hard violations: 2 new, 2 fixed, 1 unchanged
  base: 2 analyzed, 0 failed, status complete; head: 2 analyzed, 0 failed, status complete
  uncommitted changes are not part of HEAD; only committed trees are compared
  config: bundled defaults.toml (digest 776d6504309fe651)
  history: 2 commit(s) in 90 day(s) before 2026-10-14T15:36:41-07:00 (file granularity); 0 co-change pair(s) with support >= 3; hotspots: not computed: ...
  analysis status: complete
gate: FAIL (exit 1)
  2 new hard violation(s) and gates.new_hard_violations = "fail"
  1 legacy finding(s) matched the base revision a56894b07dc4 (1 hard) and do not fail the gate (gates.legacy = "baseline"); they are still counted
```

The moved `x = 2` (line 1 at `c1`, line 3 at `c2`) is `unchanged`; `dirty.py`
takes no part in the diff. `diff` with the same arguments prints the same
report and exits 0.

### Failures observed during development (and what was done)

1. The three self-gate findings above (fixed in code).
2. Two test expectations were wrong on first run: `c1` has three findings, not
   two, and the test's own uncommitted `dirty.py` was swept into a later
   commit by `git add -A`, making the "fixed only" gate fail. Both corrected
   in the tests, not the code.
3. Two Milestone A tests asserted the old refusals (`--format sarif` exits 2,
   `evaluate_gate` raises `UnsupportedFeatureError`); replaced by tests of the
   new behaviour.

### Limitations and next tasks

* Part 2 of Milestone F (separate session): profiles, `check` with `scan`
  alias, `version` subcommand, `shockharness.toml` filename,
  `effective_profile`, release and reusable workflows, Dependabot, consumer
  examples.
* Hotspot score waits for Milestone E complexity metrics
  (`metrics.history.hotspots = null` with the reason until then).
* Fingerprints are file-scoped: a file rename makes every finding in it new.
  Following renames through `git log --follow` or content hashing is a
  possible later refinement.
* `diff` analyzes both whole trees; on large repositories that is two full
  analyses per run. Cross-file rules (none yet) are the reason.

## Milestone F part 2: profiles, check command, release automation — DONE (2026-10-14)

The distribution half of Milestone F, per specification section 20 decisions
1, 3, 4, 7, 9, 10, 11, 13 and the brief's sections 2-5 and 8. One commit,
not pushed, not tagged, version left at `0.1.0a1` (the bump to `0.1.0` is the
maintainer's call).

Delivered:

* **CLI (decision 1).** `check` is the canonical analysis command; `scan` is
  the same parser built by the same helper (`_add_check_arguments`) and is
  hidden from `--help` by being added without a `help` string (argparse lists
  only subcommands that have one; `help=argparse.SUPPRESS` prints the literal
  `==SUPPRESS==` on CPython 3.14, which is why it is not used). `version`
  prints exactly what `--version` prints. Every doc, README example, CI step
  and the pre-commit entry say `check`.
* **Config filename (decision 3).** `shockharness.toml` joins
  `.shockharness.toml` at the dedicated tier (`DEDICATED_FILENAMES`); both
  present is a `ConfigError` whose origin names both paths (exit 2). Either
  file shadows a `pyproject.toml` table with the existing note.
* **Profiles (decision 4).** Three overlays as package data
  (`src/shockharness/profiles/{strict,recommended,minimal}.toml`, a package so
  `importlib.resources` finds them in the wheel). `strict` is an empty overlay:
  the bundled defaults *are* strict, so nothing can drift between the two.
  `recommended` sets `rules.defaults.nullish_fallbacks = "review"` (DEF003 is
  already `review` in strict). `minimal` sets `parse_errors = "warn"`,
  `complexity.enabled = false`, and `severity = "review"` on the three rule
  sections. Layering in `load_config_with_overrides`: bundled defaults <
  overlay (origin `profile:<name>`) < source (origin tier) < CLI overrides
  (origin `cli_override`). The profile name is resolved first (`--profile`,
  else the source's `profile`, else `strict`), so the repository's own keys
  always sit above whichever profile is in force. Overlays are validated with
  the user schema and may not contain `profile`.
* **Per-section severity.** `rules.magic_numbers.severity`,
  `rules.exceptions.severity`, `rules.defaults.severity` in `{"error",
  "review"}` (`rules/severity.py`, applied in the three rule runners; for
  `rules.defaults` it also caps DEF005, which has no mode). `SUPP001` is not
  in any section and still fails under `minimal`. Each cap is a deviation
  line; so is `complexity.enabled = false`, which was previously silent
  because `complexity` is not under `rules`.
* **CLI overrides.** `--profile NAME` and `--parse-errors fail|warn` on every
  command that loads configuration. Both add a config note naming the flag
  and the replaced value, enter `origins` as `cli_override`, and change the
  digest. `docs/configuration.md` says why these two and no others.
* **`effective_profile` (decision 13).** Renamed from `policy_profile` in
  `report.py`, `gating/diff.py`, both JSON schemas, SARIF run properties
  (which also gained `config_deviations` so the deviation line reaches every
  format) and the tests. `schema_version` stays `"1"`; CHANGELOG says why.
  Specification section 10 still lists `policy_profile` in its field list;
  per the brief for this session the spec was not edited (no deviation from
  section 20 was needed). Maintainer: a one-word edit in section 10 would
  align it with decision 13.
* **Release automation (decision 9).** `.github/workflows/publish.yml`: on
  `v*` tags, `uses: ./.github/workflows/ci.yml` (ci.yml gained
  `workflow_call`), then build, tag-equals-`version.py` check, artifact
  filename check, clean-venv install with `shockharness version`, then
  `pypa/gh-action-pypi-publish@release/v1` in environment `pypi` with
  `id-token: write` and no token. `docs/releasing.md` holds the one-time PyPI
  publisher values (project `shockharness`, owner `evolvingstuff`, repository
  `ShockHarness`, workflow `publish.yml`, environment `pypi`) and the
  per-release steps.
* **Reusable workflow.** `.github/workflows/check.yml` (`workflow_call`;
  inputs `shockharness-version` required, `config`, `base`, `python-version`
  default `"3.12"`); inputs reach the shell through `env:` so no expression
  is interpolated into a command; `fetch-depth: 0` so `gate --base` can see
  the base; SARIF uploaded with `github/codeql-action/upload-sarif@v3` under
  `if: !cancelled() && hashFiles(...)` so a failing gate still uploads and a
  config error (no file) does not; permissions `contents: read`,
  `security-events: write` only.
* **Dependabot (decision 10).** `.github/dependabot.yml` (github-actions +
  pip, weekly). `docs/integration.md` gives consumers the snippet and states
  where the pin may live (pyproject, requirements file, workflow input) and
  never in a shell string; it also states plainly that Dependabot does not
  rewrite the `shockharness-version` input.
* **Examples (decision 11).** `examples/python` (hatchling package
  `example_service`, `shockharness==0.1.0a1` under optional-dependencies
  `dev`, `.shockharness.toml`, workflow calling `check.yml@v0.1.0`, four
  source files, one suppressed `404` with an RFC citation, tests exempt by
  override) and `examples/js` (`package.json` with `npm run policy`, analyzer
  via `uv tool install`/`pipx`, never an npm dependency, `.shockharness.toml`,
  workflow, three ES modules, one suppressed `404`, `node --test` tests).
  `scripts/consumer_upgrade_check.py` (stdlib only, passes the self-gate with
  no override: its only literals are 0 and 1) copies each example, `git init`
  + commit, creates a venv, installs the wheel from `dist/` by path (with
  `--no-index --find-links WHEELHOUSE` when given, which CI does), asserts
  `shockharness version` equals the wheel's version, that the example's pins
  agree, `check .` exit 0, then commits one injected `= 25` and asserts
  `check .` exit 1 and `gate --base HEAD~1 --head HEAD` exit 1. CI runs it in
  a new ubuntu-only `consumer-examples` job whose only network access is
  `pip download` of the wheel's dependencies.
* **Tests.** 34 new (443 total): `tests/unit/test_profiles.py` (effective
  values, severities, deviation lines, origins, precedence, CLI overrides,
  init text), CLI tests (`check` == `scan` byte for byte, `scan` absent from
  `--help`, `version`, `--profile`, `--parse-errors`, both filenames and the
  both-present error, `init --profile`), config tests, `tests/unit/
  test_workflows.py` (key lines of every workflow, dependabot, hook, example
  workflows, and that README/docs no longer say `shockharness scan`),
  `tests/unit/test_consumer_script.py` (the script's helpers, and an
  in-process twin of its check steps on both examples).

Decisions recorded here (not in the specification or the brief):

* **Profile below strict in `init`.** `init --profile recommended|minimal`
  writes only `profile = "<name>"` plus comments. Writing the full defaults
  with the profile line changed would put every strict value in the
  repository layer and silently override the profile.
* **`--profile` replaces the layer, not the file.** A repository configured
  for `minimal` run with `--profile strict` keeps its includes, boundaries,
  overrides and any `severity` keys it set explicitly (those are repository
  policy and win over the profile); only the profile's own keys change. The
  note in the report says so.
* **Example workflow refs.** Both example workflows pin `check.yml@v0.1.0`
  with a comment showing the SHA form. No tag exists yet, so the ref is a
  forward reference until the first release; the alternative (`@main`) is
  exactly what the docs tell consumers not to do. `docs/limitations.md`
  records this.
* **Two pins in the Python example.** The analyzer version appears in
  `pyproject.toml` (Dependabot-visible) and as the workflow input (not
  Dependabot-visible). The upgrade script asserts they agree so drift fails
  CI rather than passing unnoticed.
* **SARIF `config_deviations`.** Added so "every report" includes the
  profile deviation line; SARIF had no deviation list before.

### Dogfooding: what the gate found in the new code

Nothing in `src/`. The script's first draft had `None if x is None else
x.resolve()`, replaced by an explicit branch before the gate ran on it; the
self-gate now covers `scripts/` and passes with no new override.

### Evidence (all run 2026-10-14 on macOS arm64)

```text
$ ruff check src tests scripts && ruff format --check src tests scripts
All checks passed!
73 files already formatted

$ pytest -q                      # CPython 3.14.7
443 passed in 4.56s
$ pytest -q                      # CPython 3.13.1
443 passed in 4.46s
$ pytest -q                      # CPython 3.12.8
443 passed in 4.57s
$ pytest -q                      # CPython 3.11.11
443 passed in 5.04s

$ shockharness check src tests scripts    # self-compliance (3.11 and 3.14 shown identical)
gate: PASS (exit 0)

$ shockharness config validate
shockharness: configuration is valid (dedicated: .../.shockharness.toml; profile strict)
  ... (19 policy deviations: 17 boundaries, 2 overrides)

$ shockharness version
shockharness 0.1.0a1
$ shockharness --help | grep -c scan
0
$ shockharness scan --help | head -1
usage: shockharness scan [-h] [--root ROOT] [--config CONFIG]

$ python -m build
Successfully built shockharness-0.1.0a1.tar.gz and shockharness-0.1.0a1-py3-none-any.whl
$ unzip -l dist/shockharness-0.1.0a1-py3-none-any.whl | grep -c profiles/
4

$ python3.12 -m pip download --dest wheelhouse dist/shockharness-*.whl
$ python3.12 scripts/consumer_upgrade_check.py --dist dist --examples examples --wheelhouse wheelhouse
wheel under test: .../dist/shockharness-0.1.0a1-py3-none-any.whl
js: git init + commit: clean example committed: ok
js: install wheel: (no output): ok
js: shockharness version: shockharness 0.1.0a1 (wheel 0.1.0a1): ok
js: analyzer pins agree: pins: 0.1.0a1: ok
js: check . (clean): exit 0: ok
js: check . (after violation in src/pages.js): exit 1;   1 new hard violation(s) and gates.new_hard_violations = "fail": ok
js: gate --base HEAD~1 --head HEAD: exit 1;   0 legacy finding(s) matched the base revision e2b6ddd57af1 (0 hard) and do not fail the gate (gates.legacy = "baseline"); they are still counted: ok
python: git init + commit: clean example committed: ok
python: install wheel: (no output): ok
python: shockharness version: shockharness 0.1.0a1 (wheel 0.1.0a1): ok
python: analyzer pins agree: pins: 0.1.0a1, 0.1.0a1: ok
python: check . (clean): exit 0: ok
python: check . (after violation in src/example_service/pages.py): exit 1;   1 new hard violation(s) and gates.new_hard_violations = "fail": ok
python: gate --base HEAD~1 --head HEAD: exit 1;   0 legacy finding(s) matched the base revision 7827b14d10cf (0 hard) and do not fail the gate (gates.legacy = "baseline"); they are still counted: ok
consumer upgrade check: 2 example(s), 14 step(s), 0 failed
```

Smoke corpus (`src/a.py`: `x = 2`, a parameter default, a `KeyError` handler
returning `None`; `src/b.js`: `const y = 3 ?? 4;`), no configuration file:

```text
$ shockharness check src                      # strict: 7 errors, gate FAIL (exit 1)
$ shockharness check src --profile recommended --format json
effective_profile = recommended; DEF004 review, everything else error; exit 1
  deviations: "profile is 'recommended', below 'strict'; ...",
              "rules.defaults.nullish_fallbacks is 'review' (strict profile: 'forbid'); DEF004 ..."
$ shockharness check src --profile minimal
src/a.py:1:5: MAGIC001 review: Numeric literal 2 has no permitted justification in executable code  [x = 2]
src/a.py:2:12: DEF001 review: parameter 'b' of f() has a default value: None  [def f(a, b=None):]
src/a.py:5:5: DEF005 review: except handler converts the exception into a fallback value: return None (...)  [except KeyError:]
src/a.py:5:5: EXC001 review: except handler of 'KeyError' is forbidden: ...  [except KeyError:]
src/b.js:1:11: DEF004 review: 3 falls back to 4 when null or undefined; ...  [const y = 3 ?? 4;]
src/b.js:1:11: MAGIC001 review: Numeric literal 3 has no permitted justification in executable code  [const y = 3 ?? 4;]
src/b.js:1:16: MAGIC001 review: Numeric literal 4 has no permitted justification in executable code  [const y = 3 ?? 4;]

shockharness 0.1.0a1: 2 file(s), 2 analyzed, 0 failed; 7 finding(s), 0 suppressed
  by severity: review=7
  ...
  config note: profile 'minimal' selected by --profile on the command line replaces profile 'strict'; the configuration file's other keys still apply on top of it
  policy deviation: profile is 'minimal', below 'strict'; the lines that follow are what it changes (see docs/configuration.md, Profiles)
  policy deviation: rules.magic_numbers.severity is 'review'; MAGIC001 findings are reported as review and never fail the gate
  policy deviation: rules.exceptions.severity is 'review'; EXC001-EXC003 findings are reported as review and never fail the gate
  policy deviation: rules.defaults.severity is 'review'; DEF001-DEF006 findings are reported as review and never fail the gate
  policy deviation: complexity is disabled
  policy deviation: parse_errors is 'warn'; syntax failures do not fail the gate
  config: bundled defaults.toml (profile minimal, digest c91d6f67462897d8)
  analysis status: complete
gate: PASS (exit 0)

$ printf '[tool.shockharness]\nprofile = "minimal"\n' > shockharness.toml
$ shockharness config effective | jq '.origins | with_entries(select(.value != "bundled"))'
{"complexity.enabled": "profile:minimal", "parse_errors": "profile:minimal", "profile": "dedicated",
 "rules.defaults.severity": "profile:minimal", "rules.exceptions.severity": "profile:minimal",
 "rules.magic_numbers.severity": "profile:minimal"}
$ shockharness config effective --profile strict --parse-errors warn | jq '.origins.profile, .origins.parse_errors, .notes'
"cli_override"  "cli_override"
["profile 'strict' selected by --profile on the command line replaces profile 'minimal'; ...",
 "parse_errors = 'warn' set by --parse-errors on the command line (configured value: 'fail')"]
$ printf '[tool.shockharness]\n' > .shockharness.toml && shockharness config validate
shockharness: error: .../.shockharness.toml and .../shockharness.toml: two dedicated configuration files exist; keep exactly one of .shockharness.toml, shockharness.toml   (exit 2)
```

### Failures observed during development (and what was done)

1. `help=argparse.SUPPRESS` on the `scan` subparser rendered as a literal
   `==SUPPRESS==` row in `--help` on CPython 3.14. Replaced by adding the
   subparser without `help`, which argparse omits from the list on 3.11-3.14
   (asserted by a test).
2. One existing schema test enumerated the known keys of
   `rules.magic_numbers`; it gained `severity`. The `profile` enum message
   test gained the two new names. Both are test updates, not code changes.
3. My own workflow test flagged the word `password:` inside a comment of
   `publish.yml` that explained there is no password. The comment was
   reworded; the assertion stays.

### Not run here

* `publish.yml` and `check.yml` have not executed on GitHub (no tag has been
  pushed and nothing is pushed from this session). Their structure is
  tested; their first real run is the first `v*` tag.
* The `consumer-examples` CI job was run locally with the same commands
  (above), not on GitHub.

### Limitations and next tasks

* Profiles are the three built-in ones; no user-defined or remote profiles.
* The example workflows reference `check.yml@v0.1.0`, which exists after the
  first tagged release.
* Specification section 10 still names `policy_profile`; one word to align
  with section 20 decision 13.
* Milestone E (complexity + graph) and Milestone G (skills) are unchanged.

## Follow-up: `--exit-zero` for advisory runs — DONE (2026-10-14)

Approved by the maintainer after the Milestone F part 2 commit; its own commit
"Add --exit-zero for advisory runs". Not pushed, not tagged, version unchanged.

Delivered: `--exit-zero` on `check` (and the hidden `scan` alias, which shares
the parser helper) and on `gate` (both the `PATH...` and the `--base/--head`
forms). `GateResult` gained an `advisory` flag (`gate.as_advisory`,
`gate.process_exit_code`, `gate.advisory_line`); `evaluate` always sets it
false and the CLI flips it after analysis, so the library API and every count,
severity and verdict are untouched. The process returns
`process_exit_code(gate)`: `EXIT_VIOLATIONS` becomes `EXIT_OK` under the flag,
`EXIT_INTERNAL_ERROR` never does, and configuration or usage errors are raised
before any gate exists, so they stay exit 2. Visible in every format:
`gate.advisory` in the JSON and diff reports (both schemas, additive,
`schema_version` still 1), the line `shockharness: advisory run
(--exit-zero): gate verdict FAIL reported as exit 0` after the gate lines in
text (the `gate: FAIL (exit 1)` line itself is unchanged), and `advisory` in
SARIF run properties; the SARIF invocation `exitCode` is the process exit code
while `properties.gate.exit_code` keeps the verdict's. The `report written to`
summary names the process exit. `diff` does not take the flag: it already
exits 0.

Not a configuration key, on purpose: the checked-in form is
`gates.new_hard_violations = "warn"`, which is reviewed, digested and reported
as a deviation. `docs/configuration.md` gained "Adopting ShockHarness on an
existing codebase" comparing baseline, `gates.new_hard_violations = "warn"`,
`profile = "minimal"` and `--exit-zero` with when to use each; the README has
the short form; `docs/integration.md` points to it.

Tests (4 new, 447 total): exit 0 with violations under the flag with the
verdict text and counts byte-identical to the strict run plus the one advisory
line; `gate.advisory` true in JSON, `advisory` true and invocation `exitCode`
0 in SARIF; the alias and both `gate` forms; `--output` summary; exit 2 for an
invalid configuration and for a missing target under the flag; exit 3 for a
strict parse failure under the flag (with the advisory line saying `ERROR
reported as exit 3`); `diff --exit-zero` is an argparse error; a unit test
that `as_advisory` changes only the `advisory` key of the gate's JSON.

### Evidence (all run 2026-10-14 on macOS arm64)

```text
$ ruff check src tests scripts && ruff format --check src tests scripts
All checks passed!
73 files already formatted

$ pytest -q        # CPython 3.14.7 / 3.13.1 / 3.12.8 / 3.11.11
447 passed in 4.77s / 4.71s / 4.69s / 5.55s

$ shockharness check src tests scripts    # self-compliance, all four interpreters
gate: PASS (exit 0)

$ shockharness check src --exit-zero      # smoke corpus: 7 hard violations
  ...
gate: FAIL (exit 1)
  7 new hard violation(s) and gates.new_hard_violations = "fail"
shockharness: advisory run (--exit-zero): gate verdict FAIL reported as exit 0
$ echo $?
0
$ shockharness check src --exit-zero --format json | jq .gate
{"status": "fail", "exit_code": 1, "hard_violations": 7, ..., "advisory": true}

$ shockharness check src --exit-zero      # with an unparseable src/bad.js added
gate: ERROR (exit 3)
  1 file(s) could not be analyzed and parse_errors = "fail"
shockharness: advisory run (--exit-zero): gate verdict ERROR reported as exit 3
(exit 3)

$ shockharness check src --exit-zero      # with include = 5 in .shockharness.toml
shockharness: error: .../.shockharness.toml: configuration is invalid:
  include: expected a list, got integer
(exit 2)
```

### Failures observed during development (and what was done)

1. The first patch of `cli.py` did not apply (a multi-line match missed the
   one-line `config` parser call) and the three new CLI tests failed with
   "unrecognized arguments: --exit-zero"; the patch was re-applied with the
   correct anchor. Nothing else changed.
