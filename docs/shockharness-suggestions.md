# ShockHarness 0.1.0: changes proposed after a first run on a real codebase

## Context

ShockHarness 0.1.0 (strict profile, inline suppressions on, run through the library API: `load_config` + `analyze_paths`) was run on a 906-file Python/JavaScript application: 495 Python files, 411 JS/MJS files, about 16,500 functions, with a test suite included in scope. It took 12.5 seconds and parsed every file. Results: 7,028 hard violations, 236 review, 1,341 warnings. By rule: MAGIC001 6,486 · CPLX004 599 · DEF002 385 · CPLX002 371 · CPLX001 244 · EXC001 150 · DEF001 123 · CPLX005 102 · DEF003 87 · DEF004 31 · CPLX003 25 · EXC002 1 · DEF006 1. The hard rules found real things (notably 308 `.get`/`getattr` fallbacks in application Python that the project's own linter missed). The items below are about precision, noise and adoption cost, and are meant to hold for any project, not this one.

Implement in this order. Each item has acceptance criteria; add tests for every criterion and document each new option in `docs/configuration.md` and `docs/rules.md`.

## 1. MAGIC001: the definition of a named constant is not a magic number

**Observation.** 143 of the 2,074 application-code MAGIC001 findings were the *definition* of a module-level constant, e.g. `MAX_WEB_PAGES_PER_CALL = 8` (Python) or `const SETTLE_MS = 400;` (JS). That definition is exactly the remedy the rule asks for. Flagging it forces every adopter to keep one exempt constants file, as ShockHarness itself does with `constants.py`.

**Change.** A numeric literal that is the whole right-hand side of a module-scope assignment to a constant name is the name, not the magic, and is not reported. Make it a rule option so strict mode can still refuse it if a project wants:

```toml
[tool.shockharness.rules.magic_numbers]
named_constant_definitions = "allow"   # "allow" (new default in every profile) or "report"
```

Definition of "constant definition":
- Python: module scope; target is a simple name in UPPER_SNAKE_CASE (leading underscores allowed), or any simple name annotated `Final` / `typing.Final[...]`; value is a numeric literal, optionally with unary minus, int or float.
- JavaScript: module scope; `const NAME = <numeric literal>` or `export const NAME = <numeric literal>` with the same name rule; `let`/`var` do not qualify.
- Not covered (still reported): literals inside containers (`LIMITS = {"retries": 3}`, `const SIZES = [8, 16]`), inside function bodies, inside class bodies, and expressions (`TIMEOUT = 30 * 60`: both literals reported, as today).

**Acceptance.** `MAX_PAGES = 8` and `_PORT_WAIT_SECONDS = 10.0` at module scope: no finding. `x = 8` inside a function: finding. `const MAX_PAGES = 8;` and `export const MAX_PAGES = 8;`: no finding; `let maxPages = 8;`: finding. `LIMITS = {"retries": 3}`: finding. With `named_constant_definitions = "report"`, all of the above are findings and the report lists the option as a deviation from the default only if you decide "allow" is the default; otherwise list "allow" as the deviation. State the chosen default in `docs/rules.md` with the reasoning above.

## 2. CPLX005: one finding per import cycle, not one per member

**Observation.** 85 of the 102 CPLX005 findings were a single 75-module JavaScript import cycle reported once per module. It drowned the two five-module Python cycles, which are the actionable ones.

**Change.**
- Emit one finding per cycle. Anchor it on the lexically first module in the cycle (stable fingerprint), say how many modules take part, and list them in the message up to a cap (say 8, then "… and N more"); the full membership stays in `metrics.graph.cycles`.
- Say which language the cycle is in, and note in the message that ES-module cycles are usually resolved at call time while Python cycles fail at import time, so the Python ones come first in the text report.

**Acceptance.** A fixture with a 6-module JS cycle and a 3-module Python cycle produces exactly two CPLX005 cycle findings; fan-out findings are unaffected; `metrics.graph.cycles` is unchanged; the fingerprint of a cycle does not change when an unrelated module is added.

## 3. EXC001/EXC002: transparent guard calls, and boundaries with several types

**Observation.** The codebase has one house pattern for its 89 JavaScript catches: the handler's first statement is `rethrowUnexpectedError(error)`, a function that re-raises anything not on an allowlist and returns for expected failures. Python codebases do the same with `if not isinstance(exc, (A, B)): raise` as the first statement. Under 0.1.0 each of these is an EXC001 finding, and declaring them needs one `boundaries` entry per exception type per path: about 150 entries for this project.

**Change.**
- New option `exceptions.transparent_guards = ["rethrowUnexpectedError"]` (default empty). A handler whose first statement calls a listed guard with the caught exception as its only argument is treated as narrowed by that guard: EXC001 does not report the catch itself, and EXC002's swallow/log-only classification applies to the statements after the guard. Report every configured guard as a policy deviation, like boundaries.
- Python: a handler whose first statement is `if not isinstance(<caught>, T) / (T1, T2): raise` is treated as a catch of T / (T1, T2) for EXC001's boundary check, instead of the broad type on the `except` line.
- Let one `boundaries` entry approve several exception types for one path: accept `exceptions = ["OSError", "ProcessLookupError"]` alongside the existing single-type form, with one reason. Keep "one sanctioned operation per try" (EXC003) unchanged.

**Acceptance.** With the guard configured, `catch (error) { rethrowUnexpectedError(error); showBanner(error.message); }` yields no EXC001; the same handler without the guard call still does. `catch (error) { rethrowUnexpectedError(error); }` with nothing after it is still reported by EXC002 as swallowing. `except Exception as exc: if not isinstance(exc, OSError): raise; …` is checked as a catch of OSError. A multi-type boundary entry validates, approves each listed type, and is reported once as a deviation.

## 4. `check --summary`: a first-contact overview

**Observation.** On an existing codebase the text report prints 8,600 lines before its totals. The first thing an adopter needs is the shape of the problem.

**Change.** Add `shockharness check <paths> --summary` (text) and a `summary` object in the JSON report, both containing:
- findings by rule × top-level directory (e.g. `src/`, `tests/`, `scripts/`), and by severity;
- the N files with the most policy findings (MAGIC/EXC/DEF/SUPP, not CPLX), N default 10;
- complexity: units analyzed, units over each threshold, NPath-saturated units, cycle count, fan-out findings;
- parse failures, and the elapsed time.

The gate line and exit code are unchanged by `--summary`.

**Acceptance.** `--summary` output ends with the same `gate:` line as the full report; the JSON `summary` totals equal `execution_summary`; a directory split for a fixture with `src/` and `tests/` findings is exact.

## 5. CPLX006: unit size

**Observation.** The per-unit data already carries `size.logical_lines`, and the worst units in this run were also the longest (346, 466 and 273 logical lines). Most code-review standards check length; ShockHarness does not.

**Change.** Add `CPLX006`: a unit whose `logical_lines` exceeds `complexity.max_lines_warn` (default 50; module bodies exempt). Warning severity, advisory, never gating, like CPLX001-CPLX004; threshold and convention in `docs/complexity.md`; the unit's size already in `metrics.complexity.functions`.

**Acceptance.** A 51-logical-line function is reported, a 50-line one is not; a module body of any length is not; the finding names the count and the threshold; `complexity.enabled = false` disables it with the others.

## 6. A content-hash cache

**Observation.** 12.5 seconds for 906 files is fine once, and too slow to run on every startup or save.

**Change.** Cache per-file parse and rule results in a cache directory (`.shockharness-cache/` under the analyzed root, gitignore-able; or `$XDG_CACHE_HOME/shockharness`; make the location a config key and `--no-cache` a CLI flag). Key: tool version + config digest + file content hash + language. Cross-file work (call graph, cycles, history) is recomputed. A cache hit must produce byte-identical findings for that file.

**Acceptance.** A second run over an unchanged tree produces an identical JSON report (ignoring timing fields) in a fraction of the time; changing one file re-analyzes only that file's per-file results; changing the config or the tool version invalidates everything; `--no-cache` bypasses it.

## 7. DEF001: check which classes count as dataclasses

**Observation.** DEF001 reported `id: int = 1` and `encryption_nonce: Optional[bytes] = None` on a class in a database module as "dataclass field … has a default value". If that class is not decorated with `@dataclass` (ORM models and plain classes use the same annotated-assignment syntax), the classification is wrong.

**Change.** Confirm that `dataclass_fields` fires only for classes decorated with `dataclass`/`dataclasses.dataclass` (and, if you support them, `attrs.define` and pydantic `BaseModel` subclasses). Either leave annotated class attributes of other classes unreported, or report them under a separate `class_attribute_defaults` mode that defaults to `review`, with its own message text. Add a test with an undecorated class and an ORM-style class.

## 8. CPLX004 (NPath): present it as the coarse measure it is

**Observation.** 596 CPLX004 findings against 371 CPLX002; 144 units saturated at the 10,000 cap. NPath explodes on long sequences of independent `if`s, so a 466-line dispatcher scores "infinite" even when every branch is trivial, and it repeats what cognitive complexity already says with less resolution.

**Change.** In the text report, order complexity findings by cognitive complexity and show NPath per unit only once (not as a separate finding) when CPLX002 already fires for the same unit; or make that deduplication an option (`complexity.npath_only_without_cognitive = true`). Keep the per-unit numbers in `metrics.complexity.functions` as they are.

**Acceptance.** A unit over both thresholds yields one line in the text report naming both numbers; a unit over the NPath threshold alone still yields CPLX004; JSON findings keep both rule IDs unless the option is on.

## 9. Small defaults

- `recommended` profile: set `magic_numbers.allow_unary_negative_one = true`. In this run 441 of 6,486 MAGIC001 findings were `-1`, almost all `indexOf(...) === -1`, `[-1]` and `.at(-1)`. Keep it false in `strict`.
- Fan-out (CPLX005): the units over 20 were the application's orchestrators (login, chat streaming, restore). Consider reporting fan-out at `review` rather than `warning`, or raising `fan_out_warn` to 30 in `recommended`.

## Non-goals

No semantic exemptions for MAGIC001 (HTTP status codes, pixel sizes, timeouts): those are project conventions, and the tool is right to make a project name them. No change to DEF002-DEF006 behaviour: the findings were accurate.
