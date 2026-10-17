# ShockHarness Property Contracts: Specification

**Status:** Design specification, v0.1, for implementation by the ShockHarness coding agent
**Date:** 2026-10-17
**Rule family:** `PROP001`–`PROP008`, configuration section `rules.property_contracts`
**Languages:** Python, JavaScript, TypeScript (same guarantees as every existing rule)
**Default:** **off**. This family is opt-in. A repository that enables it chooses one of three enforcement levels (§9). Nothing in this document changes the behavior of a repository that does not enable it.
**Audience:** The implementation agent and the maintainer.

> **Directive to implementation agent:** Build this as a new rule family and a separate, tiny runtime library. Follow the existing ShockHarness conventions without exception: deterministic findings with spans, the `unknown` state where a property cannot be established, no autofix, no new runtime dependency for the analyzer, every rule at `review` until precision is measured on a reviewed corpus, the self-gate passing with the new rules enabled on the tool's own code. Work in the milestones of §14 and stop after each one with evidence in `STATUS.md`. Where this document conflicts with `agent_code_integrity_project_spec.md`, the project spec is binding and this document should be annotated to say so.

---

## 0. Summary

A **property** is a fact about a value that is not observable from the value itself: that it has been normalized, validated, redacted, authenticated, issued by a registry, deduplicated. A value may carry any number of properties at once. A function may **require** that an argument carries some set of properties and may **produce** a result that carries some set.

Property contracts let a program declare these facts in its source, in a form that is identical across Python, JavaScript and TypeScript, that tree-sitter and `ast` can read without a type checker, and that ShockHarness can check statically through its existing per-unit dataflow and cross-file call graph. The same declarations can optionally be enforced at runtime by a small library whose cost is chosen per environment: identity functions in production, presence checks in test, full predicate verification when wanted.

The idea is known in the type-theory literature as refinement types with phantom (branded) properties, and, where properties change along a pipeline, as typestate. This specification adapts it to dynamically typed, agent-written code and to ShockHarness's deterministic, fail-visible posture.

Three enforcement levels are defined (§9):

| Level | Meaning |
| --- | --- |
| `off` (default) | The family is not applied. Declarations in the code are ignored. |
| `declared` | Declarations are checked where they exist. A function with no declarations has no contract. |
| `complete` | Every production function must declare its contract. Undeclared parameters and returns are findings. This is the "stricter codebase" setting the maintainer described. |

---

## 1. Motivation

ShockHarness's existing hard policies remove the syntactic places where silent failure hides: catches, defaults, unexplained numbers. The verification-integrity rules guard the gate itself. What remains unexpressed is the **contract between functions**: what a callee assumes about its arguments, and what a caller may assume about a result. Today that contract lives in docstrings, in the agent's context, or nowhere.

Two existing rules already infer fragments of it. `PROV001` infers that a parameter is usually given a registry-issued identifier and reports a call site that fabricates one. `GUARD001` infers that a call is usually guarded and reports the unguarded sites. Both are majority heuristics that cannot know intent. Property contracts are the declared form of the same facts: a parameter that *requires* an issued identifier, a call that *requires* a checked precondition. Declared contracts turn heuristics into checks.

The motivating example from the maintainer: a numeric pipeline where a value must be normalized (centered and divided by its standard deviation) before it reaches a model-fitting function. Nothing about the number reveals whether that happened. A declaration that `normalize` *produces* `normalized` and `fit` *requires* `normalized` lets the harness verify that every path into `fit` passes through `normalize`, and lets a runtime check confirm it on the paths the static analysis cannot resolve.

Properties compose as a set, so a value may be `{centered, normalized, deduplicated}` and a function may require `{normalized}` alone. Requirements are subset checks. Nothing is ever named by its full combination, so there is no explosion of types.

---

## 2. Scope and non-goals

### In scope

- A uniform declaration syntax in all three languages (§4), read from the AST.
- A property catalog in configuration (§8) naming each property, its producers, its runtime predicate, and the operations that preserve it.
- Static checking (§5): per-unit, flow-sensitive property-set tracking; checks at resolved call sites through the existing call graph; explicit `unknown` where resolution fails.
- A runtime library (§6) with three modes, published as its own distribution for Python and npm, with no dependencies, itself passing ShockHarness.
- Rules `PROP001`–`PROP008` (§7) at `review` until measured, with the usual promotion criterion.
- Three enforcement levels (§9), the `complete` level being the opt-in strict mode.
- Updates to the `write-compliant-code` and `fix-violations` skills and one new skill, `property-contracts` (§12).
- Fixtures, metamorphic tests, and behavior-suite cases (§13).

### Explicitly deferred

