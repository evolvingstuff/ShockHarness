# ShockHarness: second batch, coverage gaps found against a project's own linter

## Context

The same 906-file Python/JavaScript codebase as the first brief has its own startup linter with the same philosophy (exception transparency, no defaults). Comparing the two rule by rule, ShockHarness matches or exceeds it on explicit `try/except` and `catch`, parameter defaults, `.get` fallbacks and `||`/`??`/`or` defaulting. Four things it enforces that ShockHarness cannot see are general Python or JavaScript idioms, not project conventions. They are the four items below, in priority order, plus one design note. Each item has acceptance criteria; add tests for every criterion and document every new option in `docs/configuration.md` and `docs/rules.md`.

## 1. Exception capture through context managers

**Observation.** In that codebase 86 of its 149 Python exception-handling sites are not `try/except` at all but a context manager that swallows a declared exception type and exposes it afterwards:

```python
capture = CapturedExceptionContext(ProcessLookupError, boundary="main.py:_is_process_running")
with capture:
    os.kill(pid, 0)
if capture.captured_exception is not None:
    ...
```

The standard library has the same thing: `contextlib.suppress(FileNotFoundError)`. ShockHarness treats both as ordinary `with` blocks, so a codebase can satisfy EXC001-EXC003 by moving every catch into a helper, which defeats the policy.

**Change.**
- Treat `with contextlib.suppress(T1, T2):` (and `from contextlib import suppress` → `with suppress(...)`) as a catch of T1 and T2 whose handler swallows: EXC001 checks the types against the boundaries for the file, and EXC002 reports it as a swallow unless a boundary approves it, exactly as for `except T1: pass`.
- New option listing a project's own capture managers:

```toml
[tool.shockharness.rules.exceptions]
capture_managers = ["app.services.exception_capture.CapturedExceptionContext"]
```

A `with` whose context expression is a call to a listed manager (matched by qualified name after import resolution, or by bare name when the import is unresolved, with the usual `probable` confidence) is a catch of the exception types passed as its positional arguments. Positional arguments that are not names of exception types (strings, keywords) are ignored; if no type can be read, report it as an untyped catch, like a bare `except`. Every configured manager is reported as a policy deviation, like boundaries.
- `rules.md` gains a section explaining that a capture manager is a catch and is approved the same way.

**Acceptance.** `with suppress(FileNotFoundError): path.unlink()` in a file without a boundary for `FileNotFoundError`: one EXC001 finding on the `with` line, one EXC002 swallow finding. The same with a boundary approving `FileNotFoundError` for that path: no finding. `with suppress(Exception):`: EXC001 broad catch. With `capture_managers` configured, `with CapturedExceptionContext(ProcessLookupError, boundary="x"):` behaves like `except ProcessLookupError:` for EXC001; an unlisted manager is still an ordinary `with`. Fingerprints are stable across unrelated edits.

## 2. The missing default forms (DEF001 / DEF002)

**Observation.** DEF002 covers `m.get(k, v)` and `getattr(o, a, v)`, DEF001 covers dataclass fields. Five standard ways of substituting a value for missing data are not covered, and the project's own linter forbids all of them:

