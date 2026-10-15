# Rules

`shockharness rules list` prints every registered rule with its status;
`shockharness rules explain <ID>` prints the full description. This page is the
same information for the implemented rules, plus the planned set.

Severities: `error` fails the gate (unless suppressed or the gate is set to
`warn`); `warning` and `review` are reported and counted but never fail; `note`
is informational.

## Implemented

### MAGIC001: numeric literal outside 0/1 (error, Python and JavaScript)

Every numeric literal in executable code must be exactly `0` or `1`.

**Detection guarantees.** Exact on numeric AST nodes: Python `int`, `float`,
`complex` constants; JavaScript `number` tokens including BigInt. Value-based:
`0x1`, `1.0`, `1e0`, `0b0`, `1n`, `0j` pass. A chain of unary `+`/`-` over a
literal is checked as one unit: `-1` fails unless `allow_unary_negative_one` is
true; `-0` and `-0.0` always fail; `- -1` folds to `1` and passes. Python
booleans are never flagged. Literals in Python type annotations (`Literal[2]`)
are flagged and labelled. `match`/`case` patterns, JSX attribute expressions,
and template substitutions are executable code and are scanned.

**Limitations.** Strings and regular-expression literals are not numeric nodes:
`"30"` and `/\d{3}/` are not flagged. Numbers built at runtime (`int("30")`)
are not detected. `NaN` and `Infinity` are identifiers. Files that do not parse
are reported as parse failures, never as clean.

**Named constant definitions (0.2.0).** A literal that is the *whole* value
of a module-level named constant definition is marked by the adapters:

| Covered (marked) | Not covered (always reported) |
|---|---|
| Python: `MAX_PAGES = 8`, `_PORT_WAIT_SECONDS = 10.0`, `NEGATIVE = -8` (one UPPER_SNAKE_CASE target, leading underscores allowed), `wait: Final = 2.5`, `limit: t.Final[int] = 7` (any simple name annotated `Final`), `MAX_RETRIES: int = 5`; a statement of the module body itself | `LIMITS = {"retries": 3}` and `SIZES = [8, 16]` (containers), `TIMEOUT = 30 * 60` (an expression: both literals), `A = B = 9` (chained targets), `lower = 4`, class bodies, function bodies, `if ...: NESTED = 11` at module level |
| JavaScript: `const MAX_PAGES = 8;`, `export const _SETTLE_MS = -400;`, each declarator of `const A = 1, TWO = 2;` | `let maxPages = 8;`, `var LIMIT = 8;`, `const camel = 8;`, `const SIZES = [8, 16];`, a `const` inside a function or block, `export default 5;` |

`rules.magic_numbers.named_constant_definitions` decides what the mark means.
`"report"` (the `strict` default) keeps the specification's reading: a named
constant is not automatically justified, and `ITERATIONS = 2` is a finding like
any other. `"allow"` (the `recommended` and `minimal` default) does not report
the definition. The reasoning, from the first run on a real codebase: 143 of
the 2,074 application-code MAGIC001 findings there were definitions such as
`MAX_WEB_PAGES_PER_CALL = 8` or `const SETTLE_MS = 400;`, and that definition
is exactly the remedy the rule asks for; reporting it forces every adopter to
keep one exempt constants file, as ShockHarness itself does with
`constants.py`. The strict profile keeps reporting them because the
specification's semantics (section 5) are unchanged there; `"allow"` under
`strict` is a reported policy deviation, and under the other profiles it is one
of the lines that follow the profile's own deviation line.

**Configuration.** `rules.magic_numbers.*`; see `docs/configuration.md`.
Files matching `configuration_files` skip this rule and say so in the report.

**Remediation.** Find the contract behind the value. Variable policy (timeouts,
limits, sizes) becomes a required, validated configuration parameter. Invariant
mathematics or a published specification value becomes a named constant that
cites its source. Never move the number into an unexplained constant and never
add a fallback. A `0` or `1` that carries meaning (an exit code, a sentinel)
deserves a name too, even though the rule permits it.

### EXC001: forbidden catch (error, Python and JavaScript)