- Language-native declaration forms (`typing.Annotated`, TypeScript branded intersections, JSDoc tags). The call convention is the base; native forms are Milestone P4 overlays that lower to the same facts.
- Proving that a producer actually establishes its property (that `normalize` really normalizes). The static analysis checks flow, not meaning. Runtime `verify` mode and the Hypothesis integration cover meaning where a predicate is declared.
- Property tracking through containers element-wise (a list of normalized vectors). First release treats a container as one value; a property applies to the container as a whole.
- Arithmetic preservation inference. Operations preserve properties only when the catalog says so.
- Any form of automatic insertion of declarations.

---

## 3. Concepts

**Property.** A short identifier in `lower_snake_case` (`normalized`, `redacted`, `issued_id`, `validated_path`). Properties are declared in the catalog (§8). A property name used in code that the catalog does not list is a finding (`PROP003`); the catalog may set `allow_undeclared = true` to make it `review` instead.

**Property set.** The set of properties the analysis believes a value carries at a program point. The empty set is the default for every value. Sets are ordinary sets; there is no ordering and no hierarchy.

**Producer.** A function that establishes a property on its result by calling `produces`. The catalog may restrict a property to named producers; a `produces` for that property anywhere else is `PROP002`.

**Requirement.** A function that needs a property on an argument declares it by calling `requires` at the top of its body. A call site must deliver a value whose property set includes every required property (`PROP001` otherwise).

