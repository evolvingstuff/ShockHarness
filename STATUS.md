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
- CI has not run yet (nothing pushed). The matrix is defined; first push will show Linux/Windows results.