Every catch is forbidden unless the file sits inside a configured boundary
(`rules.exceptions.boundaries`: `path` glob, `language`, qualified `exception`,
`reason`) **and** every exception identity the handler names matches that
boundary's exception. There is no global whitelist: `ValueError` around
parsing external input may be a boundary; `ValueError` around your own
arithmetic is a hidden bug, and the rule cannot tell them apart, so the
boundary has to say which file it is.

**Python.** Every `except` / `except*` handler of a `try` is checked. The
handler type is resolved through the module's symbol table and the finding
records the confidence:

| Resolution | Confidence | Example |
|---|---|---|
| Builtin not shadowed in the module | `exact` | `except OSError` is `OSError` |
| Module-level absolute import, with aliases and dotted access | `exact` | `from requests.exceptions import Timeout as T` then `except T` is `requests.exceptions.Timeout`; `import tomllib` then `except tomllib.TOMLDecodeError` |
| Relative import | `approximate` | `from .errors import X` is `.errors.X` |
| Class defined in the module | `approximate` | `class X(Exception)` in `src/pkg/m.py` is `src.pkg.m.X` |
| Import nested in a function or in a module-level `if`/`try` | `approximate` | |
| Anything else: unbound name, name rebound by assignment, `except kinds[0]`, `except make()`, `*rest`, star imports | `unresolved` | |

A bare `except`, an unresolved identity, and a dynamic type expression can never
be approved: the finding says so explicitly ("strict mode fails closed") and
carries `confidence = "unresolved"`. `Exception` and `BaseException` are
reported as broad catches; a boundary may still name them (the tool's own
process boundary in `cli.py` does), which is visible in `config.deviations`.
Tuples are checked member by member and every member must be approved. An
`exact` identity must equal the boundary's `exception` string; an `approximate`
identity matches when one dotted name is a suffix of the other, so `.errors.X`
and `src.pkg.errors.X` both match a boundary for `pkg.errors.X`.

**JavaScript.** A `catch` has no type. The convention is: a JavaScript catch is
approved only inside a boundary whose `exception` names an error class, and only
when the handler's first statement is a guard that re-throws everything else:

```javascript
catch (err) {
  if (!(err instanceof TimeoutError)) throw err;   // or the block form { throw err; }
  ...
}
catch (err) {
  if (err instanceof TimeoutError) { ... } else { throw err; }
}
```

The guarded class is the catch's identity with `approximate` confidence
(nothing proves what `TimeoutError` is bound to). A boundary `exception` of `*`
is rejected at configuration time. `err.name === "..."` checks, guards joined
with `||`, and a catch without a binding are untyped and fail. Promise
`.catch(handler)` and `.then(onFulfilled, onRejected)` are checked the same
way when the handler is an inline function; a handler passed by reference is
opaque and fails closed.

**`transparent_rethrow`.** Off by default. When true, a handler whose only
non-logging statement re-raises the caught exception (`raise`, `raise err`,
`throw err`) passes EXC001 outside any boundary, including a bare `except:
raise`. `raise Other from err` is a conversion, not a re-raise, and is not
transparent.

**`transparent_guards` (0.2.0).** A list of guard functions, named as the
callee is written (`"rethrowUnexpectedError"`, `"errors.rethrow_unexpected"`),
that re-raise anything unexpected and return for expected failures. A handler
whose **first** statement calls a listed guard with the caught exception as its
only argument is treated as narrowed by that guard: EXC001 does not report the
catch, and EXC002 classifies the statements after the guard (so
`catch (error) { rethrowUnexpectedError(error); }` with nothing after it is
still reported as swallowing, and `rethrowUnexpectedError(error); return null;`
as a fallback). The call must be the first statement, have exactly that one
argument, and not be awaited. Default empty; every configured guard is a
reported policy deviation, like a boundary. EXC003 never runs on a guarded
catch: it is not a boundary.

**Python `isinstance` guard (0.2.0).** A handler whose first statement is
`if not isinstance(<caught>, T): raise` (or a tuple `(T1, T2)`), with a bare
`raise` as the guard's only statement and no `else`, is checked by EXC001 as a
catch of `T` (each tuple member must be approved) instead of the type written
on the `except` line; the finding says `narrowed from 'Exception' by its
isinstance guard` when it still fails. EXC002 classifies the statements after
the guard, as it already does after a JavaScript `instanceof` guard. Any other
shape (an inverted test, a guard that returns, an `else` branch, another
subject) leaves the broad catch as written.

