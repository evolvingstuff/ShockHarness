# Property contracts

Some facts about a value cannot be seen in the value itself: a series is normalized,
text is redacted, markup is sanitized, a path was validated. Property contracts let you
write these facts into the code and have ShockHarness check every path to the place
that needs them. The design is `docs/shockharness_property_contracts_spec.md`. This page
is how to use it. The rules are described in `docs/rules.md`, and every key in
`docs/configuration.md` ("Property contracts").

The family is **opt-in**: no profile turns it on, and it is off in a repository until
`rules.property_contracts.enabled = true`.

## Adopting it

1. **Start with one pipeline**, the one where a missing property is a real bug: the
   privacy boundary before a cloud call, or the HTML sink. Do not start with the whole
   codebase.
2. **Install the runtime file.** It is a single file your project owns. Nothing is
   published, and your project does not depend on `shockharness`:

   ```
   shockharness contracts install --language python --dest app/contracts.py
   shockharness contracts install --language javascript --dest static/js/vendor/shockharness-contracts.js
   ```

   List the destination under `runtime_module`. `shockharness contracts install --check`
   (in CI) reports a copy that was edited or that an upgrade made stale.
3. **Write the catalog**: a few properties, each with a description, its producers and
   its `runtime` level, and the sinks that need them (a callee such as
   `app.cloud.send_messages:0`, or an assignment such as `innerHTML`).
4. **Declare** with the four calls imported from the runtime file:
   * `requires(x, "p")` at the top of a function, for what a parameter must carry;
   * `return produces(value, "p")` in the producer;
   * `preserves(result, source)` and `preserves_except(result, source, "p")` where a
     result keeps what its source carried.
5. **Run `shockharness check`** and read the PROP001 findings. A violation means a path
   reaches the requirement without the property. An unknown finding means the analysis
   could not follow the value (next section).
6. **Gate when the unknown count is understood.** The findings are `review`. Raise
   `severities.PROP001` to `error` to gate on violations. Set `fail_on_unknown = true`
   only when the pipeline's unknown findings are few and each one is understood.

Declaring a result computed *from* a value by an operation the analysis cannot credit
(arithmetic, a comprehension, a rebuilt dict) uses the nesting idiom. Each call returns
its first argument:

```python
def normalize(x):
    requires(x, "numeric")
    return produces(preserves((x - x.mean()) / x.std(), x), "normalized")
```

`preserves` gives the result `x`'s set (here `numeric`), and `produces` adds
`normalized`. Any operation not declared destroys every property: that is the
conservative default, and each `preserves` is a visible claim that a reviewer can check.

**Pass-through helpers.** A property never passes through a parameter on its own:
`def ident(x): return x` carries nothing, whatever the caller passed. A generic wrapper
says `return preserves(x[:n], x)` on a parameter that requires nothing (or that has a
no-property `requires(x)`). Its result is then *parametric*: each call site passes on
what its own argument carried (decision 48). A wrapper that relies on a property says
`requires(x, "p")` instead.

## What the analysis follows

* **Within a function**, in source order: assignments, branches (the intersection),
  loops (a fixed point), `try`/`except` (a handler starts from the set at the start of
  the try), `a or b`, `c ? a : b`.
* **Into the functions it calls**:
  * a call that resolves through imports to a project function is checked against that
    function's `requires`;
  * its result is that function's own result, with the function's further calls
    followed up to `max_depth` (3 by default) and recursion not followed;
  * a function that returns another function's result carries the property through
    without redeclaring it.
* **Await and generators.**
  * `await f(x)` of a project async function gives that function's result. `await` is
    otherwise transparent.
  * A coroutine or Promise passed on without being awaited carries nothing.
  * A `for` or `for await` over a call of a project generator binds the loop variable to
    the intersection of the generator's yields. `yield from` and `yield*` delegate.
* **Strings.** A plain string literal carries the properties marked
  `literal_satisfies`. A composition carries what the catalog's rules say: an f-string,
  a template literal, a concatenation with a string literal in it, or `str.format`.
* **Sinks.** These are catalog callees (`json.dumps:0`, `fetch:1`, a project function)
  and assignment targets (`el.innerHTML = v`, `headers[k] = v`).

## Expect unknown findings

On a real application **many findings will be unknown**. They are reported, never
silent, and each says why. The usual causes:

* **A method on a value whose class is not exact**: a parameter (`store.get(x)` on an
  argument), an attribute (`self.cipher.redact(x)`), a callable in a container
  (`ops["f"](x)`), `self.m()` where an analyzed subclass overrides `m`, `this.m()` in
  an object literal's method. A method does resolve when its receiver is exact:
  * `self.m()`, `cls.m()` and `this.m()` in a class no analyzed subclass overrides `m`
    in;
  * a module-level singleton bound once (`store = Store()`,
    `export const store = new Store()`), used in its module or imported by name;
  * a JavaScript module-level object literal (`export const Auth = { init() {...} }`);
  * a local the function constructs (`s = Store()`, `const s = new Store()`);
  * `Store.m()`, `Store().m()` and `new Store().m()`.

  In Python the call's arguments start after the `self` or `cls` the receiver supplies
  (`docs/proposal-receivers.md`, R1 and R2).
* **Framework injection** (FastAPI `Depends`, a callback registered by name) and
  **dynamic imports** (`await import(...)`): the callee is not visible.