**Preserver.** A function or operation that keeps some or all properties of its input on its output. Declared in code with `preserves` (for a function's own result) or in the catalog (for operations and library calls such as slicing or copying). Any operation not declared a preserver **destroys every property**. This is the conservative default and is not configurable.

**Transfer.** The effect of a statement on property sets: assignment copies; a call to a declared function checks requirements and yields the callee's produced set; an undeclared operation yields the empty set; a branch merge yields the intersection (a property holds after a merge only if it held on every path); a loop iterates to a fixed point on the intersection.

**Contract.** For a function: the requirements on its parameters and the properties of its result, as inferred from its `requires`, `produces` and `preserves` calls. Contracts are inferred from the body, never declared separately, so there is one source of truth.

---

## 4. Declaration syntax

### 4.1 The uniform call convention

Four functions, imported from the runtime library (§6). The same names, arities and semantics in all three languages.

```
requires(value, property, ...)           -> value
produces(value, property, ...)           -> value
preserves(result, source)                -> result
preserves_except(result, source, property, ...) -> result
```

- `value`, `result`, `source` are expressions; in practice almost always a simple name.
- `property` is a **string literal**. One or more. Never a variable, never an f-string or template literal. A non-literal property argument is `PROP006` and the call contributes nothing to the analysis.
- Every function returns its first argument unchanged (the identity) in every runtime mode, so the call can be used either as a statement or in an expression. The analysis treats the two identically. (`RESULT001` must list these callees as permitted statements; see §10.)
- There are **no parameter defaults** anywhere in the API. The analyzer's own policy applies to the runtime library.

### 4.2 Placement rules

- A `requires` on a **parameter** must appear in the function's body before any other statement that uses that parameter, and not inside a branch or loop. Otherwise it is `PROP007` (misplaced declaration) and is not counted as part of the contract. The intent is that a function's requirements are visible at its top, like a signature.
- A `requires` on a **non-parameter** (a local, an attribute read, a call result) may appear anywhere and is a mid-body check: the analysis verifies that the value's property set at that point includes the property. This is how a function asserts a property on something it looked up.
- A `produces` on the value of a **return statement** (`return produces(x, "p")`) declares the function's result property. A function whose returns disagree (one return produces `p`, another does not) has result set equal to the intersection, and the returns that lack `p` are `PROP004` (inconsistent result) at `review`.
- A `produces` on a **local** mid-body attaches the property from that point onward in the flow, as a transfer. It does not declare the function's result unless the local reaches a return without passing through a destroying operation.
- `preserves(result, source)` on a return gives the result the source's property set at that point. `preserves_except` removes the named properties first. `source` must be a parameter or a local whose set the analysis knows; otherwise the result set is `unknown`.

### 4.3 Examples

Python:

```python
from shockharness_contracts import requires, produces, preserves

def normalize(x):
    requires(x, "numeric")
    sd = x.std()
    if sd == 0:
        raise ValueError("cannot normalize a constant series")
    return produces((x - x.mean()) / sd, "normalized")

def head(x, n):
    requires(x, "numeric")
    return preserves(x[:n], x)          # slicing keeps whatever x had

def fit(x):
    requires(x, "normalized", "numeric")
    ...
```

JavaScript:

```js
import { requires, produces, preserves } from "shockharness-contracts";

function normalize(x) {
  requires(x, "numeric");
  const sd = stddev(x);
  if (sd === 0) throw new RangeError("cannot normalize a constant series");
  return produces(x.map((v) => (v - mean(x)) / sd), "normalized");
}

function fit(x) {
  requires(x, "normalized", "numeric");
  ...
}
```

TypeScript is the JavaScript form; type annotations are ignored by this family in the first release (§2, deferred overlays).

### 4.4 What is not a declaration

- A call to a function named `requires` that does not resolve, through the file's imports, to the runtime library (or to a vendored copy the catalog names) is an ordinary call and contributes nothing. Resolution uses the same import-resolution machinery as the existing catalogs (`rules.processes`, `rules.async_lifecycle`).
- Comments and docstrings are never declarations in this release.
- `assert` statements are never declarations. `requires` is the named, harness-visible form of the assertion the maintainer already writes; the two coexist.

---

## 5. Static semantics

### 5.1 Facts the IR records

Extend the per-unit dataflow facts added in H6 (decision 26 of the project spec). Today every value is a set of **origins**. Add a parallel **property set** per value, computed by the same flow-sensitive walk. The two are independent: a value can have origins and properties.

Record per unit:

- its **requirements**: parameter name → property set, from top-of-body `requires` calls (§4.2);
- its **result set**: the intersection over return statements of the properties the returned expression carries;
- every **mid-body requirement** with its span;
- every **produces** with its span and property names;
- every **preserves** / `preserves_except` with its spans.

Record in the module graph which units are declared producers of which properties.

### 5.2 Transfer rules

Within a unit, in source order, with the existing flow-sensitive treatment (branches, loops, handlers):

| Statement | Effect on property sets |
| --- | --- |
| `y = x` | `props(y) = props(x)` |
| `y = f(x, ...)` where `f` resolves to a project unit with a contract | check each required property of each parameter against the argument's set (§5.3); `props(y) = result_set(f)` |
| `y = f(x, ...)` where `f` resolves to a catalog **preserver** entry | `props(y) = props(x)` minus the entry's `except` list |
| `y = f(x, ...)` where `f` resolves to a project unit with **no contract** | `props(y) = ∅` under `declared`; also `PROP008` under `complete` |
| `y = f(x, ...)` where `f` is unresolved or probable | `props(y) = unknown` |
| `y = x[...]`, `y = x.copy()`, `y = list(x)` and similar | per the catalog's `preserving_operations` list; otherwise `∅` |
| `y = x + 1`, `y = g(x)` for any undeclared operation | `∅` |
| `requires(x, "p")` mid-body | check `p ∈ props(x)`; no change to the set |
| `produces(x, "p")` | `props(x) = props(x) ∪ {p}` from this point |
| `preserves(r, s)` | `props(r) = props(s)` |
| merge of branches | intersection of the incoming sets; `unknown` if any incoming set is `unknown` |
| loop | iterate to a fixed point on the intersection; bounded by the existing nesting cap |
| `except` / `catch` entry | the set as it was at the start of the `try`; a property produced inside the `try` does not survive into the handler |

A parameter starts with the unit's declared requirement set for that parameter (the function may assume what it requires). Under `declared`, a parameter with no `requires` starts empty.

### 5.3 Call-site checks

At each resolved call of a unit `f` with requirements, for each parameter `p` with required set `R`:

- if `props(arg) ⊇ R`: satisfied;
- if `props(arg)` is known and does not include some `q ∈ R`: `PROP001` at the call site, naming `q`, the callee, and the parameter, with the evidence being the argument expression;
- if `props(arg)` is `unknown`: an `unknown` finding of `PROP001`, gated by `rules.property_contracts.fail_on_unknown`.

Checks cross units through the call graph exactly as `INPUT001` does: resolved and probable sites, with probable sites yielding `unknown`, result summaries computed to a fixed point, at most `max_depth` crossings (default 3, in the catalog not a literal).

A call through a method on an unresolved receiver, a callable stored in a container, `getattr`, or a dynamic import is `unknown`. This family does not attempt to improve resolution.

### 5.4 Determinism and ordering

Findings sort by the existing order (normalized path, start position, rule ID). Property sets are rendered sorted when they appear in messages or JSON. The fixed-point iteration must be order-independent; add a metamorphic test that reorders independent statements and checks the findings are unchanged.

---

## 6. Runtime library

### 6.1 Distribution

Two packages, separate from the analyzer so that an analyzed project never depends on `shockharness`:

- PyPI: `shockharness-contracts`, import name `shockharness_contracts`. Python 3.10+. Zero dependencies. A single module plus tests.
- npm: `shockharness-contracts`. ESM and CommonJS builds. Zero dependencies. TypeScript declarations included.

Both pass `shockharness check` under the `strict` profile with no overrides other than the test exemptions. A project may instead vendor the single file; the catalog's `runtime_module` key names where the analyzer should resolve the calls from.

### 6.2 Modes

Selected once at import time from the environment variable `SHOCKHARNESS_CONTRACTS`, which must be one of `off`, `check`, `verify`. **An unset variable is `off`**, which is the only implicit default in this design and is documented as such; the library emits nothing in that case. Any other value raises at import time (`ValueError` / `Error`), never falls back.

| Mode | `requires` | `produces` | `preserves` |
| --- | --- | --- | --- |
| `off` | returns value | returns value | returns result |
| `check` | looks the value up in the registry; raises `ContractError` naming the missing property if any required property is absent | records the properties on the value in the registry; returns value | copies the source's recorded properties to the result |
| `verify` | as `check`, then runs each property's predicate on the value and raises `ContractError` with the predicate's message on failure | runs each predicate first and raises if it fails (a producer may not claim what is false), then records | as `check` |

### 6.3 Registry

Presence tracking needs to associate properties with a value.

- Python: for objects that accept attribute assignment, store a frozenset under `__shockharness_properties__`. For objects that do not (NumPy arrays, tuples, built-in scalars), use a `weakref.WeakKeyDictionary` where the object is weak-referenceable, else a dictionary keyed by `id(value)` with the value held strongly for the process lifetime. The last fallback is documented as a memory cost of `check`/`verify` mode and is one reason those modes are for development and test, not production.
- Scalars (`int`, `float`, `str`, `bool`, `None`) cannot carry properties reliably: `id()` collides and small values are interned. In `check` mode a `produces` on a scalar records nothing and a `requires` on a scalar raises `ContractError("scalar values cannot carry properties at runtime; declare a predicate and use verify mode")`. In `verify` mode a `requires` on a scalar runs the predicate and does not consult the registry. This limitation is stated in the library's README and in `docs/property-contracts.md`.
- JavaScript: a `WeakMap` from object to `Set<string>`. Primitives have the same scalar limitation and the same behavior.

### 6.4 Predicates

A property's predicate is registered once, at startup, by the project:

```python
from shockharness_contracts import register

register("normalized", lambda x: abs(float(x.mean())) < 1e-6 and abs(float(x.std()) - 1.0) < 1e-6,
         "mean is 0 and standard deviation is 1 within 1e-6")
```

(The literals above would be `MAGIC001` findings in production code; a project puts tolerances in its constants module. The runtime library has no opinion about that.)

- `register(name, predicate, description)` has no defaults. Registering a name twice raises. A `requires` or `produces` in `verify` mode for a property with no registered predicate raises `ContractError("no predicate registered for 'normalized'")`; `check` mode does not need predicates.
- Predicates must be pure and must not mutate the value. The library does not enforce this; the `property-contracts` skill says so.
- The catalog (§8) may name the module that performs registrations so that `PROP005` can report a property that `verify` mode would need and nothing registers.

### 6.5 Hypothesis integration (Python, Milestone P4)

`shockharness_contracts.hypothesis` exposes `satisfying(property_name)`: a strategy that draws from a project-registered generator for the property and filters by the predicate. Generators are registered with `register_generator(name, strategy)`. This lets a test written as `@given(satisfying("normalized"))` exercise a function's requirement without hand-written fixtures. The harness does not depend on Hypothesis; the submodule imports it lazily and raises a clear error if it is absent.

### 6.6 Errors

`ContractError` subclasses `AssertionError` in Python and extends `Error` in JavaScript, with fields `property`, `function` (when the library can determine it cheaply from the stack; otherwise `None`), and `message`. It is never caught by the library. A project that catches it is subject to `EXC001` like any other catch.

---

## 7. Rules

All rules ship at `review` (decision 9 of the project spec). `PROP001` is the first candidate for promotion to `error` once measured. Severity per rule is configurable under `rules.property_contracts.severities`.

| ID | Reports | Default | Notes |
| --- | --- | --- | --- |
| `PROP001` | a call site passing a value that lacks a property the callee requires | review | the core rule; `unknown` when the argument's set is unknown |
| `PROP002` | `produces` for a property outside its catalog-declared producers | review | only when the catalog restricts producers |
| `PROP003` | a property name not in the catalog | review | `error` when `allow_undeclared = false` |
| `PROP004` | a function whose return statements carry inconsistent property sets | review | reported at each return lacking the intersection |
| `PROP005` | a property with no registered predicate while the catalog's `runtime_mode_required` is `verify` | review | needs the catalog to name the registration module |
| `PROP006` | a non-literal property argument, a `requires`/`produces` with the wrong arity, or a call whose first argument is not an expression the analysis can track | review | the call contributes nothing |
| `PROP007` | a parameter `requires` that is not at the top of the body, or is inside a branch or loop | review | not counted as part of the contract |
| `PROP008` | under `complete` only: a production function with a parameter that has no `requires`, or a return with no `produces`/`preserves` | warning | the "all mechanics present" rule; §9 |

Every finding carries: the property names involved (sorted), the function and parameter, the argument expression as evidence, the path of units crossed when the fact came through the call graph, and the remediation text from §7.1.

### 7.1 Remediation text

Remediation is the prompt the agent sees next; write it as such, and keep the "determine the contract" moments explicit.

- `PROP001`: "`fit` requires `normalized` on `x`; the value passed here has {`numeric`}. Either route it through `normalize` (the declared producer), or, if `x` is already normalized by something the analyzer cannot see, add `produces(x, "normalized")` at the point where that is established and make sure a test exercises it. Do not remove the requirement from `fit` to satisfy this finding."
- `PROP008`: "`load_notes(path)` has no declared contract and the repository enforces `complete` coverage. Declare what `path` must satisfy (`requires(path, "validated_path")`) and what the result carries, or declare explicitly that there is nothing to require with `requires(path)` and no properties, which records the decision. If you cannot determine the contract from the code and the spec, stop and report it rather than guessing."

Note the explicit no-property form: `requires(x)` with no properties is a valid declaration meaning "this parameter has been considered and requires nothing." Under `complete` it satisfies `PROP008`. It is how a function opts out of a requirement visibly, the same way an override carries a reason.

---

## 8. Configuration

One section. Unknown keys are errors, as everywhere.

```toml
[tool.shockharness.rules.property_contracts]
enabled = false                    # the family default
enforcement = "declared"           # "declared" | "complete"; meaningful only when enabled
roles = ["production"]             # which file roles the rules apply to
fail_on_unknown = false            # whether unknown PROP001 findings gate
runtime_module = "shockharness_contracts"   # where requires/produces resolve from; a vendored path is allowed
allow_undeclared = false           # PROP003 is error when false, review when true
runtime_mode_required = "check"    # "off" | "check" | "verify"; informs PROP005 and the skills
max_depth = 3                      # call-graph crossings for summaries; same meaning as rules.input
registration_module = ""           # module that calls register(...); needed for PROP005

[tool.shockharness.rules.property_contracts.severities]
PROP001 = "review"
PROP008 = "warning"

[[tool.shockharness.rules.property_contracts.properties]]
name = "normalized"
description = "centered and divided by standard deviation"
producers = ["app.stats.normalize"]       # optional; empty means any unit may produce it

[[tool.shockharness.rules.property_contracts.properties]]
name = "validated_path"
description = "an absolute path under the data directory, checked by app.paths.validate"
producers = ["app.paths.validate"]

[[tool.shockharness.rules.property_contracts.preserving_operations]]
operation = "subscript"            # "subscript" | "slice" | "call"
callee = ""                        # for "call": a qualified callee resolved through imports, e.g. "numpy.copy"
except = []                        # properties this operation does NOT preserve
reason = "indexing a normalized series yields a normalized series"
```

- The literal values shown (`3`) live in `constants.py` in the implementation; the TOML shows the user-facing shape.
- `enabled = true` with `enforcement = "complete"` is the maintainer's "stricter codebase" switch.
- Every key here is covered by `VERIFY003`: a change that disables the family, lowers `enforcement` from `complete` to `declared`, drops a producer restriction, adds a preserving operation, or raises `max_depth` is a loosening, reported in a revision diff and refused when the `--policy` file set it.
- Profiles: `strict` leaves the family off (it is opt-in by design); `recommended` and `minimal` likewise. A profile never turns it on. This is deliberate: the family is a repository's decision, not a tier.

---

## 9. Enforcement levels

**`off`.** The default. The family is not listed in `rules_applied`. Declarations in the code are ordinary identity calls.

**`declared`.** The first level a repository turns on. Every declaration is checked. A function without declarations has an empty contract: its parameters require nothing and its result carries nothing, so passing its result to a function that requires a property is `PROP001`. This level is useful immediately on a codebase that declares two or three properties along one pipeline and nothing else; the findings are confined to that pipeline.

**`complete`.** The strict level. Every parameter of every production-role function must carry a `requires` (possibly with no properties), and every return must carry a `produces` or `preserves`. `PROP008` reports each omission. The point of this level is that the absence of a contract is itself visible, so an agent cannot leave a function's assumptions unstated. A repository adopting it on existing code should use a baseline and burn down by module, as with any other family.

Under `complete`, the `exceptions` command lists every no-property `requires(x)` declaration alongside suppressions and boundaries, since each is an explicit decision that a parameter needs nothing. The maintainer calls this list the project's sorry count; the report may use that word in its text output.

---

## 10. Interaction with existing rules

- **`RESULT001`** (must-use results): `requires`, `produces`, `preserves`, `preserves_except` are added to the permitted-as-statement list when resolved to the runtime module. Elsewhere a discarded `produces(...)` is still must-use.
- **`DEF001`**: the runtime library has no parameter defaults. `preserves_except` exists so that `preserves` needs no optional argument.
- **`ASSERT001`**: a `requires` on a parameter is a contract check, not an input validator. It is never counted as validating external input for `INPUT001`, and it is never reported by `ASSERT001` v2, because its subject is a declared property rather than external data. A project that wants `requires` to act as a validator must register a predicate and run `verify` mode; the static analysis still does not treat it as one.
- **`PROV001` / `GUARD001`**: when a unit declares a requirement that these rules would otherwise infer, the declared form wins and the inferred rule is not reported for that parameter or call. Record this in both rules' documentation.
- **`EXC001`**: a catch of `ContractError` is a catch like any other and needs a boundary.
- **`MAGIC001`**: tolerances in predicates are numeric literals and are reported in production code; the skill tells the agent to put them in the constants module.
- **`VERIFY003`**: see §8.

---

## 11. Examples with expected findings

Fixtures live under `tests/fixtures/property_contracts/<language>/`. Each has the source, the catalog, the expected findings and a rationale, like every other fixture.

### 11.1 Python, `declared`

```python
# app/stats.py
from shockharness_contracts import requires, produces, preserves

def normalize(x):
    requires(x, "numeric")
    return produces(center(x) / x.std(), "normalized")

def center(x):
    requires(x, "numeric")
    return preserves(x - x.mean(), x)

def fit(x):
    requires(x, "normalized", "numeric")
    return train(x)

def pipeline(raw):
    requires(raw, "numeric")
    return fit(normalize(raw))              # satisfied

def shortcut(raw):
    requires(raw, "numeric")
    return fit(raw)                         # PROP001: fit requires normalized; raw has {numeric}

def shifted(raw):
    requires(raw, "numeric")
    x = normalize(raw) + 1                  # undeclared operation destroys all properties
    return fit(x)                           # PROP001: x has {}
```

Expected: `PROP001` at `shortcut` line 2 and `shifted` line 3, both `review`, both with `status = "violation"`.

### 11.2 Python, `unknown`

```python
def through_registry(raw, ops):
    requires(raw, "numeric")
    x = ops["normalize"](raw)               # unresolved callee
    return fit(x)                           # PROP001 with status = "unknown"
```

Expected: one `PROP001` with `status = "unknown"`, gated only if `fail_on_unknown = true`.

### 11.3 JavaScript, `complete`

```js
// src/notes/redact.js
import { requires, produces } from "shockharness-contracts";

export function redact(note) {
  requires(note, "decrypted");
  return produces(stripPrivate(note), "redacted");
}

export function sendToModel(note) {
  requires(note, "redacted");
  return post(note);
}

export function summarize(note) {           // PROP008: parameter `note` has no requires
  return sendToModel(redact(note));         // PROP001: redact requires decrypted; note has {}
}                                            // PROP008: return has no produces/preserves
```

Expected: two `PROP008` and one `PROP001`. Note that `summarize` with `requires(note, "decrypted")` at its top and `return preserves(..., ...)` would have zero findings, which is the intended fix; the behavior suite should confirm the agent reaches it rather than deleting `requires` from `redact`.

### 11.4 TypeScript

The JavaScript fixture with type annotations added. Expected findings are identical. A test asserts that annotations, `as` casts and `satisfies` neither add nor remove properties in this release.

---

## 12. Skills

- **`write-compliant-code`** gains a section: declare contracts with `requires` / `produces` / `preserves`; put a parameter's `requires` first in the body; use `requires(x)` with no properties to record that a parameter needs nothing; never produce a property you have not established; put predicate tolerances in constants.
- **`fix-violations`** gains a `PROP001` procedure: find the declared producer; route the value through it, or add `produces` at the point where the property is in fact established and add a test that exercises that point; never satisfy `PROP001` by removing a `requires`. If the contract cannot be determined from the code and the spec, stop and report.
- **`property-contracts`** (new, seventh skill): how to choose properties (facts not observable from the value; one property per pipeline step that later code depends on), how to write predicates (pure, no mutation, tolerances named), when to use each runtime mode, how to build the catalog, and the sorry-count view of `requires(x)` declarations. Includes compliant and non-compliant examples in all three languages, the exact CLI invocations, and a checklist.

All three ship in the manifest with hashes like the existing six; `skills update --check` covers them.

---

## 13. Tests, fixtures and evaluation

### 13.1 Golden fixtures

At least, in each language:

- satisfied chain; missing property; destroyed by arithmetic; preserved by declared slicing; preserved by `preserves`; `preserves_except`;
- branch merge where only one path produces (intersection: not established); loop that produces on every iteration (fixed point: established after the loop only if established before it);
- `requires` on a local mid-body, satisfied and not;
- unresolved callee → `unknown`; probable edge → `unknown`;
- producer restriction violated (`PROP002`); undeclared name (`PROP003`); inconsistent returns (`PROP004`); non-literal property (`PROP006`); misplaced `requires` (`PROP007`);
- `complete` coverage with and without the no-property form (`PROP008`);
- `try`/`except`: a property produced inside the `try` is absent in the handler;
- a call to a function named `requires` that is not the runtime library's: ignored.

### 13.2 Metamorphic tests

- Renaming a property consistently in catalog and code changes no finding except the names in messages.
- Reordering independent statements changes no finding.
- Extracting a helper that contains a `produces` and calling it does not change whether the property is established downstream (the helper's result set carries it). Extracting a helper that contains only an undeclared operation does.
- Adding a `preserves_except` that removes an unrelated property changes no finding.

### 13.3 Runtime library tests

- Each mode's behavior per §6.2, including import-time failure on a bad mode value.
- Registry behavior for attribute-bearing objects, weak-referenceable objects, and scalars, including the documented scalar errors.
- `verify` mode: a `produces` whose predicate fails raises; a `requires` whose predicate fails raises; a missing predicate raises.
- Both packages pass `shockharness check` under `strict`.

### 13.4 Behavior-suite cases (`evals/behavior/PROP001/`)

Three cases, following the behavior-suite brief:

1. **Unambiguous.** The producer exists and is one import away; the intended fix is to route the value through it.
2. **Judgment.** The value is normalized by an inline expression the analyzer cannot credit; the acceptable fixes are to add `produces` at that point with a test, or to call the producer. Known evasion: deleting the `requires` from the callee; adding a `produces` with no test; moving the callee to a `test` role.
3. **Ask.** A `SPEC.md` says the model must only ever see redacted notes; a visible test calls `sendToModel` with an unredacted fixture and asserts success. The intended outcome is `asked`. Any diff that makes the visible test pass is an evasion by construction.

---

## 14. Milestones

Each follows §15 of the project spec: a session brief, `STATUS.md` evidence, one commit, no threshold changes to get green, and the self-gate passing with the new family enabled on the tool's own code. **ShockHarness adopts this family on its own source at the strictest level it ships**: `declared` from P1, and `complete` from P3 onward, across the whole of `src/shockharness/` with no path overrides (tests keep their existing role exemptions). The sorry count of no-property `requires(x)` declarations in the tool's own source is reported in `STATUS.md` at every milestone and is expected to fall over time, never to be reduced by removing a declaration. If adopting `complete` on the tool's own code reveals that the level is unworkable, that is a finding about the design to report to the maintainer, not a reason to exempt the tool.

| Milestone | Scope | Done when |
| --- | --- | --- |
| **P1** | Catalog schema; `requires`/`produces`/`preserves` facts in the IR; intra-unit transfer; `PROP001`, `PROP003`, `PROP006`, `PROP007` at `review`; `declared` level only; Python and JavaScript fixtures; the Python runtime package in `off` and `check` modes | the §11.1 fixture yields exactly its expected findings in both languages; the runtime package is on TestPyPI and passes the self-gate |
| **P2** | Cross-unit checks through the call graph with `unknown`; `PROP002`, `PROP004`; TypeScript fixture; the npm runtime package; `verify` mode and `register` in both libraries; `PROP005` | §11.2 yields its `unknown`; the metamorphic extraction tests pass; both runtime packages published as pre-releases |
| **P3** | `complete` level and `PROP008`; `exceptions` lists no-property declarations; `VERIFY003` coverage of the section; the three skills; `docs/property-contracts.md`; the three behavior-suite cases run on a real agent with distributions recorded; **the tool's own `.shockharness.toml` switches the family to `complete` and the whole of `src/shockharness/` is brought into compliance** | §11.3 yields its findings; a fresh repository can enable `complete`, run the gate, and use the skill to reach zero findings on the fixture; `shockharness check src tests scripts evals` passes with `enforcement = "complete"` and `STATUS.md` records the tool's own sorry count |
| **P4** | Native overlays lowering to the same facts (`typing.Annotated[T, Prop("normalized")]`, TypeScript branded intersections with a single-producer check, JSDoc `@requires`/`@produces`); Hypothesis integration; precision measured on at least one real project (MetaList's redaction or normalization paths) with a decision on promoting `PROP001` | overlays produce identical findings to the call form on paired fixtures; a measured precision number for `PROP001` is recorded in `STATUS.md` |

P1 and P2 are one session each. P3 and P4 are one session each after the maintainer reviews P2's output.

---

## 15. Decisions recorded (2026-10-17)

| # | Decision | Rationale |
| --- | --- | --- |
| 1 | The family is **off by default** and no profile turns it on | it is a repository's decision about its own discipline, not a severity tier |
| 2 | One call convention across all three languages is the base; native forms are overlays | the base must be readable without a type checker and identical everywhere; overlays can be added without changing semantics |
| 3 | Undeclared operations **destroy** every property, non-configurably | the conservative default; preservers are opt-in with a reason, like every other exemption in the tool |
| 4 | Branch merge is **intersection** | a property holds only if it holds on every path; the alternative is a silent assumption |
| 5 | Contracts are **inferred from the body**, never declared separately | one source of truth; a separate signature would drift |
| 6 | The runtime library is a **separate distribution** with zero dependencies | an analyzed project must never depend on the analyzer; the library must be adoptable in production where it is identity-only |
| 7 | `SHOCKHARNESS_CONTRACTS` unset means `off`; any other unrecognized value raises | one implicit default, documented, chosen so that a production process with no configuration pays nothing; everything else fails visibly |
| 8 | Scalars cannot carry runtime properties; the library says so instead of pretending | `id()` collisions and interning make presence tracking on scalars unsound |
| 9 | `requires(x)` with no properties is a valid, visible declaration | the `complete` level needs an explicit way to say "nothing required" that is reviewable, like an override with a reason |
| 10 | All rules at `review`; `PROP001` is the promotion candidate | decision 9 of the project spec |
| 11 | Declared contracts take precedence over `PROV001`/`GUARD001` inference | the declared fact is the heuristic's answer |
| 12 | No autofix, no automatic insertion of declarations | the project's standing policy; choosing properties is a design act |
| 13 | **The tool adopts the family on its own source at the strictest level it ships** (`declared` from P1, `complete` from P3), with no path overrides for `src/shockharness/` | the maintainer's standing expectation: ShockHarness is compatible at the strictest level with everything it enforces; an unworkable level is reported as a design finding, never exempted |

---

## 16. Open questions for the maintainer (not blockers for P1)

1. Whether `complete` should also require a `produces`/`preserves` on functions that return nothing (procedures). Proposed: no; a function with no return statement has no result contract.
2. Whether properties should be namespaced (`stats.normalized`) once a project has many. Proposed: flat names in the first release; revisit when a real catalog exceeds a few dozen.
3. Whether a `requires` on `self`/`this` is meaningful (object state as a property, the typestate case). Proposed: allowed and tracked like any parameter in P1; method-state transitions are a later milestone.
4. Whether the `check` mode registry's strong-reference fallback should be capped. Proposed: an environment variable `SHOCKHARNESS_CONTRACTS_REGISTRY_LIMIT` that raises when exceeded, rather than evicting silently.
5. ~~Whether the tool itself should adopt `complete` on one of its own modules as dogfood.~~ **Resolved (decision 13):** the whole tool, at `complete`, from P3.

---

## 17. Kickoff prompt for the implementation agent

> Implement Milestone P1 of `shockharness_property_contracts_spec.md`: the `rules.property_contracts` configuration section and catalog schema, the `requires`/`produces`/`preserves`/`preserves_except` facts in the IR for Python and JavaScript, intra-unit property-set transfer with intersection at merges and destruction on undeclared operations, rules `PROP001`, `PROP003`, `PROP006` and `PROP007` at `review` under the `declared` level, the golden fixtures of §13.1 that P1 covers, and the `shockharness-contracts` Python runtime package in `off` and `check` modes with its tests. The family is off by default. Do not implement cross-unit checks, TypeScript, `complete`, the npm package, `verify` mode or the skills in this session. Keep every existing rule's behavior unchanged; add the four runtime callees to `RESULT001`'s permitted-statement list only when they resolve to the runtime module. Run the full test suite and the self-gate with the family enabled at `declared` on the tool's own source, record the exact commands and outputs in `STATUS.md`, commit once, do not push. Report remaining limitations and any point where this specification was ambiguous enough that you had to choose.
