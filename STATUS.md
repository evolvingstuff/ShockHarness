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

## CI after Milestones E, F, G (2026-10-14)

The push of Milestones F, G, E and the logo (e25f195) was the first CI run for
four milestones at once and it failed on every matrix job. Two real
portability bugs, neither reproducible on the development Mac:

1. **Git date spelling.** Git 2.45+ prints UTC commit dates as `Z`; the
   history module passed git's text through, so `metrics.history` differed by
   host. Fixed in ba20ce8 by parsing and re-emitting dates canonically.
2. **CRLF checkouts.** Windows runners check out text files with CRLF; the
   skill reader returned raw bytes, breaking frontmatter checks and manifest
   hashes. Fixed in ad5dee5 (normalize on read) and `.gitattributes` (LF on
   checkout everywhere).

Run https://github.com/evolvingstuff/ShockHarness/actions/runs/38677190178
on ea0aa08: 15 of 15 jobs green (ubuntu/macos/windows x 3.11-3.14, wheel
build, consumer upgrade check, skill eval corpus).

## Release 0.1.0 (2026-10-14)

Tag `v0.1.0` at 18cf64c. Published to PyPI by `publish.yml` through trusted
publishing (run https://github.com/evolvingstuff/ShockHarness/actions/runs/38678824321):
full matrix, build, tag-equals-version check, clean-venv smoke test, then the
upload behind the `pypi` environment's required-reviewer approval. The first
attempt (run 38678116671) failed at the upload with `invalid-publisher`
because the PyPI publisher entry did not match the workflow's claims; the entry
was corrected on PyPI and the same tag was re-pushed. Nothing was uploaded by
the failed attempt.

Verified after publication: `pip install shockharness==0.1.0` into a fresh
venv from PyPI with no cache; `shockharness version` prints `shockharness
0.1.0`; `check --profile minimal` and `skills install --agent claude` work from
the installed package. PyPI lists `0.1.0` (latest) and `0.1.0a1`.

From this release the CLI surface, exit codes, rule IDs and report
`schema_version` 1 are stable (CHANGELOG 0.1.0).

## Content-hash cache (0.3.0 brief, item 3) — DONE (2026-10-15)

Item 3 of `docs/shockharness-suggestions-3.md` (item 6 of the first brief,
deferred from 0.2.0), as its own commit after the feedback round. 19 tests were
added (600 -> 619). No version bump, no tag, no push.

### What was built

* `src/shockharness/cache/codec.py`: a JSON codec for the frozen dataclasses of
  the per-file phase. Encoding walks dataclass fields; decoding is driven by
  the type hints and is strict (a missing or unknown field, a wrong type, a
  `bool` where an `int` is expected, an inconsistent control tree all raise
  `CacheEntryError`). Control trees, the one recursive structure, are
  flattened to a pre-order list and rebuilt with an explicit stack, so a
  300-deep unit (the existing tree-sitter regression input) round-trips
  without touching the recursion limit. Complex literals (`1j`) are encoded as
  `{"__complex__": [re, im]}`; `inf` from `1e400` survives through Python's
  JSON. Entries are plain JSON, never pickles: nothing read from the cache is
  executed.
* `src/shockharness/cache/store.py`: the directory. `index.json` holds the key
  header (schema version, tool version, config digest, host); `entries/<ab>/
  <sha256 of the relative path>.json` holds one entry per file with the full
  key (header + language + SHA-256 of the bytes) and the serialized
  `PendingFile` minus its source text. Writes are `mkstemp` in the same
  directory then `os.replace`. A header mismatch removes every entry
  (`invalidated` = the number removed); a changed file's entry is counted as
  invalidated and overwritten. Every cache problem is counted under `errors`,
  described once under `problems`, and ignored; the store never raises.
* `analysis.py`: `AnalysisOptions` gains the required field `cache`
  (`CACHE_CONFIGURED` | `CACHE_BYPASSED`); `prepare_file(file, config, cache)`
  reads the bytes once, hashes them, and either rebuilds the `PendingFile`
  from the entry (re-attaching a fresh `SourceText`) or analyzes and stores;
  `analyze_files(files, config, options, cache)`. Suppressions, fingerprints,
  the call graph and everything after run as before on a hit.
* `api.analyze_paths` opens the cache from `cache.enabled` / `cache.directory`
  unless the options say bypassed; `build_report` takes the `coverage.cache`
  block; `gating/diff.py` analyzes revision exports with no cache and records
  `bypassed` with the reason; `analyze_source` is bypassed (no root).
* `discovery.py` skips the configured cache directory like `.git`, without
  counting it (a count would differ between a cold and a warm run over the
  root and break byte-identity).
* `config.py`: the `cache` table is excluded from the configuration digest.
* CLI: `--no-cache` on `check`/`scan`/`gate PATH...`; `baseline create`
  always bypasses; the text trailer prints one `cache:` line and one
  `warning: cache:` line per problem.
* `schemas/report-v1.schema.json`: `coverage.cache` (required). `.gitignore`
  and both examples' new `.gitignore` list `.shockharness-cache/`.
  `.shockharness.toml` declares four boundaries for `cache/store.py`
  (`OSError`, `UnicodeDecodeError`, `json.JSONDecodeError`,
  `shockharness.cache.codec.CacheEntryError`), each with its reason.

### Decisions (mine; review these)

* **The host is part of the key.** The brief lists tool version, config
  digest, language and content hash. Parse facts also depend on the host
  interpreter (`ast` of CPython 3.11 vs 3.14 accept different syntax) and on
  the JavaScript grammar version, so the index header carries
  `"CPython 3.14.7; tree-sitter-javascript 0.25.0"` and a different host
  invalidates everything. Without it, switching interpreters would serve
  stale facts.
* **`cache` is not in the config digest.** A baseline records the digest;
  turning the cache off or moving its directory cannot change a result, so it
  must not invalidate baselines or the cache key. Documented in
  `docs/configuration.md` (Cache) and the CHANGELOG schema note.
* **Entries are keyed by path hash, not content hash.** One entry per file
  path, overwritten when the file changes, so the directory never accumulates
  stale entries and no pruning pass is needed; "changing one file" shows as
  `misses = 1, invalidated = 1`. The content hash lives inside the entry's key.
* **The whole `PendingFile` is stored**, not only what the warm path consumes
  (comments, imports, bindings, units, findings): simpler, and any future
  consumer of facts after the per-file phase keeps working. Cost on this
  repository: 6.8 MB for 102 files; about 60 MB would be expected for the
  906-file codebase. Compression is a follow-up if that matters.
* **Library API change.** `AnalysisOptions(inline_suppressions=True)` no
  longer constructs (the field has no default: the tool's own DEF001 policy);
  consumers pass `cache=CACHE_CONFIGURED` or `CACHE_BYPASSED`. README and
  CHANGELOG say so. Every call site in the repository was updated.
* **Determinism tests** compare JSON with `coverage.cache` removed
  (`tests.conftest.without_cache_block`) and text with the `  cache: ` line
  removed; the SARIF test drops `runs[0].properties.coverage.cache`. The diff
  outputs stay byte-identical as before (no cache is involved).
* **Discovery over the root with a cache directory present** was the one
  byte-identity trap found while building: the first design counted the
  skipped directory under `coverage.discovery`, which differs between cold
  and warm. The count was removed.
* Self-scan: 169 -> 175 advisory findings (six CPLX warnings in `cache/`:
  `store.py` is boundary-heavy by nature); no hard finding remains; the
  self-gate caught the ten hard findings of the first draft (a literal `6`,
  nine undeclared boundaries) and the second draft's digest exclusion was
  driven by `test_cache.py`.

### Evidence (all run 2026-10-15 on macOS arm64)

```text
$ ruff check src tests && ruff format --check src tests
All checks passed!
97 files already formatted

$ pytest -q                      # CPython 3.14.7 (includes the slow timing bound)
619 passed in 56.96s
$ pytest -q                      # CPython 3.13.1
619 passed in 32.19s
$ pytest -q                      # CPython 3.12.8
619 passed in 30.74s
$ pytest -q                      # CPython 3.11.11
619 passed in 44.69s

$ rm -rf .shockharness-cache
$ for i in 1 2 3 4 5; do time shockharness check src tests scripts evals --format json --output run$i.json; done
run1: gate pass (exit 0)  real 3.30 s   coverage.cache: enabled, hits 0,   misses 102, invalidated 0, errors 0
run2: gate pass (exit 0)  real 0.62 s   coverage.cache: enabled, hits 102, misses 0,   invalidated 0, errors 0
run3..run5: identical to run2 (0.62-0.63 s)
$ md5 of run1..run5 with coverage.cache removed (sorted keys)
5 d262bd1113cf44cd2efe28d278333d6e      # five consecutive reports byte-identical
$ du -sh .shockharness-cache; find .shockharness-cache -name "*.json" | wc -l
6.8M    103                             # 102 entries + index.json

$ shockharness check src tests scripts evals --no-cache
  cache: bypassed (--no-cache)
gate: PASS (exit 0)
$ shockharness check src tests scripts evals
  cache: .shockharness-cache: 102 hit(s), 0 miss(es), 0 invalidated, 0 error(s)
gate: PASS (exit 0)
$ shockharness check src tests scripts evals --profile recommended
gate: PASS (exit 0)
$ shockharness check src tests scripts evals --format json --no-cache | jq .execution_summary.findings
175                                     # 169 before the cache; all advisory

$ python -m build
Successfully built shockharness-0.2.0.tar.gz and shockharness-0.2.0-py3-none-any.whl
$ python3.12 scripts/consumer_upgrade_check.py --dist dist --examples examples --wheelhouse <wheelhouse>
js: check . (clean): exit 0: ok
js: check . (after violation in src/pages.js): exit 1; 1 new hard violation(s) ...: ok   # a warm run
python: check . (clean): exit 0: ok
python: check . (after violation in src/example_service/pages.py): exit 1; ...: ok    # a warm run
consumer upgrade check: 2 example(s), 14 step(s), 0 failed
```

### Failures observed during development (and what was done)

1. **Ten hard findings in the first draft** of `cache/`: a numeric literal
   (`CONTROL_FIELDS = 6`, moved to `constants.py` as `CACHE_CONTROL_FIELDS`)
   and nine `except` handlers with no boundary (declared, with reasons).
2. **Recursion in the codec test, not the codec**: comparing two 300-deep
   control trees with dataclass `==` exceeded CPython 3.11's recursion limit
   (3.12+ use fewer frames per level). The test compares the flattened forms.
3. **`coverage.discovery` differed cold vs warm** when the root was a target
   (the skipped cache directory was counted). Not counted any more.
4. **Three CLI tests compared text or JSON between a cold and a warm run**
   (check vs scan alias, `--exit-zero` vs plain, `--summary` trailer); each
   now drops the cache block or line, as the brief prescribes.

## Feedback round 0.3.0: bound captures, constant arithmetic, root anchors, EXC002 message — DONE (2026-10-15)

Input: `docs/shockharness-suggestions-3.md`, written after the maintainer ran
0.2.0 on the same 906-file codebase. Items 1, 2, 4 and 5 are implemented here
in the order 1, 2, 4, 5 decided with the lead session; item 3 (the content-hash
cache) is the next commit, "Content-hash cache". No version bump, no tag, no
push; the maintainer releases. 28 tests were added (572 -> 600).

### What changed, per item

1. **Capture managers bound to a name** (`ir/python_catches.py`,
   `rules/exceptions.py`, `ir/model.py`). A `with` whose context expression is
   a plain name is resolved to the bindings of that name in the enclosing scope
   (function or module body; `if`/`for`/`while`/`try`/`with` bodies belong to
   the scope, nested defs and classes do not), walking backwards from the
   `with`. The adapter records the facts (`NameResolution`: every preceding
   binding with its kind, line, value, and whether its block encloses the
   `with`; whether the name is a parameter or a comprehension target; the
   calls the name is bound to elsewhere in the module) and the rule applies
   `capture_managers`: the latest binding being an assignment to a listed
   manager or `contextlib.suppress` is that catch, `exact` when its block
   encloses the `with` (same block or an outer one), `approximate` when it
   sits in a branch or loop the `with` is not inside or the name is also a
   parameter or a comprehension target; an earlier listed binding followed by
   a rebinding, or a `with M(T) as name` binding, is `unresolved` (an untyped
   catch, like a bare `except`; the message names both lines); a name bound
   to a listed manager only elsewhere in the module (another scope, after the
   `with`) is `unresolved` too, with the message saying where it was last
   bound. `ManagerFact` was restructured: `call: ManagerCall | None` for the
   inline form, `resolution: NameResolution | None` for the bound form.
2. **Literal arithmetic in named constants** (`ir/python.py`,
   `ir/javascript.py`). The accepted value grammar is numeric literals, unary
   `+`/`-`, parentheses and `+ - * / // % **` (JavaScript: `+ - * / % **`).
   Every literal of an accepted value is marked `constant_definition`; a
   unary sign over a sub-expression (`-(30 * 60)`) is walked through, because
   the literal collector only folds a sign that sits directly on a literal.
   Spec section 5 gained one sentence and section 19 row 16.
4. **Root-anchored patterns** (`globs.py`). `split_anchor` separates a leading
   `/` or `./`; an anchored pattern matches the whole relative path and is
   never basename-only; `CompiledGlob` keeps the pattern as written for
   reports and the anchor-free `body` for matching and directory pruning.
   `validate_glob` accepts the anchor and rejects a bare `/` or `./` and a
   `//` after the anchor. Every consumer compiles through `compile_glob`, so
   `include`, `exclude`, overrides, `configuration_files` and boundary paths
   honour the anchor without further change.
5. **EXC002 guard-only message** (`rules/exceptions.py`). When the handler is
   a transparent guard followed by nothing (`guard_body` classifies as empty)
   the swallow message ends with the three remedies. Message only.

### Decisions (mine; review these)

* Item 1 trigger. The brief's `unresolved` outcomes ("no assignment is found
  in the scope", "imported from another module", "bound by `with ... as`")
  cannot apply to every `with name:` without turning `with lock:` and
  `with fh:` into untyped-catch findings. They apply when the name is bound to
  a listed manager (or `suppress`) somewhere in the module (any scope, by
  assignment or by `with ... as`); a name with no such binding anywhere is an
  ordinary `with`. So an imported manager instance is `unresolved` only when
  the module also binds that name to a listed manager. Documented in
  `docs/rules.md` (EXC001) and `docs/configuration.md`.
* Item 1 "same block level": an assignment in an enclosing block counts as
  exact (module-level `capture = M(T)` with the `with` inside an `if` at module
  level; both inside the same `if`). "Approximate" is reserved for a binding
  whose block does not enclose the `with`.
* Item 1 parameter/comprehension: the brief lists "the name is a parameter or
  a comprehension target" under `approximate`. Read as a downgrade of a found
  assignment (the name is bound in more than one way in the scope), not as a
  trigger: a parameter alone, without an assignment to a listed manager, is
  an ordinary `with`.
* Item 1 cross-scope binding: a module-level `capture = M(T)` used inside a
  function is `unresolved`, as the brief says ("in the same scope"), with the
  message "is not assigned in this scope before the with but is bound to
  M(...) elsewhere in the module".
* Item 1 unresolved findings carry the handler classification `opaque`
  (EXC002 has nothing to classify), so a rebound name yields EXC001 only.
* Item 2: a `bool` literal (`True * 2`) is not numeric here (as in 0.2.0);
  a JavaScript comment inside the parentheses does not disqualify the value;
  `(x, 3)` (a sequence expression) does.
* Item 4 error wording: a bare `/` or `./` is "must name something after the
  anchor"; `//a.py` is "must not start with '//' or './/'". The former
  leading-slash error ("must be relative to the analysis root") is gone.
* Self-scan: 164 -> 169 advisory findings (five new CPLX warnings in the new
  code after one refactoring pass that split the five most complex new
  functions: `_binding_of`, `collect_python_managers`,
  `_module_call_bindings`, `_resolve_bound`, `_is_constant_value`); the
  self-gate caught one hard finding during development (a nullish ternary in
  `_manager_fact`), fixed by explicit branches. No threshold was tuned.

### Evidence (all run 2026-10-15 on macOS arm64)

```text
$ ruff check src tests && ruff format --check src tests
All checks passed!
93 files already formatted

$ pytest -q                      # CPython 3.14.7
600 passed in 22.33s
$ pytest -q                      # CPython 3.13.1
600 passed in 19.14s
$ pytest -q                      # CPython 3.12.8
600 passed in 19.92s
$ pytest -q                      # CPython 3.11.11
600 passed in 23.80s

$ shockharness check src tests scripts evals
gate: PASS (exit 0)
$ shockharness check src tests scripts evals --profile recommended
gate: PASS (exit 0)
$ shockharness config validate
shockharness: configuration is valid (dedicated: .../.shockharness.toml; profile strict)
$ shockharness check src tests scripts evals --format json | jq .execution_summary.findings
169                              # 164 before this round; all advisory (CPLX*, DEF003)
```

## Feedback round 0.2.0: precision, noise, adoption — DONE (2026-10-14)

Input: `docs/shockharness-suggestions.md`, written by the maintainer after
running 0.1.0 (strict, library API) on a 906-file Python/JavaScript
application. Items 1-5 and 7-9 are implemented here, in the order 2, 5, 8, 9,
7, 1, 3, 4 decided with the lead session. Item 6 (a content-hash cache) is
deferred to a later release and was not built. No version bump, no tag; the
maintainer releases.

### What changed, per item

| Item | Delivered | Where |
|---|---|---|
| 2 | `CPLX005` reports one finding per import cycle, anchored on the lexically first member at its import into the cycle; the message names the language, the size, up to 8 members (`CYCLE_MEMBERS_LISTED`) then `... and N more`, the entering import, and the import-time vs call-time note. `metrics.graph.cycles` unchanged. Text output lists cycle findings as a group after the per-file findings, Python first (`output/text.py: finding_lines`). If `CPLX005` is disabled on the first member by an override, the first active member carries the finding. | `rules/complexity.py`, `output/text.py`, `constants.py` |
| 5 | `CPLX006` unit size: `size/1` logical lines above `complexity.max_lines_warn` (default 50 in every profile; `minimal` has the family off), module bodies exempt, warning, full registry metadata, in `rules_applied`/`rules_disabled`, in `metrics.complexity.thresholds`, in revision-diff regressions (same exemption) and in the summary. | `rules/registry.py`, `rules/complexity.py`, `complexity/{assemble,regressions}.py`, `schema.py`, `defaults.toml` |
| 8 | `complexity.npath_only_without_cognitive = true`: a unit above both `cognitive_warn` and `npath_warn` is one `CPLX002` finding whose message carries the NPath number (`...; its NPath estimate is ..., reported here instead of as CPLX004`); JSON keeps only `CPLX002` for that unit; `false` reports both as in 0.1.0; NPath alone is still `CPLX004`. The per-unit metrics are untouched. Not a deviation either way. | `rules/complexity.py` |
| 9 | `recommended`: `allow_unary_negative_one = true`, `fan_out_warn = 30`, and fan-out findings at `review` through the new key `complexity.fan_out_severity` (`"warning"` default, `"review"` in `recommended`; both advisory, so not a deviation). `strict` unchanged. | `profiles/recommended.toml`, `schema.py`, `rules/complexity.py` |
| 7 | Verified, not changed: `DEF001` dataclass kinds fire only on classes decorated `dataclass` / `dataclasses.dataclass` (with or without arguments); `_decorator_name` reads the attribute name, so the qualified form is recognized. New test with an undecorated class, an ORM-style class (`Mapped[int] = mapped_column(...)`, `Column(..., default=...)`) and both decorator spellings. The report in the brief must have come from a decorated class. | `tests/unit/test_defaults.py` |
| 1 | `rules.magic_numbers.named_constant_definitions` (`"report"` strict default, `"allow"` in `recommended` and `minimal`). The adapters mark a literal that is the whole value of a module-level named constant definition (`NumericLiteral.constant_definition`): Python `UPPER_SNAKE = <int\|float literal>` with one simple target (leading underscores allowed), or any simple name annotated `Final`/`typing.Final[...]`, as a statement of the module body itself, one unary minus allowed; JavaScript each declarator of a `const`/`export const` statement of the program whose name is UPPER_SNAKE_CASE and whose value is a number (one unary minus allowed). Containers, expressions, chained targets, class/function bodies, `let`/`var`, block-nested `const` and definitions inside module-level `if`/`try` are not marked. `"allow"` is a deviation line (under every profile; under `recommended`/`minimal` it is one of the lines that follow the profile line). Spec section 5 gained the paragraph and section 19 the row (decision 15, "middle ground"). | `ir/{model,python,javascript}.py`, `rules/magic_numbers.py`, `schema.py`, `config.py`, `defaults.toml`, both profile overlays, spec |
| 3 | `rules.exceptions.transparent_guards` (list of callees as written; each a deviation): a handler whose first statement is `guard(<caught>)` with that one argument is narrowed by it; `EXC001` skips the catch, `EXC002` classifies the statements after the guard (`guard(e);` alone still swallows; `guard(e); return null;` is an `EXC002` fallback, reported there because `DEF005` reads the whole body). Python `if not isinstance(exc, T): raise` (or a tuple) as the first statement narrows the catch to `T` for `EXC001` (each member must be approved; the message says `narrowed from 'Exception' by its isinstance guard`), and `EXC002` classifies what follows, as after a JavaScript `instanceof` guard. `boundaries[].exceptions = [...]` accepted alongside `exception = "..."`; exactly one of the two per entry, non-empty, each name validated; one deviation line listing every class. `EXC003` unchanged (guards are not boundaries). `CatchFact` gained `narrowed_from`, `guard_call`, `guard_body`. | `ir/{model,python_catches,javascript_catches}.py`, `rules/exceptions.py`, `schema.py` (`boundary_exceptions`), `config.py`, `defaults.toml` |
| 4 | `check --summary` (also `scan`, `gate PATH...`): findings by rule x top-level directory (`src/`, `tests/`, `.` for root files) and by severity, the 10 (`SUMMARY_TOP_FILES`) files with the most policy findings (`MAGIC`/`EXC`/`DEF`/`SUPP`; suppressed ones count, as in `execution_summary`), complexity counts (units, units over each threshold computed from `metrics.complexity` with the same threshold logic as the rules, NPath-saturated units, cycles, units over `fan_out_warn`), parse failures, elapsed seconds (discovery + analysis + gate, measured in `api.analyze_paths` and per revision in `gating/diff.py`), then the full report's trailer verbatim, so the `gate:` line and exit code are identical. JSON always carries the same object as `summary`; `schema_version` stays `"1"` and `schemas/report-v1.schema.json` describes it. `summary.elapsed_seconds` is the one run-dependent field; the byte-identity test zeroes it before comparing. | `report.py`, `output/text.py`, `cli.py`, `api.py`, `gating/diff.py`, schema |

### Decisions taken here (beyond the brief and the lead's notes)

* Item 1 deviation under `recommended`/`minimal`: the line is emitted whenever
  the value is `"allow"`, so under those profiles it appears among the lines
  that follow the profile's own deviation line, exactly like
  `allow_unary_negative_one`. The alternative (suppress it when a profile set
  it) would have made `_deviations` layer-aware for one key; the existing
  design lists every changed key after the profile line, and the docs say so.
* Item 1 scope: a definition must be a statement of the module body itself.
  Python has no block scope, but `if sys.platform...: TIMEOUT = 5` is a
  decision about a value and belongs in validated configuration; the narrow
  definition is what the brief wrote and is documented in `docs/rules.md`.
  Python covers `int`/`float` literals (the brief's words); JavaScript covers
  any `number` token (BigInt included). Each JavaScript declarator of one
  `const` statement is judged on its own; a Python chained assignment
  (`A = B = 9`) is not a single-target definition and stays reported.
* Item 2 anchor when `CPLX005` is disabled on the first member: the first
  member where the rule is active carries the finding (documented); a cycle
  with no active member has no finding, as before.
* Item 2 text ordering: cycle findings are a cross-file fact, so the text
  report groups them after the per-file findings, Python before JavaScript;
  JSON keeps the fixed path order so `findings` stays byte-stable.
* Item 3: a guard call is recognized as the first statement only, with
  exactly one argument (the bound name), not awaited; the callee must be an
  identifier or member expression and is matched as written. A `DEF005`
  interaction was found while building it: `DEF005` reads the whole-body
  classification, so a literal return after a configured guard would have
  gone unreported; `EXC002` reports it instead and the message names the
  guard. The `isinstance` guard narrows unconditionally (no configuration):
  it is the Python spelling of the already-recognized JavaScript `instanceof`
  guard.
* Item 4: the elapsed time is in the JSON report because the brief lists it
  for both outputs (and item 6's acceptance presumes timing fields); the
  report docstring and the schema say it is the one run-dependent field.
  `fan_out_severity` and `npath_only_without_cognitive` are not deviations:
  they change advisory reporting, not what can fail the gate.
* Item 5 and the tool's own code: see the self-scan below. The 32 `CPLX006`
  warnings on `src/` (units of 51-111 logical lines: `build_parser`,
  `prepare_text`, `gate.evaluate`, the IR collectors) are advisory and left in
  place, like the 62 `CPLX002` warnings already there; splitting those
  functions is a refactoring pass of its own (`refactor-complexity`, with
  before/after graphs), not threshold tuning, and the threshold was not
  touched. No hard finding appeared; the gate passes under both `strict` and
  `recommended`.
* `docs/shockharness-suggestions-2.md` appeared untracked in the tree during
  this session (a second brief from the maintainer); it is not part of this
  commit and nothing in it was acted on.

### Self-scan before and after (strict, `.shockharness.toml`, `check src tests scripts`)

| Point | Gate | Findings | By rule |
|---|---|---|---|
| Before this round (4702882) | PASS | 137 | CPLX002 61, CPLX004 39, CPLX001 23, CPLX003 4, DEF003 10 |
| After item 2 | PASS | 137 | unchanged (the tool has no import cycle) |
| After item 5 (`CPLX006`) | PASS | 176 | + CPLX006 38 (30 in `src/`, 1 in `scripts/`, 7 in `tests/`), CPLX004 40 (one new test) |
| After item 8 (NPath folded) | PASS | 148 | CPLX004 40 -> 11 (29 units were above both thresholds), CPLX001 24 |
| Final (every item, new tests included) | PASS | 159 | CPLX002 65, CPLX006 42, CPLX001 26, CPLX004 12, CPLX003 4, DEF003 10 |

`check --profile recommended` on the same tree: PASS, the same six rule
counts (no fan-out above 30, no `-1` or named-constant literal outside the
exempt `constants.py`, `DEF003` review either way).

### Evidence (all run 2026-10-14 on macOS arm64)

```text
$ ruff check src tests scripts && ruff format --check src tests scripts
All checks passed!
94 files already formatted

$ pytest -q                      # CPython 3.14.7
559 passed in 17.82s
$ pytest -q                      # CPython 3.13.1
559 passed in 17.24s
$ pytest -q                      # CPython 3.12.8
559 passed in 17.09s
$ pytest -q                      # CPython 3.11.11
559 passed in 20.25s
(535 tests before this round; 24 new)

$ shockharness check src tests scripts          # self-compliance, own strict config
  analysis status: complete
gate: PASS (exit 0)

$ shockharness config validate
shockharness: configuration is valid (dedicated: .../.shockharness.toml; profile strict)
  ... (23 policy deviations: 20 boundaries, 3 overrides)

$ shockharness check src tests scripts --summary
shockharness 0.1.0 summary: 97 file(s), 97 analyzed, 0 parse failure(s); 159 finding(s), 0 suppressed; 1.668 s
  by severity: review=10, warning=149
  findings by rule and top-level directory:
    rule     scripts/  src/  tests/  total
    CPLX001              24       2     26
    CPLX002              62       3     65
    CPLX003               4              4
    CPLX004              12             12
    CPLX006         1    32       9     42
    DEF003                2       8     10
    total           1   136      22    159
  files with the most policy findings (MAGIC/EXC/DEF/SUPP; not CPLX; top 10):
         8  tests/property/test_complexity_fuzz.py
         1  src/shockharness/ir/javascript_functions.py
         1  src/shockharness/ir/python_functions.py
  complexity: 1299 unit(s) analyzed; over cyclomatic_warn = 15: 26, cognitive_warn = 15: 65, max_nesting_warn = 4: 4, npath_warn = 200: 42, max_lines_warn = 50: 42; 7 NPath saturated; 0 import cycle(s); 0 unit(s) over fan_out_warn = 20
  parse failures: 0
  ...
gate: PASS (exit 0)

$ python -m build
Successfully built shockharness-0.1.0.tar.gz and shockharness-0.1.0-py3-none-any.whl
```

Sample 0.2.0 finding lines (from the test fixtures and the self-run):

```text
py/a.py:1:1: CPLX005 warning: module import cycle of 3 Python module(s): py/a.py -> py/b.py -> py/c.py -> py/a.py (one finding per cycle, anchored on py/a.py, whose import of py/b.py enters it; a Python import cycle fails at import time; resolved edges only; every member is listed in metrics.graph.cycles)  [from py import b]
src/shockharness/gate.py:86:1: CPLX002 warning: cognitive complexity of function evaluate is 36, above cognitive_warn = 15 (convention cognitive/1; not a Sonar score); its NPath estimate is saturated at the cap (>= 10000) (convention npath/1), reported here instead of as CPLX004 (npath_only_without_cognitive = true)  [def evaluate(]
src/shockharness/cli.py:75:1: CPLX006 warning: size of function build_parser is 109 logical line(s), above max_lines_warn = 50 (convention size/1; module bodies are exempt)  [def build_parser() -> argparse.ArgumentParser:]
src/core/reader.py:4:5: EXC001 error: except handler of 'OSError' (narrowed from 'Exception' by its isinstance guard) is forbidden: catch of 'OSError' is not approved by any boundary for this file  [except Exception as exc:]
web/a.js:4:5: EXC002 error: catch clause after the transparent guard rethrowUnexpectedError(...) swallows the exception: handler body is empty; the failure vanishes  [} catch (error) {]
```

### Acceptance criteria and their tests

| Brief | Test |
|---|---|
| 1: `MAX_PAGES = 8`, `_PORT_WAIT_SECONDS = 10.0` no finding; `x = 8` in a function, `let maxPages = 8;`, `LIMITS = {"retries": 3}` findings; `const`/`export const` no finding; `"report"` reports all; deviation line | `tests/unit/test_magic001.py::test_strict_reports_constant_definitions_and_allow_is_a_deviation`, `::test_constant_definitions_are_marked_in_the_ir`, `::test_recommended_and_minimal_allow_constant_definitions`, `::test_named_constant_mode_is_validated` |
| 2: 6-module JS + 3-module Python cycle = exactly two cycle findings; fan-out unaffected; `metrics.graph.cycles` unchanged; fingerprint stable when an unrelated module is added; 8-member cap | `tests/unit/test_callgraph.py::test_cycle_findings_are_one_per_cycle_with_stable_fingerprints`, `::test_module_cycles_produce_one_cplx005_per_cycle_in_both_languages` (text order), `::test_long_cycle_lists_eight_members_then_a_count`, `::test_cycle_finding_moves_to_the_first_member_where_cplx005_is_active` |
| 3: guarded JS catch no `EXC001`, unguarded still; guard alone is `EXC002` swallow; `isinstance` guard checked as a catch of `OSError`; multi-type boundary validates, approves each type, one deviation | `tests/unit/test_exceptions.py::test_transparent_guard_call_narrows_javascript_catch`, `::test_exc002_classifies_the_statements_after_a_transparent_guard`, `::test_python_isinstance_guard_narrows_the_catch_for_exc001`, `::test_python_transparent_guard_call`, `::test_multi_type_boundary_approves_each_listed_type_once`, `::test_boundary_needs_exactly_one_of_exception_and_exceptions` |
| 4: `--summary` ends with the same `gate:` line; JSON totals equal `execution_summary`; exact `src/`/`tests/` split | `tests/cli/test_cli.py::test_check_summary_ends_with_the_same_gate_line`, `tests/unit/test_gate_and_report.py::test_summary_counts_policy_files_complexity_and_cycles`, `::test_summary_with_complexity_disabled`, `::test_report_matches_published_schema` |
| 5: 51 lines reported, 50 not, module body never, message names count and threshold, disabled with the family | `tests/unit/test_complexity_metrics.py::test_cplx006_reports_units_above_max_lines_warn_and_exempts_module_bodies`, `::test_cplx006_javascript_and_threshold_key`, `::test_cplx006_is_disabled_with_the_family` |
| 7: undecorated and ORM-style classes; `dataclasses.dataclass` recognized | `tests/unit/test_defaults.py::test_def001_dataclass_fields_only_on_decorated_classes` |
| 8: one text line naming both numbers; NPath alone still `CPLX004`; JSON keeps both only with the option off | `tests/unit/test_complexity_metrics.py::test_npath_is_folded_into_cognitive_by_default`, `::test_npath_option_off_reports_both_rule_ids`, `::test_npath_folding_needs_cplx002_active` |
| 9: `recommended` values and deviations; fan-out `review` above 30, `strict` unchanged | `tests/unit/test_profiles.py::test_recommended_profile_values_and_deviations`, `::test_recommended_fan_out_is_review_above_thirty` |

### Failures observed during development (and what was done)

* The first `CPLX006` edit silently did not land: the replacement anchored on
  text that item 2 had already moved, and `ruff --fix` then removed the
  "unused" `size` import. Caught by the new tests (no finding on a 5-line
  unit with `max_lines_warn = 3`); fixed by re-inserting the branch and the
  import. Lesson recorded: assert the match count before replacing.
* A circular import appeared when `rules/exceptions.py` imported the
  boundary helper from `config.py` (`config` -> `rules.defaults` ->
  `rules.exceptions` -> `config`). The helper lives in `schema.py`, which has
  no project imports.
* The JavaScript rejection-handler path left `statements` unbound for an
  expression-bodied arrow (`.catch(() => null)`); caught by the existing
  adapter test, fixed by binding an empty list in that branch.
* Test-data mistakes caught by the tests themselves: a nested-`if` fixture
  has NPath 3^8 = 6561, not 2^8; a module made only of functions has 0
  logical lines of its own (nested units give up their whole span); a JS
  `const A = 1, TWO = 2;` marks two literals.

## Feedback round 0.2.0, second batch: coverage gaps — DONE (2026-10-14)

Input: `docs/shockharness-suggestions-2.md` (the same codebase compared rule by
rule with its own startup linter). Items 1-4 are implemented; item 5 (a plugin
API) is a design note and was not built. Same rules as the first batch: no
version bump, no tag, the maintainer releases. Both suggestion documents are
committed with this batch so the reasoning travels with the code.

### What changed, per item

| Item | Delivered | Where |
|---|---|---|
| 1 | `ModuleFacts.managers`: every `with` item whose context expression is a call, with the callee resolved through the symbol table, its positional arguments resolved as exception identities, the `as` name and the body attributed like a `try` body (`ManagerFact`). The exception rule turns the ones that catch into catch facts of kind `context manager`: `contextlib.suppress` (either import spelling; swallows, so `EXC002` reports it unless a boundary approved it) and the configured `rules.exceptions.capture_managers` (qualified names; exact when the import resolves, approximate by bare name when it does not; the exception stays available after the block, so `other` for `EXC002`). No readable type is an untyped catch (`unresolved`, never approvable). Boundaries approve them like `except` handlers; `EXC003` reads the body; each configured manager is a deviation and is validated as a dotted name. | `ir/model.py`, `ir/python_catches.py` (`collect_python_managers`), `ir/python.py`, `ir/javascript.py` (empty), `rules/exceptions.py` (`manager_catches`), `schema.py`, `config.py`, `defaults.toml` |
| 2 | `DEF002`: `next(iterator, default)` (kind `next_default`) and `collections.defaultdict(factory)` through any import spelling (kind `defaultdict`; resolved with the catch module's `SymbolTable`, so `import collections as c; c.defaultdict(list)` and `from collections import defaultdict as dd` are found; `defaultdict()` is not). `d.pop(k, v)` and `d.setdefault(k, v)` were already covered since Milestone D and gained dedicated tests. `DEF001`: pydantic models (a base that resolves to `pydantic.BaseModel`) are checked like dataclasses with `pydantic field` messages: `x: int = v`, `Field(default=v)`, `Field(v)`, `Field(default_factory=f)`; `Field(...)`, `Field()` and `= ...` are required fields; an unresolved base does not count. The golden fixture `def_mapping_get.py` gained its `defaultdict(int)` row. | `ir/python_defaults.py`, `rules/defaults.py`, `ir/model.py`, `tests/fixtures/expected.json` |
| 3 | Verified against Milestone C's promise handling, criterion by criterion (below). Gaps fixed: a handler given as a reference to a function defined at the top level of the module (declaration, exported or not, or a `const` bound to an arrow/function expression) is classified by that function's body; any other reference stays opaque with `unresolved` confidence and a message that says so; an expression-bodied arrow that only logs is `logging_only`; a bare `log(...)` call joins the JavaScript logging set. | `ir/javascript_catches.py` (`module_functions`, `is_logging_expression`) |
| 4 | `unsupported_sources` (`fail` / `warn` / `ignore`; `warn` in strict and recommended, `ignore` in minimal). Discovery lists the files `include` matched (and `exclude` kept) whose extension no adapter parses (`DiscoveryResult.unsupported`, `counts.unsupported_sources`; `unsupported_extension` still counts every unparseable file). `fail`: each becomes a `FileResult` with status `unsupported_source` and language `unsupported` (`analysis.with_unsupported_sources`, applied in `api.analyze_paths` and per revision in `gating/diff.py`), the gate errors with its own reason regardless of `parse_errors`, `analysis_status` is `failed`, exit 3, and the text report names the file. `warn`: `coverage.unsupported_sources` lists them and the text trailer prints a `warning:` line. `ignore`: only counted; a reported deviation. `coverage.unsupported_sources_policy` records the value. An explicit unsupported target stays a usage error. | `discovery.py`, `analysis.py`, `api.py`, `gating/diff.py`, `gate.py`, `report.py`, `output/text.py`, `schema.py`, `config.py`, `defaults.toml`, `profiles/minimal.toml`, `schemas/report-v1.schema.json` |

### Item 3: which acceptance criteria already held

| Criterion | Before this batch | Work |
|---|---|---|
| `fetchData().catch(() => {})`: `EXC001` and `EXC002` swallow | held (inline arrow, empty block) | test only |
| `.catch((error) => { throw error; })`: `EXC001` without `transparent_rethrow`, nothing with it | held (`reraise` classification, the `transparent_rethrow` path is kind-agnostic) | test only |
| `.then(render, (error) => log(error))`: `EXC002` log-only | did not hold: an expression body was `other` and a bare `log(...)` was not a logging call | fixed |
| `.finally(cleanup)`: nothing | held (`REJECTION_HANDLER_ARGS` lists `catch` and `then` only) | test only |
| an `async` function's `try`/`catch` unchanged | held | test only |
| a reference to a module function is classified by its body; other references are `unresolved` | did not hold: every reference was opaque | fixed |

### Decisions taken here

* Item 1, `EXC002` on an approved `suppress`: the brief says `EXC002` reports
  the swallow "unless a boundary approves it" and its acceptance expects no
  finding for an approved `suppress(FileNotFoundError)`, which differs from an
  approved `except T: pass` (still `EXC002`). The brief is followed:
  `suppress` names its discard and has no handler to inspect, so the boundary
  approved the discard itself. Documented in `docs/rules.md` and the registry.
* Item 1, configured capture managers are `other` for `EXC002`: the manager
  keeps the exception for inspection after the block (`capture.captured_exception`),
  which is the equivalent of `except T as exc: captured = exc`, not of `pass`.
* Item 1, confidence vocabulary: the lead's "probable" for a bare-name match
  is reported as `approximate`, the finding confidence the schema allows
  (`exact` / `approximate` / `unresolved`); the docs say so.
* Item 2, `defaultdict` resolution reuses `python_catches.SymbolTable` (the
  defaults index now carries one), so the spelling table matches the one
  `EXC001` uses for exception identities.
* Item 3, bare `log(...)` as logging is JavaScript-only (Python keeps its
  receiver-based regex plus `print`); the brief's acceptance names it.
* Item 4, deviation: `"ignore"` is reported under every profile, as
  `parse_errors = "warn"` is; `"fail"` is stricter than any profile default
  and is not a deviation. The gate's reason for unsupported sources is its
  own line, independent of `parse_errors`.
* Item 5 was not built.

### Self-scan before and after (strict, `.shockharness.toml`, `check src tests scripts`)

| Point | Gate | Findings | By rule |
|---|---|---|---|
| After the first batch (38bb8f2) | PASS | 159 | CPLX002 65, CPLX006 42, CPLX001 26, CPLX004 12, CPLX003 4, DEF003 10 |
| Final (second batch, new tests included) | PASS | 162 | CPLX002 67, CPLX006 43, CPLX001 26, CPLX004 12, CPLX003 4, DEF003 10 |

No new hard finding: the tool uses no `contextlib.suppress`, `defaultdict`,
`next(it, default)` or pydantic model, and `coverage.unsupported_sources` is
empty under the default `warn` (the eight unparseable files the walk sees are
`.toml`, `.md` and `.json` that `include` does not match). `--profile
recommended`: PASS, same counts.

### Evidence (all run 2026-10-14 on macOS arm64)

```text
$ ruff check src tests scripts && ruff format --check src tests scripts
All checks passed!
94 files already formatted

$ pytest -q                      # CPython 3.14.7
572 passed in 18.73s
$ pytest -q                      # CPython 3.13.1
572 passed in 18.55s
$ pytest -q                      # CPython 3.12.8
572 passed in 18.47s
$ pytest -q                      # CPython 3.11.11
572 passed in 21.01s
(559 tests after the first batch; 13 new)

$ shockharness check src tests scripts          # self-compliance, own strict config
  analysis status: complete
gate: PASS (exit 0)

$ shockharness config validate
shockharness: configuration is valid (dedicated: .../.shockharness.toml; profile strict)
  ... (23 policy deviations: 20 boundaries, 3 overrides)

$ python -m build
Successfully built shockharness-0.1.0.tar.gz and shockharness-0.1.0-py3-none-any.whl
```

Sample finding lines (a throwaway tree with `include = ["src/**/*"]` and one
configured capture manager, `--parse-errors warn`):

```text
src/app.js:1:13: EXC002 error: promise .then rejection handler only logs the exception; logging is not handling  [fetchData().then(render, (error) => log(error));]
src/app.js:3:13: EXC002 error: promise .catch handler swallows the exception: handler body is empty; the failure vanishes  [fetchData().catch(swallow);]
src/io/fs.py:7:34: DEF001 error: pydantic field 'retries' of Settings has Field(default=...): 3  [retries: int = Field(default=3)]
src/io/fs.py:11:5: EXC001 error: context manager of 'FileNotFoundError' is forbidden: catch of 'FileNotFoundError' is not approved by any boundary for this file  [with suppress(FileNotFoundError):]
src/io/fs.py:11:5: EXC002 error: context manager swallows the exception: suppress(...) discards the exception; nothing after the block can tell that the operation did not happen  [with suppress(FileNotFoundError):]
src/io/fs.py:13:14: DEF002 error: defaultdict(int) falls back to int() for every missing key; defaultdict(factory) creates factory() for every missing key, so a lookup never fails and a missing key is indistinguishable from an empty value  [counts = defaultdict(int)]
src/io/fs.py:14:13: DEF002 error: next(iter(counts)) falls back to 0 when the iterator is exhausted; next(iterator, default) substitutes the default for an exhausted iterator; an empty sequence and a sequence that ends with the default look the same  [first = next(iter(counts), 0)]
src/io/fs.py:15:5: EXC001 error: context manager of 'ProcessLookupError' is forbidden: catch of 'ProcessLookupError' is not approved by any boundary for this file  [with CapturedExceptionContext(ProcessLookupError, boundary="x") as capture:]
  warning: 1 included file(s) have an extension no adapter parses and were not analyzed (unsupported_sources = "warn"): src/types.ts
```

### Acceptance criteria and their tests

| Brief | Test |
|---|---|
| 1: `with suppress(FileNotFoundError)` without a boundary: `EXC001` + `EXC002` on the `with` line; with a boundary: nothing; `suppress(Exception)`: broad; configured manager behaves like `except ProcessLookupError:`; unlisted manager is an ordinary `with`; fingerprints stable | `tests/unit/test_exceptions.py::test_contextlib_suppress_is_a_swallowing_catch`, `::test_capture_managers_are_catches_when_configured`, `::test_manager_catch_fingerprints_survive_unrelated_edits` |
| 2: one finding per form, none for the no-default variants, aliased `defaultdict` found, evidence in JSON | `tests/unit/test_defaults.py::test_pop_setdefault_and_next_with_defaults`, `::test_defaultdict_under_every_import_spelling`, `::test_pydantic_model_fields_are_dataclass_fields`; golden `python/def_mapping_get.py` |
| 3: swallow, rethrow with/without `transparent_rethrow`, log-only, `.finally`, async `try`/`catch`; references | `tests/unit/test_exceptions.py::test_promise_rejection_handlers_acceptance`, `::test_promise_handler_references_resolve_to_module_functions` |
| 4: `fail` exits 3 and names the file; `warn` lists it; `ignore` says nothing; a `.ts` outside `include` is never mentioned; strict default `warn` shown by `config effective` | `tests/cli/test_cli.py::test_unsupported_sources_policy[fail|warn|ignore]`, `::test_unsupported_sources_default_and_config_effective`, `tests/unit/test_discovery.py::test_unsupported_sources_are_listed_only_when_included`, `tests/unit/test_profiles.py::test_minimal_reports_everything_at_review_and_never_fails` |

### Failures observed during development (and what was done)

* The `warn` policy first exited 3 in its CLI test: the text renderer raised
  `NameError` because a formatter pass had split the condition my edit was
  anchored on, leaving the variable unbound. The process boundary turned it
  into exit 3 with a traceback, as designed. Fixed; the test now distinguishes
  the three policies' exit codes.
* The golden fixture `def_mapping_get.py` already contained
  `counts = defaultdict(int)`; the new `DEF002` row was reviewed and added to
  `expected.json`.

## Release 0.2.0 (2026-10-14)

Tag `v0.2.0` at c05a035. Published by `publish.yml` through trusted publishing
(run https://github.com/evolvingstuff/ShockHarness/actions/runs/38690998487,
17 of 17 jobs green) after the maintainer's approval at the `pypi`
environment. Contents: the two feedback-round commits (38bb8f2, a1818d9)
driven by `docs/shockharness-suggestions.md` and
`docs/shockharness-suggestions-2.md`, the release commit 795707f, and
c05a035.

The release commit's first CI run failed on five of twelve matrix jobs with no
platform pattern: `summary.elapsed_seconds` had been added to the JSON report,
so two runs differed by a millisecond and the byte-identical determinism tests
failed whenever a runner's timings rounded differently. Elapsed time now lives
on the `Report` object and is printed by the text summary only; the JSON
report is byte-identical again (spec section 10). Nothing had been tagged.

Verified after publication: `pip install shockharness==0.2.0` into a fresh
venv from PyPI; `shockharness version` prints `shockharness 0.2.0`; runtime
dependencies are `tree-sitter` 0.25.2 and `tree-sitter-javascript` 0.25.0
only; `check --summary --profile recommended` and `rules list` (18 rules,
all implemented except MAGIC002) work from the installed package. PyPI lists
`0.2.0` (latest), `0.1.0` and `0.1.0a1`.

## Release 0.3.0 (2026-10-15)

Tag `v0.3.0` at 75e0c03. Published by `publish.yml` through trusted publishing
(run https://github.com/evolvingstuff/ShockHarness/actions/runs/38704879047,
all jobs green) after the maintainer's approval at the `pypi` environment.
Contents: the third feedback round (b243a03: bound capture managers, literal
arithmetic in named constants, root-anchored patterns, EXC002 guard-only
message; c35b3aa: the content-hash cache), the release commit 3eb3e6f, and a
test fix 75e0c03.

The release commit's first CI run failed on the four Windows jobs only: one
test wrote an absolute Windows path into a TOML basic string, where a
backslash is an escape (`\U` in `\Users` is an invalid unicode escape). The
test now writes the path with forward slashes, valid on Windows and in TOML.
Nothing had been tagged. This is the third Windows-only lesson in a row
(git date spelling, CRLF checkouts, backslashes in TOML); each is now covered
by a test or a repository setting.

Verified after publication: `pip install shockharness==0.3.0` into a fresh
venv from PyPI; `shockharness version` prints `shockharness 0.3.0`; the cache
reports 60 misses on a cold run and 60 hits on the warm run over the same
tree; `check --profile recommended` accepts arithmetic constant definitions;
runtime dependencies are `tree-sitter` 0.25.2 and `tree-sitter-javascript`
0.25.0 only. PyPI lists `0.3.0` (latest), `0.2.0`, `0.1.0` and `0.1.0a1`.

## Release 0.4.0 (2026-10-16)

Tag `v0.4.0` at 79947b5. Published by `publish.yml` through trusted publishing
(run https://github.com/evolvingstuff/ShockHarness/actions/runs/38944777102)
after the maintainer's approval at the `pypi` environment. Contents: Milestone
H1 (66f56fb: the `unknown` finding status, `fail_on_unknown`, file roles), H2
part 1 (b608940: VERIFY001, VERIFY002, VERIFY004), H2 part 2 (2aa2da2:
VERIFY003, `--policy`, the `verification-integrity` skill), a CI fix c21cc3b
and the release commit 79947b5.

The first CI run on the H2 commits (2aa2da2) failed in the build job only: the
wheel smoke test expected exactly four `SKILL.md` files, and H2 part 2 ships
five. Every test job was green. The smoke test now takes the expected count
from `SKILL_NAMES` in the installed wheel (c21cc3b). Nothing had been tagged.
The Dependabot `actions/checkout` branch was cut from 2aa2da2 and failed CI for
the same reason; it passes once rebased onto main.

Verified after publication: `uv pip install shockharness==0.4.0` into a fresh
environment from PyPI; `shockharness --version` prints `shockharness 0.4.0`;
`skills list` shows five skills; `rules list` shows `VERIFY003` implemented;
runtime dependencies are `tree-sitter` 0.25.2 and `tree-sitter-javascript`
0.25.0 only. PyPI lists `0.4.0` as the latest release, with a wheel and an sdist.

## Release 0.5.0 (2026-10-16)

Tag `v0.5.0` at 25e49cb. Published by `publish.yml` through trusted publishing
(run https://github.com/evolvingstuff/ShockHarness/actions/runs/38965371003)
after the maintainer's approval at the `pypi` environment; the release commit's
CI run (https://github.com/evolvingstuff/ShockHarness/actions/runs/38964860058)
was green before the tag. Contents: the fourth suggestions brief and plan
(899c5e5), feedback round F4 (56af310) and the release commit 25e49cb. Since
0.4.0, `main` also carries the five GitHub Actions bumps applied from
Dependabot (52c069b to 7643b56; `actions/download-artifact` v8 ran for the first
time in this publish, without problems).

Verified after publication: `uv pip install shockharness==0.5.0` into a fresh
environment from PyPI (the simple index lagged the JSON API by under a minute;
the install was retried until it resolved); `shockharness --version` prints
`shockharness 0.5.0`; `shockharness exceptions` runs; a `@router.get(...)`
decorator and a checked-then-raised `getattr(o, a, None)` are not reported;
runtime dependencies are `tree-sitter` 0.25.2 and `tree-sitter-javascript`
0.25.0 only. PyPI lists `0.5.0` as the latest release, with a wheel and an sdist.

## Release 0.6.0 (2026-10-16)

Tag `v0.6.0` at c8cad1b. Published by `publish.yml` through trusted publishing
(run https://github.com/evolvingstuff/ShockHarness/actions/runs/38976324000)
after the maintainer's approval; the release commit's CI run
(https://github.com/evolvingstuff/ShockHarness/actions/runs/38975889655) was
green before the tag. Contents: Milestone H3 (5b00143), the guard-consistency
note for H6 (650eab3), the tool's Boolean flags passed by keyword (9050b4f),
`write-compliant-code` principle 8 on immutable values (af192d5) and the
release commit c8cad1b.

Verified after publication: `uv pip install shockharness==0.6.0` into a fresh
environment from PyPI; `shockharness --version` prints `shockharness 0.6.0`;
`rules list` shows EXC004, STUB001, STUB002, ASSERT001, BOOL001, STATE001 and
IMPORT001; runtime dependencies are `tree-sitter` 0.25.2 and
`tree-sitter-javascript` 0.25.0 only. PyPI lists `0.6.0` as the latest release,
with a wheel and an sdist.

## Next tasks

Updated 2026-10-16, after the fourth suggestions batch
(`docs/shockharness-suggestions-4.md`; spec 21.1 decisions 12-18, 21.2 table).
In order:

1. **F4, the 0.5.0 feedback round** (done and released as 0.5.0 on 2026-10-16)
   (suggestions-4 items 1-9): DEF002
   precision (decorator `.get`, checked-then-raise, discarded `pop(k, None)`,
   the `setdefault` grouping idiom, "absence is normal" remediation);
   `recommended` stops gating on unknown `DEF*` findings; the `shockharness
   exceptions` command; skill guidance (propose a rule, validate outputs);
   docs for Python 3.10 projects, empty trees, and covered-versus-planned
   checks. The checked-then-raise item supersedes the earlier note here about a
   flow-sensitive refinement for the implicit-`None` finding. Release 0.5.0.
2. **H3**: STUB001, STUB002, ASSERT001, BOOL001, STATE001, IMPORT001, plus
   EXC004 (`return`/`break`/`continue` in `finally`). Done 2026-10-16 (see its
   entry below); released as 0.6.0.
3. **H4** (async lifecycle, including uninspected `gather(return_exceptions=True)`
   and `Promise.allSettled` results; done 2026-10-16, not released), **H5** (done
   2026-10-16, not released) (API catalog, PROCESS001 naming
   `check=False`), **H-TS** (TypeScript; `tree-sitter-typescript` approved),
   then H6 and H7.
- Declined: Python 3.10 support (decision 17). Recorded, not scheduled: a rule
  for `__qualname__`/`__name__` on values of unknown type (decision 16).
- Still open from earlier: `.gitignore` handling (spec: only if configured) and
  `-0` policy wording in docs if challenged.
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

## Milestone G: agent skills, skills install/update, eval corpus — DONE (2026-10-14)

Delivered (spec sections 5, 12, 14 "Milestone G", 20 decision 5):

* **Four skills as package data**, `src/shockharness/skills/<name>/SKILL.md`
  (`write-compliant-code`, `fix-violations`, `refactor-complexity`,
  `pre-commit-review`), open Agent Skills format (frontmatter `name` +
  `description`, Markdown body), vendor-neutral. Each has a rule table quoted
  from the registry, compliant and non-compliant Python and JavaScript
  examples (the worked examples are `examples/python` and `examples/js`),
  exact CLI invocations with finding lines copied from real runs, a
  corrective workflow, a checklist, and an "Adopting ShockHarness" section
  that is byte-identical to the README's (`test_adoption_section_is_identical_in_readme_and_every_skill`).
  `refactor-complexity` says in its first paragraph that `CPLX001`-`CPLX005`
  are registered but not implemented (Milestone E) and tells the agent how to
  record call structure by hand. 250-400 lines each (spec recommends < 500).
* **`shockharness skills list | show NAME | install | update`**
  (`src/shockharness/skills/{__init__,adapters,install}.py`, CLI in
  `cli.py`). `install --agent claude|codex|generic [--project PATH] [--user]
  [--force]`; `update --agent ... [--project PATH] [--user] [--check]`.
  `--project`/`--user` are mutually exclusive (argparse, exit 2).
* **Manifest** `<destination>/.shockharness-skills.json`: `schema_version
  "1"` (`SKILLS_MANIFEST_SCHEMA_VERSION` in `constants.py`), `tool_version`,
  `agent`, `skills.<name>.{path, sha256}`; sorted keys, indent 2. Files are
  written and hashed as bytes (no newline translation), so hashes agree on
  every platform.
* **Eval corpus** `evals/`: 8 tasks (`py-01-http-settings`,
  `py-02-mapping-fallbacks`, `py-03-json-boundary`,
  `py-04-pagination-numbers`, `js-01-config-env`, `js-02-catch-fallback`,
  `js-03-pagination-defaults`, `js-04-status-codes`), each with `task.md`,
  `start/`, `tests/` (unittest / `node --test`), `expected.json`,
  `reference/`. `evals/run_evals.py` (stdlib only) scores candidates:
  unsuppressed findings by rule, test exit code, suppressions added; JSON
  scorecard; exit 0 only when every task passes. `evals/README.md` documents
  the with/without-skills comparison protocol.
* **README "Adopting ShockHarness"** (replaces the shorter "on an existing
  codebase" section): pinned `uv tool install` / `uvx --from` / `pip` forms,
  `init`, the four onboarding paths, direct and reusable CI with the
  Dependabot snippet, `skills install`, a verify table; absolute links only.
* Docs: `docs/skills.md` (new), `docs/integration.md` section 7,
  `docs/limitations.md` "Skills", `docs/releasing.md` (the pin now lives in
  five places), `CHANGELOG.md`. CI: Ruff and the self-gate cover `evals/`;
  the `package` job runs `skills list` from the installed wheel and counts
  the four `SKILL.md` members; new `skill-evals` job (ubuntu, node 22) scores
  the references and round-trips install + `update --check` for all three
  agents. sdist now includes `evals/`.

### Decisions (mine; review these)

1. **Codex paths verified 2026-10-14.** `https://developers.openai.com/codex/skills`
   redirects (308) to `https://learn.chatgpt.com/docs/build-skills`, whose
   discovery table lists `$CWD/.agents/skills` and every parent up to
   `$REPO_ROOT/.agents/skills`, then `$HOME/.agents/skills`, `/etc/codex/skills`
   and a bundled SYSTEM set. The page does not mention `.codex/skills` or
   `$CODEX_HOME/skills` (only `~/.codex/config.toml` for `[[skills.config]]`).
   Third-party guides still say `~/.codex/skills`; the adapter follows the
   official page: **project `.agents/skills`, user `~/.agents/skills`**. Claude:
   `.claude/skills` project, `~/.claude/skills` user (`https://code.claude.com/docs/en/skills`).
   Each is one `Adapter(...)` entry in `skills/adapters.py` with the URL and
   date in its `documentation` field (asserted by `test_adapter_table`).
2. `install` refuses (exit 2, writes nothing) when **any** target file or the
   manifest exists, listing them; `--force` replaces all. Consistent with
   `init` and `baseline create`.
3. `update` statuses: `up-to-date`, `stale` (rewritten), `edited` (conflict,
   left alone, old generated hash kept so it stays a conflict), `missing`
   (restored), `new` (added), `removed` (reported, file not deleted, manifest
   entry dropped). A shipped skill whose file exists but has no manifest entry
   is treated as `edited` (never overwrite a file we did not write). `update`
   exits 1 while a conflict remains; `--check` writes nothing (not even the
   manifest) and exits 1 on any of the five drift statuses, which is wider than
   the brief's "stale or edited" so consumer CI also notices a new or removed
   skill. The remediation printed for a conflict: save edits, delete the file,
   rerun `update` (restored), re-apply; `skills show NAME` prints the shipped
   version.
4. Frontmatter parsing is a deliberate YAML subset (single-line `key: value`
   between two `---` lines), applied only to the shipped files; the test suite
   validates them against the Agent Skills constraints (name regex, 64 chars,
   description 1-1024 chars, name == directory).
5. `generic` requires `--project DIR` and rejects `--user` (both exit 2); it
   prints the `AGENTS.md` pointer line with the path as the user typed it.
   No command edits an agent's configuration or instruction file.
6. The eval runner is stdlib-only and therefore holds its own `JSON_INDENT =
   2`; `.shockharness.toml` gains `include = [..., "evals/*.py"]`, `exclude`
   of `evals/tasks/**` (deliberately dirty starts) and a declared `MAGIC001`
   override for `evals/run_evals.py` with that reason. Python tasks use
   `unittest` (no pytest dependency in the workspace); JavaScript tasks pass
   the explicit `tests/*.test.js` list to `node --test` (Node 24 rejects a bare
   directory argument). A missing `node` is recorded as a test failure.
7. Two tasks require config edits in the solution (`py-03`, `js-02`: one
   declared boundary each; `js-02` demonstrates the `instanceof` guard and the
   `{ cause: err }` form EXC002 requires). Two allow bounded cited suppressions
   (`py-01`: 1 for the RFC 793 port ceiling; `js-04`: 3 for RFC 9110 status
   codes); the runner fails a candidate that exceeds the allowance.
8. Ruff's formatter reformats fenced Python inside `.md` files, which would
   mangle the aligned, partly non-compliant snippets, so
   `src/shockharness/skills` joined `extend-exclude` (Ruff never lints the
   Markdown; the Python modules in the same package are still checked and
   formatted).
9. The adoption section pins `0.1.0a1` in the README and in all four skills;
   `test_adoption_section_is_identical_in_readme_and_every_skill` asserts the
   pin equals `version.py`, so a version bump must touch the five copies
   (`docs/releasing.md` step 2 says so). Not bumped here.
10. Analyzer message texts quoted in the skills were taken from real runs
    (`env.X ?? v` on a parameter is DEF002, not DEF006; the JavaScript EXC001
    and DEF005 wordings; the diff gate's `N new, N fixed, N unchanged
    finding(s)` line; the baseline gate's `N legacy finding(s) matched the
    baseline` line).

### Dogfooding: what the gate found in the new code

The first `install.py` wrote `mkdir` + `write_bytes` inside one `try`
(EXC003 would flag two operations under the new `OSError` boundary); the two
calls moved into `_create_parent_and_write` so the `try` wraps one call. The
first `adapters.py` imported `SKILL_NAMES` inside `pointer_line` (an
approximate-confidence import); moved to module level. No numeric literal
other than 0/1 appears outside `constants.py` and the declared eval override.

### Evidence (all run 2026-10-14 on macOS arm64)

```text
$ ruff check src tests scripts evals && ruff format --check src tests scripts evals
All checks passed!
77 files already formatted

$ pytest -q        # CPython 3.12.8 / 3.11.11 / 3.13.1 / 3.14.7
483 passed in 13.96s / 20.12s / 19.16s / 19.04s      (447 before; 36 new)

$ shockharness check src tests scripts evals    # self-compliance, all four interpreters
gate: PASS (exit 0)

$ shockharness config validate | head -1
shockharness: configuration is valid (dedicated: .../.shockharness.toml; profile strict)
  (22 boundaries, 3 overrides; the three new boundaries are skills/install.py OSError,
   UnicodeDecodeError, json.JSONDecodeError)

$ python evals/run_evals.py --reference --output scorecard.json   # all four interpreters
js-01-config-env: PASS; analyzer exit 0, unsuppressed findings 0; tests exit 0; suppressions added 0
js-02-catch-fallback: PASS; analyzer exit 0, unsuppressed findings 0; tests exit 0; suppressions added 0
js-03-pagination-defaults: PASS; analyzer exit 0, unsuppressed findings 0; tests exit 0; suppressions added 0
js-04-status-codes: PASS; analyzer exit 0, unsuppressed findings 0; tests exit 0; suppressions added 3
py-01-http-settings: PASS; analyzer exit 0, unsuppressed findings 0; tests exit 0; suppressions added 1
py-02-mapping-fallbacks: PASS; analyzer exit 0, unsuppressed findings 0; tests exit 0; suppressions added 0
py-03-json-boundary: PASS; analyzer exit 0, unsuppressed findings 0; tests exit 0; suppressions added 0
py-04-pagination-numbers: PASS; analyzer exit 0, unsuppressed findings 0; tests exit 0; suppressions added 0
evals: 8 task(s), 8 passed, 0 failed, 0 unsuppressed finding(s), 4 suppression(s) added
(exit 0)

$ python evals/run_evals.py --candidates <copies of every start/>
evals: 8 task(s), 0 passed, 8 failed, 38 unsuppressed finding(s), 0 suppression(s) added
(exit 1; every start fails both the analyzer and its tests)

$ python -m build && unzip -l dist/*.whl | grep SKILL.md
shockharness/skills/fix-violations/SKILL.md
shockharness/skills/pre-commit-review/SKILL.md
shockharness/skills/refactor-complexity/SKILL.md
shockharness/skills/write-compliant-code/SKILL.md
$ tar tzf dist/*.tar.gz | grep -c evals/
74

$ # fresh directory, clean venv with the built wheel
$ shockharness skills install --agent claude
shockharness: installed 4 skill(s) for claude into .../.claude/skills
  written    write-compliant-code/SKILL.md
  written    fix-violations/SKILL.md
  written    refactor-complexity/SKILL.md
  written    pre-commit-review/SKILL.md
  manifest   .shockharness-skills.json (shockharness 0.1.0a1)
Claude Code loads .claude/skills/<name>/SKILL.md from the project and ~/.claude/skills/<name>/SKILL.md from the home directory automatically.
$ shockharness skills install --agent claude ; echo $?
shockharness: error: .../.claude/skills: skill files already exist and would be overwritten; pass --force to replace them, or run `skills update` to refresh unedited files and keep edited ones: ...
2
$ shockharness skills install --agent codex | head -1
shockharness: installed 4 skill(s) for codex into .../.agents/skills
$ shockharness skills update --agent claude --check ; echo $?
  up-to-date write-compliant-code/SKILL.md
  ...
shockharness: 4 skill(s) up to date
0
$ echo "# mine" >> .claude/skills/fix-violations/SKILL.md; rm .claude/skills/pre-commit-review/SKILL.md
$ shockharness skills update --agent claude --check ; echo $?
  edited     fix-violations/SKILL.md: left unchanged: conflict (content differs from the manifest hash; the file is yours, so it is left unchanged. To take the shipped version: save your edits, delete the file, run `shockharness skills update --agent claude` (the file is restored), then re-apply your edits. To read the shipped version: `shockharness skills show fix-violations`.)
  missing    pre-commit-review/SKILL.md: would be restored from the package (in the manifest but absent on disk)
shockharness: 2 of 4 skill(s) drifted from the installed package (exit 1)
1
$ shockharness skills update --agent claude ; echo $?
  missing    pre-commit-review/SKILL.md: restored from the package (in the manifest but absent on disk)
shockharness: 1 conflict(s) left unchanged (exit 1)
1
$ shockharness skills install --agent generic ; echo $?
shockharness: error: --agent generic needs --project DIR (the directory that receives <name>/SKILL.md); there is no conventional location for a generic agent
2
$ shockharness skills install --agent generic --project docs/agent-skills | tail -2
Add this line to the agent's instruction file (for example AGENTS.md):
  Before writing, fixing, refactoring or reviewing code, read the matching ShockHarness skill in docs/agent-skills/<name>/SKILL.md (write-compliant-code, fix-violations, refactor-complexity, pre-commit-review).
```

### Failures observed during development (and what was done)

1. The first eval run failed every task: `unittest discover -t .` needs
   `tests/` to be a package (dropped `-t .`); `node --test tests` is a module
   path on Node 24, not a directory (the runner now passes the
   `tests/*.test.js` files); the `js-02` reference threw
   `new ParseError(msg, err)`, which EXC002 reports as "cause is not
   preserved" (changed to `{ cause: err }`).
2. `ruff format --check` failed on the three SKILL.md files (it formats
   fenced Python in Markdown); excluded the skills directory from Ruff.
3. A naive "no `[[` wiki links" assertion in `test_skills.py` matched nested
   list literals in a code sample; removed.
4. The first draft of `fix-violations` quoted a DEF006 finding for
   `env.REQUEST_TIMEOUT_MS ?? 2500` and invented JavaScript EXC001/DEF005
   wordings; both corrected from real analyzer output before commit.

### Not run here

GitHub Actions (`skill-evals` job, the `package` job's `skills list` and
`SKILL.md` count) have not run on GitHub; they are exercised by the next push.
`docs/assets/` (hero and logo images, untracked, created today by someone
else) is not part of this commit.

### Limitations and next tasks

* See `docs/limitations.md` "Skills": no YAML parser, hash-based conflicts
  without merging, no agent is run and review accuracy is not scored, `node`
  required for the JavaScript tasks, adapter paths need a release when a
  vendor moves.
* Milestone E (complexity) is next; `refactor-complexity` must then drop its
  "not implemented" paragraph and quote the real thresholds.
* The eval corpus has one reference per task; collecting agent runs with and
  without the skills (the protocol in `evals/README.md`) is maintainer work.

## Milestone E: complexity metrics, call graph, hotspots — DONE (2026-10-14)

Delivered (spec sections 0, 9, 13, 14 "Milestone E"):

* **Function facts in the IR** (`ir/model.py`: `ControlNode`, `CallSite`,
  `FunctionFact`, `ImportFact`, `ModuleBinding`; `ir/python_functions.py`,
  `ir/javascript_functions.py`, `ir/lines.py`). Every module body, class
  body, function, method, lambda and arrow is a *unit* with its qualified
  name, span, parameter count, statement count, logical lines, a
  language-neutral control tree, its call sites as written, locals and
  writes. Builders are iterative (explicit work stack, bottom-up freeze);
  nested units are stopped at and measured on their own, so a parent's
  numbers exclude nested bodies (documented in `docs/complexity.md`).
* **Metrics** (`complexity/{cyclomatic,cognitive,nesting,npath,size}.py`,
  `complexity/metrics.py`), one versioned convention each
  (`cyclomatic/1`, `cognitive/1`, `nesting/1`, `npath/1`, `size/1`),
  exposed as `metrics.complexity.conventions` and named in every finding.
  NPath is clamped at `npath_cap` at every node (no enumeration) and
  reported as `>= cap` with `saturated = true`. Per unit under
  `metrics.complexity.functions` (path, then source order, enclosing unit
  first), per file under `metrics.complexity.files`.
* **Rules** `CPLX001`-`CPLX004` (`rules/complexity.py`), warnings anchored on
  the unit's first line with the unit as scope; messages carry value,
  threshold and convention. A plain `check` never fails on them.
* **Call graph and coupling** (`complexity/callgraph.py`,
  `complexity/coupling.py`, `complexity/assemble.py`): edges classified
  `resolved` / `probable` / `unresolved` with a reason each, targets `unit` /
  `external` / `builtin` / `unresolved`; counts per class; fan-in/fan-out
  (builtins excluded, unresolved never counted); module edges for Python
  (absolute, relative, canonical package-rooted names, `from pkg import
  submodule` as a submodule edge) and JavaScript (`import`, `export ... from`,
  `export *`, `require`); iterative Tarjan SCC for cycles;
  shared-mutable-state notes. `CPLX005` per cycle member (at the closing
  import) and on fan-out above `fan_out_warn`. All under `metrics.graph`
  with `confidence` descriptions.
* **Hotspots** (`history/hotspots.py`): `log1p(churn) * normalized_complexity`
  at file granularity, `hotspots_formula` in the report, `null` with a reason
  when history or complexity is unavailable.
* **Diff mode** (`complexity/regressions.py`, `gating/diff.py`, `gate.py`):
  `metrics.complexity.regressions`, `gates.complexity_regressions` (`warn`
  default, `fail`, `ignore`), `gate.complexity_regressions`,
  `summary.complexity_regressions`; experimental
  `metrics.graph.abstraction_displacement` behind
  `complexity.abstraction_displacement = false` (every entry
  `confidence: approximate`, `experimental: true`, no rule ID).
* **Pipeline** (`analysis.py`): per-file phase (rules + unit measurement),
  cross-file phase (graph, `CPLX005`), then suppressions and fingerprints,
  so graph findings are suppressible and baselined. `build_report` takes
  the metrics, `collect_history` the complexity section, `gate.evaluate` the
  regression count; `api.analyze_paths`, `gating/diff.py` and the CLI use
  `analyze_files`.
* **Config**: `cyclomatic_counts_boolean_operators`, `npath_cap`,
  `npath_warn`, `fan_out_warn`, `abstraction_displacement` in `schema.py`,
  `defaults.toml`, `docs/configuration.md`; profiles inherit them (`minimal`
  keeps `enabled = false`, now with a comment);
  `cyclomatic_counts_boolean_operators = false` is a reported deviation.
* **Docs**: `docs/complexity.md` (new), `docs/rules.md`, `docs/limitations.md`,
  `docs/configuration.md`, `docs/architecture.md`, README, CHANGELOG,
  `schemas/report-v1.schema.json` and `schemas/diff-v1.schema.json`
  (additive), the `refactor-complexity` skill rewritten around the real
  commands and fields, `pre-commit-review` / `write-compliant-code` no longer
  say the rules are unimplemented.
* **Tests** (+47, 530 total): `tests/unit/test_complexity_metrics.py`
  (parity table of 12 equivalent construct pairs, identical control trees,
  Python-only and JavaScript-only constructs, boolean-operator switch, NPath
  saturation with exact 2^40 at a high cap, nested-unit exclusion, size
  convention, whitespace/rename invariance, helper extraction at depth 0 and
  1 in both languages, artificial splitting, report shapes, disabled family,
  per-path disable and inline suppression), `tests/unit/test_callgraph.py`
  (Python and JavaScript resolution classes: aliases, from-imports, relative
  imports, re-exports, default imports, `require`, higher-order passes,
  dynamic calls asserted unresolved, `self`/`this`, nested functions,
  builtins; canonical module names with `import json` next to an analyzed
  `json.py`; cycles in both languages with one `CPLX005` per member;
  fan-out; shared mutable state; SCC on a 5000-node chain; determinism),
  `tests/unit/test_complexity_diff.py` (regressions under warn/fail/ignore,
  plain check never failing, new-unit regressions, abstraction displacement
  off/on), hotspot computation in a temp git repository plus the unavailable,
  disabled and unparseable-file paths (`test_history.py`), CLI text/JSON/SARIF
  output and `rules explain CPLX002` (`test_cli.py`),
  `tests/property/test_complexity_fuzz.py` (Hypothesis grammar rendered to
  both languages: never raises, same tree and numbers). Golden corpus gains
  four reviewed `CPLX004` rows (fixture files with many `||`/`or` statements).

### Decisions (mine; review these)

1. **Units include the module body and class bodies**, not only functions,
   so module-level control flow has a number and file aggregates cover every
   line. A class body is a unit for its field initializers and class-level
   statements; methods are separate.
2. **Nested units are excluded from their parent** (brief), which means
   extracting deeply nested code lowers the file sum by the nesting
   increments it stops paying. The metamorphic extraction test therefore
   pins depth 0 and depth 1 (what "extract method" normally does); the depth
   >= 2 behavior is documented in `docs/complexity.md` and
   `docs/limitations.md` rather than asserted away.
3. **Comprehensions** belong to the containing unit. `cyclomatic/1` counts
   each `for` and `if` clause; `cognitive/1` and `nesting/1` count only the
   `if` clauses (a generator expression is linear, idiomatic code; counting
   the `for` made `metrics.py:file_aggregate`, ten `sum(... for ...)` calls
   in a dict literal, cognitive 10); `npath/1` treats a comprehension `for`
   as `(iterable - 1) + body` with no zero-iteration path.
4. **Cognitive operator runs** are counted per parenthesized group in source
   order (`a and (b or c) and d` is three runs); conditions are nested at
   the construct's inner level; `else`, `elif`, loop `else` and `try/else`
   are +1 without nesting; `case` arms add nothing beyond the `switch`.
   Explicitly not a Sonar score (registry, conventions block, every
   `CPLX002` message).
5. **NPath** follows the classic formulas with every intermediate clamped;
   `try` is `body * try_else + handlers`, then `* finally`; a `switch`
   without default adds one path. `npath_warn = 200` (PMD's classic
   default) and `npath_cap = 10000` are the defaults the brief asked for.
6. **Optional chaining is never counted** (consistent with `DEF004` treating
   `o?.x` as propagation); `??`, `&&=`, `||=`, `??=` count as one operator
   and one run each.
7. **Python module names are canonical**: a module's absolute name starts at
   the first directory with an analyzed `__init__.py`; nothing is matched by
   dotted suffix. The first self-run matched the standard library's `json`
   to `src/shockharness/output/json.py` and reported a 13-module cycle
   through the package `__init__`; both were resolution bugs, not code
   facts. `from pkg import mod` where every name is a submodule is an edge
   to the submodules, not to `pkg/__init__.py` (the facade pattern this
   package uses is not a cycle).
8. **Fan-out** = distinct targets of resolved + probable edges, analyzed units
   plus external symbols, builtins excluded (`len`, `console.log`); the
   message states the unresolved count that was not counted.
9. **Shared mutable state is a note** under `metrics.graph`, not a `CPLX005`
   finding: it is a module-local heuristic (no alias or cross-module
   tracking) and a finding would be noise on every module with a cache.
10. **Regression** = a head unit above a `CPLX001`-`CPLX004` threshold whose
    value grew since base; a unit absent at base counts as grown from
    nothing (a renamed complex function shows up once). Matching is by
    `path::name` key with an occurrence suffix for duplicate names.
11. **Hotspots** need both inputs; a file that failed to parse has churn but
    no score (it is omitted from the list, not scored 0).
12. **`collect_history`, `build_report` and `gate.evaluate` gained required
    parameters** rather than defaults (DEF001 applies to the tool itself);
    `shockharness.api` signatures are unchanged.
13. The self-compliance test now treats only `error` findings as offenders
    and asserts the complexity findings are unsuppressed warnings and that
    the tool's own module graph has no cycle. The brief said warnings are
    not blockers; the test previously asserted zero findings of any severity.

### Dogfooding: what the metrics found in the tool

First self-run, before any fix: the gate **failed** on 24 hard violations in
the new code (two `[:-1]` slices, nine `_Builder` dataclass defaults, eleven
`x if y is not None else z` ternaries, two `m[k] if k in m else None`
spellings), all fixed in code (explicit branches, required dataclass fields
built through a `_builder()` helper, `[: len(x) - 1]`); plus the two
resolution bugs of decision 7. Then 42 complexity warnings on the new code
itself; the genuinely tangled ones were refactored: `_UnitCollector._call`
(JavaScript, cognitive 49, nesting 5) into `_new_call` / `_member_call` /
`_mutation_through_call`; `collect_javascript_bindings` (cognitive 64,
nesting 6) into `_statement_bindings` / `_declaration_bindings` /
`_declarator_bindings`; `_import_statement` (39) and `_export_statement`
(32) around shared `_specifier_names` / `_import_clause`;
`_UnitCollector.run` (36) into `_seed` / `_method_member`;
`shared_mutable_state` (33) into `_mutable_bindings` / `_writers`.

Final self-run (`shockharness check src tests scripts evals`): **gate PASS**,
128 `CPLX` warnings (121 in `src/`, 6 in `tests/`, 1 in `evals/`): 61
`CPLX002`, 40 `CPLX004`, 23 `CPLX001`, 4 `CPLX003`, 0 `CPLX005`; 1245 units in
98 files, 6 NPath-saturated units (`gate.evaluate`, `config._deviations`,
`_Collector._call` in both defaults collectors, `_child_context` in both,
`update_skills`); graph: 2367 resolved / 761 probable / 1229 unresolved call
edges, 347 resolved / 260 external / 0 unresolved module edges, 0 cycles, 0
shared mutable bindings. Highest cognitive scores in `src/`:
`collect_python_bindings` 43, `complexity/cognitive.py:cognitive` 38,
`python_defaults._Collector._call` 38, `suppressions.apply_suppressions` 37,
`javascript_functions._UnitCollector._statement` 34 (a dispatcher),
`config._semantic_issues` 33, `gate.evaluate` 31. None of these is hidden,
none is suppressed, no threshold was raised. The pre-existing ones (Milestones
B-G code: `config.py`, `suppressions.py`, both `*_defaults.py` collectors,
`gate.py`, `skills/install.py`) are left as recorded warnings for a later
refactoring pass with their own behavior tests; the walkers in the new
extractors are long `if`/`elif` dispatchers over node kinds and are left as
such on purpose. Hotspots on the tool's own history (13 commits in the
90-day horizon): `ir/python_defaults.py` 0.470, `ir/javascript_catches.py`
0.461, `config.py` 0.404, `ir/javascript_defaults.py` 0.396,
`ir/python_catches.py` 0.337.

### Evidence (all run 2026-10-14 on macOS arm64)

```text
$ ruff check src tests scripts evals && ruff format --check src tests scripts evals
All checks passed!
96 files already formatted

$ pytest -q                      # CPython 3.11.11
530 passed in 18.37s
$ pytest -q                      # CPython 3.12.8
530 passed in 16.35s
$ pytest -q                      # CPython 3.13.1
530 passed in 17.17s
$ pytest -q                      # CPython 3.14.7
530 passed in 17.23s

$ shockharness check src tests scripts evals --format text   # self-gate
  ... 128 CPLX warning lines ...
  rules applied: MAGIC001, EXC001, EXC002, EXC003, DEF001, DEF002, DEF003, DEF004, DEF005, DEF006, CPLX001, CPLX002, CPLX003, CPLX004, CPLX005, SUPP001, SUPP002
  rules not implemented (not analyzed): MAGIC002
  complexity: 1245 unit(s) in 98 file(s); conventions cyclomatic/1, cognitive/1, nesting/1, npath/1; 6 NPath saturated; advisory (CPLX001-CPLX004 are warnings)
  graph: call edges 2367 resolved, 761 probable, 1229 unresolved; module edges 347 resolved, 260 external, 0 unresolved; 0 cycle(s); 0 shared mutable binding(s)
  history: 13 commit(s) in 90 day(s) before 2026-10-14T17:26:38-07:00 (file granularity); 126 co-change pair(s) with support >= 3
  hotspots (log1p(churn) * normalized cognitive, file granularity): src/shockharness/ir/python_defaults.py (0.470), src/shockharness/ir/javascript_catches.py (0.461), src/shockharness/config.py (0.404), src/shockharness/ir/javascript_defaults.py (0.396), src/shockharness/ir/python_catches.py (0.337)
  analysis status: complete
gate: PASS (exit 0)

$ shockharness config validate
shockharness: configuration is valid (dedicated: .../.shockharness.toml; profile strict)
  (20 boundaries, 3 overrides reported as deviations, as before)

$ python -m build
Successfully built shockharness-0.1.0a1.tar.gz and shockharness-0.1.0a1-py3-none-any.whl
```

Sample finding lines from the self-run:

```text
src/shockharness/gate.py:86:1: CPLX001 warning: cyclomatic complexity of function evaluate is 24, above cyclomatic_warn = 15 (convention cyclomatic/1)  [def evaluate(]
src/shockharness/gate.py:86:1: CPLX004 warning: NPath estimate of function evaluate is saturated at the cap (>= 10000) (convention npath/1; a bounded estimate, not an exact count)  [def evaluate(]
src/shockharness/suppressions.py:122:1: CPLX002 warning: cognitive complexity of function apply_suppressions is 37, above cognitive_warn = 15 (convention cognitive/1; not a Sonar score)  [def apply_suppressions(]
```

### Failures observed during development (and what was done)

* First self-run: `import json` resolved to `output/json.py` (dotted-suffix
  matching) and `from shockharness import gate` to the package `__init__`,
  producing a false 13-module cycle. Replaced suffix matching with canonical
  package-rooted names and submodule edges (decision 7); regression tests in
  `test_callgraph.py`.
* JavaScript import bindings never matched their module edge because the
  edge key derived a relative-import "level" from the leading dots of
  `./util.js`. The edge now carries the fact's level explicitly.
* `class` keyword tokens (anonymous tree-sitter nodes named `class`) were
  discovered as class units; unit discovery now requires named nodes.
* The golden corpus gained `CPLX004` rows on four fixture files whose module
  bodies are long runs of `||`/`or` fallback statements (NPath 256-512 per the
  convention); reviewed and kept.
* The tool's own gate caught 24 hard violations in the first draft of the
  new code (see Dogfooding); all fixed in code, none suppressed.

### Limitations and next tasks

* See `docs/limitations.md` "Complexity metrics and the call graph".
* The pre-existing high-cognitive functions listed above are candidates for
  a refactoring pass with the `refactor-complexity` skill and before/after
  graphs; not done here to keep the milestone to its scope.
* Per-function churn, rename following, change-impact radius and data flow
  remain Milestone H.
* `docs/shockharness_advanced_guardrails_spec.md` existed untracked in the
  tree before this session and is not part of this commit.

## Milestone H1: unknown finding status, fail_on_unknown, file roles — DONE (2026-10-16)

Scope: specification section 21, decisions 3 and 4 and the H1 row of 21.2
(guardrails brief Phase A, A1 and A4). Built on main at 68fa69a (0.3.0 plus
spec 21.1 decision 11). The report shape changed only additively, so
`schema_version` stays `"1"` (decision recorded in the 21.2 row: "bump if the
report shape changes"; additive fields are allowed under schema "1").

Delivered:

* `Finding.status` (`violation` | `unknown`), required on every construction,
  validated in `__post_init__`; JSON `findings[].status`, SARIF
  `properties.status` (`level` still from severity), text marker
  `RULE severity (unknown):`, diff `findings[].finding_status` (a diff
  finding's `status` already meant new/fixed/unchanged).
* `fail_on_unknown` per family; `gate.unknown`, `gate.unknown_gating_families`,
  a gate reason when unknown findings are reported only, the text line
  `unknown: N finding(s) the rules could not establish; fail_on_unknown
  families: ...`, `summary.by_status`.
* `src/shockharness/roles.py`: six roles, precedence generated > vendor >
  config > test > docs > production, `[tool.shockharness.file_roles]` with the
  documented defaults; `files[].role`, `files[].role_pattern`,
  `coverage.roles`, `summary.by_role`.
* `[[overrides]]` with `roles = [...]` (exactly one of `paths`/`roles`,
  validated), deviation `overrides[i] disables ... for file role(s) ...`,
  origin `overrides[i]`.
* The MAGIC001 configuration-file exemption on top of the config role;
  `rules.magic_numbers.configuration_files` as the legacy spelling, folded into
  `file_roles.config` at load time.
* Cache schema `"2"`; report and diff schemas, CHANGELOG `[Unreleased]` (with a
  Schema heading), `docs/rules.md` (Finding status, the five-state mapping, the
  inventory), `docs/configuration.md` (File roles, Unknown findings, overrides by
  role, precedence), `docs/limitations.md`, `docs/architecture.md`, README
  Configuration, and the `fix-violations` and `pre-commit-review` skills.
* This repository: the `tests/**` override is now `roles = ["test"]`
  (dogfooding); `test_file_roles.py::test_override_by_path_still_works` keeps
  the `paths` form tested.

### Unresolved-finding inventory (status decisions)

Every place in `src/` that produces an `unresolved` confidence, an `opaque`
handler body or a status decision, or constructs a `Finding`, is listed in
`tests/unit/test_unknown_inventory.py::SITES` with its decision; the test
AST-scans `src/shockharness` and fails on any function not listed (and on a
listed one that no longer exists), so a new unresolved finding cannot appear
without an explicit status decision here. One snippet per row below pins the
assigned status (`CASES`), and the golden corpus's nine unknown findings are
pinned (`CORPUS_UNKNOWN`); every `unresolved`-confidence finding in the corpus
is EXC001.

| # | Where | Finding | Confidence | Status |
|---|---|---|---|---|
| 1 | `rules/exceptions.py` `evaluate_approval` (identities from `ir/python_catches.py` `resolve_identity`, `SymbolTable.resolve_name`, `_bind_statement`) | EXC001, every unapproved identity is unresolved: unbound name, name rebound by assignment, `except errors[0]`, `except make()`, star import | unresolved | **unknown** |
| 2 | same | EXC001, an unresolved identity plus a resolved one no boundary approves (`except (Missing, KeyError)`, corpus `exc_tuple.py:21`) | unresolved | violation |
| 3 | same, inside a boundary approving the resolved member (`except (Missing, ValueError)` with ValueError approved) | EXC001, only the unresolved member stands in the way | unresolved | **unknown** |
| 4 | `rules/exceptions.py` `bare_status`; `ir/javascript_catches.py` `_rejection_handler` | EXC001, promise rejection handler referencing a function the module does not define (`p.catch(onError)`, corpus `exc_promise_catch.js:10`) | unresolved | **unknown** |
| 5 | `rules/exceptions.py` `_unresolved`, `manager_catches`, `bare_status` | EXC001, `with name:` whose capture-manager binding cannot be established (rebound, bound elsewhere, `with M() as name`) | unresolved | **unknown** |
| 6 | `rules/exceptions.py` `bare_status` | EXC001, capture manager with no readable exception-type argument (`suppress(*errors)`) | unresolved | **unknown** |
| 7 | `rules/exceptions.py` `evaluate_approval` via the manager's identities | EXC001, capture manager whose type argument does not resolve (`suppress(Missing)`) | unresolved | **unknown** |
| 8 | `rules/exceptions.py` `bare_status` | EXC001, bare `except:`; untyped JavaScript `catch (e)`; inline untyped rejection handler: each provably binds every exception | unresolved | violation |
| 9 | `rules/defaults.py` `fact_status` (facts from `ir/python_defaults.py`) | DEF002 `m.get(k, v)`, `m.setdefault(k, v)`, `m.pop(k, v)` on a receiver not proven a mapping (corpus `def_mapping_get.py:19,35`) | approximate | **unknown** |
| 10 | same | DEF002 review `m.get(k)` on a receiver not proven a mapping (corpus `def_mapping_get.py:20,47`) | approximate | **unknown** |
| 11 | `rules/exceptions.py` `_manager_match`, `ir/python_catches.py` `_resolve_callee` | unresolved manager callee matched by bare name | approximate | violation (no unknown: the manager is listed by name) |
| 12 | `complexity/callgraph.py` (7 functions), `complexity/coupling.py` (4) | unresolved call and module edges | unresolved | no finding: metrics only; CPLX005 counts resolved targets and names the unresolved count |
| 13 | `rules/exceptions.py` `_finding` (EXC002, EXC003), `rules/defaults.py` `_finding` (other DEF kinds, DEF005), `rules/magic_numbers.py`, `rules/complexity.py`, `suppressions.py` (SUPP001, SUPP002) | everything else, including approximate EXC003 (unattributable statement), DEF003/DEF004 (non-constant fallback) and DEF005 (static trace): the approximation is about intent, not about whether the shape is present | exact/approximate | violation |

Not turned into unknown findings (they would add findings, which H1 must not
do; recorded in `docs/limitations.md`): a capture manager with one readable
type and further unreadable arguments (`suppress(OSError, *more)`, judged by
the readable type alone; `ManagerCall.unreadable_arguments` is collected but
not used by the rule), and a unit whose unresolved calls could push it over
`fan_out_warn`.

### Defaults chosen, and why

| Key | Default | Why |
|---|---|---|
| `rules.exceptions.fail_on_unknown` | `true` | EXC001 already fails closed (spec 21.1 decision 3's example); rows 1, 3-7 are error findings that failed the gate in 0.3.0 and must keep doing so |
| `rules.defaults.fail_on_unknown` | `true` | rows 9-10: DEF002 on an unproven receiver was an `error` that failed the gate in 0.3.0 (`def_mapping_get.py`); `false` would have turned that fixture's gate from fail to pass, against the "same verdicts as 0.3.0" requirement. The family therefore "already fails closed" in decision 3's sense |
| `rules.magic_numbers.fail_on_unknown` | `false` | the spec's default; MAGIC001 is exact and produces no unknown findings, so either value gives 0.3.0's verdicts |
| `complexity.fail_on_unknown` | `false` | the spec's default; CPLX findings are never unknown and are advisory under either value |
| profiles | unchanged | no profile sets `fail_on_unknown`; `recommended`/`minimal` cap severities instead, which already keeps their unknown findings from gating where they were not gating before |
| `file_roles.*` | as the brief | test, config (= the 0.3.0 `configuration_files` list), generated, vendor, docs exactly as specified; `examples/` stays production |

Interpretations (mine; review these):

1. **Where `fail_on_unknown` lives for complexity.** The brief says
   `rules.<family>.fail_on_unknown`; the complexity family has no table under
   `rules` (its settings are `[tool.shockharness.complexity]`), so the key is
   `complexity.fail_on_unknown`, next to the family's other settings. The three
   others are `rules.magic_numbers`, `rules.exceptions`, `rules.defaults`.
2. **Unknown and non-gating means counted only in `gate.unknown`.** It adds to
   none of `hard_violations`/`warnings`/`review`; a gating unknown finding is
   counted by severity as before and also in `gate.unknown`. The diff summary's
   `*_hard_violations` use the same predicate.
3. **Mixed catches.** One resolved type that no boundary approves makes the
   catch a violation whatever else it names (row 2); unknown only when nothing
   but unresolved identities stands in the way.
4. **`conftest.py` is config by default.** The default config list contains
   `conftest.py` and config precedes test, so `**/conftest.py` in the test list
   only applies when a project leaves `conftest.py` out of its config role. This
   keeps the 0.3.0 MAGIC001 exemption of `conftest.py` unchanged. Consequence
   for this repository: with `roles = ["test"]`, `tests/conftest.py` (role
   config) lost its override and the self-gate failed on one MAGIC001
   (`tests/conftest.py:103`, a literal `2`). Since that file is pytest fixtures
   and helpers, not tooling configuration, `.shockharness.toml` now sets
   `[tool.shockharness.file_roles] config = []` (the repository analyzes no
   tooling configuration files; it already had `exclude_configuration_files =
   false`), so `tests/conftest.py` is `test` by `tests/**`.
5. **A generated/vendor file that a config glob also matches** (e.g.
   `vendor/pkg/setup.py`) keeps the 0.3.0 MAGIC001 exemption even though its
   role is vendor; "files whose role is config skip MAGIC001" taken literally
   would have added findings for such files. The `rules_disabled` reason says
   the role took precedence.
6. **Legacy `configuration_files`.** Set alone it *replaces* the config role's
   globs (as it replaced the exempt list in 0.3.0; merging it with the default
   would have widened the exemption for such configurations); set together with
   `file_roles.config` the two are merged. Only a user source counts as "set"
   (origin `cli`/`dedicated`/`pyproject`), and a config note says which case
   applied.
7. **Rule-disable reason text changed** for the configuration-file exemption
   (`file role is config (pattern 'conftest.py'; exclude_configuration_files =
   true)`); its origin `configuration_file` is unchanged. Not a verdict change.
8. **New schema properties are optional** in `schemas/report-v1.schema.json`
   (as `summary` was in 0.2.0), so 0.3.0 reports still validate.

### Regression against 0.3.0

`tests/fixtures/profile_verdicts_0.3.0.json` was generated by running the new
test module's snapshot function against the unmodified 0.3.0 code (68fa69a,
before any H1 source change), then committed; the H1 code is compared against
it (169 tests: 55 fixtures alone with their own settings and the corpus as one
tree, under each of the three profiles, plus a coverage check; finding sets with rule, span,
severity, confidence, message digest, suppression; gate status, exit code and
counts). New fields are not compared.

```text
$ python -m tests.unit.test_profile_regression <scratch>/snap2     # at 68fa69a, before any src change
$ pytest -q tests/unit/test_profile_regression.py                  # at 68fa69a
169 passed in 1.22s
```

Corpus verdicts recorded there (unchanged by H1): strict `error` exit 3 (370
hard, 7 warnings, 29 review, 2 parse failures), recommended `error` exit 3 (347
hard), minimal `fail` exit 1 (5 hard: SUPP001).

Self-gate per profile, 0.3.0 (68fa69a) vs H1, `check src tests scripts evals
--profile P --no-cache`, gate `[status, exit, hard, warnings, review,
suppressed, analysis_failures]`:

```text
strict      0.3.0 ['pass', 0, 0, 165, 10, 0, 0]   H1 ['pass', 0, 0, 165, 10, 0, 0]   same
recommended 0.3.0 ['pass', 0, 0, 165, 10, 0, 0]   H1 ['pass', 0, 0, 165, 10, 0, 0]   same
minimal     0.3.0 ['pass', 0, 0, 165, 10, 0, 0]   H1 ['pass', 0, 0, 165, 10, 0, 0]   same
```

The existing 619 tests pass unchanged except one expectation that lists the
known keys of `rules.magic_numbers` (now including `fail_on_unknown`,
`tests/unit/test_schema.py`).

### Evidence (all run 2026-10-16 on macOS arm64)

```text
$ ruff check src tests scripts evals && ruff format --check src tests scripts evals
All checks passed!
105 files already formatted

$ pytest -q                      # CPython 3.11.11 (uv venv under the session scratchpad)
896 passed in 43.24s
$ pytest -q                      # CPython 3.12.8
896 passed in 32.67s
$ pytest -q                      # CPython 3.13.1
896 passed in 33.13s
$ pytest -q                      # CPython 3.14.7 (.venv)
896 passed in 25.64s

$ shockharness check src tests scripts evals           # self-gate, cache on: cold run, then warm run
cold exit 0 (cache: 0 hits, 107 misses); warm exit 0 (107 hits, 0 misses)
$ shockharness check src tests scripts evals --no-cache
no-cache exit 0
JSON reports with coverage.cache removed: cold == warm == no-cache (byte-identical)
shockharness 0.3.0: 107 file(s), 107 analyzed, 0 failed; 175 finding(s), 0 suppressed
  by severity: review=10, warning=165
  policy deviation: overrides[1] disables MAGIC001, DEF001 for file role(s) test: Test code encodes literal expected outputs and pytest fixture signatures
  analysis status: complete
  unknown: 0 finding(s) the rules could not establish; fail_on_unknown families: exceptions, defaults
gate: PASS (exit 0)
coverage.roles: config 0, docs 0, generated 0, production 67, test 37, vendor 0

$ shockharness check python/exc_unresolved.py python/def_mapping_get.py --no-cache   # copy of the golden corpus
python/exc_unresolved.py:25:5: EXC001 error (unknown): except handler of 'MyError' is forbidden: 'MyError' could not be resolved to a known exception (...); strict mode fails closed  [except MyError as exc:]
python/def_mapping_get.py:19:13: DEF002 error (unknown): payload["items"] falls back to [] when the key is missing; .get(key, fallback) substitutes the fallback for a missing key; the receiver's type is not established, so this is approximate  [items = payload.get("items", [])]
  unknown: 8 finding(s) the rules could not establish; fail_on_unknown families: exceptions, defaults
gate: FAIL (exit 1)
# same file with rules.exceptions/defaults.fail_on_unknown = false:
  policy deviation: rules.exceptions.fail_on_unknown is false (profile 'strict': true); EXC001-EXC003 findings whose status is unknown are reported and never fail the gate
  unknown: 4 finding(s) the rules could not establish; fail_on_unknown families: none
gate: FAIL (exit 1)        # the 7 resolved, unapproved catches in the fixture still fail it
  4 unknown finding(s) (the rule could not establish the property) are reported only: their family's fail_on_unknown is false

$ python -m build --outdir <scratch>/dist .
Successfully built shockharness-0.3.0.tar.gz and shockharness-0.3.0-py3-none-any.whl
$ python scripts/consumer_upgrade_check.py --dist <scratch>/dist --examples examples --wheelhouse <scratch>/wheelhouse
consumer upgrade check: 2 example(s), 14 step(s), 0 failed
```

The wheel was built into the session scratchpad, not `dist/`, so the 0.3.0
release artifacts there are untouched; the version is still 0.3.0 (not
bumped). Determinism with unknown findings and several roles:
`test_unknown_status.py::test_unknown_report_is_byte_identical_across_five_runs`
(five `check --format json` runs, the first cold, byte-identical with
`coverage.cache` removed).

New tests: `test_profile_regression.py` (169), `test_unknown_inventory.py`
(19), `test_unknown_status.py` (25), `test_file_roles.py` (64); 619 + 277 =
896 (one existing expectation rewritten, none removed).

### Failures observed during development (and what was done)

* Migrating the repository's `tests/**` override to `roles = ["test"]` failed
  the self-gate on `tests/conftest.py:103` (MAGIC001): that file's role is
  config under the documented precedence. Resolved by classifying it as test in
  this repository's own `file_roles` (interpretation 4), not by widening the
  override.
* `analysis.finish` grew past `max_lines_warn` (CPLX006) with the role fields;
  the two `FileResult` constructions now share `_file_result`, and the
  self-gate's warning count is back to 0.3.0's 165.
* The first snapshot of the 0.3.0 verdicts was 730 KB (full messages, indented
  arrays); messages are now compared by SHA-256 prefix and scalar arrays are
  written on one line (258 KB).

### Not run here

* CI (nothing pushed): Windows, Linux and the wheel job run when the
  maintainer pushes. Paths in the new tests are POSIX strings and no test
  writes a filesystem path into TOML.
* `ruff check .` (wider than CI's scope) reports one pre-existing import-order
  issue in `examples/python/tests/test_example_service.py`; not touched.

### Limitations and next tasks

* H2 (verification integrity) can scope VERIFY rules by role (`test`) and
  H3's STUB/ASSERT rules by `production`; both read `files[].role`.
* The two shapes listed under the inventory that are not yet unknown findings
  (unreadable extra manager arguments; fan-out with unresolved calls).

## Milestone H2 part 1: VERIFY001, VERIFY002, VERIFY004 — DONE (2026-10-16)

Implemented in the lead session (the maintainer chose "do it here"). Spec section
21.2, H2 row: diff-based detection of a change weakening its own verification.
VERIFY003 (semantic diff of policy files, workflows and baselines), the
`--policy FILE` tier, the `verification-integrity` skill and adversarial policy
PR fixtures are part 2 and are not built here.

### What was built

* **Facts** (`ir/model.py`: `SkipMarker`, `SuppressionDirective`, `CaseFact`,
  `Tautology`, `VerificationFacts`; `ModuleFacts.verification`), extracted with
  every other fact and cached with them (cache schema "3"):
  `ir/python_verification.py`, `ir/javascript_verification.py`,
  `ir/suppression_directives.py`.
* **Rules** (`rules/verification.py`): `compare_revisions` compares each head
  file with its base version (same path, or the path `git diff -M` reports it
  was renamed from: `history/git.py:renamed_files`) and reports only what was
  added, as a multiset difference keyed on (test, kind, text) for markers,
  (tool, text) for directives, (test, text) for tautologies, and test name for
  assertion counts.
* **Diff integration** (`gating/diff.py`): the VERIFY findings join the head
  revision before fingerprint classification, so they flow through `new`,
  legacy handling, the gate, `--exit-zero`, JSON, text and SARIF unchanged.
* **Registry**: VERIFY001, VERIFY002, VERIFY004 implemented with full metadata;
  VERIFY003 registered as planned; finding categories (`policy_integrity`,
  `contract_integrity`, `structural`) per family; `needs_base_revision`.
* **Config**: `[tool.shockharness.rules.verification]` (`enabled`, `severity`,
  `fail_on_unknown`, `allowed_skip_reasons`, `report_narrow_suppressions`).
* **Reports**: `findings[].category`, `coverage.verification`,
  `coverage.rules_needing_base_revision`, `summary.by_category`, diff
  `summary.new_policy_integrity`, SARIF `properties.category` and rule
  `properties.needs_base_revision`; both schema files updated (additive).
* **Suppressions**: `shockharness: ignore[VERIFY...]` is SUPP001.

### Decisions (beyond the brief)

1. **Severity semantics.** `rules.verification.severity` *is* the severity of
   every VERIFY finding (`warning` | `error` | `review`), not a cap like the
   other families' `severity` key: the documented default is `warning`
   (decision 9) and the knob has to be able to *raise* it. `error` tightens
   and is not a deviation; `review` is.
2. **Not suppressible inline** (decision 5): a change could otherwise excuse
   its own skip with a comment it adds itself. Exceptions are
   `allowed_skip_reasons` or `[[overrides]]` by path or role.
3. **Role scopes.** VERIFY001/004: test role only. VERIFY002: every role except
   `generated` and `vendor` (regenerated code legitimately carries blanket
   `eslint-disable` headers).
4. **Unknown, not guessed.** Base version unanalyzable, or rename detection
   failed and the file has no base under its own path: findings are `unknown`
   (confidence `unresolved`); `fail_on_unknown` defaults to `false`.
5. **Identity ignores free text.** An eslint `-- description` and a
   ShockHarness `reason="..."` are not part of a directive's identity, so
   rewording them is not a new suppression.
6. **`@ts-expect-error` is blanket** (names no code), the strict reading.
7. **Assertions** are counted syntactically, including calls whose name starts
   with `assert`/`expect` (helpers such as `assert_frame_equal`) so that a test
   delegating to such helpers is not reported as having lost its assertions.
8. **Self-compliance caught two violations in the new code** before commit:
   `m[k] if k in m else []` (DEF002) in `gating/diff.py` and
   `"" if variant is None else variant` (DEF004) in
   `ir/suppression_directives.py`; both rewritten as statements.

### Evidence (2026-10-16, macOS, all commands from the repository root)

```text
$ ruff check src tests scripts evals && ruff format --check src tests scripts
All checks passed!
110 files already formatted

$ shockharness check src tests scripts                 # cold, warm, --no-cache
gate: PASS (exit 0)    (three times)

$ pytest -q        # CPython 3.11.11 / 3.12.8 / 3.13.1 / 3.14.7
969 passed         (on each)

$ python -m build && python scripts/consumer_upgrade_check.py --dist dist --examples examples
consumer upgrade check: 2 example(s), 14 step(s), 0 failed
```

New tests: `tests/unit/test_verification_facts.py` (38),
`tests/unit/test_verification_rules.py` (23), `tests/cli/test_verification_cli.py`
(11), plus registry and inventory updates (`rules/verification.py:_finding` is
inventoried: violation, or unknown with confidence unresolved).

Verdicts against published 0.3.0 (`pip install shockharness==0.3.0`), same
inputs, all three profiles: golden fixtures (410/400/402 findings, exits 3/3/1),
both examples, and the self-scan (192 findings, exit 0; 0.3.0 run with the
pre-H1 `.shockharness.toml`) are **identical**. VERIFY rules never run under a
plain `check`, so no existing verdict can change.

Determinism: five consecutive `check src tests --format json` runs are
byte-identical with `coverage.cache` removed; two `diff` JSON runs on the same
revisions are byte-identical (tested).

Self-diff: the working tree committed in a scratch clone and gated against the
H1 commit (`gate --base HEAD~1 --head HEAD`): 114 files compared (7 new, 0
renamed, 0 with an unanalyzable base), **no VERIFY findings**, 0 new hard
violations, `gate: PASS (exit 0)`.

### Next

H2 part 2: VERIFY003 (semantic diff of `.shockharness.toml`, workflows,
baselines and tool configuration against the trusted base), the `--policy FILE`
tier (spec 21.1 decision 6), the `verification-integrity` skill, and adversarial
PR fixtures. The next release waits for it, per the maintainer.

## Milestone H2 part 2: VERIFY003, --policy tier, verification-integrity skill — DONE (2026-10-16)

Implemented in the lead session (the maintainer chose "do it here"). Spec section
21.2, H2 row, second half; spec 21.1 decision 6 (the policy tier). With part 1
this completes H2; release 0.4.0 waits for the maintainer.

### What was built

* **Loosening test** (`loosening.py`), shared by the policy tier and VERIFY003:
  new deviation lines (list indices normalized, multiset difference, so
  reordering is not a loosening), ordered settings moved to their looser end
  (gate modes, `unsupported_sources`, `parse_errors`, VERIFY severity, fan-out
  severity), raised complexity thresholds, a narrower `include` or wider
  `exclude`. One entry per key.
* **VERIFY003** (`rules/policy_integrity.py`): each revision's export is
  snapshotted (committed configuration loaded as `check` would, tool
  configuration files, workflows, baselines, and the head tree's file scope under
  both configurations). `compare_policy` reports configuration loosenings,
  dropped files (first five listed), baseline growth, workflow tampering
  (`rules/workflows.py`, line-based, no YAML library) and tool-config loosening
  (`rules/tool_configs.py`: ruff, flake8, pytest, coverage, JSON ESLint; stdlib
  `tomllib`, `configparser`, `json`, `shlex`). An unreadable or unparseable side
  makes the finding `unknown` (inventoried in
  `tests/unit/test_unknown_inventory.py`).
* **`--policy FILE`** (`config.py`): refused inside the root (exit 2); layered
  between profile and repository; a repository key that would loosen a policy
  key is dropped and recorded as `PolicyAttempt` (`config.policy_attempts`, a
  config note, and a VERIFY003 finding at the key's line, in `check` too).
  `config.policy` carries the path, the SHA-256 of the canonical JSON and the
  keys.
* **Strictest of base** (`strictest_verification`): in a diff the VERIFY rules
  run with the stricter of the run's and the base revision's
  `rules.verification`.
* **Reusable workflow**: `check.yml` gains `policy-repository`, `policy-ref`,
  `policy-path` and a `policy-token` secret.
* **Skill**: `verification-integrity` (fifth skill; the generic pointer line
  and every count derive from `SKILL_NAMES`).
* **Reports**: `config.policy`, `config.policy_attempts`,
  `coverage.verification.policy`, `coverage.verification.policy_attempts`;
  both schema files updated (additive). The test suite's schema checker now
  understands union types (`["object", "null"]`).

### Decisions (beyond the brief; review these)

1. **`check.yml` takes a repository, not a path.** The brief asked for a policy
   path input, but any path inside the checked-out workspace is editable by the
   change under review and is refused by `--policy`. The workflow clones
   `policy-repository` at `policy-ref` (a branch or tag: `git clone --branch`
   does not take a commit) into `$RUNNER_TEMP` and passes that path. A private
   policy repository needs the `policy-token` secret; the token is used only in
   the clone URL of that step.
2. **Strictest of base.** Without it a change could set
   `rules.verification.enabled = false` (or `severity = "review"`, or an
   allowed skip reason for its own skip) and the rules reporting it would obey
   the head. The loosening is reported by VERIFY003 and applies after merge.
   `tests/cli/test_verification_cli.py` now commits the allowed reason at base,
   and a new test checks that a same-change exemption does not apply.
3. **Command-line overrides stay above the policy.** `--profile` and
   `--parse-errors` are the operator's (the layer order in spec 19 puts the CLI
   last). A `--profile` looser than the policy's adds a config note, and a
   workflow that adds `--profile minimal|recommended` or `--parse-errors warn`
   to a ShockHarness job is a VERIFY003 finding. The reusable workflow has no
   input for either flag.
4. **A list is one policy key.** A repository `exclude` that extends the
   policy's list is an attempt and the policy's list applies, rather than a
   merge.
5. **A tightening of a policy key is allowed** (a lower threshold, a stricter
   severity); only loosening is reverted.
6. **Boundaries are loosenings.** A new `[[rules.exceptions.boundaries]]` entry
   is a deviation, so it is a VERIFY003 finding. This change itself adds eight
   (the new modules read external files) and the self-diff reports exactly
   those eight, at warning. All of them anchor at the first boundaries header,
   because a TOML array-of-tables entry has no key of its own to find.
7. **Workflows only at the repository top level**: when `--root` is a
   subdirectory, `.github/workflows` is outside the analysis and
   `coverage.verification.policy.workflows_checked` is false, with a note.
8. **Complexity in the new code**: the first self-diff showed new CPLX warnings
   on `take_snapshot`, `_config_findings`, `parse_jobs`, `workflow_loosenings`,
   `_ini`, `tool_loosenings`, `diff_revisions` and `load_config_with_overrides`;
   each was split into named steps. The final self-diff adds no CPLX finding.
9. **Self-compliance caught**: a `-1` step in `range` (rewritten with
   `reversed`), five DEF004 and three DEF002 fallbacks, three EXC003 try bodies
   that returned a tuple (now a single call followed by the return), and a
   DEF003 review `a.startswith(x) or a.startswith(y)` (now one `startswith`
   with a tuple). Eight new boundaries are declared in `.shockharness.toml`.

### Evidence (2026-10-16, macOS, all commands from the repository root)

```text
$ ruff check src tests scripts evals && ruff format --check src tests scripts
All checks passed!
119 files already formatted

$ rm -rf .shockharness-cache; shockharness check src tests scripts   # cold, then warm
gate: PASS  191 findings  (cache hits 0 / misses 122, then 122 / 0)
$ shockharness check src tests scripts --no-cache
gate: PASS (exit 0)

$ pytest -q        # CPython 3.14.7
1022 passed
$ pytest -q        # CPython 3.11.11 / 3.12.8 / 3.13.1 (fresh uv environments)
1021 passed, 1 skipped   (on each; the skip is the wheel test, `build` not installed there)

$ python -m build && python scripts/consumer_upgrade_check.py --dist dist --examples examples
consumer upgrade check: 2 example(s), 14 step(s), 0 failed
```

New tests: `tests/cli/test_policy_integrity_cli.py` (14: adversarial fixtures
(a) to (i) parametrized, (j) the policy attempt, an untouched repository,
`check --policy`, a policy inside the root, and a plain check without a policy;
reports validated against both schemas), `tests/unit/test_policy_tier.py` (10),
`tests/unit/test_loosening.py` (9), `tests/unit/test_tool_configs.py` (8),
`tests/unit/test_workflow_loosening.py` (8), plus updates to the registry,
config, report, inventory, workflow and verification CLI tests.

Adversarial fixtures, each one head commit on a small repository whose base
sets `rules.verification.severity = "error"`; `gate` exits 1 on every one with
a `new`, `error`, `policy_integrity` finding: (a) magic numbers disabled,
(b) `exclude = ["src/**"]` (dropped files), (c) `it.only`, (d) `assert True`,
(e) a baseline fingerprint added, (f) `continue-on-error: true`, (g) the gate
job deleted, (h) `--exit-zero`, (i) a ruff per-file-ignore, (j) a repository
`cognitive_warn = 40` against a policy's 15 (reverted, attempt recorded).

Verdicts against published 0.3.0 (`pip install shockharness==0.3.0`), same
inputs, all three profiles, no `--policy`: golden fixtures (410/400/402
findings, exits 3/3/1), both examples, and the self-scan (191 findings, exit 0;
0.3.0 run with the pre-H1 `.shockharness.toml` plus this change's eight new
boundaries) are **identical**.

Determinism: three `check src tests --format json --no-cache` runs are
byte-identical with `coverage.cache` removed.

Self-diff: the working tree committed in a scratch clone and gated against H2
part 1 (`gate --base b608940 --head HEAD`): 123 files compared (9 new),
VERIFY001-VERIFY004 applied, policy configuration `compared`, five policy files
checked (three workflows, `.shockharness.toml`, `pyproject.toml`); new findings
are exactly the eight VERIFY003 boundary additions (warning); `gate: PASS
(exit 0)`.

### Failures observed during development (and what was done)

* One run of the 3.12 suite, in parallel with the 3.11 and 3.13 suites,
  reported one failure that was not captured; two more parallel runs and a
  serial run passed on every version. Running the three suites in parallel also
  made a concurrent warm self-gate miss the cache: the suites' own self-scan
  writes the repository's `.shockharness-cache`. The cold/warm figures above
  were taken with nothing else running.
* The first test of fixture (d) used `assert LIMIT == LIMIT`, which VERIFY004
  does not treat as a tautology (it judges equal *constants* only, as
  documented); the fixture now uses `assert True`.

### Limitations and next tasks

* Listed in `docs/limitations.md` (VERIFY001-VERIFY004): workflow text parsing,
  tool configuration at the root only, ESLint flat config not read, baselines by
  file name, and the CLI overrides above the policy.
* Release 0.4.0 (H1 + H2) when the maintainer asks: bump, changelog date, pins
  in the examples and docs (`docs/configuration.md` already shows `@v0.4.0` for
  the policy inputs), tag after CI.

## Feedback round F4 (planned 0.5.0) — DONE (2026-10-16)

Input: `docs/shockharness-suggestions-4.md` (notes from agents running
ShockHarness on MetaList; spec 21.1 decisions 12, 13 and 18). Implemented in
the lead session; Milestone H3 follows.

### What changed, per item

1. **Decorator `.get`** (`ir/python_defaults.py:_decorator_gets`): a
   `.get`/`.pop`/`.setdefault` call that is itself a decorator is claimed
   before the fact pass and produces nothing.
2. **Checked then raised** (`_checked_lookups`, `_checked_then_raised`): a
   `None`-fallback lookup assigned to a name, followed immediately by an `if`
   without `else` whose body only raises and whose test is `x is None`, `not x`,
   `not callable(x)`, `not isinstance(x, ...)` or an `or` starting with one.
3. **Discarded removal**: `m.pop(k, None)` as an expression statement is fact
   kind `discarded_removal`, reported at `review` in every mode but `allow`,
   status by receiver as before.
4. **Grouping idiom** (`_mutated_accumulator`): `m.setdefault(k, <empty
   container>)` whose result is mutated in place.
5. **Remediation**: DEF002's registry remediation and guarantees, `docs/rules.md`
   and the `fix-violations` skill name the three cases.
6. **`recommended`** sets `rules.defaults.fail_on_unknown = false`. The
   `fail_on_unknown` deviation is now measured against `strict` (the bundled
   defaults) rather than the selected profile, so the profile's own setting is
   listed as a deviation like its other changes.
7. **`shockharness exceptions`** (`inventory.py`, `schemas/exceptions-v1.schema.json`).
   Each `FileResult` now carries its parsed suppression comments
   (`suppressions`), taken from the cached facts; it is not serialized, so check
   reports and the cache are unchanged.
8. **Skills**: propose-a-rule steps (`fix-violations`, `pre-commit-review`),
   output validation (`write-compliant-code` principle 7), the "absence is
   normal" worked example; all examples pass `shockharness check` themselves.
9. **Docs**: Python 3.10 projects and empty trees (`docs/integration.md`),
   covered-versus-planned checks (`docs/limitations.md`), the inventory
   (`docs/configuration.md`), README links outside the adoption section (which
   stays byte-identical to the skills'), and the architecture table (it was
   also missing the H2 modules; added).

### Decisions (mine; review these)

1. **Exemptions are claimed in a pre-pass**, not decided in the rule: the
   facts never exist, so DEF002 cannot be configured back on for them. They
   are documented as "not fallbacks" in the rule's guarantees.
2. **Checked-then-raised is strictly the next statement**, in the same block,
   with a raise-only body and no `else`. Anything looser (a statement between,
   a `return` instead of a `raise`) stays reported; the brief's acceptance
   cases pin both sides.
3. **`fail_on_unknown` deviation reference.** Measuring against the selected
   profile would have hidden `recommended`'s new value. Measuring against
   `strict` keeps every looser-than-strict setting visible, as the brief asks;
   the deviation text is unchanged ("(profile 'strict': true)").
4. **`exceptions` lists repository and policy `exclude` patterns only.** The
   bundled excludes (`.git`, `node_modules`, ...) are defaults, not exceptions,
   and would bury the list.
5. **No new configuration keys.** Every item is either a precision fix or a
   profile value, so VERIFY003 and the `--policy` tier need no change.

### Regression against 0.4.0

`pip install shockharness==0.4.0` against this tree, same inputs, all three
profiles: the self-scan (198 findings) and both examples are identical. The
golden fixtures differ by exactly one finding in every profile:
`python/def_mapping_get.py:47` (`raw = table.get("raw")` followed by
`if raw is None: raise KeyError`), removed by item 2; exit codes are unchanged
(3/3/1). Under `recommended`, item 6 moves two unknown DEF002 findings in that
fixture out of the gate counts (hard 12 -> 10, review 3 -> 1; the corpus 347 ->
345 and 42 -> 40). `tests/unit/test_profile_regression.py` now applies these
listed differences to the 0.3.0 snapshot before comparing, so any other change
still fails it.

### Evidence (2026-10-16, macOS)

```text
$ ruff check src tests scripts evals && ruff format --check src tests scripts
All checks passed!
122 files already formatted

$ rm -rf .shockharness-cache; shockharness check src tests scripts   # cold, then warm
gate: PASS  191 findings  (cache hits 0 / misses 125, then 125 / 0)
$ shockharness check src tests scripts --no-cache
gate: PASS (exit 0)

$ pytest -q        # CPython 3.14.7
1034 passed
$ pytest -q        # CPython 3.11.11 / 3.12.8 / 3.13.1
1033 passed, 1 skipped   (on each; the skip is the wheel test, `build` not installed there)

$ python -m build && python scripts/consumer_upgrade_check.py --dist dist --examples examples
consumer upgrade check: 2 example(s), 14 step(s), 0 failed
```

Determinism: three `check src tests --format json --no-cache` runs are
byte-identical with `coverage.cache` removed; two `exceptions --format json`
runs (cached and `--no-cache`) are byte-identical (tested).

Self-diff in a scratch clone against 899c5e5 (the plan commit): 126 files
compared (3 new), `gate: PASS (exit 0)`, no VERIFY finding. The only new
findings are three CPLX warnings on `config.py:_deviations`, which carries the
same numbers in 0.4.0; they are "new" because its signature changed
(`profile_values` -> `strict_values`). The first self-diff also flagged new
complexity in `_exemptions` (cognitive 50), `_tests_absence`,
`_checked_then_raised`, `inventory._suppressions` and one test; each was split
into named steps, and a DEF003 review on a boolean `or` return was rewritten.

New tests: `tests/unit/test_def002_precision.py` (7: each acceptance case of
items 1-6), `tests/cli/test_exceptions_cli.py` (4: every item with its source,
JSON schema and byte identity, profile/policy origins, exit codes), plus the
updated golden, inventory, profile and regression expectations.

### Failures observed during development (and what was done)

* Two hand-counted line numbers in the new tests were off by one; corrected
  against the analyzer's output.
* A handmade baseline in a test lacked `schema_version`; the test now builds it
  from the module's version constants.
* Rewriting `tests/fixtures/expected.json` with the wrong indentation produced a
  6,000-line diff; it was rewritten with its original two-space indent, so the
  diff is the one removed finding.
* macOS `sed` has no `\b`; a rename done with it silently did nothing and was
  redone with Python.

## Milestone H3: syntax-level guardrails — DONE (2026-10-16)

EXC004, STUB001, STUB002, ASSERT001, BOOL001, STATE001 and IMPORT001, as
recorded in spec 21.2 (H3 row) and 21.1 decisions 14 and 19. Implemented in the
lead session; not released.

### What was built

* **Facts** (`ir/model.py`: `FinallyExit`, `Placeholder`, `AssertFact`,
  `BooleanArgument`, `ImportTimeCall`, `GuardrailFacts`;
  `ModuleFacts.guardrails`), extracted by `ir/python_guardrails.py` and
  `ir/javascript_guardrails.py` and cached with the other facts (cache schema
  "4"). STUB002 reads the existing import facts; STATE001 the existing binding,
  `global` and write facts (the same ones `metrics.graph.shared_mutable_state`
  uses).
* **Rules** (`rules/guardrails.py`), run in the per-file phase after the
  defaults rules. IMPORT001 resolves callees through the file's own imports
  (`import subprocess as sp`, `from os import system`, `import { execSync } from
  "node:child_process"`, `require`).
* **Registry**: seven implemented rules with full metadata; families `stubs`,
  `assertions`, `import_effects` (contract_integrity) and `boolean_arguments`,
  `module_state` (structural).
* **Config**: `rules.stubs`, `.assertions`, `.boolean_arguments`, `.module_state`,
  `.import_effects` (enabled, severity, roles, plus each rule's catalogs and
  permissions); deviation lines for every loosening; the five severities in the
  loosening order, so VERIFY003 and `--policy` cover them.

### Decisions (mine; review these)

1. **Severities** follow decision 9: `warning` for all, `review` for BOOL001,
   whose callee is not resolved. Each section's `severity` is the findings'
   severity, as in `rules.verification`, so `error` opts in to gating.
2. **Role scoping** like the VERIFY rules: a rule outside its section's
   `roles` is not applied to the file and not listed in `rules_disabled`. A first
   version listed them as disabled; that put six entries on every test file and
   changed many expected lists for no information the section does not already
   give.
3. **EXC004 is in `rules.exceptions`** and applies to every role: a `return` in
   `finally` discards an exception in a test as surely as in production.
4. **ASSERT001 allows type narrowing by default** (`x is not None`,
   `isinstance`, `and` of those): 51 of the tool's own 57 asserts were of this
   kind, and they record invariants for the type checker rather than validate
   input. `allow_type_narrowing = false` tightens.
5. **BOOL001 needs more than one positional argument**: `toggle(True)` names its
   flag in the function name. The lookups DEF002 judges (`get`, `getattr`,
   `setdefault`, `pop`, `next`, and `setattr`) are allowed by default.
6. **STUB001 treats as abstract**: `@abstractmethod`, `@overload`, and every
   method of a class deriving from `ABC`/`Protocol` or using `ABCMeta`. A
   docstring-only body is not a stub; empty JavaScript functions are not
   reported. `raise NotImplemented` is reported even in abstract code (it is a
   `TypeError`).
7. **STUB002 matches names, not files**, and treats a JavaScript bare package
   name as never being a path (`import x from "fixtures"` is a package).
8. **IMPORT001 reports only catalog operations**; an unresolved top-level call
   (most of them: `FastAPI()`, `getLogger()`) is not an unknown finding, which
   would bury the list. Instance field initializers in JavaScript run at
   construction and are excluded; static fields and static blocks are included.
9. **The 0.3.0 regression** runs with the H3 rules off (their sections disabled
   and an override for EXC004), and a new test checks that turning them on
   changes no gate status, exit code or hard-violation count.
10. **The made-up-identifier suggestion** (a `run_id` from `start_run()` in one
    place and `uuid4()` in another) is recorded as decision 20 for H6: it needs
    argument provenance across files.

### The tool's own code

The new rules found, on `src/` and `scripts/`: six asserts that check real
invariants (`findings.py`, `analysis.py`, `gating/diff.py` (3),
`complexity/callgraph.py`), now explicit `raise AssertionError(...)`; two
`raise NotImplementedError` in `schema.Field`, which is now an `ABC` with
abstract methods; one module-level cache in `cache/codec.py`, now
`functools.cache`. Left as reported: **49 BOOL001 review findings**
(`CallSite(..., False)`, `ModuleBinding(..., False, span)`,
`analyze_revision(..., None, False)`, `_add_revision_arguments(diff, True)` ...).
They do not gate; converting them to keyword arguments is a mechanical cleanup
proposed as its own session. The H3 code itself passes its own rules: its flags
are keyword-only.

**Follow-up done (2026-10-16):** all 49 sites now pass the flag by keyword (the
callee's own parameter or field name, from the first Boolean argument onward),
and the function flags are keyword-only (`analyze_revision(..., *, is_head)`,
`_add_revision_arguments(parser, *, required)`, `SymbolTable._bind_statement`
/ `_bind_import(..., *, top_level)`, `resolve_attribute(..., *, receiver_self)`).
The tool's own code has no BOOL001 finding; the suite (1056), Ruff and the
self-gate pass. A self-diff against 650eab3 fixes 51 findings and adds one
CPLX002 on `SymbolTable._bind_import` with the same cognitive complexity (17)
as before: its signature changed, so its fingerprint did. `_python_comment`
grew past 50 lines as the keyword calls wrapped, so its pylint and code-free
directive loops moved into `_pylint` and `_codeless`.

### Regression against 0.5.0

`pip install shockharness==0.5.0` against this tree, same inputs, all three
profiles, H3 findings excluded from the comparison: the self-scan (191), the
golden fixtures (409/399/401, exits 3/3/1) and both examples are identical.
H3 adds 49 findings to the self-scan (all BOOL001 review) and 10 to the golden
corpus (8 IMPORT001 on top-level `fetch` calls in `exc_promise_catch.js`, one
STATE001 on `counts` in `def_mapping_get.py`, one ASSERT001 in
`def_truthiness.py`); `expected.json` records them.

### Evidence (2026-10-16, macOS)

```text
$ ruff check src tests scripts evals && ruff format --check src tests scripts
All checks passed!
126 files already formatted

$ rm -rf .shockharness-cache; shockharness check src tests scripts   # cold, then warm
gate: PASS  240 findings  (cache hits 0 / misses 129, then 129 / 0)
$ shockharness check src tests scripts --no-cache
gate: PASS (exit 0)

$ pytest -q        # CPython 3.14.7
1056 passed
$ pytest -q        # CPython 3.11.11 / 3.12.8 / 3.13.1
1055 passed, 1 skipped   (on each; the skip is the wheel test, `build` not installed there)

$ python -m build && python scripts/consumer_upgrade_check.py --dist dist --examples examples
consumer upgrade check: 2 example(s), 14 step(s), 0 failed
```

Determinism: three `check src tests --format json --no-cache` runs are
byte-identical with `coverage.cache` removed.

Self-diff in a scratch clone against a1a8874 (the 0.5.0 STATUS commit): 130
files compared (4 new), `gate: PASS (exit 0)`, **no new findings**. The first
self-diff showed new complexity warnings in `prepare_text`,
`_guardrail_deviations`, `diff_revisions`, `_scan_finally`,
`_Placeholders.visit` and `_aliases`, one DEF003 review and four BOOL001 reviews
in the new code; each was split or rewritten.

New tests: `tests/unit/test_guardrails.py` (18), a loosening test for the H3
settings, the regression test's H3-on verdict check (3), and the updated golden,
registry, report, analysis, exception and inventory expectations.

### Failures observed during development (and what was done)

* `isinstance(node, FUNCTIONS | ast.Lambda)` with `FUNCTIONS` a tuple raised a
  `TypeError`; spelled out as a union of classes.
* A stray `[2]` index in the new rule code was a MAGIC001 error in the self-gate;
  replaced by unpacking.
* STATE001 first missed a variable named only by a `global` statement: the
  binding fact marks mutable containers, and the `global` declaration is on the
  function fact. It now combines both, as `complexity/coupling.py` does.
* Two expected line numbers in the new tests were miscounted by hand.

## Milestone H4: async lifecycle — DONE (2026-10-16)

ASYNC001, ASYNC002 and ASYNC003 and the `async-lifecycle` skill, as recorded in
spec 21.2 (H4 row) and decisions 15 and 22. Implemented in the lead session; not
released.

### What was built

* **Facts** (`ir/model.py`: `DiscardedCall`, `SettledBatch`, `AsyncFacts`;
  `ModuleFacts.asynchrony`) from `ir/python_async.py` and
  `ir/javascript_async.py`, cached (cache schema "5").
* **Call graph**: `CallGraph.sites` keeps each call site's resolution (path, call
  span -> target and confidence); edges are unchanged.
* **Rules** (`rules/async_lifecycle.py`), run in the cross-file phase
  (`analysis.async_findings`): the per-file phase only records whether they
  apply to the file (`rules_applied`), so cached files stay correct. ASYNC001
  combines a configured API catalog resolved through the file's imports with
  project functions declared `async`, resolved by the call graph.
* **Config**: `rules.async_lifecycle` (enabled, severity, roles default
  production and test, fail_on_unknown, two catalogs, supervisors), deviations
  through the H3 machinery, the severity in the loosening order, and the
  section in `FAIL_ON_UNKNOWN_SECTIONS`.
* **Skill**: `async-lifecycle` (sixth skill), with the shared adoption section;
  its compliant examples pass `shockharness check`.

### Decisions (mine; review these)

1. **Roles default to production and test.** An unawaited coroutine in a test
   makes the test pass without checking anything; that is the case the rule most
   wants to catch.
2. **Only whole-statement calls and `void`.** A coroutine stored in a variable
   and never awaited is not tracked; the statement form is where agents drop
   async work, and it needs no data flow.
3. **No type inference for JavaScript.** A call is a Promise only when its callee
   is in the catalog or is a project function declared `async`; an arbitrary
   library call is never assumed to return one (the brief's warning).
4. **Graph confidence decides the status.** A resolved edge is a violation; a
   probable edge (including `self.method()`, which a subclass may override) is
   `unknown`, gated only with `fail_on_unknown = true`.
5. **The graph is built for ASYNC001 even with complexity disabled**, and the
   units it needs are measured then; neither is reported.
6. **Supervisors are recognized by the binding `with`/`async with`** in the same
   function; a `TaskGroup` passed in as a parameter is not recognized
   (documented; the finding is approximate).
7. **ASYNC003 inspection is function-wide**, not traced to the batch's results;
   returning the batch, or a concise arrow evaluating to it, counts as handing
   the check to the caller.

### Regression against 0.6.0

`shockharness==0.6.0` against this tree, same inputs, all three profiles: the
self-scan, the golden fixtures (exits 3/3/1) and both examples are identical,
and no target has an ASYNC finding (the tool and the corpus have no dropped
async calls). The 0.3.0 regression runs with the H4 section off.

### Evidence (2026-10-16, macOS)

```text
$ ruff check src tests scripts evals && ruff format --check src tests scripts
All checks passed!
130 files already formatted

$ rm -rf .shockharness-cache; shockharness check src tests scripts   # cold, then warm
gate: PASS  190 findings  (cache hits 0 / misses 133, then 133 / 0)
$ shockharness check src tests scripts --no-cache
gate: PASS (exit 0)

$ pytest -q        # CPython 3.14.7
1065 passed
$ pytest -q        # CPython 3.11.11 / 3.12.8 / 3.13.1
1064 passed, 1 skipped   (on each; the skip is the wheel test, `build` not installed there)

$ python -m build && python scripts/consumer_upgrade_check.py --dist dist --examples examples
consumer upgrade check: 2 example(s), 14 step(s), 0 failed
```

Determinism: three `check src tests --format json --no-cache` runs are
byte-identical with `coverage.cache` removed.

Self-diff in a scratch clone against 265f18f (the 0.6.0 STATUS commit): 134
files compared (4 new), `gate: PASS (exit 0)`, **no new findings**. The first
self-diff flagged complexity in `prepare_text`, `build_call_graph`,
`javascript_async._settled` and `_async001`; each was split into named steps.

New tests: `tests/unit/test_async_lifecycle.py` (7: cross-file and catalog
ASYNC001, JavaScript `void` and entry points, the probable-edge unknown,
complexity disabled, supervisors, settled batches, roles and deviations), plus
the updated rule lists, skill list, inventory and regression.

### Failures observed during development (and what was done)

* With `complexity.enabled = false` ASYNC001 found nothing: no units were
  measured, so the graph had nothing to resolve to. Units are now measured
  whenever ASYNC001 applies.
* A concise arrow `(ps) => Promise.allSettled(ps)` was not seen as returning the
  batch: tree-sitter returns a fresh wrapper per access, so `is` never matched;
  nodes are compared by `id`.
* A `len((ISINSTANCE, GATHER))` trick to avoid a literal was replaced by the
  named constant `ISINSTANCE_ARGUMENTS`; the self-gate also caught a `[2]` index
  and a conditional fallback in the new extractors.

## Milestone H5: API-catalog rules — DONE (2026-10-16)

PROCESS001, RESULT001, TYPE001 (Python half), SLEEP001, RETRY001, BATCH001 and
STUB003, as recorded in spec 21.2 (H5 row) and decisions 15 and 23. Implemented
in the lead session; not released.

### What was built

* **Facts** (`ir/model.py`: `ProcessCall`, `SleepCall`, `RetryFact`,
  `BatchLoop`, `TypeEscape`, `ConstantPredicate`, `CatalogFacts`;
  `ModuleFacts.catalog`) from `ir/python_catalog.py` and
  `ir/javascript_catalog.py`, cached (cache schema "6"). RESULT001 reuses H4's
  discarded-call facts; TYPE001's `type: ignore` comes from the H2 directive
  facts.
* **Rules** (`rules/api_catalog.py`), run in the per-file phase next to the H3
  rules (`analysis._policy_rules`), with callees resolved through each file's
  imports (`import_aliases` / `qualified_callee`, shared with IMPORT001 and
  ASYNC001).
* **Config**: six sections plus `rules.stubs.stub003_severity`; deviations,
  the loosening order and `--policy` protection through the H3 machinery, and
  a deviation for each TYPE001 kind switched off.

### Decisions (mine; review these)

1. **Severities**: warning for PROCESS001, RESULT001, RETRY001, BATCH001;
   review for TYPE001, SLEEP001 and STUB003, whose patterns are often
   deliberate (a validated boundary, rate limiting, a flag that is always on).
2. **PROCESS001 has two findings**: injection (a shell plus a non-literal
   command) and an ignored exit status (returned, then dropped or never read).
   JavaScript `exec` reports failure through its callback and `execSync`
   throws, so only `spawnSync` is judged for its status. Whether the data can
   contain shell syntax is H6's question.
3. **RESULT001 method entries match by name** and are approximate; a function
   of an imported module never matches one (`os.replace` is not `.replace`).
   Roles default to production and test: `name.strip()` as a statement is a no-op
   in a test too.
4. **RETRY001 counts a handler that can raise, return or break as bounded**, so
   `if attempts > LIMIT: raise` passes without modeling counters.
5. **STUB003 lives in `rules.stubs` with its own severity key**, since its
   default (review) differs from STUB001/002's (warning).
6. **This repository sets `rules.types.report_any = false`**: its configuration,
   report and cache values are dynamic TOML/JSON data typed `Mapping[str, Any]`
   by design (validated by `schema.py`); 304 review findings would bury the
   casts and `type: ignore` comments, which stay reported (there are none). The
   setting is a reported deviation, and the self-diff reports it as VERIFY003,
   as intended.
7. **ROLE001** (decision 24) follows as its own change.

### Regression against 0.6.0

`shockharness==0.6.0` against this tree (its configuration without the new
`rules.types` key, which 0.6.0 does not know), same inputs, all three profiles:
the self-scan (190), the golden fixtures (exits 3/3/1) and both examples are
identical, and no target has an H4 or H5 finding. The 0.3.0 regression runs
with the H5 sections off.

### Evidence (2026-10-16, macOS)

```text
$ ruff check src tests scripts evals && ruff format --check src tests scripts
All checks passed!
134 files already formatted

$ rm -rf .shockharness-cache; shockharness check src tests scripts   # cold, then warm
gate: PASS  190 findings  (cache hits 0 / misses 137, then 137 / 0)
$ shockharness check src tests scripts --no-cache
gate: PASS (exit 0)

$ pytest -q        # CPython 3.14.7
1075 passed
$ pytest -q        # CPython 3.11.11 / 3.12.8 / 3.13.1
1074 passed, 1 skipped   (on each; the skip is the wheel test, `build` not installed there)

$ python -m build && python scripts/consumer_upgrade_check.py --dist dist --examples examples
consumer upgrade check: 2 example(s), 14 step(s), 0 failed
```

Determinism: three `check src tests --format json --no-cache` runs are
byte-identical with `coverage.cache` removed.

Self-diff in a scratch clone against 6980823 (H4): 138 files compared (4 new),
`gate: PASS (exit 0)`; the one new finding is VERIFY003 on this repository's
own `rules.types.report_any = false` (decision 6). The first self-diff also
flagged complexity in `prepare_text`, `extract_javascript_facts` (fan-out),
`javascript_catalog._shell`, `collect_javascript_catalog`, `_type_escapes` and
one test; each was split.

New tests: `tests/unit/test_api_catalog.py` (9: each rule in both languages
where it applies, TYPE001 switches, STUB003's severity, role scoping), plus the
updated rule lists, inventory, regression and the split report test.

### Failures observed during development (and what was done)

* A first end-to-end probe reported no H5 findings: the cache from an earlier
  run had the same key (tool version 0.6.0, cache schema "6") although the code
  had changed. Only a development tree hits this; a release bumps the version.
* RESULT001 first matched `os.replace(...)` against `.replace`; method entries
  now skip receivers that are imported modules.
* `isinstance(node, SCOPES | LOOPS)` with tuples raised a `TypeError` (the
  third time this mistake was made: noted for next time).
* A scripted rewrite of an expected rule list found the wrong closing bracket
  and mangled a test; the file was restored and patched by hand.

## ROLE001: is code classified as a test really a test? — DONE (2026-10-16)

From the maintainer's question: when a repository shields code by classifying it
as a test, can the claim be checked? Spec 21.1 decision 24. Implemented in the
lead session as its own change after H5; not released.

### What was built

* **ROLE001** (`rules/role_integrity.py`, category `policy_integrity`), run in
  the cross-file phase with the module graph (built for it when complexity is
  disabled, shared with ASYNC001): a production-role file importing a test-role
  file through a resolved module edge (exact, at the import, `severity`
  warning); a test-role file with no test case (the VERIFY test-case facts) that
  matches none of `support_files` (approximate, at line 1,
  `empty_test_severity` review).
* **VERIFY003** (`rules/policy_integrity.py:_role_findings`): in a revision
  diff, a file analyzed at both revisions (renames followed) that the base's
  `file_roles` classified as production and the head's classifies as test. Each
  snapshot now records the files its own configuration analyzes (`own_scope`).
* **Config**: `rules.role_integrity` (enabled, severity, empty_test_severity,
  support_files with glob validation); lowering a severity or adding a support
  glob is a deviation; both severities are in the loosening order.

### Decisions (mine; review these)

1. **The import check is the proof; the content check is evidence.** Test code
   is a dead end, so a production import of a test-role file is reported as a
   violation at warning (decision 9 for new rules), and a test file without
   tests only at review.
2. **Not role-scoped**: ROLE001 is about the role claim itself, so it applies to
   every file (production files carry the import findings, test files the empty
   ones).
3. **Support files by glob**, with generous defaults (`conftest.py`,
   `__init__.py`, fixtures, helpers, mocks, factories, testing, setup files),
   because a missing exemption here costs only a review finding.
4. **Reclassification is VERIFY003, not ROLE001**: it needs a base revision and
   it is a policy loosening like the others in that rule.
5. **New files added under `tests/` are not reclassifications**; only files that
   exist at both revisions (renames followed) are compared.

### Evidence (2026-10-16, macOS)

```text
$ ruff check src tests scripts evals && ruff format --check src tests scripts
All checks passed!
136 files already formatted

$ rm -rf .shockharness-cache; shockharness check src tests scripts   # cold, then warm
gate: PASS  190 findings  (cache hits 0 / misses 139, then 139 / 0)
$ shockharness check src tests scripts --no-cache
gate: PASS (exit 0)

$ pytest -q        # CPython 3.14.7
1078 passed
$ pytest -q        # CPython 3.11.11 / 3.12.8 / 3.13.1
1077 passed, 1 skipped   (on each; the skip is the wheel test, `build` not installed there)

$ python -m build && python scripts/consumer_upgrade_check.py --dist dist --examples examples
consumer upgrade check: 2 example(s), 14 step(s), 0 failed
```

Determinism: three `check src tests --format json --no-cache` runs are
byte-identical with `coverage.cache` removed.

This repository has no ROLE001 finding: every file under `tests/` holds test
cases or matches a support glob. Verdicts against `shockharness==0.6.0` (its
configuration without the `rules.types` key), all three profiles, H3-H5 and
ROLE001 findings excluded: identical on the self-scan, the golden fixtures and
both examples. Self-diff in a scratch clone against 9768a19 (H5): 140 files
compared (2 new), `gate: PASS (exit 0)`, no new findings, after splitting
`take_snapshot`'s scope computation (`_scopes`) and moving ROLE001's
applicability into `_policy_rules`, which the first self-diff flagged.

New tests: `tests/cli/test_role_integrity.py` (3: production imports and empty
test files, support files and severities, and a diff that re-globs one file and
moves another under `tests/`). Nine existing tests used samples under `tests/`
with no test function; they now hold one, so they stay honest test files and
keep testing what they were written for.

### Failures observed during development (and what was done)

* A test asserted `finding.category`, which is not a field of `Finding` (the
  category is derived from the registry); it now uses `registry.category_of`.

## Milestone H-TS: TypeScript — DONE (2026-10-16)

TypeScript as a third language, as recorded in spec 21.2 (H-TS row) and
decisions 8 and 25. Implemented in the lead session; not released.

### What was built

* **Language plumbing**: `registry.TYPESCRIPT`, `ALL_LANGUAGES` and
  `JAVASCRIPT_FAMILY`; `.ts`, `.tsx`, `.mts`, `.cts` in discovery; the report
  schema's language enum; default include, exclude (`**/*.d.ts`), test-role and
  config-role globs; the dependency `tree-sitter-typescript>=0.23.2,<0.24`.
* **Parsing** (`ir/javascript.py`): `extract_typescript_facts` picks the TSX
  grammar for `.tsx` and the TypeScript grammar otherwise, and runs the same
  extraction core as JavaScript (`_extract_facts`, now split into
  `_parse_failure`, `_literals_and_comments`, `_literal`).
* **TypeScript node types in the JavaScript extractors**: the anonymous
  `number` keyword token is not a literal; literal types count as annotations;
  `required_parameter` / `optional_parameter` through one helper
  (`parameter_parts`) for DEF001, complexity and locals; `this: T` is not a
  parameter; `public_field_definition` next to `field_definition`;
  `abstract_class_declaration` next to `class_declaration`; `as`, `!`,
  `satisfies` and `<T>` seen through wherever parentheses are (`unwrap_parens`,
  DEF context).
* **Imports and the graph**: type-only imports, specifiers and re-exports are
  erased; `import x = require()`; `.js` → `.ts` specifier resolution
  (`callgraph.TYPESCRIPT_SOURCES`); TypeScript cycles are labelled TypeScript.
* **TYPE001's TypeScript half** (`ir/javascript_catalog._type_escape`,
  `rules/api_catalog._type001`): `any` (excerpt: the annotated parameter,
  variable, member or type parameter, else the type), assertions, non-null
  (`report_non_null`), and the `@ts-*` directives.
* **Exception boundaries**: a JavaScript boundary covers TypeScript.

### Decisions (mine; review these)

1. **TypeScript is in the default `include`.** Support means analysis; leaving
   it out would make a TypeScript repository look clean. This is the one change
   that can move a verdict (for TypeScript repositories only); the CHANGELOG
   says how to keep the old scope.
2. **`.d.ts` files are excluded by default**: they hold no executable code, and
   their literal types would only add MAGIC001 findings.
3. **Type-only imports are erased**, as `tsc` erases them: a type-only cycle is
   not a runtime cycle, and type-only code from a test file ships nothing.
   `verbatimModuleSyntax` (which keeps a side-effect import) is not modelled.
4. **Literal types are annotations**, reported and labelled like Python's
   `Literal[8080]`; enum member values are executable code.
5. **A JavaScript boundary covers TypeScript**: the runtime and the catch
   semantics are the same, and a mixed repository should not have to declare
   every boundary twice.
6. **TYPE001 does not apply to plain JavaScript** (no types to escape), and
   `x as unknown as T` is one assertion.
7. **An optional parameter (`x?: T`) is not a default**: there is no value.
8. **The JavaScript locals fix ships with H-TS**: found while unwrapping
   TypeScript parameters, it is a real JavaScript bug (parameters were missing
   from a unit's locals), and fixing it changes no verdict on any target below.

### Evidence (2026-10-16, macOS)

```text
$ ruff check src tests scripts evals && ruff format --check src tests scripts evals
All checks passed!

$ rm -rf .shockharness-cache; shockharness check src tests scripts   # cold, then warm
gate: PASS  188 findings  (cache hits 0 / misses 140, then 140 / 0)

$ pytest -q        # CPython 3.14, 3.11.11, 3.12.8, 3.13.1
1104 passed        (on each)

$ python -m build && python scripts/consumer_upgrade_check.py --dist dist --examples examples
consumer upgrade check: 2 example(s), 14 step(s), 0 failed
```

Determinism: three `check src tests --format json --no-cache` runs are
byte-identical with `coverage.cache` removed.

**Parity.** The whole suite was run with a plugin that extracts every
JavaScript source it analyzes a second time as TSX and compares the facts
(language, parser and parse-failure message aside): no difference on any
source. The `.ts` grammar differs only on JSX, which TypeScript accepts in
`.tsx` only.

**Regression against 0.6.0.** `shockharness==0.6.0` against this tree (its
configuration without `rules.types`), all three profiles, H4, H5 and ROLE001
rule IDs excluded: identical exits and findings on the self-scan (188), the
golden fixtures (exits 3/3/1) and both examples. None of them contains
TypeScript. Self-diff in a scratch clone against 1785ca7 (ROLE001):
`gate: PASS (exit 0)`, no new findings, no complexity regressions, after the
first self-diff flagged the renamed extraction core, three functions that each
grew by a line or a branch, and a comment in `rules/api_catalog.py` that
spelled out the Python type-ignore directive (TYPE001 and VERIFY002 read it as
one).

New tests: `tests/unit/test_typescript.py` (17: discovery and `.d.ts`, the TSX
grammar, roles, MAGIC001, DEF001, locals in both languages, classes and type
wrappers, a JavaScript sample giving identical findings as TypeScript, imports,
`.js` → `.ts` resolution with a type-only cycle, ROLE001 and type-only imports,
TYPE001 kinds and switches, every suffix). Six existing test functions used `.ts`
as the example of an unsupported file; they now use `.rs`.

### Failures observed during development (and what was done)

* The first TypeScript file crashed the literal walk: the TypeScript grammar's
  anonymous `number` keyword (`x: number`) has the same type name as a numeric
  literal. Only named `number` nodes are literals now; `string` and `object`
  have the same collision and are only ever tested on named expression fields.
* A patch script stopped on a missing count and wrote nothing; it was rerun.
* The self-gate caught a `m[k] if k in m else v` lookup (DEF002) and a
  conditional on `is None` (DEF004) in the new code; both are explicit now.

## Milestone H6, part one: INPUT001-INPUT002 — DONE (2026-10-16)

Bounded taint tracking and unchecked configuration reads, as recorded in spec
21.2 (H6 row) and decision 26. Implemented in the lead session; not released.
Part two (the cross-site consistency rules of decisions 20 and 21) follows.

### What was built

* **Dataflow facts** (`ir/model.py`: `FlowRead`, `FlowCall`, `FlowStore`,
  `FlowReturn`, `FlowUnit`, `DataflowFacts`; `ModuleFacts.dataflow`) from
  `ir/python_dataflow.py` and `ir/javascript_dataflow.py` (JavaScript and
  TypeScript). Each unit, discovered exactly as the function facts are (so the
  call graph's unit keys line up), gets its reads, calls with the origins of
  their receiver and arguments, stores, returns and tested origins. Nesting past
  `DATAFLOW_MAX_DEPTH` (100) is truncated and marked; operator chains are
  flattened. Cache schema "8".
* **Rules** (`rules/dataflow.py`): INPUT002 in the per-file phase; INPUT001 in
  the cross-file phase, with return summaries iterated to a fixed point and
  parameter-to-sink reach closed over the call graph's resolved and probable
  sites, at most `max_depth` crossings.
* **Config**: `rules.input` (sources, `callee:N` sinks, validators,
  configuration reads per language; `max_depth`; `input002_severity`), with
  deviations for removed catalog entries, added validators, lowered severities
  and a lowered depth, and a configuration error for a malformed sink.

### Decisions (mine; review these)

1. **Facts are config-free value dependencies; catalogs apply in the rules.**
   The same facts will serve the cross-site rules (argument provenance).
2. **Unresolved calls pass everything on**, so a value is not lost through
   `json.loads` or a method call; validators are the only way to clean a value.
3. **Default sources are remote input only.** Measured on pip, pytest,
   hypothesis, build, hatchling and npm (790 files): all six INPUT001 findings
   came from `sys.argv` in command-line code using its own arguments, so
   `sys.argv`, `input` and `process.argv` are left for projects to add.
4. **INPUT002 is review.** On the same corpus its findings were mostly variables
   that are optional by design (`PYTEST_THEME`, an environment report); the
   rule cannot know which variables are required. A chained property read
   (`process.env.HOME.length`) throws when unset and is not a candidate.
5. **A Python use on the read's own line is DEF006's**, which already reports
   the implicit None there; INPUT002 reports later uses.
6. **`JSON.parse` is never a validator**, although `.parse` is (zod).

### Evidence (2026-10-16, macOS)

```text
$ ruff check src tests scripts evals && ruff format --check src tests scripts evals
All checks passed!

$ rm -rf .shockharness-cache; shockharness check src tests scripts   # cold, then warm
gate: PASS  188 findings  (cache hits 0 / misses 144, then 144 / 0)

$ pytest -q        # CPython 3.14, 3.11.11, 3.12.8, 3.13.1
1113 passed        (on each)

$ python -m build && python scripts/consumer_upgrade_check.py --dist dist --examples examples
consumer upgrade check: 2 example(s), 14 step(s), 0 failed
```

Determinism: three `check src tests --format json --no-cache` runs are
byte-identical with `coverage.cache` removed. Parity: the whole suite rerun with
every JavaScript source extracted a second time as TSX gives identical facts,
dataflow included. Cost: the self-scan takes 6.7 s against 6.1 s before H6; the
790-file corpus 51.4 s against 45.6 s for 0.6.0.

**Regression against 0.6.0** (H4-H6 and ROLE001 rule IDs excluded, all three
profiles): identical exits and findings on the self-scan (188), the golden
fixtures (exits 3/3/1) and both examples. The golden corpus gains one reviewed
INPUT002 finding (`javascript/def_process_env.js:7`, `process.env.FALLBACK_LEVEL`
stored unchecked), and the 0.3.0 regression runs with `rules.input` off.
Self-diff in a scratch clone against ec8e1b1 (H-TS): `gate: PASS (exit 0)`, no
new findings, no complexity regressions, after splitting three functions and
`config._semantic_issues`'s new check, which the first self-diff flagged.

New tests: `tests/unit/test_dataflow.py` (9: Python and JavaScript facts,
methods and depth, INPUT001 in one function, across files with `max_depth`, in
JavaScript, INPUT002 in both languages, sink validation).

### Failures observed during development (and what was done)

* The first dataflow walkers recursed and overflowed on 300 nested `if`s;
  operator chains are now flattened and nesting is capped and marked.
* `ast.get_source_segment` for excerpts cost 2.7 s of profile time on the
  self-scan; excerpts now slice the cached line.
* The golden fixture showed three INPUT002 false positives: a ternary that
  checks a second read of the same variable, and `||=` / `??=`, which test their
  left side. Both are fixed; the remaining finding there is a true one.
* CPython 3.11's parser cannot build a 3000-term expression; the test uses 800.
* Found on the way, not fixed here: a Python expression of about 2000 terms
  crashes `ir/python_guardrails.py` (H3) with a RecursionError; 0.6.0 crashes
  the same way.

## Fix: RecursionError on very long Python expressions — DONE (2026-10-16)

Found while building H6: a Python expression of about 2000 terms crashed
`shockharness check` with an internal error (exit 3); 0.6.0 crashes the same way.

### What was done

* `ir/python_guardrails._Placeholders` (H3: STUB001's placeholder facts) recursed
  once per AST level. It now walks with an explicit stack of (node, scope,
  abstract) and returns the same facts (sorted as before).
* `ir/python._parse` turns a `RecursionError` from `ast.parse` into a parse
  failure (a declared boundary in `.shockharness.toml`). CPython 3.11 counts the
  caller's frames toward its parser limit, so inside the tool it cannot build an
  expression of roughly 2900 terms that a bare interpreter can; 3.12 and later
  can.
* Every other collector already walked iteratively: thirteen deep Python shapes
  (operator, Boolean and comparison chains, nested calls, lists, attributes,
  subscripts, `if`s, lambdas, ternaries, unary signs, string concatenation) at
  the largest size each interpreter parses, and ten JavaScript/TypeScript shapes
  at depth 5000, are analyzed without error.

### Evidence (2026-10-16, macOS)

`tests/unit/test_deep_sources.py` (19 cases: ten Python shapes at 1500 terms or
90 levels, four JavaScript and TypeScript shapes at depth 2000, and a parser that
raises RecursionError) passes on CPython 3.11.11, 3.12.8, 3.13.1 and 3.14.7; six
of its cases fail against the previous code. Self-diff in a scratch clone against ed16372
(H6 part one): `gate: PASS (exit 0)`, no complexity regressions; its one new
finding is the intended VERIFY003 report of the new `RecursionError` boundary in
`.shockharness.toml` (an approved catch is a loosening, and is meant to be seen).

## Feedback: STUB001 TODO markers and IMPORT001 scripts — DONE (2026-10-16)

From an agent working on MetaList; two sources of noise, no new rule.

* **STUB001.** A JavaScript `throw new Error("...")` was a placeholder when the
  message started with "todo" in any case, so `"Todo toggle missing ..."` (a
  component name) was reported. The message now has to open with `TODO` in
  capitals, or `todo` in any case followed by `:` or `(`. The opt-in
  `rules.stubs.markers` now match only a comment line that opens with the
  marker (after `#`, `//`, `/*` or `*`), not the word inside a sentence.
* **IMPORT001.** Scripts do their work at the top level. The rule no longer
  applies to a file whose first line is a shebang (decided per file), nor to a
  file the new `rules.import_effects.script_files` (`scripts/**`, `bin/**`)
  matches that no analyzed file imports through a resolved module edge (decided
  in the cross-file phase, with the module graph). A script another module
  imports stays reported: its effects run in the importer. Each exemption is in
  `files[].rules_disabled` with origin `script`; adding a glob is a deviation.

Evidence: `tests/unit/test_guardrails.py` gains the message shapes, a sentence
comment, and a tree with a shebang script, a JavaScript bin script, an
unimported and an imported `scripts/` file. 1133 tests pass on CPython 3.14 and
3.11.11; the self-gate passes; verdicts against 0.6.0 are identical on the
self-scan, the golden fixtures and both examples, in all three profiles (none of
them has a TODO-shaped message or a script); self-diff against ed8881b: no new
findings, no complexity regressions (after splitting the script filter).

## Asserts: ASSERT001 version 2 and ASSERT002 — DONE (2026-10-16)

From the maintainer and an agent on MetaList (spec 21.1 decision 28, approved):
asserts are encouraged; the rule targets their misuse.

### What was built

* **Facts**: `FlowAssert` (span and every origin the test looks at) in each
  Python unit's dataflow facts.
* **ASSERT001 v2** (`rules/dataflow.run_assert001`): the INPUT001 engine,
  generalized with a `Mode`, with asserts as sinks, no validators, and as
  sources the `rules.input` sources, the configuration reads and the new
  `rules.assertions.external_reads`. It runs in the cross-file phase, so input
  passed into a function that asserts on it is found too.
* **ASSERT002** (`run_assert002`, review): one finding per run when production
  code has asserts other than pure type narrowing and no analyzed file reads
  `sys.flags.optimize`.
* **The CLI refuses `python -O`** (exit 2), which also satisfies ASSERT002 for
  this repository.
* **Skills**: write-compliant-code principle 9 (assert internal invariants,
  raise for expected failures, refuse `-O` at the entry point, `console.assert`
  only logs) and a checklist line; fix-violations rows for both rules ("never
  delete an assert to satisfy a finding").
* **Dataflow fix**: imported names are reads wherever the import is (they were
  locals, which hid `sys.flags.optimize` and a function-level `from flask import
  request`).

### Decisions (mine; review these)

1. **`allow_type_narrowing` keeps its meaning** (default true: a narrowing assert
   is never reported, even on input), so existing configurations are unchanged.
2. **Validators do not clean a value for ASSERT001**: `assert int(x) > 0` checks
   input as much as `assert x`.
3. **`os.environ.*`, not `os.environ`**: a variable read from the environment is
   external input; the environment object handed to a subprocess is not (the
   corpus showed `assert proc.stdout` reported through `env=os.environ.copy()`).
   A catalog entry ending in `.*` matches only below it.
4. **`console.assert`** is a note in the skill, not a rule (decision 28 named it
   a candidate).

### Evidence (2026-10-16, macOS)

On the 790-file corpus (pip, pytest, hypothesis, build, hatchling, npm):
ASSERT001 goes from 581 findings (0.6.0) to 7, each an assert on data read from
a file or the environment (hypothesis's charmap cache and bundled TLD list, pip's
netrc credentials and an uninstall record); ASSERT002 gives one finding
("581 assert(s) in 158 file(s)"). This repository has neither: its asserts are
internal, and the CLI reads `sys.flags.optimize`.

1135 tests pass on CPython 3.14 and 3.11.11; ruff clean; the self-gate passes.
The golden fixture `python/def_truthiness.py`'s `assert a or b` (an invariant on
parameters) is now an ASSERT002 finding instead of ASSERT001. Verdicts against
0.6.0 (ASSERT and H4-H6 rule IDs excluded) are identical on all twelve runs.
Self-diff against 6c820ca: no new findings, no complexity regressions. The
TSX parity rerun shows no differences (its own dataclass comparison recurses on
the new deep-source fixtures, a limit of the scratch plugin, not of the tool).