| Form | Rule | Mode |
|---|---|---|
| `d.pop(key, default)` | DEF002 | `missing_value_fallbacks` |
| `d.setdefault(key, default)` | DEF002 | `missing_value_fallbacks` |
| `next(iterator, default)` | DEF002 | `missing_value_fallbacks` |
| `collections.defaultdict(factory)` (and `defaultdict` after `from collections import defaultdict`) | DEF002 | `missing_value_fallbacks`: every lookup silently creates a value |
| `pydantic.Field(default=...)`, `Field(default_factory=...)`, and a pydantic model field with `= value` | DEF001 | `dataclass_fields` (pydantic `BaseModel` subclasses; the first brief's item 7 asks to confirm which classes count) |

**Change.** Add each form with the message style of its neighbours (what falls back to what, and why that hides missing data) and the same remediation text. `d.pop(key)` with no default and `next(iterator)` with no default are not findings.

**Acceptance.** One fixture per form yields one finding with the rule and mode above; the no-default variants yield none; a `defaultdict` import under an alias (`import collections as c; c.defaultdict(list)`) is still found; JSON findings carry the evidence line.

## 3. Promise rejection handlers (EXC001 / EXC002, JavaScript)

**Observation.** `.catch(handler)` and `.then(onFulfilled, onRejected)` are JavaScript's other catch syntax. The rules read only `catch` clauses, so every async codebase has a hole the size of its promise chains.

**Change.** Treat the handler function of `promise.catch(fn)` and the second argument of `promise.then(ok, fn)` as a catch handler: untyped (JavaScript rejections carry no type), so EXC001 applies the boundary check as for an untyped `catch (error)`, and EXC002 classifies the handler's body (swallow, log only, rethrow, return fallback → DEF005) exactly as for a `catch` clause. A handler that is a reference to a function (not an inline function) is `unresolved` unless the function is defined in the same module, in which case classify its body. `finally(fn)` is not a catch.

**Acceptance.** `fetchData().catch(() => {})`: EXC001 and EXC002 (swallow). `.catch((error) => { throw error; })`: with `transparent_rethrow = true`, no finding; without it, EXC001 as today for a rethrowing `catch` clause. `.then(render, (error) => log(error))`: EXC002 log-only. `.finally(cleanup)`: nothing. An `async` function's `try/catch` is unchanged.

## 4. Unanalyzable sources as a policy

**Observation.** The coverage block already counts files skipped for an unsupported extension (333 in this run, mostly TypeScript-free, but the point stands), and nothing can fail on it. A project that adds a `.ts` file to a JavaScript tree, or a `.pyx`, quietly removes it from the policy. The project's own linter fails startup if any TypeScript file exists in a JavaScript-only tree.

**Change.** New top-level setting, alongside `parse_errors`:

```toml
[tool.shockharness]
unsupported_sources = "warn"   # "fail" | "warn" | "ignore"; "warn" in strict and recommended, "ignore" in minimal
```

It applies to files that match `include` but have an extension ShockHarness cannot parse. `fail` counts them as analysis failures (exit 3, like an unparseable file under `parse_errors = "fail"`); `warn` lists them in the report under coverage with a warning line; `ignore` is today's behaviour. Files excluded by `exclude` or never matched by `include` are unaffected. State in `docs/limitations.md` that TypeScript is not analyzed and that this setting is how a project notices.

**Acceptance.** A tree with `include = ["src/**/*"]` and one `src/a.ts`: `fail` exits 3 and names the file; `warn` exits by the gate as usual and lists it; `ignore` says nothing. A `.ts` file outside `include` is never mentioned. The strict profile's default is `warn` and `shockharness config effective` shows it.

## 5. Design note, not for this batch: project rules through a plugin API

> **Declined 2026-10-16** (spec section 21.1, decision 11): ShockHarness will not execute project code named in configuration. The data-only alternative (importing an external findings file) is recorded there and not scheduled.

The remaining checks in that project's linter are its own architecture: a decorator required on every route that writes, a file-immutability invariant for backups, a state-ownership rule for its JavaScript modules. None of these belongs in ShockHarness. What would be general is a way to run such checks inside ShockHarness so they share its report, baselines, diff gate and SARIF: a `[[tool.shockharness.plugins]]` entry naming an importable callable that receives the parsed unit (the IR already built for a file) and returns findings with a project rule ID (`PROJ001`-style, listed under a separate `rules_project` key so a clean run never implies the tool checked them). Design questions to settle before building it: which IR is exposed and how stable it is across versions, whether plugins may read other files, and how a plugin's failure is reported (as an analysis failure, never swallowed). Worth a short design document first.

## Non-goals

A general "any conditional expression used as a default" rule: too broad to define without false positives; DEF004's `x if x is not None else v` form stays as it is.