**Limitations.** Class hierarchies are not known: a boundary for `OSError` does
not approve `FileNotFoundError`, and a broad library base class other than
`Exception`/`BaseException` is only flagged for not being approved. Shadowing by
a nested import that rebinds a module-level name is not tracked. Context
managers, `__exit__`, `contextlib.suppress`, signal handlers, and
`addEventListener("error")` are not catches and are not inspected.

### EXC002: suppressed or converted exception (error, Python and JavaScript)

The handler's body is classified; four shapes are findings, approved boundary or
not:

| Classification | Python | JavaScript |
|---|---|---|
| `empty` | `pass`, `...` | `{}` |
| `logging_only` | only `logging.*`, `logger.*`, `log.*` (any receiver chain ending in a logger name), `print`, `warnings.warn`, `traceback.print_*`, `sys.stderr.write` | only `console.*`, `logger.*`, `log.*`, `process.stderr.write` |
| `return_fallback` | the one non-logging statement returns nothing, `None`, a constant, or a list/tuple/set/dict built only of constants | returns nothing, `null`, `undefined`, `true`/`false`, a number, string, substitution-free template, or an array/object built only of those |
| `raise_other` | `raise X`, `raise X from None`, `raise X from something_else` | `throw new X()` without `{ cause: err }`, `throw other` |

Not flagged: bare `raise`, `raise err`, `raise X from err`, `throw err`,
`throw new X(msg, { cause: err })`, and any handler with several non-logging
statements or a non-literal return (`return default`, `return compute()`),
which is reported as `other` and left to EXC001. For a guarded handler (a
JavaScript `instanceof` guard, a Python `isinstance` guard, or a configured
transparent guard call) the statements after the guard are classified, and the
message names the guard; a fallback returned after a transparent guard call is
reported here rather than by DEF005, which reads the whole body.

**Shared handler with DEF005.** While DEF005 is active (the default), the
`return_fallback` classification is reported once, as DEF005, with the EXC002
classification named in the message; EXC002 itself reports the other three
shapes. When DEF005 is disabled (`rules.defaults.enabled = false` or an
override), EXC002 reports `return_fallback` as before. One handler never counts
twice in the gate.

### EXC003: broad try scope / unverified boundary (error, Python and JavaScript)

Runs only on catches EXC001 approved through a boundary. The `try` body must be
exactly one statement that performs exactly one operation:

* Python: an expression, assignment, annotated or augmented assignment, or
  `return` whose value is a single call (optionally `await`ed), or an `import`.
  Nested calls in arguments, comprehensions, lambdas, generator expressions,
  subscripts (`table[key]`), compound statements (`with`, `for`, `if`, nested
  `try`) and `assert` are not attributable.
* JavaScript: an expression statement, single-variable declaration, assignment,
  or `return` of one call or `new` expression (optionally `await`ed). For a
  promise handler the receiver of `.catch`/`.then` must itself be one call:
  `fetch(u).catch(h)` is attributable; `pending.catch(h)` and
  `fetch(u).then(f).catch(h)` are not.

A body with more than one statement is reported on the second statement with
`exact` confidence. A single statement that cannot be attributed is reported on
that statement with `approximate` confidence and the message says that static
analysis cannot tell which part may raise: the boundary is unverified, not
proven wrong. `finally` and `else` clauses are not inspected.

### SUPP001: invalid suppression comment (error)

A comment containing `shockharness:` that is not exactly
`shockharness: ignore[RULEID[, RULEID]] reason="non-empty"`, or names an
unknown rule, or has an empty reason. Under `--no-inline-suppressions`, every
suppression comment is reported as SUPP001.

### SUPP002: unused suppression comment (warning)

A valid suppression whose rule produced no finding on that line. A suppression
for a disabled or unimplemented rule is reported as unused because it did
nothing.

### DEF001-DEF006: defaults and fallbacks (Python and JavaScript)

The second hard policy: code must not substitute a value for something that is
absent. Six rules share the `rules.defaults` section. Each has a *mode* key
(`forbid` -> `error`, `review` -> `review`, `allow` -> no finding); the strict
profile forbids everything except truthiness fallbacks, which are `review`
because `or` is also ordinary Boolean logic. Every mode looser than the strict
value is listed in `config.deviations`. Findings are suggestions only
(`safe_autofix` is always false): removing a default changes a contract, and
only the author knows whether the value was optional.

