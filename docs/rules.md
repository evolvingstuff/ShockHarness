# Rules

`shockharness rules list` prints every registered rule with its status;
`shockharness rules explain <ID>` prints the full description. This page is the
same information for the implemented rules, plus the planned set.

Severities: `error` fails the gate (unless suppressed or the gate is set to
`warn`); `warning` and `review` are reported and counted but never fail; `note`
is informational.

## Finding status

Every finding also has a **status** (H1), orthogonal to its severity:

* `violation`: the rule established the property it checks, and it does not hold.
* `unknown`: the rule could not establish the property, and says so instead of
  passing. Whether an unknown finding gates is decided per rule family by
  `fail_on_unknown` (`rules.exceptions` and `rules.defaults`: true, so they
  keep failing closed as they always have; `rules.magic_numbers` and
  `complexity`: false). With `true` it gates by its severity like a violation;
  with `false` it is reported, counted in `gate.unknown`, and never fails. See
  [configuration.md, Unknown findings](configuration.md#unknown-findings).

The text report marks an unknown finding `EXC001 error (unknown): ...`; JSON has
`findings[].status` and `summary.by_status`; SARIF keeps `level` from the
severity and adds `properties.status`; a revision diff, whose `status` already
means new/fixed/unchanged, carries it as `finding_status`.

What is unknown today (the inventory, kept as a test in
`tests/unit/test_unknown_inventory.py`):

| Rule | Finding | Status |
|---|---|---|
| EXC001 | handler whose only obstacles are exception types that do not resolve (`except MissingError`, `except make_error_type()`, `except errors[0]`, a name rebound by assignment) | `unknown` |
| EXC001 | the same with at least one resolved type that no boundary approves (`except (Missing, KeyError)`) | `violation` |
| EXC001 | promise rejection handler that references a function this module does not define (`p.catch(onError)` with `onError` imported) | `unknown` |
| EXC001 | `with name:` whose binding to a capture manager cannot be established (rebound, bound elsewhere, `with M() as name`) | `unknown` |
| EXC001 | capture manager whose positional arguments name no readable exception type (`suppress(*errors)`), or whose type does not resolve | `unknown` |
| EXC001 | bare `except:`, untyped JavaScript `catch (e)`, inline untyped rejection handler: each provably binds every exception | `violation` |
| DEF002 | `m.get(k, v)`, `m.setdefault(k, v)`, `m.pop(k, v)`, `m.get(k)` on a receiver not proven a mapping (`approximate` confidence): whether it is a fallback depends on the receiver's type | `unknown` |
| ASYNC001 | a dropped call whose async callee the call graph matched by name only (a `probable` edge) | `unknown` |
| every other finding | MAGIC001, EXC002, EXC003, EXC004, the other DEF findings (an `approximate` one there is about intent, not about whether the shape is present), CPLX001-CPLX006, SUPP001, SUPP002, STUB001, STUB002, ASSERT001, BOOL001, STATE001 (its `approximate` confidence is about aliasing, not about whether the binding is written), IMPORT001 | `violation` |

Unresolved call-graph edges never become findings: CPLX005 counts resolved
targets only and names the unresolved count in its message.

**The guardrails brief's five states.** `docs/shockharness_advanced_guardrails_spec.md`
section 1 names five finding states; they map onto ShockHarness as follows.

| Brief | ShockHarness |
|---|---|
| `violation` | `status: violation` with severity `error` |
| `warning` | `status: violation` with severity `warning` or `review` (advisory) |
| `unknown` | `status: unknown` (any severity), gated per family by `fail_on_unknown` |
| `pass` | a rule listed in the file's `rules_applied` with no finding there (per file, not per finding) |
| `not_applicable` | a rule listed in the file's `rules_disabled` (with its reason and origin), or in `coverage.rules_disabled_globally` / `rules_not_implemented` |

A file that could not be analyzed is never `pass`: its `status` is
`parse_error`/`decode_error`/`read_error`/`unsupported_source` and its
`rules_applied` is empty.

## Categories

Every finding carries a `category`, the category of its rule's family (spec
section 21.1 decision 2). It tells "the code is wrong" from "the checks were
weakened" without a separate exit code: a gating finding of any category exits
1.

| Category | Families | Meaning |
|---|---|---|
| `policy_integrity` | `VERIFY*` | the change weakened its own verification: skipped tests, blanket suppressions, assertions that cannot fail |
| `contract_integrity` | `MAGIC*`, `EXC*`, `DEF*`, `SUPP*`, `STUB*`, `ASSERT001`, `IMPORT001`, `ASYNC*`, `PROCESS001`, `RESULT001`, `TYPE001`, `SLEEP001`, `RETRY001`, `BATCH001` | the code hides a failure, a missing value, an unexplained number, a missing implementation, a check that can vanish, or an effect at import |
| `structural` | `CPLX*`, `BOOL001`, `STATE001` | complexity, coupling, unreadable call sites and shared state (advisory) |

