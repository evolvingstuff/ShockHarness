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
which is reported as `other` and left to EXC001. For a guarded JavaScript
handler the statements after the guard are classified. A returned variable may
still be a fabricated default; DEF005 (Milestone D) will cross-reference
catches with defaults.

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

## Registered, not implemented

These IDs are reserved and configurable now; they produce no findings and are
listed in every report under `coverage.rules_not_implemented`.

| ID | Name | Planned milestone |
|---|---|---|
| MAGIC002 | suspicious string literal (advisory) | post-B |
| DEF001 | function parameter default | D |
| DEF002 | missing mapping/object fallback | D |
| DEF003 | truthiness fallback | D |
| DEF004 | nullish fallback | D |
| DEF005 | exception-to-default | D |
| DEF006 | implicit configuration fallback | D |
| CPLX001 | cyclomatic complexity | E |
| CPLX002 | cognitive complexity | E |
| CPLX003 | nesting depth | E |
| CPLX004 | NPath estimate | E |
| CPLX005 | coupling / cycles | E |

## Rule metadata contract

Each rule has an immutable ID, a version (bumped when detection semantics
change), a default severity, a summary, rationale, detection guarantees,
limitations, remediation guidance, and compliant/non-compliant examples. All of
this is in `src/shockharness/rules/registry.py` and printed by `rules explain`.