Every finding carries a confidence. `exact` means the shape is unambiguous and
the fallback is *constant-shaped*: a literal, a container of literals, an
`UPPER_CASE` name or attribute, or an empty constructor call (`dict()`,
`new Map()`). `approximate` means the analyzer could not establish a type (the
receiver of `.get`) or an intent (the right operand of `or` is a variable, so it
may be a legitimate alternative); the message says which.

Two *implicit* shapes are `review` findings whatever the mode (unless `allow`):
`m.get(k)` and `os.getenv("X")` with no fallback yield `None` for a missing
value, and nothing proves the value was optional.

#### DEF001: function parameter default (error, mode `function_parameters` / `dataclass_fields`)

| Reported | Not reported |
|---|---|
| Python `def f(a, b=1, *, c=None)`, `lambda x, y=2`, async defs, methods, nested functions | `*args`, `**kwargs`, `...` defaults under `@overload` |
| dataclass fields: `x: int = 0`, `field(default=...)`, `field(default_factory=list)` (own kinds, mode `dataclass_fields`) | `ClassVar` fields, `field()` without a default, attributes of classes without the `dataclass` decorator |
| JavaScript `function f(a = 1)`, arrow, method, constructor, `static`, generator parameters | rest parameters, class field initializers (`class K { x = 1 }`) |
| destructuring defaults inside parameters: `function f({ retries = 3 }, [first = 0] = [])` (each default is a finding) | |

The finding sits on the default value; the message names the parameter and its
owner (`parameter 'b' of f() has a default value: 1`). Decorator detection is by
name (`dataclass`, `dataclasses.dataclass`, with or without arguments); attrs,
pydantic and NamedTuple defaults are not recognized.

#### DEF002: missing mapping/object fallback (error, mode `missing_value_fallbacks`)

| Reported | Confidence |
|---|---|
| Python `m.get(k, v)`, `m.setdefault(k, v)`, `m.pop(k, v)` | `exact` when the receiver is proven a mapping (a dict display; a name bound to a dict display or to `dict`/`defaultdict`/`OrderedDict`/`Counter`/`ChainMap(...)`; a name or parameter annotated `dict`/`Dict`/`Mapping`/`MutableMapping` and relatives, anywhere in the module); otherwise `approximate` |
| Python `getattr(o, a, v)` | `exact` |
| Python `m[k] if k in m else v`, `v if k not in m else m[k]` | by the fallback |
| Python `m.get(k)` with no fallback | `review`; reported when the receiver is a known mapping, or when it is unknown and the key is a string literal; not when the result is awaited, compared with `None`, or the left operand of a reported `or` |
| JavaScript `const {x = v} = o`, `const [x = v] = a`, `for (const {x = v} of rows)`, `({x = v} = o)` | `exact` |
| JavaScript `o?.x ?? v`, `o.x ?? v`, `o[k] ?? v`, `m.get(k) ?? v`, and their `??=` forms | by the fallback |
| JavaScript ternaries on a null/undefined check of a property (`o.x == null ? v : o.x`) and membership ternaries (`k in o ? o[k] : v`, `o.hasOwnProperty(k) ? ...`, `Object.hasOwn(o, k) ? ...`) | by the fallback |

Method names are matched, not types: `client.get(url, params)` is an
approximate error and `client.get("path")` an approximate review finding. A
bare JavaScript property read (`o.x`, `map.get(k)`) is never a finding: every
absent property yields `undefined` and nothing in the syntax singles it out.
Object spread merging and `Object.assign` are not recognized.

#### DEF003: truthiness fallback (review, mode `truthiness_fallbacks`)

`x or v` / `x || v` replace every falsy value (`None`/`null`/`undefined`, `0`,
`''`, empty containers, `false`) alike. Reported:

* `x or v` and `x || v` **outside a Boolean test**: not the condition of
  `if`/`while`/`assert`/`for`/ternary, not an operand of `not`/`!`, `and`/`&&`
  or a comparison. Exact when `v` is constant-shaped (any position, including
  call arguments and object properties); approximate when the expression is the
  value of an assignment, declaration, object property or `return` and `v` is
  any other expression.