The JSON report counts findings per category in `summary.by_category`; SARIF
results carry it in `properties.category`; the text output of `diff` and `gate`
lists policy-integrity findings first, under their own heading.

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
| Python: `MAX_PAGES = 8`, `_PORT_WAIT_SECONDS = 10.0`, `NEGATIVE = -8` (one UPPER_SNAKE_CASE target, leading underscores allowed), `wait: Final = 2.5`, `limit: t.Final[int] = 7` (any simple name annotated `Final`), `MAX_RETRIES: int = 5`, `CHUNK_BYTES = 64 * 1024` (literal arithmetic, 0.3.0: every literal of the expression); a statement of the module body itself | `LIMITS = {"retries": 3}` and `SIZES = [8, 16]` (containers), `TIMEOUT = BASE * 2` and `SIZE = int(x) * 2` (a name or call in the expression: every literal), `A = B = 9` (chained targets), `lower = 4`, class bodies, function bodies, `if ...: NESTED = 11` at module level |
| JavaScript: `const MAX_PAGES = 8;`, `export const _SETTLE_MS = -400;`, `const MAX_MS = 30 * 60 * 1000;` (literal arithmetic, 0.3.0), each declarator of `const A = 1, TWO = 2;` | `let maxPages = 8;`, `var LIMIT = 8;`, `const camel = 8;`, `const SIZES = [8, 16];`, `const T = BASE * 2;`, a `const` inside a function or block, `export default 5;` |