* **A call deeper than `max_depth`**, or recursion.
* **Generators consumed by something other than a for loop** (`list(gen())`,
  `next(gen)`), `.join` builds, `async with` bindings, and `new`/constructors.
* **A value read from a module-level variable**, or from an enclosing function.

What to do about an unknown finding:

* **When the property is established by something the analysis cannot see**, add
  `produces(x, "p")` at the point where it is established, and make sure a test
  exercises it. In `check` or `verify` mode the test then proves the claim at run time.
* **When the value goes through a helper**, call the helper directly instead of through
  an object or a registry, or give the helper its own `requires`/`produces`.
* **Do not remove a requirement to make a finding go away.** A requirement is the
  contract; the finding is the evidence that some path does not meet it.

Read the unknown count of the one pipeline you started with before setting
`fail_on_unknown = true`. Improvements to call resolution belong to the call graph, and
an unknown finding that later becomes a pass or a violation measures that improvement.

## The runtime: off, check, verify

The runtime file is identity-only until test code turns it on, once, before any
declaration has run:

```python
# conftest.py
from app.contracts import enable
enable("check", ["cloud_disclosable", "sanitized_html"])   # the catalog's static properties
```

The second argument is the catalog's `runtime = "static"` list. The file cannot read
`.shockharness.toml`. `shockharness contracts static-properties` prints the list to
paste, and PROP005 reports a bootstrap whose literal list has drifted. Production never
calls `enable`, so production has no setting to get wrong. When the application server
is started by production code (a browser suite), start it from a test-only entry script
that calls `enable` first.

In a browser, the page's modules evaluate before any test harness can import the
module. There are two sanctioned patterns:

* **A test-entry page** whose first module script is
  `import { enable } from "./vendor/shockharness-contracts.js"; enable("check", [...]);`.
  Module scripts evaluate in document order. In Node, call `enable` and then
  `await import("./app.js")`, because a static import is evaluated before the call.
* **An init script** (Playwright `addInitScript`, Puppeteer `evaluateOnNewDocument`)
  that sets `globalThis.__shockharnessContracts = { mode: "check", static: [...] }`.
  The module reads it once, at load, treats it exactly as a call to `enable`, and
  deletes it.

What each mode does:

| Mode | `requires` | `produces` | `preserves` |
|---|---|---|---|
| `off` (not enabled) | returns the value | returns the value | returns the result |
| `check` | throws `ContractError` when a property is not recorded on the value | records the properties | copies the source's recorded properties |
| `verify` | as `check`, then runs each property's predicate | runs the predicates first (a producer may not claim what is false), then records | as `check` |

In `verify` mode, predicates are registered once, at startup, in the catalog's
`registration_module`: `register("normalized", predicate, "mean 0, deviation 1")`. With
`runtime_mode_required = "verify"`, PROP005 reports any non-static property that module
never registers.

**Runtime levels per property** (`runtime` in the catalog):

* **Strings and numbers cannot carry runtime properties**: `id()` collides and small
  values are interned. A property whose values are strings (sanitized HTML, redacted
  text, a validated path) is `runtime = "static"`. The static analysis checks it on
  every path. The runtime skips it and counts the skip (`report()["static_skips"]`).
* **`"check"`** tracks presence on objects. A check-level property that reaches a
  string, number, boolean or None at run time throws, because that is a catalog mistake.
  Mark the property `static` or `verify`.
* **`"verify"`** runs a predicate. It works for strings too: a string is checked by its
  predicate alone.

**The memory cost of check and verify mode.** The registry holds weakly referenceable
objects weakly. Lists, dicts and slotted objects are held for the life of the process.
That is one reason the modes are for tests, never production.

## The `complete` level

`declared` checks the declarations that exist. `complete` makes their absence visible.
Under `enforcement = "complete"`, or in a file matching `complete_paths`:

* every parameter of every module-level function and method needs a `requires` (PROP008);
* every return of a value needs a `produces` or `preserves` (PROP008).

`self` and `cls` are exempt. Nested functions, lambdas and inline callbacks are not
contract units, and a function with no return has no result contract. `requires(x)`
with no property is the honest declaration for a parameter that needs nothing:
`shockharness exceptions .` lists each one under "the sorry count", and reviewers read
that list like the suppressions.

Adopting `complete` on an existing application goes path by path. Add the security
layer to `complete_paths`, take a baseline, burn the PROP008 findings down, and then
add the next area. A greenfield repository sets `enforcement = "complete"` and leaves
the list empty. Narrowing `complete_paths`, or lowering `enforcement`, is a VERIFY003
loosening.

## Skills

`shockharness skills install` ships three skills that cover contracts:
* `property-contracts`: choosing properties, predicates, the runtime modes, where
  `enable` goes, the catalog, the sorry count;
* `write-compliant-code`, principle 10: declaring contracts in new code;
* `fix-violations`: the PROP001 and PROP008 procedures. Route the value through the
  producer, or `produces` with a test; never delete a `requires`; stop and ask when the
  contract cannot be determined.

## Not there yet

* Annotation forms of the declarations (`Annotated[T, Prop("p")]`, branded types) and
  Hypothesis integration are P4, with the two MetaList measurements.
* Annotations do not type a receiver (R3), and JavaScript static methods and default
  imports are not resolved through their receivers. Catalog preserving operations
  (slicing) are not implemented.