* `x ||= v`, `x if x else v`, `x ? x : v`.
* Chains report once, on the whole chain, with the last operand as the fallback.
* Any operand that is itself Boolean logic (a comparison, `and`/`&&`, `not`,
  `True`/`false`, `isinstance(...)`) makes the whole `or` Boolean logic: not
  reported. Boolean-typed *variables* are not distinguished from values, so
  `return ok || done` is an approximate review finding.

Environment reads on the left (`os.environ.get("X") or v`,
`process.env.X || v`) are DEF006 instead.

#### DEF004: nullish fallback (error, mode `nullish_fallbacks`)

| Reported | Not reported |
|---|---|
| Python `x if x is not None else v`, `v if x is None else x` (also `==`/`!= None`), where the non-missing branch mentions `x` | `None if x is None else f(x)` (propagation); `'a' if x is None else 'b'` (a choice); `if x is None: x = v` (a statement) |
| JavaScript `x ?? v`, `x ??= v` with a plain identifier on the left (a property on the left is DEF002) | `??` inside a Boolean test |
| JavaScript ternaries guarded by `x === undefined`, `x === null`, `x == null`, `typeof x === "undefined"` and their negations | `x == null ? null : x.y` (propagation); `o?.x` alone |

Exact when the fallback is constant-shaped, approximate otherwise. `x ?? null`
is reported: normalizing `undefined` to `null` is still a substitution.

#### DEF005: exception-to-default (error, no mode)

A catch whose handler returns a value converts a failure into data.

* **Exact:** every handler EXC002 classifies as `return_fallback` (returns
  nothing, `None`/`null`/`undefined`, a constant, or a container of constants,
  possibly after logging), including inline promise handlers such as
  `.catch(() => null)`; and a handler returning an empty constructor call
  (`dict()`, `new Map()`).
* **Approximate (static trace, one step, module-local):** the one non-logging
  statement returns a name bound at module level to a constant-shaped value
  (`DEFAULT = {}`, `let mutable = {}`), or calls a module-level function whose
  body is a single `return <constant>` (Python `def`, JavaScript function
  declaration, `const` arrow or function expression, including an expression
  body such as `() => ({})`).
* **Not traced:** imported names, `self.method()`, parameters (`return default`),
  names bound to non-constant values, helpers with more than one statement.
  Those handlers are EXC001 territory only.

While DEF005 is active EXC002 does not also report `return_fallback`; see
EXC002 above.

#### DEF006: implicit configuration fallback (error, mode `configuration_fallbacks`)

Configuration is external input; it is read once, validated, and fails loudly
when missing. Reported:

| Python (`import os`, `import os as o`, `from os import environ, getenv`, with aliases) | JavaScript |
|---|---|
| `os.getenv("X", v)`, `os.getenv("X", default=v)`, `os.environ.get("X", v)`, `os.environ.setdefault("X", v)`, `os.environ.pop("X", v)` | `process.env.X || v`, `process.env.X ?? v`, `process.env["X"] || v` |
| `os.environ["X"] if "X" in os.environ else v` | `process.env.X ||= v`, `process.env.X ??= v` |
| `os.getenv("X") or v`, `os.getenv("X") if os.getenv("X") is not None else v` | `process.env.X === undefined ? v : process.env.X` |
| `os.getenv("X")`, `os.environ.get("X")` with no fallback: `review` (the implicit `None`), unless compared with `None` in the same expression | `const { X = v } = process.env`, `({ X = v } = process.env)` |

Not reported: `os.environ["X"]`, a bare `process.env.X` read, variables read
through wrappers or configuration libraries. The rule does not know where the
configuration boundary is: a fallback in the one module that validates
configuration is still reported there.

### CPLX001-CPLX006: complexity and coupling (warning, Python and JavaScript)

The advisory family of Milestone E. Every finding is a `warning`; none fails a
plain `check`. In a revision diff a per-unit regression against the base
follows `gates.complexity_regressions` (`warn` by default). Conventions,
examples and the report shapes are in `docs/complexity.md`; the one-line
summary of each rule:

