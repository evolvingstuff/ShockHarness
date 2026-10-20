# Rules

`shockharness rules list` prints every registered rule with its status;
`shockharness rules explain <ID>` prints the full description. This page is the
same information for the implemented rules, plus the planned set.

Severities: `error` fails the gate (unless suppressed or the gate is set to
`warn`); `warning` and `review` are reported and counted but never fail; `note`
is informational.

**TypeScript** (`.ts`, `.tsx`, `.mts`, `.cts`; H-TS) is read by the JavaScript
extractors, so every rule this page lists for JavaScript applies to it with the
same guarantees; TypeScript syntax is understood where it matters (typed and
parameter-property defaults, `public` fields, abstract classes, `as`/`!`/
`satisfies` seen through, literal types as annotations, type-only imports
erased). `TYPE001` applies to Python and TypeScript, not to plain JavaScript.

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
| every other finding | MAGIC001, EXC002, EXC003, EXC004, the other DEF findings (an `approximate` one there is about intent, not about whether the shape is present), CPLX001-CPLX006, SUPP001, SUPP002, STUB001, STUB002, ASSERT001, ASSERT002, BOOL001, STATE001 (its `approximate` confidence is about aliasing, not about whether the binding is written), IMPORT001 | `violation` |

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
| `policy_integrity` | `VERIFY*`, `ROLE001` | the change weakened its own verification: skipped tests, blanket suppressions, assertions that cannot fail |
| `contract_integrity` | `MAGIC*`, `EXC*`, `DEF*`, `SUPP*`, `STUB*`, `ASSERT*`, `IMPORT001`, `ASYNC*`, `PROCESS001`, `RESULT001`, `TYPE001`, `SLEEP001`, `RETRY001`, `BATCH001` | the code hides a failure, a missing value, an unexplained number, a missing implementation, a check that can vanish, or an effect at import |
| `structural` | `CPLX*`, `BOOL001`, `STATE001` | complexity, coupling, unreadable call sites and shared state (advisory) |

The JSON report counts findings per category in `summary.by_category`; SARIF
results carry it in `properties.category`; the text output of `diff` and `gate`
lists policy-integrity findings first, under their own heading.

## Implemented

### MAGIC001: numeric literal outside 0/1 (error, Python, JavaScript and C#)

Every numeric literal in executable code must be exactly `0` or `1`.