**Literal arithmetic (0.3.0).** The value may also be an expression built only
of numeric literals, unary `+`/`-`, parentheses and the binary operators `+ - * /
// % **` (JavaScript: the same set, `**` included, no `//`): `CHUNK_BYTES = 64 *
1024`, `MAX_MS = 30 * 60 * 1000`, `-(30 * 60) / 2`. The definition is still the
remedy; the arithmetic only documents how the number is built, so every literal
of such a value carries the mark. Any name, attribute, call, subscript or
non-numeric literal anywhere in the expression (`BASE * 2`, `int(x) * 2`,
`True * 2`, `"3" * 2`) keeps every literal in it reported, as do containers.
Under `"report"` every literal is reported as before.

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
Files whose role is `config` (`file_roles.config`, legacy spelling
`configuration_files`) skip this rule under `exclude_configuration_files = true`
and say so in the report.

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
and `src.pkg.errors.X` both match a boundary for `pkg.errors.X`. The finding's
status (H1) separates the two cases: a bare `except` provably catches
everything and is a `violation`; a catch whose only obstacle is a type that did
not resolve is `unknown` (see [Finding status](#finding-status)), and still
fails the gate under the default `rules.exceptions.fail_on_unknown = true`.

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
way when the handler is an inline function or a reference to a function defined
at the top level of the same module (a declaration, exported or not, or a
`const` bound to an arrow or function expression), whose body is then
classified; any other reference (an import, `obj.method`) is opaque and fails
closed with `unresolved` confidence. `.finally(fn)` is never a catch. With
`transparent_rethrow = true` a rethrowing handler (`.catch((e) => { throw e; })`)
passes like a rethrowing `catch` clause. An expression-bodied arrow that only
logs (`(error) => log(error)`) is `logging_only`; a bare `log(...)` call counts
as logging in JavaScript, next to `console.*` and `logger.*`.

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

**Context managers that catch (0.2.0).** A `with` block is a catch when its
context expression calls `contextlib.suppress` (either import spelling, resolved
through the module's symbol table) or one of the project's own capture managers
listed in `rules.exceptions.capture_managers` (qualified class names). The
exception types are the call's positional arguments that resolve as exception
identities (`suppress(FileNotFoundError, PermissionError)`,
`CapturedExceptionContext(ProcessLookupError, boundary="x")`); keyword
arguments and non-name arguments are ignored, and a manager with no readable
type is an untyped catch that no boundary can approve, like a bare `except`.
The finding sits on the `with` line, in the enclosing unit's scope, with the
kind `context manager`, and is approved exactly like an `except` handler: a
boundary for the file, the language and every type. A listed manager whose
import resolves matches by qualified name with `exact` confidence; one whose
import cannot be resolved matches by bare name with `approximate` confidence
(the call graph's "probable"). An unlisted manager is an ordinary `with`.
`contextlib.suppress` swallows by definition: EXC002 reports it as a swallow
unless a boundary approved it (the construct has no handler, so the boundary
approved the discard itself). A capture manager keeps the exception for
inspection after the block and is not an EXC002 finding; what the code does
with it is not inspected. EXC003 applies to an approved manager's body as to
a `try` body. Every configured manager is a reported policy deviation.

**Capture managers bound to a name (0.3.0).** The common form binds the manager
first, because the capture is inspected afterwards:

```python
capture = CapturedExceptionContext(ProcessLookupError, boundary="main.py:_is_process_running")
with capture:
    os.kill(pid, 0)
if capture.captured_exception is not None:
    ...
```

When the context expression is a plain name, it is resolved to the most recent
binding of that name in the same scope (the function body or the module body,
walking backwards from the `with`; nested `if`/`for`/`while`/`try`/`with`
bodies belong to the scope, nested functions and classes do not). If that
binding is an assignment whose value is a call to a listed manager or to
`contextlib.suppress`, the `with` is that catch, exactly as the inline form
(same findings, same line, same approval by boundaries, same EXC002 treatment
of `suppress`), with this confidence:

| Binding | Confidence |
|---|---|
| Assignment at the same block level or in an enclosing block (`capture = M(T)` then `with capture:`, or both inside the same `if`), nothing rebinds the name in between | `exact` (or the callee's own confidence when its import does not resolve) |
| Assignment inside a branch or loop body the `with` is not inside (`if flag: capture = M(T)` then `with capture:` after the `if`), or the name is also a parameter of the function or a comprehension target in the scope | `approximate`, still a catch; it still matches a boundary |
| The name was bound to a listed manager earlier but the latest binding before the `with` is something else (`capture = M(T)`, then `capture = other()`, then `with capture:`), or that latest binding is a `with M(T) as capture:` (which binds what `__enter__` returns) | `unresolved`: an untyped catch, reported by EXC001 like a bare `except`, never silently the older binding |
| No binding of the name in the scope before the `with` (a module-level `capture = M(T)` used inside a function), or the latest one is an import, a loop target, a `def`, or a tuple unpacking, while the name is bound to a listed manager elsewhere in the module | `unresolved`, as above; the message says where the name was last bound |

A name that is never bound to a listed manager anywhere in the module is an
ordinary `with` (`with lock:`, `with fh:`); an unlisted manager bound to a name
is an ordinary `with` too. Resolution never crosses modules: an imported
manager instance is `unresolved` only when the same name is also bound to a
listed manager in the module, because nothing else says the `with` is a catch.

**Limitations.** Class hierarchies are not known: a boundary for `OSError` does
not approve `FileNotFoundError`, and a broad library base class other than
`Exception`/`BaseException` is only flagged for not being approved. Shadowing by
a nested import that rebinds a module-level name is not tracked. `__exit__`
methods that swallow, context managers other than `contextlib.suppress` and
the configured capture managers, signal handlers, and
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
which is reported as `other` and left to EXC001. A handler that consists only
of a transparent guard call (`catch (error) { rethrowUnexpectedError(error); }`)
swallows the expected errors; since 0.3.0 its message ends with the three
things that satisfy the policy: handle the expected error after the guard, log
it and continue with a stated reason, or suppress the finding with a reason. A
handler with statements after the guard keeps the plain message. For a guarded handler (a
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
| pydantic model fields (0.2.0; a class whose base resolves to `pydantic.BaseModel` through `from pydantic import BaseModel` or `import pydantic`): `x: int = 1`, `Field(default=3)`, `Field(7)`, `Field(default_factory=list)` (the dataclass kinds, mode `dataclass_fields`, messages say `pydantic field`) | `Field(...)`, `Field()`, `x: int = ...` (required), `ClassVar`, a class whose base cannot be resolved (`class M(SomethingElse)`) |
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
| Python `next(iterator, v)` (0.2.0) | `exact`; `next(iterator)` is not a finding |
| Python `collections.defaultdict(factory)` (0.2.0) through any import spelling: `defaultdict(list)`, `collections.defaultdict(int)`, `c.defaultdict(set)` after `import collections as c`, `dd(set)` after `from collections import defaultdict as dd` | `exact`; every lookup creates `factory()` for a missing key, so a missing key is indistinguishable from an empty value; `defaultdict()` with no factory is not a finding |
| Python `m[k] if k in m else v`, `v if k not in m else m[k]` | by the fallback |
| Python `m.get(k)` with no fallback | `review`; reported when the receiver is a known mapping, or when it is unknown and the key is a string literal; not when the result is awaited, compared with `None`, or the left operand of a reported `or` |
| JavaScript `const {x = v} = o`, `const [x = v] = a`, `for (const {x = v} of rows)`, `({x = v} = o)` | `exact` |
| JavaScript `o?.x ?? v`, `o.x ?? v`, `o[k] ?? v`, `m.get(k) ?? v`, and their `??=` forms | by the fallback |
| JavaScript ternaries on a null/undefined check of a property (`o.x == null ? v : o.x`) and membership ternaries (`k in o ? o[k] : v`, `o.hasOwnProperty(k) ? ...`, `Object.hasOwn(o, k) ? ...`) | by the fallback |

**Not reported (0.5.0, `docs/shockharness-suggestions-4.md` items 1-4):**

- a `.get(...)` call that is itself a decorator (`@router.get("/notes/{id}")`,
  `@app.get(...)`): a route registration, not a lookup. A `.get` inside the
  decorator's arguments is judged as usual;
- a lookup whose fallback is `None` (`m.get(k)`, `m.get(k, None)`,
  `m.pop(k, None)`, `getattr(o, a, None)`) that is the whole value of an
  assignment to a name, when the very next statement is an `if` with no `else`
  whose body only raises and whose test is `x is None`, `not x`,
  `not callable(x)`, `not isinstance(x, ...)`, or an `or` that starts with one
  of those. Every absent path raises, so nothing is substituted. A non-`None`
  fallback is still reported;
- `m.setdefault(k, <empty container>)` (`[]`, `{}`, `()`, `set()`, `list()`,
  `dict()`, `tuple()`, `frozenset()`) whose result is immediately mutated by
  `.append`, `.add`, `.extend`, `.update`, `.insert`, `.setdefault` or a
  subscript assignment: the grouping idiom. A non-empty fallback, or a result
  that is read, is reported.

**Discarded removal.** `m.pop(k, None)` as an expression statement removes the
key if it is there. It is a `review` finding of kind `discarded_removal` in
every profile, with the receiver's status as above. Its message asks the real
question: if the key is always present, `del m[k]`; if absence is normal, say so
with `if k in m:`.

**Remediation**, in this order. (1) The key must exist: index it so a missing
key fails where it is missing, or validate once at the boundary. (2) Absence
is a normal state: an explicit `if k in m:` branch with a comment, or a small
named helper whose name says what absence means (`posting_or_empty`). Forcing
an index there turns a normal state into a crash. (3) The value comes from
outside: validate it where it enters.

Method names are matched, not types: `client.get(url, params)` is an
approximate error and `client.get("path")` an approximate review finding. Both
have status `unknown` (H1): the verdict depends on the receiver's type, which
was not established. `rules.defaults.fail_on_unknown = true` (the default in
`strict`) keeps them gating by severity as before; `recommended` sets it to
`false`, so they are reported and do not gate. A
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

### VERIFY001-VERIFY004: verification integrity (warning, Python and JavaScript; need a base revision)

These rules ask what a change did to its **own verification**. They compare a
head revision with a base revision, so they run only under
`shockharness diff --base B --head H` and `shockharness gate --base B --head H`.
A plain `check` reports them as not applicable (`coverage.verification.status =
"not_applicable"` and a line in the text output), never as passing.

Only what the change **added** is reported. A skip, suppression or weak test
that already existed at the base revision is debt, not a finding. A head file is
compared with its base version: the same path, or the path git reports it was
renamed from. A file with no base version is new, and everything in it counts
as added. When the base version could not be analyzed (a parse failure at
base), or rename detection failed and the file has no base version under its
own path, the findings are `unknown` (confidence `unresolved`): the rule cannot
tell what this change added. `rules.verification.fail_on_unknown` (default
`false`) decides whether those gate.

| Rule | What a change added | Files (role) |
|---|---|---|
| `VERIFY001` | a skip, expected-failure or focus marker on a test | test |
| `VERIFY002` | a blanket suppression comment (names no rule codes, names `all`, or covers a file); narrow ones too with `report_narrow_suppressions = true` | every role except generated and vendor |
| `VERIFY003` | a looser ShockHarness configuration, files dropped from analysis, baseline fingerprints, a weakened workflow that runs ShockHarness, or loosened ruff, flake8, pytest, coverage or ESLint settings; and, with `--policy`, a repository key that loosens the policy file (also in a plain `check`) | configuration, workflow and baseline files |
| `VERIFY004` | an assertion that can never fail; a test whose assertions all disappeared; a test whose body became empty | test |

**VERIFY001 markers.** Python: `pytest.mark.skip` / `skipif` / `xfail` (also
through `from pytest import mark`), `unittest.skip` / `skipIf` / `skipUnless` /
`expectedFailure` (also imported by name) on a test function or test class; a
`pytestmark = ...` assignment at module or class level; `pytest.skip(...)`,
`pytest.xfail(...)` or `self.skipTest(...)` called directly in a test body.
JavaScript: `describe` / `it` / `test` with `.skip` or `.only`, and `xdescribe`
/ `xit` / `xtest` / `fdescribe` / `fit`. A marker is identified by its test's
qualified name, its kind and its text, so moving it does not make it new. A
Python skip whose reason is listed in `rules.verification.allowed_skip_reasons`
is not reported (each listed reason is a policy deviation).

**VERIFY002 directives.** Python: `# noqa`, `# ruff: noqa`, `# flake8: noqa`,
`# type: ignore`, `# pylint: disable` / `disable-next` / `skip-file`,
`# pragma: no cover` / `no branch`, `# mypy: ignore-errors`. JavaScript:
`eslint-disable`, `eslint-disable-line`, `eslint-disable-next-line`,
`@ts-ignore`, `@ts-expect-error`, `@ts-nocheck`, `istanbul ignore`,
`c8` / `v8 ignore`. Both: `shockharness: ignore[...]`. A directive that names at
least one code (`# noqa: E501`, `// eslint-disable-next-line no-console`) is
*narrow*; one that names none, names `all`, or covers a whole file is
*blanket*. A directive's identity is its tool and the codes it names, not its
free-text description or a ShockHarness reason, so rewording a reason is not a
new suppression. `@ts-expect-error` names no code and is therefore blanket.

**VERIFY004 patterns.** Tautologies: `assert <truthy constant>`, `assert c == c`
or `assert c is c` on equal constants, `self.assertTrue` / `assertEqual` /
`assertIs` on constants, `expect(L).toBe(L)` / `toEqual` / `toStrictEqual`,
`expect(L).toBeTruthy()` / `toBeFalsy()` on a literal of that truthiness,
`assert(L)` / `assert.ok(L)` on a truthy literal, `assert.equal` /
`strictEqual` / `deepEqual` / `deepStrictEqual(L, L)`. Emptied tests: a test
(matched by qualified name) that had at least one assertion at base and has
none at head, reported with both counts; when its body became only `pass` /
`...` / a docstring / an empty block, the message says so. Assertions are
counted syntactically: `assert` statements, calls whose name starts with
`assert` or `expect`, `assert.*` methods, and `pytest.raises` / `warns` /
`deprecated_call` blocks.

**Severity and gating.** Every VERIFY finding carries
`rules.verification.severity`: `"warning"` by default in every profile
(specification section 21.1 decision 9: a new rule does not gate by default
until its precision has been measured on a reviewed corpus), `"error"` to make
them gate like any hard violation (exit 1), or `"review"` (a policy deviation).
Their category is `policy_integrity`; see Categories above.

**Not suppressible inline.** A change cannot excuse its own weakening of the
checks with a comment it adds itself (spec section 21.1 decision 5). A
`shockharness: ignore[VERIFY00x]` comment is a `SUPP001` error. Record
exceptions centrally: `rules.verification.*`, or an `[[overrides]]` entry by
path or role, both of which are visible policy changes in review.

**VERIFY003: a looser policy.** The base and head revisions' committed
configurations are loaded the way `check` loads them (no `--config`, no
`--policy`) and compared. A configuration is looser when:

* it has a policy deviation the base did not have (a disabled family, a lowered
  severity, an allowed value, a new boundary, guard or capture manager, an
  `[[overrides]]` entry, a looser profile, `parse_errors = "warn"`,
  `fail_on_unknown = false`, an allowed skip reason, ...). List entries are
  matched by text, so reordering a list is not a loosening;
* an ordered setting moved towards its looser end: `gates.*`,
  `unsupported_sources`, `parse_errors`, `rules.verification.severity`
  (`error` < `warning` < `review`), `complexity.fan_out_severity`;
* a complexity threshold (`*_warn`) was raised;
* `include` lost a pattern or `exclude` gained one.

Each is one finding, anchored at the key's line in the head configuration file.
Separately, files analyzed at base that the head configuration no longer
analyzes (the base revision's files under the head's include/exclude, renames
followed) are one finding listing the first five paths and the count.

The other inputs compared, each by path (renames followed):

* **Baselines.** Every ShockHarness baseline file (`*baseline*.json` with
  `fingerprint_version` and `fingerprints`) outside `.git`, `node_modules`,
  virtual environments and caches: fingerprints the head has and the base did
  not are one finding per file, with the rule IDs they cover. A new baseline
  file counts all its fingerprints.
* **Workflows** (`.github/workflows/*.yml|yaml`, only when the analysis root is
  the repository's top level): a job that ran ShockHarness at base and was
  removed or no longer mentions it; a deleted workflow file; and, in a job that
  still runs it, an added `continue-on-error: true`, `if: false`,
  `--exit-zero`, `--profile minimal` / `recommended`, `--parse-errors warn`, or
  a ShockHarness version pin moved to an older version.
* **Tool configurations** at the analysis root: `pyproject.toml`
  (`[tool.ruff]`, `[tool.pytest.ini_options]`, `[tool.coverage.*]`),
  `ruff.toml` / `.ruff.toml`, `setup.cfg` / `tox.ini` / `.flake8`
  (`[flake8]`, `[tool:pytest]`, `[coverage:*]`), `pytest.ini`, `.coveragerc`,
  `.eslintrc.json` / `.eslintrc` (JSON). Reported: a code added to an
  ignore, extend-ignore, per-file-ignores or exclude list; a code removed from
  `select` / `extend-select`; a path removed from `testpaths`; a deselecting
  pytest option added to `addopts` (`-k`, `-m`, `--deselect`, `--ignore`,
  `--ignore-glob`, `-p no:...`); a pattern added to coverage `omit` or
  `exclude_lines`; a lowered or removed `fail_under`; an ESLint rule turned
  down (`error` > `warn` > `off`) or removed, or an `ignorePatterns` entry added.

A file that cannot be read or parsed at either revision (invalid TOML, a YAML
`.eslintrc`, a configuration ShockHarness rejects) makes its comparison
`unknown` (confidence `unresolved`), never a pass; the reason is in the
message and under `coverage.verification.policy.read_errors`.

**`--policy` attempts.** With `--policy FILE` (see
[`configuration.md`](configuration.md#the-policy-tier)), every repository key
that would loosen a key the policy file sets is reverted to the policy's value
and reported as a `VERIFY003` finding at that key's line. This also happens in
a plain `check`, because it needs no base revision.

**Strictest of base.** In a revision diff the VERIFY rules use the stricter of
the run's `rules.verification` and the base revision's committed one: a change
cannot disable or lower the rules that report it, add an allowed skip reason
for its own skips, or turn off `fail_on_unknown` or
`report_narrow_suppressions` for itself. The loosening itself is reported by
`VERIFY003`, and takes effect once it is on the base branch.

### EXC004, STUB001, STUB002, ASSERT001, BOOL001, STATE001, IMPORT001: syntax-level guardrails (H3; warning, BOOL001 review)

Milestone H3 of specification section 21. Each rule ships at `warning`
(`BOOL001` at `review`) until its precision has been measured on a reviewed
corpus (decision 9), so none of them fails a gate by default. Set a section's
`severity = "error"` to gate on its rules; `"review"` lowers them and is a policy
deviation. Every finding is a `violation` (the facts are exact syntax).

| Rule | Reports | Languages | Files (role) |
|---|---|---|---|
| `EXC004` | `return`, `break` or `continue` that leaves a `finally` block, discarding the exception in flight | Python, JavaScript | every role (section `rules.exceptions`) |
| `STUB001` | `raise NotImplementedError`, `raise NotImplemented`, an empty function body (`pass`/`...`/docstring), `throw new XError("not implemented")`; comments with a configured marker | Python, JavaScript | `rules.stubs.roles` (production) |
| `STUB002` | an import of a mocking or fake-data library, or of a module under a test path segment | Python, JavaScript | `rules.stubs.roles` (production) |
| `ASSERT001` | an `assert` (removed under `python -O`); type-narrowing asserts allowed by default | Python | `rules.assertions.roles` (production) |
| `BOOL001` | a `True`/`False` literal passed positionally to a call with several arguments | Python, JavaScript | `rules.boolean_arguments.roles` (production) |
| `STATE001` | a module-level mutable binding that a function assigns or mutates | Python, JavaScript | `rules.module_state.roles` (production) |
| `IMPORT001` | a configured side-effecting call (processes, network, sockets, threads, deletion) executed at import time | Python, JavaScript | `rules.import_effects.roles` (production) |

A rule whose section does not list a file's role is not applied to that file
(it is absent from `rules_applied`, as the VERIFY role scopes are), so a test
file may use `mock` and `assert` freely.

**EXC004.** Python: `return` anywhere in a `finally` block, and `break`/`continue`
not inside a loop of their own within the block (a `break` in the `else` of such
a loop leaves the block). JavaScript: `return` in a `finally` clause; an
unlabeled `break` not inside a loop or `switch` of its own, an unlabeled
`continue` not inside a loop of its own, and a labeled `break`/`continue` whose
label is declared outside the clause. Nested functions, lambdas, arrows,
methods and classes are separate scopes. CPython 3.14 warns about the same
constructs (PEP 765). Boundaries do not apply: there is no exception type to
approve.

**STUB001.** An intentionally abstract API is not a stub: functions decorated
`@abstractmethod` or `@overload`, and every method of a class deriving from
`ABC` or `Protocol` or using `ABCMeta`, are not reported. `raise NotImplemented`
is reported in any function: `NotImplemented` is not an exception, and raising
it is a `TypeError`. A function whose body is only a docstring is not reported
(it needs a `pass` or `...`); empty JavaScript functions are not reported
(no-op callbacks are idiomatic). `rules.stubs.markers` (empty by default) adds
comments containing a listed word (`["TODO", "FIXME"]`, matched as whole words).

**STUB002.** Python: the module of every `import` / `from ... import` is
compared with `rules.stubs.mock_modules` (the module itself or one below it,
including `from unittest import mock`, which names `unittest.mock`) and its
dotted segments (and the names of `from . import x`) with
`rules.stubs.test_path_segments`. JavaScript: the specifier is compared with
`mock_modules` (`@faker-js/faker/locale/en` is below `@faker-js/faker`), and the
segments of a relative or absolute specifier (`./__mocks__/api.js`) with
`test_path_segments`; a bare package name is never a path. Matching is by name,
not by resolving files.

**ASSERT001.** Every `assert` outside `if TYPE_CHECKING:`. With
`rules.assertions.allow_type_narrowing = true` (the default) an assert whose
test only narrows types (`x is not None`, `isinstance(x, T)`, or an `and` of
those) is not reported: it records an invariant for the type checker. `false`
reports those too.

**BOOL001.** A call with more than one positional argument (and no `*args` or
spread) where one of them is a Boolean literal: one finding per literal, at
`review`. Calls whose last callee segment is in
`rules.boolean_arguments.allowed_callees` are skipped (default: `get`,
`getattr`, `setattr`, `setdefault`, `pop`, `next`, which DEF002 already judges);
each addition is a policy deviation. A single-argument call (`toggle(True)`) is
not reported.

**STATE001.** The module-level variables the analyzer marks mutable (bound to a
list/dict/set display or a mutable constructor, a JavaScript `let`/`var` or a
container `const`, or named by a Python `global` statement) that at least one
function, method or arrow assigns or mutates; one finding per binding at its
definition, naming the writers. `[[rules.module_state.allowed]]` declares a
deliberate process-wide binding (`path` glob, `name`, `reason`); each entry is
a policy deviation. Per file: writes through another module or an alias are not
seen, hence `approximate`. Local variables are never findings: mutating what a
function creates is fine. The usual fix is an immutable value (a `tuple`,
`frozenset` or frozen object nothing writes; `write-compliant-code`, principle
8) or an owner passed in by the caller.

**IMPORT001.** Calls executed when the module is imported (module body, class
bodies, decorators, default values; JavaScript top level, class static blocks
and static field initializers), not under `if __name__ == "__main__":` or
`if TYPE_CHECKING:`, whose callee resolved through the file's own imports
(`import subprocess as sp`, `from os import system`, `import { execSync } from
"node:child_process"`, `const cp = require("child_process")`) is in
`rules.import_effects.python_operations` / `javascript_operations`. An
unresolved framework call (`app.run()`, `server.listen()`) is not reported;
calls reached through a function called at import time are not followed.

### ASYNC001-ASYNC003: async lifecycle (H4; warning)

Milestone H4 of specification section 21. Every coroutine, task and Promise
needs an owner that waits for it and sees its failure. Section
`rules.async_lifecycle`; default roles production and test (an unawaited
coroutine makes a test pass without checking anything); `warning` until the
precision is measured (decision 9).

| Rule | Reports | Languages | Status |
|---|---|---|---|
| `ASYNC001` | a call that is a whole statement (or a JavaScript `void` call) whose callee is a configured coroutine/Promise API or a project function declared `async` | Python, JavaScript | `violation`; `unknown` when the call graph matched the async callee by name only (`probable`) |
| `ASYNC002` | `create_task(...)` / `ensure_future(...)` as a statement, unless the receiver was bound by a configured supervisor (`async with asyncio.TaskGroup() as group`) | Python | `violation` (exact for `asyncio.*`, approximate otherwise) |
| `ASYNC003` | `gather(..., return_exceptions=True)` / `Promise.allSettled(...)` whose result is thrown away, or whose enclosing function neither returns the batch nor checks a result for failure | Python, JavaScript | `violation` (exact when thrown away, approximate otherwise) |

**ASYNC001.** The catalog (`python_coroutine_apis`, `javascript_promise_apis`:
`asyncio.sleep`, `asyncio.wait_for`, ... `fetch`, `fs/promises` functions,
`timers/promises.setTimeout`) is matched after resolving the callee through
the file's own imports. Project callees are resolved by the cross-file call
graph, the same resolution `metrics.graph` reports: `await save(r)` in one file
and `save(r)` as a statement in another, where `save` is `async def` in a third,
reports the second. `void` is not treated as handling a rejection. The call
graph is built for ASYNC001 even when `complexity.enabled = false`.

**ASYNC002.** A supervisor is a `with`/`async with` manager listed in
`rules.async_lifecycle.supervisors` (`asyncio.TaskGroup`,
`anyio.create_task_group`, `trio.open_nursery`), matched in full or by its last
segment, that bound the receiver in the same function. A task whose handle is
kept (assigned, added to a set, awaited) is not reported.

**ASYNC003.** Python inspection is an `isinstance` check against a type whose
name contains `Exception` or `Error`; JavaScript inspection is a `.status` or
`.reason` access or a `"rejected"` string, anywhere in the enclosing function.
Returning the batch (or a concise arrow that evaluates to it) hands the check to
the caller.

### PROCESS001, RESULT001, TYPE001, SLEEP001, RETRY001, BATCH001, STUB003: API catalog (H5; warning or review)

Milestone H5 of specification section 21. Each rule resolves callees through
the file's own imports against a catalog in its section, so a project can add
its own wrappers. Advisory until measured (decision 9): `warning`, or `review`
where the pattern is often deliberate.

| Rule | Reports | Default | Languages | Section (roles) |
|---|---|---|---|---|
| `PROCESS001` | a shell command built from data; a process API whose exit status is returned and never checked | warning | Python, JavaScript | `rules.processes` (production) |
| `RESULT001` | a must-use call used as a statement: `name.strip()`, `sorted(items)`, `items.map(f)` | warning | Python, JavaScript | `rules.results` (production, test) |
| `TYPE001` | `Any` in annotations, `cast(...)`, `# type: ignore` | review | Python | `rules.types` (production) |
| `SLEEP001` | a fixed sleep (`time.sleep`, `asyncio.sleep`, `new Promise((r) => setTimeout(r, ...))`), said to be polling inside a loop | review | Python, JavaScript | `rules.sleep` (production) |
| `RETRY001` | an endless retry loop whose handler never gives up; `@tenacity.retry` / `@backoff.on_exception` without a stop | warning | Python, JavaScript (loops) | `rules.retry` (production) |
| `BATCH001` | a loop whose per-item handler only passes, continues or logs | warning | Python, JavaScript | `rules.batches` (production) |
| `STUB003` | a function named as a check whose body only returns `True` | review | Python, JavaScript | `rules.stubs` (`stub003_severity`) |

**PROCESS001.** Two findings. (1) The command is built from non-literal parts
(an f-string or template with substitutions, `+` or `%` with a non-literal,
`.format`) and runs through a shell: `shell=True`, `{shell: true}`, or an API
that always uses one (`os.system`, `os.popen`, `subprocess.getoutput`,
`child_process.exec` / `execSync`). (2) `subprocess.run` without `check=True`,
`subprocess.call` and `child_process.spawnSync` whose result is thrown away or
whose function never reads `.returncode` / `.status`, and `os.system` whose
result is thrown away. Whether the data can contain shell syntax is not traced
(that is H6).

**RESULT001.** Uses H4's discarded-call facts. An entry in
`python_must_use` / `javascript_must_use` is a qualified function (`sorted`,
`copy.deepcopy`, `structuredClone`; exact) or `.name` for a method on any
receiver (`.strip`, `.map`; approximate). A function of an imported module
(`os.replace`) never matches a method entry.

**TYPE001.** `report_any`, `report_cast` and `report_type_ignore` switch each
kind off (a deviation). Type checking stays with mypy or pyright; the
TypeScript half arrives with H-TS.

**RETRY001.** A loop is bounded when its handler raises, returns or breaks on
some path (a counter that raises counts). Decorators are matched through
`retry_decorators` and need one of `stop`, `stop_max_attempt_number`, `tries`,
`attempts`, `max_attempts` (tenacity, retrying) or `max_tries`, `max_time`
(backoff).

**BATCH001.** The handler body is only `pass`, `continue`, logging calls or
nothing. A handler that records the failure (appends it, re-raises later) is
not reported. The catch itself is also judged by EXC001/EXC002.

**STUB003.** `is_`/`has_`/`can_`/`should_` (JavaScript `isX`, `hasX`, ...) or a
name starting with `check`, `validate`, `verify`, `authorize`, `authenticate`,
`allow`, whose body (docstring aside) only returns `True` / `true`. Severity
`rules.stubs.stub003_severity` (`review` by default).

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