| ID | Fires when | Threshold (default) | Convention |
|---|---|---|---|
| `CPLX001` | a unit's cyclomatic complexity is above the threshold | `complexity.cyclomatic_warn` (15) | `cyclomatic/1`: 1 + if/elif, loops, handlers, non-default arms, conditionals, short-circuit operators (configurable) |
| `CPLX002` | a unit's cognitive complexity is above the threshold | `complexity.cognitive_warn` (15) | `cognitive/1`: structural +1 plus nesting, else/elif +1, operator runs, recursion, labeled jumps; not a SonarSource score |
| `CPLX003` | a unit's decision nesting depth is above the threshold | `complexity.max_nesting_warn` (4) | `nesting/1`: wrappers add no depth |
| `CPLX004` | a unit's NPath estimate is at or above the threshold, or saturated | `complexity.npath_warn` (200), `complexity.npath_cap` (10000) | `npath/1`: bounded, never enumerated, reported as `>= cap` when saturated |
| `CPLX005` | modules import each other in a cycle (resolved edges only; **one finding per cycle**, anchored on the lexically first member), or a unit's fan-out is above the threshold | `complexity.fan_out_warn` (20; 30 in `recommended`, where fan-out findings are `review`) | resolved and probable call edges only; unresolved calls are reported, never counted |
| `CPLX006` | a unit's logical line count is above the threshold; module bodies are exempt | `complexity.max_lines_warn` (50) | `size/1`: code lines of the unit's own span, nested units excluded |

**Units.** A module body, class body, function, method, lambda or arrow
function. Nested units are measured separately and excluded from their parent.

**Detection guarantees.** Exact on the control tree both adapters produce;
Python and JavaScript give the same number for equivalent constructs (a parity
table and a Hypothesis property enforce it). Every message names the measured
value, the threshold and the convention version. `CPLX005` reports each import
cycle once: the finding sits on the lexically first member, at its import into
the cycle (so its fingerprint does not move when unrelated modules are added),
names the language and the size, lists up to eight members and says that a
Python cycle fails at import time while an ES-module cycle is usually resolved
at call time; the full membership stays in `metrics.graph.cycles`, and the text
report lists Python cycles before JavaScript cycles, after the per-file
findings. Fan-out findings give the split into analyzed and external targets
and the number of unresolved calls not counted. `CPLX006` names the line count
and the threshold; module bodies are never reported.

**NPath and cognitive on one unit (0.2.0).** NPath is the coarsest of the four
unit measures and explodes on long runs of independent `if`s, so it mostly
repeats what cognitive complexity says with less resolution. With
`complexity.npath_only_without_cognitive = true` (the default) a unit above both
`cognitive_warn` and `npath_warn` is reported once, as `CPLX002`, with the NPath
number in the same message (`...; its NPath estimate is >= 10000 (saturated at
the cap) ..., reported here instead of as CPLX004`); a unit above the NPath
threshold alone is still `CPLX004`. With the option `false` both findings
appear, as in 0.1.0. The per-unit numbers in `metrics.complexity.functions`
are the same either way.

**Limitations.** The call graph is static: computed callees, method calls on
values of unknown type, unbound names, and `self`/`this` attributes the class
body does not define are `unresolved` and never guessed; inheritance,
decorators that rebind, star imports and runtime rebinding are not followed;
modules outside the analyzed files are `external` and cannot close a cycle.
Files that fail to parse have no metrics. See `docs/limitations.md`.

**Configuration.** `complexity.*` and `gates.complexity_regressions`; see
`docs/configuration.md`.

**Remediation.** Reduce repeated cognitive work rather than the number: hoist
validation to one load step, name a repeated condition, separate effects from
computation, and pin behavior with tests before and after. Do not split a
function into helpers that share mutable state or hide a branch behind an
early return, a catch or a default; the graph records the delegation and the
numbers stay advisory either way. The `refactor-complexity` skill walks
through it.

## Registered, not implemented

These IDs are reserved and configurable now; they produce no findings and are
listed in every report under `coverage.rules_not_implemented`.

| ID | Name | Planned milestone |
|---|---|---|
| MAGIC002 | suspicious string literal (advisory) | post-B |

## Rule metadata contract

Each rule has an immutable ID, a version (bumped when detection semantics
change), a default severity, a summary, rationale, detection guarantees,
limitations, remediation guidance, and compliant/non-compliant examples. All of
this is in `src/shockharness/rules/registry.py` and printed by `rules explain`.