**Detection guarantees.** Exact on numeric AST nodes: Python `int`, `float`,
`complex` constants; JavaScript `number` tokens including BigInt. Value-based:
`0x1`, `1.0`, `1e0`, `0b0`, `1n`, `0j` pass. A chain of unary `+`/`-` over a
literal is checked as one unit: `-1` passes while `allow_unary_negative_one` is
true, the default since the H6 feedback round (`items[-1]`, `text[:-1]`,
`indexOf(...) === -1`; MetaList's 262 findings for it held no hidden meaning);
`-0` and `-0.0` always fail; `- -1` folds to `1` and passes. Python
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
| C# (G1, decision 40): `const int Size = 8;` (any name), `static readonly Vector2 Spawn = new(64, 32);` (a Godot value type of literals), `[Export] public float Speed { get; set; } = 300f;`, `Layer = 1 << 3` in an enum | a local `const` in a method, an instance field (`Vector2 _p = new(120, -110);`), `static readonly Vector2 O = new(Speed, 2);` (a name in it), anything else |
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
`"allow"`, the default of every profile since 0.9.0 (spec 21.1 decision 36), does
not report the definition: the name is the remedy the rule asks for. `"report"`
is a tightening that reports `ITERATIONS = 2` like any other literal, so every
definition needs a suppression. The reasoning:
* The first run on a real codebase found 143 of the 2,074 application-code
  MAGIC001 findings there were definitions such as `MAX_WEB_PAGES_PER_CALL = 8` or
  `const SETTLE_MS = 400;`.
* Before decision 36, strict reported them anyway, and its users kept an exempt
  constants file (ShockHarness's own `constants.py`) or turned the option on by
  hand (MetaList did).
* In the under-the-gate experiment, coding agents under strict disguised the
  numbers instead (`HEADER_ROW + 1` for 2, `"  "` for an indent of 2,
  `len(calendar.month_name)` for 12).
* Measured before the change, allowing named constants removed 965 MetaList
  findings (843 constants), all 35 in ShockHarness's own `src`, and 58 in the
  experiment's agent-written builds; no constant name in any of them only spelled
  a number.

MAGIC004 reports that case if it appears.

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
| JavaScript `function f(a = 1)`, arrow, method, constructor, `static`, generator parameters; TypeScript `f(a: T = 1)` and `constructor(private a = 1)` | rest parameters, class field initializers (`class K { x = 1 }`), TypeScript optional parameters without a value (`a?: T`) |
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
| Python statement forms (decision 34): `if k in m: return m[k]` followed by `return v`, and `if k not in m: return v` followed by `return m[k]` | by the fallback; on `os.environ` it is `DEF006` |
| Python fallback helpers (decision 34): a call of a module-level function of the same file whose body, after a docstring and checks that only raise, is a lookup with a default that is one of its parameters (`m.get(k, default)`, `getattr(o, a, default)`, either membership form, `try: return m[k]` / `except KeyError: return default`) | `approximate`; mode `fallback_helpers` (`review` in strict); the helper's own lookup is reported as usual |
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
  subscript assignment: the grouping idiom. Since 0.9.0 the same holds when the
  result is assigned to a name that the very next statement mutates
  (`reasons = shared.setdefault(k, set())` then `reasons.add(key)`). A non-empty
  fallback, or a result that is read, is reported.

**Discarded removal.** `m.pop(k, None)` as an expression statement removes the
key if it is there. It is a `review` finding of kind `discarded_removal` in
every profile, with the receiver's status as above. Its message asks the real
question: if the key is always present, `del m[k]`; if absence is normal, say so
with `if k in m:`.

**Remediation**, in this order. (1) The key must exist: index it so a missing
key fails where it is missing, or validate once at the boundary. (2) Absence
is a normal state: branch where it matters and do the absent case's own work
there (`if tag not in index: continue`). A helper that returns a stand-in is the
fallback again, and one that takes the default as a parameter is `.get` under
another name (MetaList's `_mapping_value_or` reset 11 server-kept fields on
every edit through 26 literal defaults). A stand-in that really is the meaning
gets an inline suppression with its reason. Forcing an index there turns a
normal state into a crash. (3) The value comes from outside: validate it where
it enters.

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

* **Not reported (0.9.0, spec 21.1 decision 37):** an entry point's handler that
  returns a named non-zero exit status (`return EXIT_UNREADABLE`, where
  `EXIT_UNREADABLE = 2` at module level), inside a declared boundary that approves
  the caught type. At the process edge an exit status is how a program reports
  failure. The entry point is a top-level function named `main`, one called under
  `if __name__ == "__main__":`, or one named in `[project.scripts]` of the root
  `pyproject.toml`. A zero, a bare literal, any other function, and a catch no
  boundary approves are still reported. Python only.

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
`--policy`) and compared. A plain `check` and the edit hook compare the working
configuration with the accepted one instead (the merge base with `origin/HEAD`,
else `HEAD`, else what `init` writes) and report only the loosenings that
switch a rule off; see `docs/configuration.md`, "Switching a rule off needs a
person". Every loosening except a catch boundary naming one file switches a rule
off and is reported at `rules.verification.rule_switching_severity` (`error` by
default) in both modes; the rest of VERIFY003 keeps `rules.verification.severity`.
A configuration is looser when:

* it has a policy deviation the base did not have (a disabled family, a lowered
  severity, an allowed value, a new boundary, guard or capture manager, an
  `[[overrides]]` entry, a looser profile, `parse_errors = "warn"`,
  `fail_on_unknown = false`, an allowed skip reason, ...). List entries are
  matched by text, so reordering a list is not a loosening;
* an ordered setting moved towards its looser end: `gates.*`,
  `unsupported_sources`, `parse_errors`, `rules.verification.severity` and
  `rules.verification.rule_switching_severity` (`error` < `warning` < `review`),
  `complexity.fan_out_severity`;
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

### VERIFY005: a stub the code under test no longer reaches (warning, Python; one revision)

Spec 21.1 decision 43, from MetaList: a refactor of its namespace switcher moved the
launching to other functions, and three tests kept stubbing `open_or_launch_namespace`,
which the new code no longer called. They stayed green and launched real processes.

VERIFY005 looks at every patch of project code in test and config files:
`monkeypatch.setattr(module, "name", stub)`, `monkeypatch.setattr("pkg.mod.name", stub)`,
`patch("pkg.mod.name")` (`unittest.mock` or pytest-mock, as a call, decorator or context
manager) and `patch.object(Class, "name")`. The patch is resolved to the functions it
replaces through the file's imports or the project's module names. The tests that run it
are the test it is in, the tests that reach the helper it is in, and the tests that take
the fixture it is in as a parameter. When none of them reaches a replaced function, by the
same edges as the dead-code rules (calls, same-name fallbacks, value references,
nesting), the finding sits on the patch.

Not reported: **tripwires**, stubs there to be not called (they raise, call `pytest.fail`,
have an exception as `side_effect`, or append to a list the test asserts empty); patches
of code outside the project; patches no test is seen to run. It judges one revision, so a
plain `check` runs it, and only when the run analyzed every included file. Unlike the
other VERIFY rules it may be suppressed inline: a stub kept for code reached dynamically
says so with a reason. Severity `rules.verification.severity`.

Reachability leans toward "reached", so a stale stub whose name another reached function
shares is missed. Fixtures requested by other fixtures are not followed. A patch of
`module.name` that the code under test bypasses by importing the name directly is not
detected yet.

**Measured** on MetaList: at 87cbd073, where code and tests agree, 271 patches resolve to
project functions and none is reported. With the refactored switcher and the old tests,
the incident's state, it reports 4: the three `open_or_launch_namespace` stubs and a
`_restart_running_namespace_process` stub the same refactor stranded. With MetaList's fix,
none. The 5 unreached tripwires are not reported.

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
| `ASSERT001` | an `assert` whose test depends on external input (decision 28); internal invariants are never reported | Python | `rules.assertions.roles` (production) |
| `ASSERT002` | asserts relied on in production while no code reads `sys.flags.optimize` (one finding per run, review) | Python | `rules.assertions.roles` (production) |
| `BOOL001` | a `True`/`False` literal passed positionally to a call with several arguments | Python, JavaScript | `rules.boolean_arguments.roles` (production) |
| `STATE001` | a module-level mutable binding that a function assigns or mutates | Python, JavaScript | `rules.module_state.roles` (production) |
| `STATE002` | a shared object (a global, or `self.<attr>` outside a constructor) assigned before its fields are set | Python | `rules.module_state.roles` (production) |
| `IMPORT001` | a configured side-effecting call (processes, network, sockets, threads, deletion) executed at import time | Python, JavaScript | `rules.import_effects.roles` (production) |

A rule whose section does not list a file's role is not applied to that file
(it is absent from `rules_applied`, as the VERIFY role scopes are), so a test
file may use `mock` and `assert` freely.

**EXC005 (0.9.0).** A declared boundary names an exception that no catch in the
files it covers catches (`except`/`catch` clauses and capture managers, matched as
EXC001 matches; a JavaScript boundary also covers TypeScript). One warning per
exception, at the boundary's `path` line in the configuration file. It approves a
catch nobody has written, or no longer writes: in the under-the-gate experiment,
agents declared boundaries for files before writing them. A boundary is judged only
when it covers at least one file of the tree and every covered file was analyzed in
this run, so the edit hook, `check` on a subdirectory, and a boundary for a file that
does not exist yet produce nothing. On ShockHarness's own 37 boundaries and the
experiment's 53 it found none unused.

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
(no-op callbacks are idiomatic). A JavaScript message starts with a TODO
marker when it opens with `TODO` in capitals or with `todo` (any case) followed
by `:` or `(`; `"Todo toggle missing"` names a component and is not one.
`rules.stubs.markers` (empty by default) adds comment lines that open with a
listed word (`["TODO", "FIXME"]`; `# TODO: x`, `// FIXME`, ` * TODO(a)`), not
the same word inside a sentence.

**STUB002.** Python: the module of every `import` / `from ... import` is
compared with `rules.stubs.mock_modules` (the module itself or one below it,
including `from unittest import mock`, which names `unittest.mock`) and its
dotted segments (and the names of `from . import x`) with
`rules.stubs.test_path_segments`. JavaScript: the specifier is compared with
`mock_modules` (`@faker-js/faker/locale/en` is below `@faker-js/faker`), and the
segments of a relative or absolute specifier (`./__mocks__/api.js`) with
`test_path_segments`; a bare package name is never a path. Matching is by name,
not by resolving files.

**ASSERT001, ASSERT002 (version 2, decision 28).** Asserts are encouraged: an
assert states an internal invariant, and one that fires is a bug found at its
source. ASSERT001 reports the misuse only: an `assert` whose test depends on
external input, followed as INPUT001 follows values (through assignments,
string building, calls and project functions, up to `rules.input.max_depth`
crossings). External input is a `rules.input` source, a configuration read
(`os.getenv`, `os.environ`) or a `rules.assertions.external_reads` entry
(`sys.argv`, `input`, `sys.stdin`, `open`, `.read_text`, `json.load`,
`requests.get`, ...). No validator cleans a value here: `assert int(x) > 0` still
checks input, which deserves a typed error. With `allow_type_narrowing = true`
(the default) an assert that only narrows types (`x is not None`,
`isinstance(x, T)`, or an `and` of those) is never reported. Version 1 reported
every production assert, which pushed agents to delete invariants. ASSERT002
(review) is one finding per run, at the first production assert that is not
pure type narrowing, when no analyzed Python file reads `sys.flags.optimize`:
one startup check (`if sys.flags.optimize: raise SystemExit(...)`) makes every
assert safe to rely on. ShockHarness's own CLI refuses to run under `-O`.

**BOOL001.** A call with more than one positional argument (and no `*args` or
spread) where one of them is a Boolean literal: one finding per literal, at
`review`. Calls whose last callee segment is in
`rules.boolean_arguments.allowed_callees` are skipped (default: `get`,
`getattr`, `setattr`, `setdefault`, `pop`, `next`, which DEF002 already judges, and,
since G2, Godot's calls whose first argument names what the Boolean is for:
`SetShaderParameter`, `Set`, `SetDeferred`, `SetMeta`, `SetValue`, `SetSetting`, `Call`,
`CallDeferred`, `Rpc`, `RpcId`, `EmitSignal`); each addition is a policy deviation. In C#
a named argument (`Configure(enabled: true, 2)`) says what it switches and is not reported. A single-argument call (`toggle(True)`) is
not reported, and neither is an assertion (since 0.9.0): a callee whose last segment
starts with `assert` (`assertEqual`, `self.assertIs`, `mock.assert_called_with`) or
whose receiver is `assert` (`assert.equal`, `assert.strictEqual`). There the Boolean
is the expected value, and the assertion says what it means. MetaList measured 159 of
its 353 BOOL001 findings in browser test scripts outside the test role.

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

**STATE002 (review, Python).** A shared object published before it is
initialized:
* **The shape.** In one function, a newly constructed object (a call whose callee's
  last name is capitalized) is assigned to a name the function declares `global`, or to
  `self.<attr>` in a method other than a constructor. A later statement of the same
  function then sets one of its attributes, before a `return` or a rebinding.
* **Why it matters.** A thread reading the name in between gets a half-built object.
  MetaList's `get_encryption_service_with_token` assigned the cached service and then
  set its key, so a concurrent cache hit got a service without one. The fix is to build
  the object in a local and publish it last.
* **Measured.** In MetaList's tree before the fix it reported exactly those two
  functions (`get_encryption_service_with_token`, `set_session_dek`), and nothing after
  it. Nothing in ShockHarness, the experiment's builds, or the 1,093 Python files of pip,
  pytest, hypothesis, hatchling, packaging and their neighbours installed with
  ShockHarness.
* **Configuration.** Severity `rules.module_state.state002_severity`, `review` by
  default; roles as STATE001.

**IMPORT001.** Calls executed when the module is imported (module body, class
bodies, decorators, default values; JavaScript top level, class static blocks
and static field initializers), not under `if __name__ == "__main__":` or
`if TYPE_CHECKING:`, whose callee resolved through the file's own imports
(`import subprocess as sp`, `from os import system`, `import { execSync } from
"node:child_process"`, `const cp = require("child_process")`) is in
`rules.import_effects.python_operations` / `javascript_operations`. An
unresolved framework call (`app.run()`, `server.listen()`) is not reported;
calls reached through a function called at import time are not followed.
Scripts do their work at the top level, so IMPORT001 does not apply to a file
whose first line is a shebang (`#!`), nor to one that
`rules.import_effects.script_files` (`scripts/**`, `bin/**`) matches and that no
analyzed file imports through a resolved module edge (a script another module
imports runs its effects there, and stays reported). The exemption is listed in
`files[].rules_disabled` with origin `script`.

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
reports the second. `void` is not treated as handling a rejection, unless some
file of the project registers a global listener that reports unhandled
rejections (`window.addEventListener("unhandledrejection", h)`,
`process.on("unhandledRejection", h)`, `window.onunhandledrejection = h`, with a
handler that does more than `preventDefault()`): `void` then hands the failure
to it on purpose. A dropped call without `void` is still reported. The call
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
the caller. A Python `gather(..., return_exceptions=True)` in a `finally` body or
an `except` handler of a function that called `.cancel()` before it is the
standard wait for cancellation to finish, and is not reported (0.7.0 feedback).

### PROCESS001, RESULT001, TYPE001, SLEEP001, RETRY001, BATCH001, STUB003: API catalog (H5; warning or review)

Milestone H5 of specification section 21. Each rule resolves callees through
the file's own imports against a catalog in its section, so a project can add
its own wrappers. Advisory until measured (decision 9): `warning`, or `review`
where the pattern is often deliberate.

| Rule | Reports | Default | Languages | Section (roles) |
|---|---|---|---|---|
| `PROCESS001` | a shell command built from data; a process API whose exit status is returned and never checked | warning | Python, JavaScript | `rules.processes` (production) |
| `RESULT001` | a must-use call used as a statement: `name.strip()`, `sorted(items)`, `items.map(f)` | warning | Python, JavaScript | `rules.results` (production, test) |
| `TYPE001` | `Any` in annotations, `cast(...)`, `# type: ignore`; TypeScript `any`, `x as T` / `<T>x`, `x!`, `@ts-ignore` / `@ts-expect-error` / `@ts-nocheck` | review | Python, TypeScript | `rules.types` (production) |
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
result is thrown away. A result returned to the caller (directly, or through a
name the function returns) is the caller's to check and is not reported. Whether the data can contain shell syntax is not traced
(that is H6).

**RESULT001.** Uses H4's discarded-call facts. An entry in
`python_must_use` / `javascript_must_use` is a qualified function (`sorted`,
`copy.deepcopy`, `structuredClone`; exact) or `.name` for a method on any
receiver (`.strip`, `.map`; approximate). `/N` or `/N-M` after an entry is the
number of positional arguments the pure callee takes (`.replace/2-3`, JavaScript
`.replace/2`): a call with another count is a different method of the same name
(`location.replace(url)`, `Path.replace(p)`, `store.replaceAll({...})`) and is not
reported, nor is one with unpacked arguments. A method of a string literal is
recorded as the `str` method, so `"str.join"` (in the Python defaults) reports
`", ".join(parts)` alone on a line; `.join` on a name is not in the defaults: it
was `Thread.join` in every case measured. A call in the body of a `try` that has a handler is not reported
either: it may run for what it raises (`host.encode("idna")` to validate). A
function of an imported module (`os.replace`) never matches a method entry.

**TYPE001.** `report_any`, `report_cast`, `report_non_null` (TypeScript `x!`)
and `report_type_ignore` switch each kind off (a deviation). In TypeScript,
`report_cast` covers `x as T` and `<T>x`; `as const` is not an assertion and is
never reported, and `x as unknown as T` is one assertion, reported once.
`report_type_ignore` covers `@ts-ignore`, `@ts-expect-error` and `@ts-nocheck`.
Type checking stays with mypy, pyright or tsc.

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
`allow`, whose body (docstring aside) only returns `True` / `true`. Across
files: a method of a class that some project class extends is a default for
subclasses to override (`BaseModal.shouldCloseOnClickOutside`) and is not
reported; a method that repeats an always-yes method of its base is reported as
redundant (`HelpModal.shouldCloseOnClickOutside repeats
BaseModal.shouldCloseOnClickOutside, which already answers yes: remove the
override`). Classes are matched by the last name of each base (approximate).
Severity `rules.stubs.stub003_severity` (`review` by default).

### TYPE002: Python annotations that nothing checks (review)

Spec 21.1 decision 33. An annotation is a claim, and without a type checker nothing
verifies it: a wrong one reads as true to the next reader and to an agent. TYPE002
reports once per run when both of these hold:

* at least `rules.types.annotated_share` (0.5) of the production functions and methods
  where the rule applies, and at least `rules.types.min_annotated_functions` (20) of them,
  carry an annotation (a parameter other than `self`/`cls`, or the return);
* the analysis root configures no Python checker: `mypy.ini`, `.mypy.ini`,
  `pyrightconfig.json`, `.pyre_configuration`, `ty.toml`, a `[tool.mypy]`,
  `[tool.pyright]`, `[tool.basedpyright]`, `[tool.pyre]` or `[tool.ty]` table in
  `pyproject.toml`, or `[mypy]` in `setup.cfg` or `tox.ini`.

The finding sits on the first annotated function of the lexically first file and gives
the counts. Severity `rules.types.type002_severity`, `review` by default. Raising the share
or the minimum, or lowering the severity, is a VERIFY003 loosening.

It reads configuration only: a configured checker that CI never runs is not seen, and
neither is one configured outside the root. TypeScript is not covered, because a
TypeScript project that builds has a `tsconfig.json`. TYPE001's message is unchanged: it is
cached per file, and a checker configured elsewhere is not part of that file's key.

**Measured:** MetaList configures `[tool.mypy]` (since the backlog's measurement) and gets
no finding. ShockHarness itself gets one: 2,226 of 2,226 functions annotated, no checker.

### ROLE001: is code classified as a test really a test? (warning; review for empty test files)

The test role is an exemption: the H3 and H5 rules apply to production files
only. ROLE001 checks the claim from two directions in every run (spec 21.1
decision 24):

* **Who imports it (exact).** A production-role file that imports a test-role
  file, through a resolved edge of the module graph, ships that code while the
  production rules skip it. Reported at the import, at `rules.role_integrity.severity`.
* **What it contains (approximate).** A test-role file with no test case
  (`test_*` functions and methods; `describe`/`it`/`test` calls) that matches
  none of `rules.role_integrity.support_files` (conftest, `__init__.py`,
  fixture and helper files, support modules, mocks, factories, ...). Reported at line 1, at
  `empty_test_severity` (`review` by default).

The third direction needs a base revision and is a `VERIFY003` finding: a file
the base classified as production that the head classifies as test, by a new
`file_roles` glob or by moving it under one ("moved from ..."). ROLE001's
category is `policy_integrity`. Unresolved imports are not seen, and a helper
that only tests import is not judged.

### INPUT001, INPUT002: external input (H6; warning, INPUT002 review)

Both rules read each function's value dependencies (H6 dataflow facts): every
value is followed through assignments in source order (an assignment inside a
branch, loop or handler adds to a variable's origins instead of replacing them),
attribute and subscript reads, string building, containers and calls. A call
that is not a source, a validator or a resolved project function passes on
everything it was given (`json.loads(body)` is as tainted as `body`). Sources,
sinks, validators and configuration reads are the catalogs of `rules.input`,
resolved through each file's imports (spec 21.1 decision 26).

* **INPUT001** (`severity`, warning): a source value reaches a sink argument
  without passing a validator. Sources by default are remote input: Flask's
  `request.*`, Django/Starlette `request.GET`/`.POST`/`.body`, Express/Koa
  `req.body`/`.query`/`.params`/`.headers`/`.cookies`, AWS Lambda `event.*`;
  a dotted entry also matches a read rooted at a parameter of that name
  (approximate). Command-line arguments and stdin are not sources by default:
  whoever runs the program controls it already. Sinks are shell and process
  calls, `eval`/`exec`/`Function`, deserialization, file paths, `.execute` /
  `.query` (by method name, approximate), redirects and outbound URLs, each
  with its argument position (`"subprocess.run:0"`). Validators are
  conversions and schemas: `int`, `float`, `uuid.UUID`, `shlex.quote`,
  pydantic's `.model_validate`, `Number`, `parseInt`, zod's `.parse` /
  `.safeParse` (`JSON.parse` decodes and is not one). Values cross project
  functions through the call graph's resolved and probable call sites,
  arguments into parameters and return values back, at most
  `rules.input.max_depth` (3) crossings; the message names the source with its
  location and the functions crossed. Exact when the source, every crossing and
  the sink are resolved.
* **INPUT002** (`input002_severity`, review): `os.getenv("X")` /
  `os.environ.get("X")` (None when unset) or `process.env.X` (undefined) whose
  value reaches a call argument, a return, an attribute or a module-level
  binding while no condition of the function looks at it (`if`, `while`,
  `assert`, a ternary, `and`/`or`, `&&`/`||`/`??`, `not`/`!`, or a `node:assert`
  call given the value, even through a nested call such as
  `assert(["a", "b"].includes(name))`; `console.assert` only logs). A check of one
  read covers every read of the same variable in the function; Python's
  `int(...)` and the other validators count as checks (they raise on None),
  JavaScript's `Number(...)` does not (NaN). A Python use on the read's own line
  is DEF006's. Review by default: the rule cannot know which variables are
  required.

Neither rule sees a guard (`if not cmd.isalnum(): raise`), values stored on
objects or in module state, closures or callbacks; see
[limitations.md](limitations.md#input001-input002-h6).

### PROV001, GUARD001: cross-site consistency (H6 part two; review)

Both compare the call sites of one project function, as the call graph resolves
them (resolved and probable sites, in files whose role is in
`rules.consistency.roles`), and report the sites that disagree with the others.
They cannot know intent, so they ship at `review` (spec 21.1 decisions 20, 21
and 29).

* **PROV001**: a parameter that other call sites fill with an identifier the
  program issued, and this site fills with a freshly made one. Issued: the value
  comes (followed as INPUT001 follows values: attributes, `str(...)`, helper
  functions) from a call whose name opens with an `issuer_prefixes` word
  (`start_run`, `createSession`, `new_order`, `register`, `open`, `begin`,
  `issue`, `allocate`, `insert`). Made up: it comes from a fabricator
  (`uuid.uuid4`, `secrets.token_hex`, `crypto.randomUUID`, `uuid.v4`, `nanoid`).
  A project function is judged by its body before its name: a `new_trace_id()`
  that returns `str(uuid4())` makes up its identifier.
* **GUARD001**: a call that most sites make only after checking their argument
  (`if has_hash(x): remove_hash(x)`, `if (!hasHash(x)) return;`, `assert
  exists(x)`, `if not ok(x): raise`), made here with no check of that argument.
  A guard is a call with the same first argument (by text) known true where the
  call runs; any check counts (`isdir` where the others use `exists`). Reported
  when at least `guard_min_sites` (3) sites exist, at least `guard_min_percent`
  (75) of them are guarded, and some are not; the message names the most common
  guard. Not reported when the callee checks that parameter itself before
  anything else (`if not isinstance(tags, str): raise TypeError(...)`, `assert
  has(x)`, `if (!isNote(n)) throw ...`): a call without the check fails loudly
  there.

### DOM002: a floating control a press handler treats as outside (review, opt-in)

A page-level press handler that acts on presses outside (leaving edit mode,
swallowing the next click) skips the elements that handle their own presses
through `target.closest(<selectors>)`. A control attached to `document.body`
later (a notice, a banner, an overlay) sits outside everything that list was
written for, and its first press silently does the wrong thing (spec 21.1
decision 32; MetaList's backup reminder button did nothing while a note was
being edited). The project names the functions holding those skip lists in
`rules.dom.press_exclusions` (`"path:function"`); nothing is reported while the
list is empty, because most press handlers only close their own widget and for
them every other element is meant to be outside.

A skip list is the `closest(...)` / `matches(...)` arguments of the named
function: strings, `[...].join(",")`, constants defined in the file or imported
from an analyzed one, and the lists of the plain helper functions it calls
(followed through imports). A control is an element passed to
`document.body.append` / `appendChild` / `prepend` / `insertBefore` /
`insertAdjacentElement`, or appended into what a function that attaches and
returns an element gives back (`appNoticeStack().append(card)`), when the
building function makes something pressable (a `<button>`, `role="button"`, a
click or pointer listener) and the element is not a helper (removed again,
clicked or submitted by the code itself, a file or hidden input). It is reported
where it is attached when its id, classes and tag (or its container's) match the
last compound of no selector of a list (`.modal .close` is matched on `.close`;
attribute and pseudo parts are not evaluated). An entry whose file was analyzed
but holds no such function is reported as `unknown`. Approximate; `review`
(`rules.dom.dom002_severity`); JavaScript and TypeScript, vanilla DOM only.

Measured: on MetaList before its fix, with its two press handlers named, 5
findings: the two notice-stack buttons (the bug), the reminder surface (fixed
later), the error banner (likely) and a modal opened only outside edit mode
(probably not). Ten widely used front ends (Trilium, Etherpad, TiddlyWiki,
CodiMD, flatpickr, select2, Choices, Tom Select, Quill, summernote) attach one
pressable element to the body in vanilla DOM between them; they build floating
UI with jQuery or a framework, which DOM002 does not read.

### MAGIC002: one string repeated across files (review)

A status (`"pending"`), an error code (`"ERESOLVE"`), a platform or a mode
written out at several places and compared in more than one file is one
decision copied around: a rename or a typo in one copy splits it silently (spec
21.1 decision 31). MAGIC002 groups the string literals of every file in
`rules.magic_strings.roles` (production) by value and reports a value that is at
least `min_length` (4) characters long, whitespace aside, appears at least
`min_occurrences` (3) times in at least `min_files` (2) files, and is compared
(`==`, `!=`, `in`, `===`, `!==`, a `case`) in at least `min_compared_files` (2)
of them. One finding per value, at its first use, naming up to three other
places. Counted positions (`kinds`): call arguments, subscripts, comparisons and
plain values; dict / object keys (`key`) and JSX attribute values (`jsx`) are
opt-in. Never counted: docstrings and directives, f-string and template parts,
type annotations and TypeScript literal types, import specifiers, `require()` /
`import()` arguments, `__all__`, the value of an UPPER_SNAKE_CASE definition
(`PENDING = "pending"` is the remedy), the message of a log or print call
(`message_callees`) or of a callee ending in `Error`, `Exception` or `Warning`,
and the values in `allowed` (`"utf-8"`, `"__main__"`, `"strict"` ...).
Approximate: two equal strings may mean different things. Requiring comparisons
in two files is what separates a decision from a word that repeats: on pip,
pytest, hypothesis, build, hatchling and npm analyzed as one tree, 956 values
repeat, and 171 are reported (`"win32"`, `"darwin"`, `"only-if-needed"`,
`"teardown"`, `"ERESOLVE"`; generic words such as `"text"` and `"none"` remain).
`mode = "fail"` makes the findings errors.

### MAGIC003: a small number standing in for a meaning (review)

MAGIC001 permits `-1`, `0` and `1` because they are how code counts and indexes.
Used as a value they can also encode a meaning of the program's own: "nothing
selected", "never ran", "no limit". MAGIC003 reports the values in
`rules.sentinels.values` (`-1` by default; only values MAGIC001 permits are
checked, so nothing is reported twice) where they stand for a value: the whole
value of an assignment (a variable, attribute, subscript or class field), a
return (an arrow body too), an argument or keyword argument, or a dict / object
entry. Not reported: subscripts, slices, arithmetic, comparisons
(`indexOf(x) === -1`), an UPPER_SNAKE_CASE target (`NO_SELECTION = -1` is the
remedy), and arguments of the `python_index_callees` / `javascript_index_callees`
catalogs (`range`, `slice`, `.pop`, `.split`, `.reshape`; `.slice`, `.at`,
`.splice`, `.substr` ...), where `-1` is an index or a count. Also not reported:
an assignment to, or an entry of, a name in `standard_targets` (`tabIndex`, where
HTML defines `-1` as "focusable, not in the Tab order"), and a `-1` passed to a
callee that the same file also passes `1` (`move(-1)` beside `move(1)`: a
direction). On pip, pytest,
hypothesis, build, hatchling and npm it gives 42 findings where 0.6.0 reported
543 for `-1` (`sys.exit(-1)`, `return -1` for "not found", `lineno = -1`,
`max(..., default=-1)`, click's `nargs=-1`).

### MAGIC004: a constant name that only spells a number (review)

Allowing named constants (decision 36) invites one evasion: a name that says
nothing more than the literal (`TWO = 2`). MAGIC004 reports a module-level
constant definition, the ones `named_constant_definitions` covers, whose name,
split at underscores, is only number words (`ZERO` to `NINETEEN`, the tens,
`HUNDRED`, `THOUSAND`, `MILLION`, `BILLION`, `DOZEN`) or digits, after dropping
filler (`NUMBER`, `NUM`, `VALUE`, `CONST`, `CONSTANT`, `INT`, `AND`): `TWO`,
`ONE_HUNDRED`, `VALUE_100`. A name with any other word (`TIMEOUT_30`,
`INDENT_SPACES`) is not reported. Severity
`rules.magic_numbers.magic004_severity`, `review` by default. On the measurement
above it reported nothing.

### MAGIC005: a number written as something else (warning)

In the under-the-gate experiment, agents met MAGIC001 by spelling the number
differently. That keeps the number and hides it. MAGIC005 reports these shapes,
read from the syntax:

* **The length of a literal written for its length:** `len("  ")` of a
  whitespace-only string, `len((a, b))` or the length of another display, and in
  JavaScript `"  ".length` or `[a, b].length`.
* **A string converted to a number:** `int("30")`, `float("2.5")`,
  `Number("3000")`, `parseInt("30")`, `parseFloat("1.5")`, `+"30"`, when the text
  is a plain finite number.
* **Numbers inside an inline string that is parsed:** `json.loads`,
  `tomllib.loads`, `tomli.loads`, `ast.literal_eval`, `yaml.safe_load` or
  `JSON.parse` of a string literal (`tomllib.loads("max_age_hours = 24")`).
  Every number in the text is read; a version such as `"1.2.3"` is not a number.
* **Spaces given where an indent count is meant:** `json.dumps(v, indent="  ")`,
  `JSON.stringify(v, null, "  ")`, or the same through a module-level constant
  bound once to spaces (`REPORT_INDENT = "  "`).

A value outside `allowed_values` is reported (`-1` as `allow_unary_negative_one`
says). The rule applies exactly where MAGIC001 applies: a file or role that has
MAGIC001 off (the test exemption `init` writes) has MAGIC005 off too. Severity
`rules.magic_numbers.magic005_severity`, `warning` by default.

The length of a string with content is not reported. `line[len("Bearer "):]` or
`"YYYY-MM-DD".length` says what the number is, and `text.removeprefix("0x")` says
it better. Callees are matched by the name as written, so an alias of a parser is
not seen, and a constant imported from another module is not followed.

**Measured** (0.13.0 and this rule):
* MetaList and the third-party corpus: no findings.
* The experiment's gated builds: 11 of the 12 disguises in production code. The one
  missed imports its indent constant from another module.
* Before the length check was narrowed to whitespace, it reported 24 MetaList and 13
  corpus prefix lengths, every one of them legitimate.

### DOM001: a delegated handler that drops SVG targets (warning)

A delegated click handler that narrows `event.target` to `HTMLElement` before
`event.target.closest(...)` silently ignores a click whose target is an SVG
element, an icon inside a button, although `closest` is defined on every
`Element` (spec 21.1 decision 27). Reported, in one function body: `if (!(X
instanceof C))` followed by an early `return`, `throw`, `continue` or `break`
and, later in the same block, `X.closest(...)`; or `if (X instanceof C)` whose
consequence calls `X.closest(...)`. `X` is `<expr>.target` or a local assigned
from one (never `currentTarget`, the element the listener is on); `C` is in
`rules.dom.classes` (`HTMLElement`). A narrower class (`HTMLButtonElement`,
`HTMLInputElement`) is a deliberate filter and is not reported. JavaScript and
TypeScript; exact.

### PROP001-PROP008: property contracts (opt-in; Python, JavaScript, TypeScript; milestones P1a to P3)

The family of `docs/shockharness_property_contracts_spec.md`, milestones P1a (Python),
P1b (JavaScript; TypeScript is read as JavaScript) and P2 (transitive results, await and
generators, verify mode). How to adopt it, and what to expect, is in
`docs/property-contracts.md`. It is off
by default and no profile turns it on. Off is not a deviation, does not list the rules
as disabled, and adds nothing to `coverage.rules_disabled_globally`. Enable it with
`rules.property_contracts.enabled = true`, a catalog of properties, and the
`runtime_module` that `shockharness contracts install` wrote (see
`docs/configuration.md`, "Property contracts").

**Declarations.** There are four declarations, imported from the installed runtime
file: `requires(value, "p", ...)`, `produces(value, "p", ...)`, `preserves(result,
source)` and `preserves_except(result, source, "p", ...)`. Each returns its first
argument. A call counts only when it resolves, through the file's imports, to a module
that `runtime_module` names: a Python module path or name, or a JavaScript path or
package (`import { requires } from "./vendor/shockharness-contracts.js"`). That module
may be excluded from analysis, because only its name is needed. A function named `requires` from anywhere else is an ordinary call.
A function's contract is read from its own body:

* the `requires` statements on parameters at the top of the body, before any other use
  of the parameter;
* the result set of its own returns.

There is no separate declaration.

**The analysis.** Each function, and each module body, is walked in source order:

* **What carries properties.** Assignment copies a value's property set. `produces`
  adds to it. `preserves` copies the source's set, and `preserves_except` removes the
  named properties. Calls nest and are evaluated inside out:
  `produces(preserves(expr, x), "p")` gives a result computed from `x` by an undeclared
  operation `x`'s set plus `p` (spec §4.2). `a or b`, `a if c else b`, `a || b`,
  `a ?? b` and `c ? a : b` are the intersection of their operands.
* **Literals and compositions (spec §5.2a).** A string literal with no interpolation
  carries every property marked `literal_satisfies`. A composition carries a catalog
  rule's `produces` when every non-literal part carries one of the rules' `inputs_require`
  for that operation and `produces`. The compositions are an f-string, a JavaScript
  template literal, a `+` chain with a string literal in it, `"...".format(...)`,
  `"..." % x`, and a join (`join` rules): `"sep".join(items)` in Python and
  `[a, b].join(sep)` in JavaScript. A join's parts are a non-literal separator and the
  items: the elements of a list, tuple or set display (an array literal in JavaScript), or
  the element expression of a comprehension or generator expression (`"\n".join(prefix +
  line for line in text.splitlines())` names `prefix + line`). A join over any other
  value (a variable, `.map(...)`) is unknown: a container's items are not tracked.
  Literal parts are not checked. One part known to fall short makes the whole carry
  nothing, and the finding names that part; an unknown part makes it unknown. With no
  rule for its operation, a composition carries nothing.
* **What destroys them.** Any other operation, literal or library call carries nothing.
* **Control flow.** Branches meet in the intersection, and loops iterate to a fixed
  point. An except handler starts from the set at the start of its try. A parameter
  starts with what the function requires of it; a parameter with no `requires` starts
  with nothing (the `declared` level).
* **Calls.** A call that resolves to a project function is checked against that
  function's contract (its header `requires`). Its result is the function's own result
  set, with the function's further calls followed transitively up to `max_depth`
  crossings (3 by default; deeper is unknown, and so is recursion). A function that
  returns another's result carries the property through without redeclaring it. The
  function's file is read from the analyzed files, or else from the project under the
  root, so a check of one file still sees its imports' contracts. A `preserves(result, x)`
  on a parameter that requires nothing makes the result parametric: each call site
  substitutes its own argument's set (decision 48).
* **Await and generators (§5.2c).** `await` of a project async function gives its
  result, and `await` is otherwise transparent; a coroutine or Promise used without
  `await` carries nothing. A `for`/`async for`/`for await` over a call of a project
  generator binds the loop variable to the generator's item set (the intersection over
  its `yield`s; `yield from`/`yield*` delegate).
* **Methods.** A method resolves when its receiver's class is exact: `self.m()` /
  `cls.m()` / `this.m()` in a class no analyzed subclass overrides `m` in (a closed world
  over the analyzed files), a module-level singleton bound once to a constructor call, a
  JavaScript module-level object literal whose module never assigns that method again
  (`export const Auth = { init() {...} }`), a local the function constructs once,
  `Class.m()` in Python, and `Class(...).m()` / `new Class().m()`. `this` in an object
  literal's method is unknown: it depends on how the method is called. The method is looked up in
  the class and then in its project bases, left to right; a base that is not a project
  class makes the call unknown. The call's arguments start after the parameter the
  receiver supplies (`self` through an instance, `cls` always, none for a static method).
  A property, a getter or a setter is not a method (`docs/proposal-receivers.md`, R1 and
  R2).
* **Unknown sets.** Some calls cannot be resolved: a method on a value whose class is not
  exact, a callable in a variable or a container, a class or `new`, a dynamic import. A generator consumed by a
  library call (`list(gen())`) or a comprehension, a generator expression, `async with`,
  a loop over an unresolved iterable, and a `.join` build are unknown too.
* **JavaScript calls.** Functions resolve through `import`/`require`, re-exports and
  `export default` to `path:export` (`static/js/html.js:escapeHtml`). Package callees are
  `package:name`, with `Pkg.f()` on a default import as `package:f`. Globals are
  `fetch` or `JSON.stringify`.

| Rule | Reports | Default |
|---|---|---|
| `PROP001` | a value reaching a parameter whose function `requires` a property, a catalog sink (`callee:N`), or a mid-body `requires` on a local, without that property. When the value's set is unknown, the finding is `unknown` and gates only with `fail_on_unknown = true` | review |
| `PROP002` | a `produces` of a property whose catalog `producers` list is not empty, in a function that is not one of them (Python `module.function` or `module.Class.method`, JavaScript `path:export`); module level and nested functions are never producers | review |
| `PROP003` | a property name the catalog does not list. The name is not counted, so a misspelled requirement is never silently checked. With `allow_undeclared = true` it is `review` and counted | **error** |
| `PROP004` | a return whose known set lacks a property another return of the same function carries: the result carries only the intersection (falling off the end is not reported) | review |
| `PROP005` | a test bootstrap's `enable(mode, [...])` (in a test-role or config-role file such as `conftest.py`, whatever `roles` says) whose literal list is not the catalog's `runtime = "static"` set. The finding names what is missing and what the catalog does not mark static. `shockharness contracts static-properties` prints the list to paste. With `runtime_mode_required = "verify"`, also each non-static property the `registration_module` never passes to `register(...)`, reported on the configuration file at the `registration_module` line | review |
| `PROP006` | a declaration the analysis cannot read: a property that is not a string literal, `produces`/`preserves_except` with no property, `preserves` without exactly two arguments, any keyword or starred argument. The call is the identity and contributes nothing. In a test bootstrap, an `enable(...)` whose second argument is not a literal list of string literals | review |
| `PROP008` | under `enforcement = "complete"` or in `complete_paths`: a parameter of a module-level function or a method (`self`/`cls` excepted) with no `requires`, or a return of a value with no `produces`/`preserves`/`preserves_except`; `requires(x)` with no property satisfies it and is listed in `shockharness exceptions` as the sorry count | review |
| `PROP007` | a `requires` on a parameter that is not at the top of the body (after a use of the parameter, or inside a branch, loop, try or with). It is not part of the contract. A parameter the body rebinds is a local after that, and a `requires` on it is a mid-body check | review |

**Sinks.** A catalog sink is a callee or an assignment target. A callee is a project or
library callee resolved through imports (`app.cloud.send_messages:0`, `json.dumps:0`,
`static/js/api.js:post:1`, `fetch:1`), and its argument is addressed by position. A
Python keyword argument maps to its position through a project callee's parameter list.
For a library callee a keyword argument is unknown, and so is an argument passed through
`*args`, `**kwargs` or a spread. An assignment target is `target = "innerHTML"` (that
attribute on any receiver: `el.innerHTML = v`, and `+=`) or `target = "headers[]"` (a
subscript of the named receiver). A sink entry may name its `producer`, and the finding
repeats it.

**Severities** are `rules.property_contracts.severities.PROP001` and so on. Lowering one
is a VERIFY003 loosening. So are these:

* turning the family off;
* `fail_on_unknown` true to false;
* `allow_undeclared` false to true;
* while the family is on:
  * removing a sink (callee or target), or a property from a sink's `requires`;
  * lowering a property's `runtime`; dropping or widening its `producers`; setting
    `literal_satisfies`;
  * a composition rule that accepts parts no earlier rule with the same language,
    operation and `produces` accepted: an added rule, a property removed from
    `inputs_require`, a changed `produces`;
  * `enforcement` lowered from `complete` to `declared`, or a glob removed from
    `complete_paths`;
  * lowering `max_depth` while `fail_on_unknown` is false (paths that resolved to
    violations become unknown findings that do not gate), lowering
    `runtime_mode_required`;
  * removing a role or a runtime module.

Raising `max_depth` is never a loosening: following calls deeper turns unknown paths
into verdicts, some of them violations (decision 47). While `fail_on_unknown` is true, a
change of `max_depth` in either direction is reported in a revision diff as an
analysis-scope change at review, because it trades gating unknown findings for verdicts.

`RESULT001` never reports the four Python declarations as discarded results when they
resolve to the runtime module.

**Not in P1a and P1b** (spec §14):

* TypeScript-specific behaviour: type annotations are ignored;
* catalog preserving operations (slicing);
* annotation forms of the declarations and Hypothesis integration (P4).

JavaScript static methods and default imports are not resolved through their
receivers, and a class call (a constructor) is unknown. A JavaScript method sink (`insertAdjacentHTML`) can therefore not match, and
the subscript form of a target matches only a named receiver.

### DEAD001 and DEAD002: functions nothing in production reaches (review, opt-in)

Spec 21.1 decision 38, from MetaList: `note_renderer.build_note_tree` had no callers and
about 400 lines hung off it, among them `highlight_search_terms`, the only code that
highlighted search phrases. When the notes list moved to a new renderer its last caller
went away, and highlighting stopped for about a year while its tests kept passing.

Both rules are one reachability judgment over the call graph and the references it does
not record. **Roots** are module and class bodies, functions a decorator registers (any
decorator except the ones that only change how a function is called: `staticmethod`,
`classmethod`, `property`, `cached_property`, `setter`, `cache`, `lru_cache`, `wraps`,
`abstractmethod`, `override`, `overload`, `final`), names in `__all__`, dunder methods,
JavaScript `constructor`s, every method of a class with a base the project does not
define, directly or through project ancestors (a framework calls those:
`HTMLParser.handle_*`, `NodeVisitor.visit_*`, `server_bind`), of a class nested in a
function (its bases are not known), and of a class whose instance a file assigns to an
attribute of an imported module (`sys.stdout = stream`: the library calls `write`,
`isatty`), the `[project.scripts]` targets of the root `pyproject.toml`, the files the
property-contracts `runtime_module` names by path, and `rules.dead_code.entry_points`. **A function is
reached** through any call-graph edge, an unresolved call or an attribute read or write of
its final name (`obj.name`, `obj['name']`, `getattr(obj, 'name')`, `this.h.bind(this)`,
a method called on a call's result such as `Guard(x).check()`, a method of an exported
instance, a function another module re-exports),
a bare name used as a value (passed, stored, listed, in an `Annotated[..., Depends(f)]`
annotation), a used import of it, a name `__all__` re-exports, and a function nested in a
reached one. **A method** is alive while a method it overrides, or one that overrides it,
is alive: dispatch decides which runs.

Test and config files are roots of their own. A dead function only they reach is DEAD002;
the rest are DEAD001. One finding per head, a dead function no other dead function
reaches: the message lists what is reachable only through it (a dead method and its dead
overrides are one cluster), the logical lines in all, and which of those functions tests
still call. The judgment is made only when the run analyzed every included file and none
failed to parse.

Names are matched loosely toward "alive": a dead function that shares a final name with a
called one is not reported. Live code looks dead when its caller is invisible: `getattr`
with a computed name, a dispatch table keyed by strings built elsewhere, a function only an
HTML page, a template or an excluded file calls. Those go in `entry_points`. Arrow
functions and function expressions are judged only when bound to a declared name or a
class field, and object-literal methods only when the object is bound to a name.

**Measured** on MetaList at e60e88dc: 154 findings (111 DEAD001, 43 DEAD002), the
`build_note_tree` cluster among them (20 functions, 375 logical lines, `highlight_search_terms`
named as still tested). Of two random samples of 30 heads, 26 and 24 were dead; the false
positives (methods of a class nested in a function, FastAPI dependencies named only in
annotations, a `__all__` re-export) are roots now. On ShockHarness itself: 16, of which 12
were dead and are deleted; the other 4 are the contracts runtime's public API, the
repository's one entry point. ShockHarness runs both rules on itself.

### DUP001 and DUP002: helpers copied into several files, and copies that drifted (review, opt-in)

Spec 21.1 decision 39, from MetaList: twenty HTML escapers, one per dialog, all escaping the
same five characters, but some returned `''` for a non-string where the others threw, so a
bad value failed loudly in one dialog and showed blank text in another.

Both rules compare **function shapes**: a named function's body (a def or method; a
JavaScript declaration or method, or a function bound to a declared name, class field or
object key) as its syntax tokens in source order, with comments, layout and the docstring
dropped, parameters and locals renamed by first appearance, and a string's mention of the
file's own path or the function's own name set aside (copies that label themselves, such
as `boundary='app/a.py:run'`, compare equal). Only functions with at least
`min_statements` (3) statements and `min_tokens` (25) tokens, in the roles `roles` lists,
take part. Python is compared with Python, JavaScript with JavaScript and TypeScript.

* **DUP001** reports identical shapes in two or more files: one finding per group, at its
  first copy, listing the others.
* **DUP002** reports versions that have drifted apart: functions whose names match once
  leading underscores and case are set aside (`escapeHtml`, `_escapeHtml`), in two or more
  files, whose shapes differ but are at least `similarity` (0.85, difflib's ratio) alike.
  One finding per group, at the first copy of its most common version, with the first
  pair of lines where the two most common versions differ. Constructors are left out, and
  so are overrides of one method in classes of one inheritance family (polymorphism is
  meant to differ); DUP001 still reports identical ones.

Copies whose parameters or return are annotated with different types are parallel
implementations, not one helper: an import cannot replace one with the other (a function
over Python's `ast.AST` and its twin over a tree-sitter `Node`). Neither rule groups them.
An unannotated copy groups with any.

Judged only when the run analyzed every included file and none failed to parse. Syntax
only: bodies that do the same thing differently are not matched.

**Measured** on MetaList at e60e88dc, outside its browser test scripts: 43 DUP001 groups
(`showModalElement` in 17 modal classes, `dom-utils.js` and `dom-utils-fixed.js` sharing
eleven functions, process helpers copied into `main.py` and two services) and 24 DUP002,
about 21 of them worth acting on: `parsePort` and `_validate_job_id` throw different
exception types in their copies, one `getNoteElementById` escapes the id and one does not,
`reminderDisplayTitle` returns two different defaults. The rest differ on purpose
(`_normalize_direction` for two domains). Before the escaper merge (add573e3^) the escapers
are an 11-copy and a 4-copy DUP001 group and one DUP002 naming `throw` against `return ''`.

### IMPORT002: an import across a declared boundary (error, configured; Python and JavaScript)

Spec 21.1 decision 44, from MetaList, whose startup check (BKP001) keeps its startup and
database migrations from importing the backup service, so a migration can never touch a
backup, and lets the authentication service import only `create_timestamped_backup` from it.
A boundary like that is invisible in the code; an agent adding one convenient import crosses
it without knowing it was there.

Each `[[rules.import_boundaries.forbidden]]` entry (see `docs/configuration.md`, Import
boundaries) binds the files its `importers` globs match. Every import in a bound file is
judged, at any depth, a function's lazy import included: Python `import` and
`from ... import`, JavaScript and TypeScript `import`, `export ... from`, `require(...)` and
`import(...)` with a literal specifier. An import that resolves to a file the `imported`
globs match is reported, unless every name it takes is in `allowed_names`; an import of the
whole module takes every name. One finding per import, at the import, naming the module and
the entry's reason.

Not judged: an import that does not resolve to an analyzed file (a check of one file does
not resolve its imports, so the edit-time hook sees only what that run analyzes), computed
specifiers (`importlib.import_module(name)`, `import(expr)`), and TypeScript type-only
imports. Direct imports only: a forbidden module reached through another project module is
not reported.

**Measured** on MetaList at 4d4e9847 with BKP001's two pairs as entries: no finding. With
four imports added (a lazy `from ... import` in `app/db/migrations.py`, `from app.services
import backup_service` and `import app.services.backup_service` in `app/main.py`, and
`list_backups` added to `auth_service.py`'s import): all four reported. BKP001 reports two
of them; it does not see an import of the whole module.

## Registered, not implemented

None since MAGIC002 landed. A rule registered before it is built is listed in
every report under `coverage.rules_not_implemented`, and the text report prints
the list when it is not empty.

## Rule metadata contract

Each rule has an immutable ID, a version (bumped when detection semantics
change), a default severity, a summary, rationale, detection guarantees,
limitations, remediation guidance, and compliant/non-compliant examples. All of
this is in `src/shockharness/rules/registry.py` and printed by `rules explain`.
