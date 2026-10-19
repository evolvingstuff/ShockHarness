# Agent-Ready Specification: Explicit-Code Integrity and Complexity Analyzer

**Status:** Implementation blueprint, v1.4 (kickoff decisions in §19; distribution decisions in §20; advanced guardrails plan in §21)  
**Date:** 2026-10-14  
**Name:** **ShockHarness**. Python distribution and import package `shockharness`, CLI command `shockharness`, config table `[tool.shockharness]`, dedicated config file `.shockharness.toml`, inline suppression prefix `# shockharness:` / `// shockharness:`. Registry and trademark clearance is still the maintainer's responsibility before publishing (see §17).  
**Initial languages:** Python and JavaScript (including ESM/CommonJS); TypeScript is a future target.  
**License goal:** MIT for original code; review dependency licenses and notices.  
**Audience:** Autonomous coding agent and maintainers.

> **Directive to implementation agent:** Build a reusable, standalone, locally runnable open-source Python package and CLI. Do not modify the consuming application's business logic. Implement deterministic checks first, with rigorous fixtures and no speculative auto-fixes. Work in milestones and execute tests after each. This document is the normative product specification unless a maintainer explicitly changes it.

## 0. Product definition and invariant

Build a **strict, configurable static-analysis and quality-gate engine** for human- and agent-authored code. Its core idea is that unexpected failures, missing information, and unexplained decisions must not silently become apparently valid program behavior. Conventional linters (Ruff, ESLint) are complementary and should continue to run. This tool is not a formatter or generic linter clone.

Three **default-on hard policy families**:

1. **Exception transparency:** Prohibit catches except narrow, explicitly approved external-boundary failures. No broad catch-and-continue, arbitrary suppression, or success-shaped error fallbacks.
2. **No implicit defaults:** Prohibit fallback values that mask missing required data and prohibit function argument defaults in strict mode. Require explicit schema-validated configuration or explicit domain contracts.
3. **No magic numbers:** In executable Python/JavaScript code, reject every numeric literal **except exactly `0` or `1`**, subject only to explicitly configured exclusions/suppressions. `range(2)` is a violation. The analyzer must not invent exemptions for 2, 10, 24, 60, etc. Naming an arbitrary number without a rationale is not proof of justification.

Separate, initially advisory **complexity-analysis family**: cyclomatic/cognitive complexity, nesting, NPath approximation, coupling, call graphs, hotspot/churn, abstraction displacement, and change impact. Make selected gates configurable and measurable, but do not pretend structural complexity equals correctness.

**Critical architectural rule:** Hard policy violations are not averaged away by a composite score. Reports keep dimensions separate.

## 1. Scope and non-goals

### In scope for first release

- Analyze `.py`, `.js`, `.mjs`, `.cjs`, and JSX where parser supports it. Handle syntactically invalid source as a visible analyzer diagnostic and configurable gate failure, never silently pass.
- The tool itself requires **Python 3.11+** (needs `tomllib` and `ast.TryStar`) and is tested on 3.11 through 3.14. Python source is parsed with the host interpreter's `ast`, so the set of parseable Python syntax is whatever the running interpreter supports; this must be stated in the report's `coverage` metadata and in docs. Modern JavaScript syntax per the pinned `tree-sitter-javascript` grammar, with documented tested versions.
- Project config (TOML), schema validation, rule overrides, per-path ignores, explicit scoped suppression with reasons, and deterministic precedence.
- Default-on strict policies for magic numbers, catches, and defaults.
- Stable CLI, JSON schema-versioned diagnostics, human output, SARIF, exit codes, baseline/diff mode.
- Deterministic core analyzer usable as a Python library (`analyze_path`, `analyze_source`, `evaluate_gate`).
- Git-aware risk features, Python/JS function-level complexity, meaningful uncertainty/coverage metadata.
- Vendor-neutral agent skills in `skills/*/SKILL.md` and reproducible skill evaluations.
- CI integration examples (GitHub Actions, pre-commit), packaging, documentation, examples, tests.

### Explicitly deferred

- Full TypeScript type checking, browser/runtime behavior, whole-program soundness, precise dynamic call resolution, proof of semantic correctness.
- Hosted dashboard, telemetry, network services, IDE extension, custom LSP, runtime instrumentation.
- LLMs as an enforcement authority or automatic repair of ambiguous violations.
- Automatic inference that a named constant is justified. Provide supporting diagnostics and provenance checks, not unearned assertions.

## 2. Design principles

- **Fail visibly:** Unknown inputs, parser failures, unknown configuration keys, unresolved ambiguity, and internal analyzer errors must be explicit, not converted to success.
- **Determinism first:** Given the same files, config, tool version, and Git revision, produce stable findings and order.
- **Separate observations from policy:** Extract syntax facts; produce rule findings; separately evaluate gates.
- **Explainability:** Every diagnostic contains a stable rule ID, source span, explanation, fix guidance, severity, confidence, and if relevant why it was exempted.
- **Conservative automation:** No potentially semantics-changing autofix. Advise the agent to discover the intended contract and add tests.
- **Transparent limitations:** Distinguish exact, approximate, unresolved, unsupported, and not-analyzed states; do not report unsupported code as clean.
- **Sensible strict defaults, explicit escape hatches:** Each rule can be disabled via configuration, with changes visible in reports.
- **Independent utility:** `pip install` + local CLI works without LLMs, network access, or a Git checkout (history features degrade explicitly).

## 3. Architecture

```text
CLI / Python API
    |
Config loader + schema validation + policy resolution
    |
Discovery + language router + exclusions
    |
Parsers: Python ast; JS tree-sitter JavaScript (or vetted ESTree parser)
    |
Normalized IR: files, spans, literals, functions, catches, calls, flows
    |                         \
Policy rule engine              Structural analysis -> function graph
    |                         /             \
Findings + provenance         Git-history features   Optional semantic review
    |                                  
Gate engine + baselines + diff comparison
    |
Text / JSON / SARIF + CI exit status + agent-facing guidance
```

Use Python `ast` for Python (high-fidelity); use `tree-sitter` and `tree-sitter-javascript` with pinned compatible versions for JS (the grammar includes JSX); evaluate JSX parsing on fixtures. **tree-sitter recovers from syntax errors instead of failing:** any `ERROR` or `MISSING` node anywhere in the tree is a parse failure for the `parse_errors` gate, reported with the span of the first such node. Never analyze a tree containing error nodes as if it were complete. Avoid regex as the source of truth for AST rules. Every IR node must retain original source offsets/line-column and enclosing function/file context. Unicode and CRLF mapping need fixtures.

Suggested tree:

```text
src/shockharness/
  __init__.py
  api.py cli.py config.py schema.py discovery.py
  ir/{model.py,spans.py,python.py,javascript.py}
  rules/{registry.py,magic_numbers.py,exceptions.py,defaults.py,magic_strings.py}
  complexity/{cfg.py,cyclomatic.py,cognitive.py,npath.py,callgraph.py,coupling.py,abstraction.py}
  history/{git.py,hotspots.py,cochange.py}
  gating/{baseline.py,diff.py,policy.py,suppressions.py}
  output/{text.py,json.py,sarif.py}
  agents/{guidance.py}
skills/{write-compliant-code,fix-violations,refactor-complexity,pre-commit-review}/SKILL.md
tests/{fixtures,unit,integration,property,metamorphic,cli,benchmarks}/
examples/{python,js,mixed}/
docs/{rules,architecture,configuration,limitations,benchmarking,contributing}.md
.github/workflows/ci.yml
pyproject.toml README.md LICENSE CHANGELOG.md STATUS.md
```

### Dependency policy

- Runtime dependencies: `tree-sitter` and `tree-sitter-javascript` only, pinned to a tested compatible pair. Everything else is standard library: `argparse` for the CLI, `tomllib` for config, `ast`, `json`, `subprocess` for local `git`.
- No Click, Typer, Pydantic, Rich, or YAML libraries. Schema validation is hand-written against an explicit schema module so the error messages and unknown-key rejection are fully under our control.
- Development dependencies: `pytest`, `hypothesis`, `ruff` (format and complementary lint for the tool's own code), `build`. Environment management with `uv`; `pip install` must also work.
- Any new dependency needs a recorded rationale and a license check in `CHANGELOG.md`.

## 4. Configuration contract

Use `pyproject.toml` under `[tool.shockharness]` OR a dedicated file named `.shockharness.toml` or `shockharness.toml` (both spellings are accepted; having both in one root is an error), with a documented priority order: CLI explicit config > dedicated file > pyproject > bundled defaults. A `profile` key selects one of the built-in profiles in §20 decision 4; the profile layer sits between bundled defaults and the repository's own keys. Multiple config sources at a single tier are errors rather than silently combined. No implicit environment fallback. Support `--print-effective-config` with origins and `config validate`.

**Normative example (schema to implement; naming provisional):**

```toml
[tool.shockharness]
profile = "strict"
include = ["src/**/*.py", "src/**/*.js", "src/**/*.mjs", "src/**/*.cjs"]
exclude = ["**/node_modules/**", "**/.venv/**", "**/dist/**", "**/generated/**"]
parse_errors = "fail"

[tool.shockharness.rules.magic_numbers]
enabled = true
allowed_values = [0, 1]
# In strict profile, allowing additional values must be explicit and reported.
allow_unary_negative_one = false
exclude_configuration_files = true

[tool.shockharness.rules.exceptions]
enabled = true
mode = "boundary_whitelist"
# Not a global exception-class whitelist: require matching an allowed boundary.

[[tool.shockharness.rules.exceptions.boundaries]]
path = "src/integrations/**"
language = "python"
exception = "requests.exceptions.Timeout"
reason = "External network timeout"

[tool.shockharness.rules.defaults]
enabled = true
function_parameters = "forbid"
missing_value_fallbacks = "forbid"
truthiness_fallbacks = "review"

[tool.shockharness.rules.magic_strings]
enabled = true
mode = "review"

[tool.shockharness.complexity]
enabled = true
cognitive_warn = 15
cyclomatic_warn = 15
max_nesting_warn = 4

[tool.shockharness.gates]
new_hard_violations = "fail"
legacy = "baseline"
complexity_regressions = "warn"

[[tool.shockharness.overrides]]
paths = ["tests/**", "**/*.test.js"]
# Tests are explicit policy exceptions, not silently ignored.
disable = ["MAGIC001"]
reason = "Fixtures encode literal expected outputs"
```

Rules can be individually toggled `enabled=false`, including magic numbers; defaults: **on**. Record effective disabled rules and exclusions in report metadata. Reject unknown rule IDs, invalid glob syntax, ambiguous boundary definitions, and unsupported languages in include paths if strict. Make path exceptions opt-in and visible. Exclude CSS and other declarative stylesheets because not part of executable-language analysis; JSON/YAML/TOML are considered configuration only when explicitly designated and validated, not assumed to justify arbitrary semantics.

## 5. Exact policy semantics: numbers

### MAGIC001 numeric literal outside 0/1

Scan numeric literal nodes in executable Python and JS. For a first, testable spec:

- Accept any numeric literal whose exact value is `0` or `1`, regardless of encoding: `0`, `1`, `0.0`, `1.0`, `1e0`, `0x1`, `0b0`, `0o1`, `1n`, `0j`. The check is value-based, not spelling-based; document and test each encoding in both languages.
- Reject `2`, `-1`, `1.5`, `3.14`, `0x10`, `1e3`, `10n`, numeric separator forms, array sizes, durations, regex quantifiers **only when represented as numeric AST expression nodes**. Regex-literal internals are separate planned rule coverage and must not be mistakenly claimed as analyzed.
- Unary negative is an operator: `-1` evaluates to -1 and **is forbidden by strict default**. This is configurable (`allow_unary_negative_one`). `-0` and `-0.0` are **also flagged by default**: the sign expresses intent, and negative zero is a distinct float value in JavaScript (`Object.is(-0, 0)` is false). Unary plus (`+1`) is treated as the literal it wraps.
- Do not infer that `2` is acceptable in `range(2)`, `i + 2`, `Math.pow(x, 2)`, indexes, or test expressions. Flag it.
- Python booleans are distinct from integers despite `bool` subclassing `int`; avoid accidental treatment as numeric policy violations.
- Numeric literals inside Python type annotations (`Literal[2]`, `Annotated[int, 2]`, `tuple[int, int]` subscripts with numbers) **are flagged**. Annotations are expressions and are evaluated at definition time unless deferred; the strictest reading applies and is documented. Docstrings and comments are not AST numeric nodes and are never flagged.
- Python complex literals and JS BigInt are numeric and subject to rules. Precisely document edge cases (NaN/Infinity represented as identifiers rather than literals, signed numbers, decimal, complex).
- String numerals are strings, not numerical AST nodes; detect stringly typed policies through separate advisory rule if needed.
- ~~A declaration like `ITERATIONS = 2` **is still a numeric literal** and should be flagged in executable source unless the file is explicitly a configuration/specification location or a narrow documented suppression is granted. A named constant is not automatically justified.~~ **Superseded by §21.1 decision 36 (2026-10-17):** a module-level named constant definition is the remedy and is not reported in any profile; a literal where a number is used still is, and a name that only spells its value (`TWO = 2`) is MAGIC004.
- A reference to `math.pi` is permitted; `3.14` is not. A standard-library named constant conveys meaning without copying the numeric literal.
- A well-defined protocol numeric constant should be represented in designated spec/configuration source or through a documented suppression, not granted a universal number exemption.

**Directive to remediation agent:** For a numeric violation, determine the business/mathematical/protocol reason for the value. Prefer a required, validated configuration parameter for variable policy; a named authoritative constant for invariant math/specification; never silently move it into a meaningless constant or add an implicit fallback.

**Named constant definitions (`rules.magic_numbers.named_constant_definitions`, decided 2026-10-14, see §19 decision 15).** A numeric literal that is the *whole* right-hand side of a module-scope constant definition (Python: a single UPPER_SNAKE_CASE target, leading underscores allowed, or any simple name annotated `Final`; JavaScript: `const NAME = <literal>` or `export const NAME = <literal>` with the same name rule; the literal may carry one unary minus) is marked by the adapters. The option decides whether MAGIC001 reports it: `"report"` keeps the strict reading above (`ITERATIONS = 2` is still flagged; a named constant is not automatically justified) and is the default of the `strict` profile; `"allow"` treats the definition as the name rather than the magic and is the default of the `recommended` and `minimal` profiles, because that definition is exactly the remedy the rule asks for and forcing every adopter to keep one exempt constants file (as this tool does with `constants.py`) is adoption cost without a precision gain. Literals inside containers, expressions, class bodies, function bodies and definitions nested in module-level `if`/`try` blocks are reported under both values. Setting `"allow"` under `strict` is a reported policy deviation. Since 0.3.0 (§19 decision 16) the value may also be arithmetic built only of numeric literals, unary `+`/`-`, parentheses and the binary operators `+ - * / // % **` (`CHUNK_BYTES = 64 * 1024`; JavaScript the same set); every literal of such a definition is marked, and any name, attribute, call, subscript or non-numeric literal in the expression leaves every literal reported.

**`0` and `1` are permitted, not recommended.** When a `0` or `1` carries meaning beyond arithmetic identity (an exit or return code, a sentinel, a boolean-as-integer flag, a protocol value, a first/last index with domain meaning), the skills direct the agent to give it a named constant (`EXIT_OK`, `FIRST_PAGE`, `SUCCESS`). Plain arithmetic uses (`i + 1`, `len(x) - 1`, `range(0, n)`, `x ** 0`) stay literal. The analyzer does not flag `0`/`1`; this is a skill-level convention, not a rule.

### MAGIC002 suspicious string literals (advisory initially)

Flag duplicate decision strings, magic status strings and condition operands, hardcoded endpoints, and repeated protocols where names/enums would improve discoverability. Exempt ordinary error text, docstrings, import paths, schema keys, and UI copy initially via explicit, documented heuristic categories. High false-positive risk: never hard-fail by default until empirical calibration.

## 6. Exact policy semantics: exception handling

### EXC001 forbidden catch

Python: inspect `ast.Try`, `ast.TryStar`, each `ExceptHandler`, exception type tuple; bare `except`, `Exception`, `BaseException`, broad library bases and dynamic type expressions should fail without approved exemption. JavaScript `catch` is syntactically broad: a type name in a conditional inside `catch` does not prove it is narrow; treat every `catch` as forbidden unless it is in an approved boundary and satisfies a validated handler policy.

- **Do not globally whitelist `ValueError` or `TypeError`.** Exception allowance is context-specific, scoped by file/module/call target where analyzable, and exception identity; only failures of external systems outside program control are candidates.
- For Python, match qualified exception names by import/symbol table best effort, record resolution confidence, and fail closed (or emit unresolved blocking diagnostic) on unrecognized identities in strict mode.
- JS has no sound static exception typing. Approve boundary-specific handling via explicit policy annotation and inspect caught variable usage and handler behavior; say explicitly that proof is limited.
- Catches that immediately re-raise (`raise`, JS `throw`) should be configurable; strict default still flags catches, because wrapping/rethrowing may alter semantics and is not the same as no catch. Offer a `transparent_rethrow` exception policy if maintainers choose.

### EXC002 suppressed or converted exception

Detect empty/pass catch, `return None` / `return null` / `return undefined` / `return 0` / `return false` / success-shaped fallback from catch, logging-only catch, and catch that returns fabricated data. Fail even within otherwise whitelisted boundary unless the policy explicitly specifies a valid typed error representation or propagating behavior. Preserve stack/cause for rethrow (`raise ... from ...`, `Error(...,{cause})`) where relevant; do not count logging as a sufficient remedy.

### EXC003 broad try scope / unverified boundary

If an approved catch wraps code other than the sanctioned external operation or the resolver cannot confidently isolate it, report a boundary violation. Example: catching a timeout around parsing, validation, and I/O risks masking internal defects. Support narrow try blocks and clear callback rules. Document static uncertainty instead of pretending complete exception-flow inference.

## 7. Exact policy semantics: defaults and fallbacks

Rules default-on, with configurable severities/overrides:

- **DEF001 function parameter default:** Python `def f(x=...)`, keyword-only defaults; JS `function f(x = ...)`, arrow/default params, destructuring defaults. Default values are forbidden in strict mode regardless of type. Distinguish `*args`, `**kwargs`, `this`, annotations, abstract declarations, JS rest params.
- **DEF002 missing mapping/object fallback:** Python `mapping.get(key, fallback)` and `getattr(obj, attr, fallback)`; JS `obj?.x ?? fallback`, destructuring `const {x = fallback}`, optional chaining with fallback, and `Object` helper patterns where recognizable. `.get()` with no fallback may still implicitly yield `None`; report as a separate classified finding when requiredness cannot be established (review, not arbitrary assumptions).
- **DEF003 truthiness fallback:** `x or default`, `x || default`. These also replace legitimate falsy values; initially emit review findings unless explicitly configured to fail. Do not classify every Boolean `or` as a fallback; use AST/context heuristics and mark uncertainty.
- **DEF004 nullish fallback:** `x ?? default`, `x if x is not None else fallback`, conditional expressions with missing checks. Flag with configurable review/fail; strict profile should fail clear default substitutions.
- **DEF005 exception-to-default:** Cross-reference catches and return literals, including fallback calls delegated to helper where static trace possible.
- **DEF006 implicit configuration fallback:** Detect environment-variable defaults (`os.getenv("X", value)`, `process.env.X || value`, etc.) in application code; require explicit parse/validation at configuration boundary.

Distinguish a genuine *optional domain input* from a missing *required* input: static analysis alone cannot always decide. Report a finding rather than auto-rewrite. Agents must identify the intended contract before altering behavior. Do not claim eliminating all defaults is universally idiomatic: this is an intentionally opinionated project policy.

## 8. Rule metadata, suppressions and policy changes

Each rule has immutable ID, version, default severity, description, rationale, compliance examples, detection guarantees, limitations, and suggested (not automatic) fixes. Example stable IDs: `MAGIC001`, `MAGIC002`, `EXC001`–`EXC003`, `DEF001`–`DEF006`, `CPLX001`–`CPLX005`.

Support a documented single-line suppression form with mandatory reason, e.g. `# shockharness: ignore[MAGIC001] reason="Protocol-assigned code; see RFC section ..."`. JS equivalent `//`. Suppressions need exact rule ID and smallest practical scope; invalid/unused suppressions emit findings. `--no-inline-suppressions` for organizations that require centralized policy. Baseline fingerprints must use stable syntax context and rule ID so line moves don't reintroduce every finding; store a reviewed baseline under version control, never auto-update in CI.

Security: config files must not execute code. Reject YAML custom tags; favor TOML; do not eval source or import analyzed Python modules. Path handling must avoid traversing outside user-specified root via symlink without explicit opt-in. Avoid uploading source anywhere.

## 9. Complexity metrics (separate from hard rules)

### Baseline analyzers

- **Cyclomatic:** documented consistent language-specific decision counting, including `if/elif`, loops, `except/catch`, Boolean short-circuit (configurable standard), conditional expressions, optional chaining where meaningful. Expose exact algorithm/version.
- **Cognitive:** follow a documented published-style nesting and interruption approach; tests for nested vs flat constructs and Python/JS parity. Avoid labeling it exact Sonar score unless matched and permitted.
- **Nesting:** max nested decision depth excluding syntactically incidental wrappers.
- **NPath:** report an approximation or bounded estimate of acyclic paths, saturation cap, and potential infeasibility; avoid exponential materialization.
- **Size:** logical LOC, parameters, statements; auxiliary, not quality substitutes.

### Interprocedural/architectural analytics

Create module/function call graph, confidence-classified edges: resolved direct call / probable / unresolved dynamic. Python imports/aliases, JS import/export/re-exports, higher-order calls are explicit coverage targets with limitations. Cycle/SCC detection, fan-in/out, shared mutable state heuristics, cross-module dependencies, and change-impact radius. Never pretend indirect Python reflection or JS dynamic property calls are resolved reliably.

**Abstraction displacement heuristic** (experimental): compare before/after graphs. Flag when local score falls while reachable weighted decision burden or state/coupling grows; avoid declaring simple delegation inherently bad. Treat interface quality and contract clarity as separate signals, with model uncertainty and illustrative traces. Do not collapse into a single magic score.

### Historical risk

Read `git log` locally (no remote). Per-function attribution should handle renames and line shifts conservatively; file-level churn is acceptable for v1 with explicit granularity. Track edits over configurable horizon, hotspot score (e.g. `log1p(churn)*normalized_complexity`), co-change graph with sample-size/support thresholds, and report confidence. Do not gate solely because a file is frequently changed.

## 10. Results schema and API

JSON top-level: `schema_version`, `tool_version`, `analysis_status`, `config_digest`, `policy_profile`, `coverage`, `files`, `findings`, `metrics`, `gate`, `execution_summary`. Stable result sorting by normalized path, start position, and rule ID.

Sample finding:

```json
{
  "rule_id": "MAGIC001",
  "rule_version": "1",
  "severity": "error",
  "path": "src/client.py",
  "span": {"line": 12, "column": 28, "end_line": 12, "end_column": 30},
  "message": "Numeric literal 30 has no permitted justification in executable code",
  "evidence": "timeout=30",
  "confidence": "exact",
  "remediation": "Identify the contract; use required validated configuration or an authoritative named constant",
  "safe_autofix": false,
  "suppression": null
}
```

Exit codes: `0` all required gates pass; `1` policy violations; `2` invalid config / unsupported invocation; `3` analyzer internal error or unhandled parse failure (strict fails). Preserve stable CLI behavior in tests; distinguish report generation from policy status. Emit SARIF 2.1.0 with rule IDs and locations for GitHub code scanning.

Python library exposes typed `analyze_source(source, language, config)`, `analyze_paths(paths, config)`, `evaluate_gate(report, baseline, policy)`; never require CLI subprocess from library consumers. Errors must be typed, documented, and not swallowed.

## 11. CLI interface

```shell
shockharness init --profile strict
shockharness version
shockharness config validate
shockharness config effective
shockharness check src/ --format text            # canonical name; `scan` remains a hidden alias
shockharness check src/ --format json --output report.json
shockharness check src/ --format sarif --output report.sarif
shockharness baseline create src/ --output .shockharness-baseline.json
shockharness diff --base main --head HEAD
shockharness gate --base main --head HEAD --format text
shockharness rules list
shockharness rules explain MAGIC001
shockharness skills install --agent codex|claude [--project PATH]
shockharness skills update --agent codex|claude [--project PATH]
```

`check` is the canonical analysis command from Milestone F onward (§20 decision 1); `scan`, which Milestones A-D shipped, stays as an undocumented alias so existing CI lines keep working. Commands are **requested implementation**, not extant tools. `init` writes a config but never overwrites an existing config without explicit confirmation; CI must be noninteractive. `baseline create` requires explicit user invocation. Diff works with changed files and stable baseline comparison; perform whole graph analysis as needed to avoid missing cross-file effects. Respect `.gitignore` only if configured; explicit includes/excludes take precedence.

## 12. Agent skills and integration

Bundle four vendor-neutral skills with YAML frontmatter (name, description) and a `SKILL.md` in each subdirectory:

1. `write-compliant-code`: require clear contracts, no arbitrary catches/defaults/non-0/1 numeric literals; distinguish data/config/spec and source. Prefer named constants for `0`/`1` that carry meaning (return codes, sentinels, flags) per §5; leave arithmetic identity literals alone.
2. `fix-violations`: run analyzer; for each finding determine intended contract, add characterization tests, modify code, rerun suite and analyzer; never blindly delete `try/except` or replace `get` with indexing without contract review.
3. `refactor-complexity`: address repeated cognitive work and coupling rather than metric gaming; require before/after call graph and behavior tests.
4. `pre-commit-review`: run diff gate, show unsupported analysis and suppressions, tests, and remaining warnings; never claim passes without running.

Skills contain concrete examples of compliant and noncompliant Python/JS, exact CLI invocations, corrective workflow, and a checklist. `skills install` should support user-specified target directory and documented Codex/Claude adapters; never modify agent config without explicit invocation, and never overwrite user-customized skill files silently. `skills install` writes a manifest recording installed skill names, the source package version, and a content hash per file; `skills update` refreshes files whose hash still matches the manifest, preserves files the user edited, and reports each conflict with remediation instructions (§20 decision 5). No mandatory MCP server in v1.

Eval suite: paired coding tasks with/without skills across Python/JS, count rule violations, behavioral regressions, unnecessary suppressions, and review accuracy. Agents are not correctness oracles; automated tests and human review remain necessary.

## 13. Tests, goldens, and evaluation criteria

Create a **golden fixture corpus** with input snippets, expected diagnostics (IDs, lines, excerpts), and rationale. At least:

- Python & JS: `0`, `1`, `2`, `-1`, float/scientific/hex, BigInt, constants, `range(2)`, numeric index, negative zero, booleans, JSX attributes.
- Python exception classes: bare, broad, tuple, scoped network timeout, rethrow, logging-only, return fallback, multiple operations in try, `except*`.
- JS catches: untyped catch, rethrow, return fallback, boundary-only catch, nested catches, promise `.catch()` rejection handler (AST rule as applicable), async await and promise chains.
- Python defaults: parameter values, mapping/getattr, `or`, `.get(key)` ambiguity, environment fallbacks, dataclasses/default factories; JS parameter/destructure defaults, `||`, `??`, optional chaining, `process.env`.
- Parsing/imports: CRLF, Unicode, multiline and comments, invalid syntax, generated files, symlinks, missing config, contradictory overrides, unused suppression.
- Complexity: flat vs nested branches, short-circuit, mixed modules, recursion, cycles, unresolved dynamic calls, capped path count, extraction metamorphic pair.
- Baselines: new violation, old unchanged violation, moved line, changed rule, suppressions and stale/unused baselines.

Use `pytest`, property-based tests (Hypothesis), subprocess CLI integration tests, golden snapshots with review, and performance tests. Critical metamorphic tests: whitespace/rename invariance where intended; behavior-preserving helper extraction must not automatically cause a system-level 'better' verdict; artificial splitting should not reduce architecture assessment unchecked. Parser fuzzing with bounded input/time limits.

**Release acceptance:** (1) each default-on policy catches documented positives in both languages; (2) tests cover supported syntaxes and no obvious false passes; (3) no silently ignored parse failures; (4) baseline/diff deterministic; (5) no LLM/network required; (6) documented uncertainty; (7) CI sample works; (8) API and schema versioned; (9) installable wheel + sdist; (10) skills ship with eval fixtures.

## 14. Execution roadmap for coding agent

### Milestone A — Skeleton + contracts

- Set package name placeholder, MIT license, README, pyproject, release metadata, CI and tests.
- Define config schema, rule registry, diagnostic model, JSON output schema; implement no actual rules yet.
- Build CLI `scan`, `config validate`, `rules list`; fixtures proving errors have nonzero exit.
- **Done when:** package installs in isolated venv and CI runs green on ubuntu, macos, and windows across Python 3.11, 3.12, 3.13, and 3.14.

### Milestone B — Parsers + exact magic-number rule

- Python `ast` and JS parser adapters, spans, source extraction, parse error propagation.
- Implement `MAGIC001` with strict 0/1, all literal encodings and overrides, config-file exclusions, suppressions.
- Include behavior and metamorphic fixtures, end-to-end CLI verification.
- **Done when:** `range(2)` fails in Python; `for(let i=0;i<2;i++)` fails in JS; same code passes when rule disabled, and config report shows why.

### Milestone C — Exceptions

- Python exception rule with best-effort import resolution, JS catch policy and boundary metadata; EXC001–EXC003.
- Test whitelist scope and broad-try detection; never treat `logging` as enough.
- **Done when:** approved network failure handling passes only in verified boundary, broad catches fail, unresolved type produces explicit diagnostic.

### Milestone D — Defaults

- DEF001–DEF006, correct identification of obvious defaults vs Boolean expression heuristics; inter-rule linkage to EXC002.
- Maintain evidence and conservative no-autofix policy.
- **Done when:** representative Python and JS examples produce exact diagnostics and fixes remain suggestions.

> **Order change (§20 decision 6):** Milestone F runs before Milestone E. Distribution needs baselines, diff, SARIF and release automation sooner than it needs complexity metrics.

### Milestone E — Complexity + graph

- Per-function cyclomatic/cognitive/nesting, approximate NPath; call graph with unresolved-edge reports; coupling and cycles.
- **Done when:** validated fixtures agree with documented counting conventions; don't state unsupported resolutions as exact.

### Milestone F — Git + gates + reports + distribution

- Baseline, diff, policy evaluation; file churn, hotspots and co-change; JSON + SARIF; deterministic ordering and stable fingerprints.
- `check` as canonical command with `scan` alias, `version` subcommand, `shockharness.toml` filename, `effective_profile` in output, built-in profiles `strict`/`recommended`/`minimal` with deviation reporting (§20).
- Release automation: tag-triggered GitHub Actions workflow (`v*` tag → test matrix → build → publish to PyPI via trusted publishing), reusable `workflow_call` workflow for consumers with inputs for analyzer version, config path and diff base, `.github/dependabot.yml` for this repo, and consumer integration docs built around Dependabot.
- `examples/python` and `examples/js` consumer projects plus a script that copies each into a throwaway git repository, installs a pinned version, runs the gate, bumps the pin, and runs it again.
- **Done when:** reproducible PR gate on two commits and a complete output provenance trail.

### Milestone G — Agent skills + docs + beta

- Four skills, installation opt-in, task eval corpus, readme guide, policy examples, contributing workflow, changelog and packaging.
- **Done when:** fresh test repo can onboard, run gate, use a skill to repair a fixture, and install wheel without external setup.

### Milestone H — Experimental research (post-v1)

- Transitive weighted complexity; abstraction-quality/interface heuristics; change-impact radius; improved data flow; optional local/remote LLM review (explicit opt-in, private by default).
- Benchmark against Ruff/ESLint/Lizard/cognitive scores/LOC/churn baselines for defect prediction and refactoring invariance; temporal split, ablation, calibrated uncertainty. Never gate on unvalidated experimental scores by default.

## 15. Agent operating instructions and completion protocol

When handed this document, the coding agent shall:

1. Create a new standalone repository and implementation plan from milestones A–G. Ask only for truly blocking decisions (e.g. final project name) and otherwise use placeholder identifiers.
2. Before each milestone, state files to change, rule semantics, risks, and targeted acceptance checks in a short local issue/task record.
3. Implement the smallest vertical slice; run unit + integration tests; keep output evidence.
4. Update a `STATUS.md` with milestone completion, exact commands/tests run, observed failures, limitations, and next tasks. Never claim tests passed unless run.
5. Keep the analyzer's own code compliant. **ShockHarness runs on itself as a hard CI gate from Milestone B onward.** Bootstrapping policy, all declared as visible `[[overrides]]` or `boundaries` entries in the repository's own `.shockharness.toml`, each with a reason:
   - One designated module, `src/shockharness/constants.py`, holds every numeric constant the tool needs (exit codes, schema version, default thresholds, SARIF version, caps). `MAGIC001` is disabled for that single path. Nothing else may carry a numeric literal other than `0` or `1`.
   - Approved exception boundaries are the places where the tool meets the outside world: file reading, TOML decoding, Python `ast.parse`, tree-sitter parsing, and `git` subprocess calls. Each boundary names the qualified exception it catches and converts it to a typed analyzer diagnostic that drives exit code `3`. No other `try`/`except` is permitted in the tool.
   - `tests/**` disables `MAGIC001` and `DEF001` with the reason that fixtures encode literal expected outputs. Test code is still scanned for everything else.
   - Public API functions take no default parameters, consistent with §18 decision 2.
6. Never modify quality-gate thresholds merely to obtain green status; proposals require recorded rationale.
7. Preserve deterministic behavior, diagnostic schemas, and backward compatibility after v1 publication.
8. Provide a final local summary showing implemented files, test evidence, sample output, open limitations, and how to adopt the package in a consuming project.
9. Commit at the end of each milestone, after tests pass, with a message that names the milestone. Do not push; the maintainer pushes. Do not commit a milestone whose tests have not been run.
10. Session scope: the first implementation session delivers Milestones A and B only, then stops and reports (§16). Later milestones follow on explicit go-ahead.

## 16. Ready-to-use kickoff prompt for the coding agent

> Implement the standalone Python package and CLI specified in `agent_code_integrity_project_spec.md`. Start with Milestone A and Milestone B only, including complete tests, sample Python and JS fixtures, correct configuration behavior, clear error handling, and user documentation. Use a neutral placeholder name rather than choosing the public brand. Do not build an LLM service, dashboard, or unsupported integrations. Keep deterministic findings, source spans, strict default-on `MAGIC001` (only 0 and 1 allowed in executable source), and explicit parse failures. After completion, run tests and report exact outputs and remaining limitations. Do not proceed to Milestone C until the first two are demonstrably working.

## 17. Name exploration and collision-screening notes

**Resolved 2026-10-14:** the project is named **ShockHarness** (package `shockharness`). It was chosen by the maintainer and was not part of the screened candidate list below; the list is kept as a record of the search. Exact-name checks on GitHub, PyPI, npm, domains, and trademarks for `shockharness` must still be done immediately before publishing. Nothing below should be read as clearance of the chosen name.

**This is preliminary search screening, not legal or definitive package/repository clearance.** Search-engine indexing is incomplete, particularly for newly created GitHub repositories and package registrations. A name with "no prominent match found" is **not confirmed available**. Before publishing, check exact GitHub repo names, PyPI normalized distribution names, npm names, domains, and trademarks immediately before registration. The names below are creative candidates, **not vetted trademark advice**.

| Candidate | Rationale | Preliminary search status (2026-10-14) |
|---|---|---|
| **InvariantLens** | See underlying assumptions and contracts | No prominent exact-name GitHub/PyPI/npm result surfaced in these searches; unverified |
| **AxiomSentry** | Guard explicit correctness axioms | No prominent exact-name result surfaced; unverified |
| **TraceInvariant** | Trace where invariants are broken | No prominent exact-name result surfaced; unverified |
| **FailVisible** | Make failure observable | No prominent exact-name result surfaced; unverified |
| **UnhiddenCode** | Expose hidden behavioral policy | No prominent exact-name result surfaced; unverified |
| **NoSilent** | Prevent silent failure and fallback | Searches surfaced related lowercase `nosilent` references; collision risk; unverified |
| **ExplicitPath** | Make decisions and paths explicit | Exact phrase used as a resolver identifier in `config-file-effect`; collision risk |
| **ContractBeacon** | Illuminate contractual assumptions | Exact name used as a smart-contract identifier; collision risk |
| **ClarityGate** | Explicit CI quality gate | Already used by open-source projects; **avoid** |
| **CodeUnveil** | Reveal hidden code assumptions | Existing site/business using CodeUnveil; **avoid** |

Other **rejected** suggestions from initial screening: `FailTrace` (existing GitHub projects), `AssumptionGuard` (other product uses). See sources in next section.

**Preferred candidates for further live clearance:** `InvariantLens`, `AxiomSentry`, and `TraceInvariant`. They are recommendations only; not claims of unique ownership or availability.

### Search evidence

- ClarityGate existing GitHub repository: https://github.com/Manula-Fernando/document-blur-detector-ClarityGate
- Another product uses ClarityGate inside agent orchestration: https://github.com/beydemirfurkan/opencode-gladio
- CodeUnveil existing business: https://www.codeunveil.com/about
- FailTrace existing repository: https://github.com/BharZInstein/FailTrace
- AssumptionGuard other use: https://www.reddit.com/r/u_Main-Advertising-277/comments/1wtug45/assumptionguard/
- ExplicitPath npm context: https://www.npmjs.com/package/config-file-effect
- ContractBeacon other use: https://github.com/1v1me-me/app
- `nosilent` identifier appears in tooling discussions: https://pypi.org/project/3tears-enforcement/0.17.7/

## 18. Open decisions for maintainers (not blockers for A/B)

1. ~~Final public name and PyPI package distribution identifier.~~ **Resolved:** ShockHarness / `shockharness` (§17). Registry and trademark clearance remains open.
2. Whether strict profile forbids all default parameters even in tests and public API interfaces; proposed answer: yes in application source, explicit path overrides for tests.
3. Precise convention for sanctioned external boundaries; proposed answer: location + qualified exception + narrow try scope + documented reason.
4. Whether string-literal rule ever becomes hard gate; proposed answer: advisory until evaluated.
5. ~~Whether `-1` can be configured as allowed.~~ **Resolved:** configurable via `allow_unary_negative_one`, off by default; `-0`/`-0.0` flagged by default (§5).
6. What happens on partial JS unsupported syntax; proposed answer: explicit incomplete analysis and configurable fail (strict default fails).

## 19. Resolved decisions (2026-10-14 review)

Recorded so that the implementation agent does not re-ask them. Each is binding unless a maintainer changes it here.

| # | Decision | Resolution | Where applied |
|---|---|---|---|
| 1 | Name | **ShockHarness**; package/CLI/config key/suppression prefix all `shockharness` | header, §3, §4, §8, §11, §17 |
| 2 | First session scope | Milestones A and B only, then stop and report | §15.10, §16 |
| 3 | Python floor for the tool | 3.11+; CI on 3.11, 3.12, 3.13, 3.14; parseable Python syntax is bound to the host interpreter and reported as coverage | §1 |
| 4 | Self-compliance | Hard CI gate on the tool's own source from Milestone B; one exempt `constants.py`; declared exception boundaries; tests exempt from `MAGIC001`/`DEF001` | §15.5 |
| 5 | `MAGIC001` encodings | Value-based: any encoding of exactly 0 or 1 passes | §5 |
| 6 | `MAGIC001` negative zero | `-0` and `-0.0` flagged by default, same as `-1` | §5 |
| 7 | `MAGIC001` annotations | Numeric literals inside Python type annotations are flagged | §5 |
| 8 | Commit cadence | One commit per milestone after tests pass; never push from the agent | §15.9 |
| 9 | Dependencies | `tree-sitter` 0.25.x + `tree-sitter-javascript` 0.25.x only at runtime (0.26.0 excluded: segfaults on CPython 3.14 with deep nesting); stdlib `argparse`/`tomllib`; `uv` for environments; Ruff, pytest, Hypothesis as dev-only tools | §3 |
| 10 | JS parse errors | Any tree-sitter `ERROR`/`MISSING` node is a parse failure | §3 |
| 11 | CI matrix | GitHub Actions on ubuntu, macos, windows × Python 3.11–3.14 | §14 Milestone A |
| 12 | Meaningful `0`/`1` | Skills prefer a named constant when a `0` or `1` carries meaning (exit codes, sentinels); the rule itself never flags them | §5, §12 |
| 13 | Distribution | See §20 for the decisions taken on reviewing `docs/shockharness_distribution_integration.md` | §20 |
| 14 | Advanced guardrails | See §21 for the decisions taken on reviewing `docs/shockharness_advanced_guardrails_spec.md` | §21 |
| 15 | `MAGIC001` named constant definitions (2026-10-14, from `docs/shockharness-suggestions.md` item 1) | **Middle ground**: a `rules.magic_numbers.named_constant_definitions` option, `report` in `strict` (the §5 semantics are unchanged there) and `allow` in `recommended` and `minimal`; `allow` under `strict` is a reported deviation | §5, 0.2.0 **Superseded by §21.1 decision 36:** `allow` is the default of every profile. |
| 16 | Literal arithmetic in named constant definitions (2026-10-15, from `docs/shockharness-suggestions-3.md` item 2) | Under `named_constant_definitions = "allow"` a module-level constant whose value is arithmetic over numeric literals only (`64 * 1024`) is a definition like a single literal; anything else in the expression keeps every literal reported; `report` is unchanged | §5, 0.3.0 |

## 20. Distribution decisions (2026-10-14 review of `docs/shockharness_distribution_integration.md`)

The distribution brief in `docs/shockharness_distribution_integration.md` is a design input. Where it and this specification differ, this section is binding and the brief is annotated to say so.

| # | Topic | Decision | Where applied |
|---|---|---|---|
| 1 | Command names | `check` is the canonical analysis command; `scan` stays as a hidden alias; `version` is added as a subcommand alongside `--version`; `rules explain` and `diff --base/--head` keep the spec's forms | §11, Milestone F |
| 2 | Exit codes | Stay `0` pass, `1` violations, `2` invalid configuration or invocation, `3` internal error or strict parse failure. The brief's three-code scheme is not adopted; CI consumers need to tell a broken config from an unreadable file | §10 |
| 3 | Config schema and filename | The schema in §4 stays (`[tool.shockharness]`, `rules.exceptions`, `rules.defaults`, `complexity.cognitive_warn`). The brief's `[shockharness]`/`exception_handling`/`implicit_defaults`/`max_cognitive` names are illustrative only. Both `.shockharness.toml` and `shockharness.toml` are accepted; both present is an error | §4, Milestone F |
| 4 | Profiles | Three built-in profiles ship, selected with `profile = "..."`; `strict` is the default and keeps its name. `strict`: every rule at its documented severity, `parse_errors = "fail"`. `recommended`: as strict, except DEF003 and DEF004 are `review`. `minimal`: MAGIC001, EXC*, DEF* all `review`, `parse_errors = "warn"`, complexity off. Any profile below `strict` emits a policy-deviation line in every report. Precedence: bundled defaults < profile < repository config < explicit CLI overrides (the overridable CLI keys are decided in Milestone F and listed in docs) | §4, Milestone F |
| 5 | Skills | Names stay as in §12 (`refactor-complexity`, not `complexity-refactoring`). `skills update` with a manifest (names, package version, per-file hashes) joins Milestone G | §12, Milestone G |
| 6 | Milestone order | F before E | §14 |
| 7 | Repository | `https://github.com/evolvingstuff/ShockHarness`; reusable workflow references and package URLs point there | pyproject, Milestone F |
| 8 | Package name | `shockharness` **registered on PyPI on 2026-10-14** by publishing 0.1.0a1 (owner: Thomas Lahore); the similarity check passed. npm `shockharness` was free on the same date and is not claimed | §17 |
| 9 | Publishing | Tag-triggered: pushing `v*` runs the test matrix, builds wheel and sdist, and publishes to PyPI through trusted publishing (no stored token). One-time PyPI setup by the maintainer; exact steps documented in Milestone F | Milestone F |
| 10 | Consumer updates | Dependabot. Consumer docs show a `.github/dependabot.yml` and require the version pin to live in `pyproject.toml`, a requirements file, or a workflow `uses:` line, never inside a shell command such as `uvx --from shockharness==x` | Milestone F docs |
| 11 | Consumer examples | `examples/python` and `examples/js` inside this repository, exercised by a script that creates throwaway git repositories and performs a pinned install plus an upgrade. Real external consumer repositories only if this proves insufficient | Milestone F |
| 12 | Submodules | Not supported as an integration mechanism, per the brief | — |
| 13 | Output fields | `effective_profile` is added to the JSON report next to `tool_version` and `schema_version`; `policy_profile` is renamed to it before schema v1 is published | §10, Milestone F |

## 21. Advanced guardrails: decisions and milestone plan (2026-10-14 review of `docs/shockharness_advanced_guardrails_spec.md`)

The guardrails brief is a design input, as the distribution brief was. Where it and this specification differ, this section is binding and the brief is annotated to say so. Milestones A-G are complete at the time of this review (v0.1.0a1 on PyPI); the work below starts after the 0.1.0 release.

### 21.1 Decisions

| # | Topic | Decision |
|---|---|---|
| 1 | Names in the brief | `[shockharness]`, `rules.exception_handling`, `rules.implicit_defaults`, `DEFAULT001`, `strict-agent` are the same drafting as the distribution brief and are superseded by §4 and §20: the implemented schema, `DEF001`-`DEF006`, and the `strict` profile stand |
| 2 | Exit codes | Unchanged: `0` pass, `1` violations, `2` invalid configuration or invocation, `3` internal error or strict parse failure. The brief's reassignment of `3` to "policy integrity failure" is not adopted. Policy-integrity findings (VERIFY*) are hard violations with their own finding category `policy_integrity` and exit `1`; CI consumers distinguish them by category in JSON and SARIF, not by exit code |
| 3 | Finding states | Add an explicit `unknown` state alongside the existing `exact`/`approximate`/`unresolved` confidence: a rule that could not establish the property emits an `unknown` finding (never silence), and `fail_on_unknown` is configurable **per rule family** (`rules.<family>.fail_on_unknown`, default false except where a family already fails closed, e.g. EXC001). `pass`/`not_applicable` are per-file statuses, already reported as `analyzed` with `rules_applied`/`rules_disabled` |
| 4 | File roles | Add file-role classification (`production`, `test`, `config`, `generated`, `vendor`, `docs`) derived from configurable globs with documented defaults; roles become the scoping mechanism for STUB, ASSERT, VERIFY and for the existing `configuration_files` exemption |
| 5 | CLI overrides vs agent-proofing | `--profile`, `--parse-errors` and `--exit-zero` stay (per-invocation, visible in the report). The reusable workflow `check.yml` never passes them, and VERIFY003 treats any edit to a consumer's workflow files, `.shockharness.toml`/`shockharness.toml`, baseline files and the analyzer version pin as protected-path changes. The trust model is the brief's: a local CLI cannot stop a privileged actor; enforcement needs branch protection and required checks, and the docs say so |
| 6 | Org-level profile tier | Accepted as a precedence tier between the built-in profile and repository config: `--policy FILE` names a TOML policy file supplied by the protected CI workflow (checked out from a separate protected repository or shipped as a pinned package resource), never read from the analyzed repository. Keys set by the policy file cannot be loosened by repository config; attempts are reported as VERIFY003. Implemented with H2 |
| 7 | Skills | Keep the four shipped names (`write-compliant-code`, `fix-violations`, `refactor-complexity`, `pre-commit-review`). Add `verification-integrity` with H2 and `async-lifecycle` with H4. The brief's `complexity-refactoring` and `pre-commit-check` are not adopted |
| 8 | TypeScript | A separate adapter milestone (H-TS) using `tree-sitter-typescript` (same pinning discipline as JavaScript). **The dependency was approved by the maintainer on 2026-10-16** (`docs/shockharness-suggestions-4.md` section 10); H-TS adds it as the third runtime dependency, pinned to a release line verified on CPython 3.11-3.14 like the other two. It is a prerequisite for TYPE001's TypeScript half; TYPE001's Python half (`Any`, `cast`, `# type: ignore`) does not wait for it |
| 9 | Precision bar | The brief's >= 99 % precision target for hard gates is adopted as a release criterion for promoting any new rule from `warning` to `error` by default; until measured on a reviewed corpus, new rules ship at `warning` or `review` |
| 10 | Mascot example | `rm -rf /` appears only in documentation and parse-only fixtures; nothing in tests, evals, demos or remediation text executes or suggests it |
| 11 | Plugin API | **Declined (2026-10-16).** A configuration entry that makes ShockHarness import and run project code contradicts §8 (configuration never executes code) and would let an edit to the policy file run arbitrary code in CI. Project-specific rules stay in the project's own tooling. If integration is wanted later, the recorded alternative is data-only: ShockHarness reads an external findings file in a documented format (`--import-findings`) and routes those findings through suppressions, baselines, the revision gate and SARIF. Not scheduled |
| 12 | DEF002 precision (2026-10-16, `docs/shockharness-suggestions-4.md` items 1-5) | Adopted for the 0.5.0 feedback round (F4): `.get(...)` used as a decorator is not a lookup; a `None`-fallback lookup assigned to a name and immediately checked by an `if` whose body only raises is not reported; a discarded `m.pop(k, None)` is a `review` finding of its own kind; `m.setdefault(k, <empty container>)` immediately mutated is the grouping idiom and not reported; the remediation names "absence is normal: explicit `in` check or a named helper" as a fix |
| 13 | Unknown findings below `strict` (suggestions-4 item 6) | `recommended` sets `rules.defaults.fail_on_unknown = false` (a reported deviation); `strict` keeps `true` and fails closed; `rules.exceptions.fail_on_unknown` stays `true` in every profile. Refines decision 3 for one profile; nothing else changes |
| 14 | `return` in `finally` (suggestions-4 section 10) | New rule `EXC004` in H3: `return`, `break` or `continue` directly in a Python `finally` block or a JavaScript `finally` clause discards the in-flight exception. Exact, syntax only (CPython 3.14 warns about the same construct, PEP 765). Ships at `warning` per decision 9, as the first candidate for promotion to `error` once measured. Not approvable by a boundary, since there is no exception type to approve |
| 15 | Results that hide failures (suggestions-4 section 10) | H5's `PROCESS001` names `subprocess` calls with `check=False` or without `check=True` explicitly. H4 treats `asyncio.gather(..., return_exceptions=True)` and `Promise.allSettled` whose results are never inspected for exceptions or rejected entries as findings, alongside the existing supervisor adapters |
| 16 | Reading `__qualname__`/`__name__` on a value of unknown type (suggestions-4 section 10) | Recorded, not scheduled: it needs type inference ShockHarness does not have, and a syntactic version would be noisy. Revisit as an advisory `TYPE` rule after H5 |
| 17 | Python 3.10 (suggestions-4 section 10) | Declined. The tool's floor stays 3.11 (§19 decision 3): `tomllib` is 3.11+ and the runtime stays stdlib-only plus tree-sitter. The integration docs show running the gate as its own CI job on 3.12 for projects whose test matrix includes 3.10; the analyzer reads 3.10 code |
| 18 | Inspectable exceptions and agent guidance (suggestions-4 items 7-9) | F4 adds `shockharness exceptions`: one read-only list of inline suppressions (used or unused), every configuration exception with its reason and source line, `--policy` attempts and baseline contents (text and JSON, `report_kind = "exceptions"`, exit 0 or 2, never gating). Skills gain a "propose a rule" step (`fix-violations`, `pre-commit-review`) and output validation (`write-compliant-code`). Docs cover Python 3.10 projects, empty trees, and covered-versus-planned checks for projects that layer their own checker |
| 19 | H3 shape (2026-10-16, implemented) | Five new sections (`rules.stubs`, `.assertions`, `.boolean_arguments`, `.module_state`, `.import_effects`) with `enabled`, `severity` (the findings' severity, as in `rules.verification`) and `roles` (default `["production"]`); EXC004 lives in `rules.exceptions` and applies to every role. A rule outside its section's roles is not applied to the file and not listed as disabled, like the VERIFY role scopes. ASSERT001 allows type-narrowing asserts by default (`allow_type_narrowing`); BOOL001 ships at `review`; STATE001 reuses the existing binding and write facts; IMPORT001 resolves callees through the file's own imports against configured operation catalogs. Loosening any of these settings is a policy deviation, so VERIFY003 and `--policy` cover them |
| 20 | A made-up identifier where identifiers come from a registry (2026-10-16, from an agent on MetaList) | Recorded for H6, not scheduled earlier: when one parameter is filled from a store's `start_*`/`create_*` call in some places and from a fresh `uuid4()` (or `crypto.randomUUID()`) in others, the fabricated one is almost always a bug. It needs argument provenance across files, which is H6's bounded dataflow; ship advisory until measured |
| 21 | A strict operation guarded at most call sites and unguarded at others (2026-10-16, from an agent on MetaList) | Recorded for H6 with decision 20, as one family of cross-site consistency rules: when most calls of a throwing operation (`removeNoteHash(id)`) are preceded by its guard (`hasNoteHash(id)`) and some are not, the unguarded ones are reported. It compares call sites across files through the call graph, cannot know intent, and ships at `review` |
| 22 | H4 shape (2026-10-16, implemented) | One section `rules.async_lifecycle` (enabled, severity, roles default production and test, fail_on_unknown, catalogs, supervisors). ASYNC001 sees whole-statement and `void` calls; its callees are a configured catalog resolved through imports, or project functions declared async, resolved by the cross-file call graph's per-site resolutions (a probable edge is `unknown`); the graph and units are built for it even with complexity disabled. ASYNC002 is Python only (create_task / ensure_future with the handle dropped; a with/async with supervisor that bound the receiver owns it). ASYNC003 covers gather(return_exceptions=True) and Promise.allSettled thrown away or not inspected in the enclosing function. All at warning per decision 9; sixth skill `async-lifecycle` |
| 23 | H5 shape (2026-10-16, implemented) | Six sections (`rules.processes`, `.results`, `.types`, `.sleep`, `.retry`, `.batches`) plus `rules.stubs.stub003_severity`, each with `enabled`, `severity`, `roles` and catalogs of qualified callees resolved through the file's imports. PROCESS001: shell commands built from data, and exit statuses returned and unchecked (run without check=True, call, os.system, spawnSync). RESULT001 reuses H4's discarded calls; `.name` entries match methods by name (approximate), never a function of an imported module. TYPE001 is the Python half (Any, cast, type: ignore), at review. SLEEP001 at review; RETRY001 for endless loops whose handler never gives up and unbounded tenacity/retrying/backoff decorators; BATCH001 for loops whose handler only passes, continues or logs; STUB003 for checks that always return True, at review |
| 24 | ROLE001: is shielded code really a test? (2026-10-16, from the maintainer) | A policy-integrity rule after H5: a file in the `test` role that a production file imports (exact, through the module graph) is shipped code shielded from the production rules; a test-role file with no test cases that is not a known support file (conftest, fixtures, helpers) is reported at review; in a revision diff, a change that moves files into the test role or adds a role- or path-based override for them is reported like the other VERIFY003 loosenings |
| 25 | H-TS shape (2026-10-16, implemented) | TypeScript is a third language (`typescript`) parsed by `tree-sitter-typescript` 0.23 (`.tsx` with its TSX grammar) and read by the JavaScript extractors, so every JavaScript rule applies with the same guarantees; the extractors learn TypeScript's node types (typed and parameter-property parameters, `public_field_definition`, abstract classes, the anonymous `number`/`string` keyword tokens, `as`/`!`/`satisfies`/`<T>` wrappers seen through like parentheses, literal types as annotations for MAGIC001). Type-only imports and exports are erased as the compiler erases them (no import fact, no module edge); `import x = require()` is a module import; a `./m.js` specifier resolves to `m.ts`. A JavaScript exception boundary also covers TypeScript files. **The default `include` adds `**/*.ts`, `**/*.tsx`, `**/*.mts`, `**/*.cts` and the default `exclude` adds `**/*.d.ts`**: support means analysis, so a TypeScript repository on the defaults now gets its findings (at their severities) instead of unsupported-source warnings; a project that wants the old scope sets `include`. TYPE001 applies to Python and TypeScript (not plain JavaScript): `any`, `x as T` and `<T>x` (not `as const`; a chained `as unknown as T` once), the non-null `x!` (new `report_non_null`), and `@ts-ignore`/`@ts-expect-error`/`@ts-nocheck` under `report_type_ignore`. Found on the way and fixed for JavaScript too: a function's parenthesized parameters were not counted as its locals |
| 26 | H6 part one shape (2026-10-16, implemented): INPUT001-INPUT002 | Per-unit dataflow facts in the IR, config-free: every value is a set of origins (a parameter, a dotted read rooted at a free name or a parameter, a call's result), flow-sensitive in source order (assignments in branches, loops and handlers add rather than replace), with calls (receiver and argument origins), stores, returns and the origins conditions test; nesting past 100 levels is truncated and marked, operator chains are flattened. One section `rules.input` holds sources, sinks (`callee:N`), validators and configuration reads per language. INPUT001 composes units through the call graph's resolved and probable sites: return summaries to a fixed point with arguments substituted, and parameter-to-sink reach, at most `max_depth` (3) crossings; a call that is not a source, validator or project function passes everything on; one finding per sink and source, at the sink, naming the source and the functions crossed; warning. Default sources are remote input only (request data); command-line arguments and stdin are trusted, because whoever runs the program controls it (measured: on pip, pytest, hypothesis, build, hatchling and npm every argv finding was a CLI using its own arguments). INPUT002: an optional configuration read (`os.getenv(k)`, `os.environ.get(k)`, `process.env.X`) passed on, returned or stored with no condition of the function looking at it; review, because the rule cannot know which variables are required. Cross-site consistency rules (decisions 20, 21) are H6 part two |
| 27 | A delegated event handler that drops SVG targets (2026-10-16, from an agent; implemented 2026-10-17 as DOM001, `rules.dom`) | A small change after H6, at `warning`; the positive form (`if (X instanceof HTMLElement) { X.closest(...) }`) is reported too: in one function, a negated `<p>.target instanceof HTMLElement` test with an early `return`, followed by `<p>.target.closest(...)`. A click on an icon inside a button targets an `SVGElement`, so the guard silently drops it; `closest` is defined on `Element`, so the check should be `instanceof Element`. Narrower checks (`HTMLButtonElement`, `HTMLInputElement`) are deliberate and not reported; `currentTarget` is never affected. JavaScript and TypeScript; syntax only |
| 28 | Asserts are encouraged; ASSERT001 targets their misuse (2026-10-16, from the maintainer and an agent on MetaList; approved and implemented the same day, `console.assert` left as a skill note) | ASSERT001 as shipped in H3 reports every production assert but type narrowing, and tells agents to rewrite each as `if not ok: raise`; in a fail-fast codebase the cheapest compliant edit is deleting the assert, so the rule yields fewer checks. The `-O` risk is a deployment property, checked once at startup. Proposed rework, after H6 because it uses H6's dataflow: ASSERT001 v2 reports only an assert whose test depends on external input (the INPUT sources, configuration reads, file and network reads), never an internal invariant; ASSERT002 (one project-level finding, review) when production code relies on asserts and no entry point refuses to run optimized (`sys.flags.optimize`); the write-compliant-code skill gains a principle that encourages asserting internal invariants, and fix-violations says never to delete an assert to satisfy a finding; JavaScript `console.assert` (which only logs) is a candidate finding. Asserts are encouraged through the skills, not required by a rule (a required assert would be gamed with vacuous ones, which VERIFY004 treats as neutralized) |
| 29 | H6 part two shape (2026-10-16, implemented): PROV001, GUARD001 | One section `rules.consistency` (review, production). Both compare the call sites of one project function resolved by the call graph. PROV001 (decision 20) runs the INPUT001 engine with fabricators (`uuid.uuid4`, `crypto.randomUUID`, ...) and issuing calls (a name opening with `start`, `create`, `new`, ...) as labelled sources; a project function is judged by its return summary before its name; a site passing only a made-up identifier is reported when another site passes an issued one for the same parameter. GUARD001 (decision 21): the IR records, on every call, the guard calls known true where it runs (inside `if g(x)`, after `if not g(x): return/raise`, after `assert g(x)`, through `and`/`&&`); a site is guarded when a guard shares its first argument's text; with at least 3 sites and at least 75 percent guarded, the unguarded sites are reported (any check counts, so `isdir` where the others use `exists` is guarded, measured on pip). On the 790-file corpus neither rule reports anything |
| 30 | MAGIC001 feedback from MetaList (2026-10-16): `-1` allowed by default, and MAGIC003 (implemented) | `allow_unary_negative_one` defaults to true in every profile: on MetaList all 262 findings for `-1` were last-item, all-but-last and not-found idioms. MAGIC003 (`rules.sentinels`, review) keeps the cases that mean something: a value of `rules.sentinels.values` (`-1`; only values MAGIC001 permits) that is the whole value of an assignment, a return, an argument or a dict / object entry, except an UPPER_SNAKE target and arguments of index callees (`range`, `.split`, `.slice`, `.at` ...); subscripts, slices, arithmetic and comparisons are never reported. On the 790-file corpus: 42 findings against 543 for `-1` in 0.6.0, nearly all real meanings (exit codes, not-found returns, unknown sizes). Point 3 of the feedback (`16 * MIB` as a named definition) was withdrawn by MetaList before commit: naming the 16 surfaced a duplicated limit, a wrong unit and undocumented budgets, so the literal stays reported |
| 31 | MAGIC002 shape (2026-10-17, implemented) | One cross-file rule over string facts recorded per file (value, position kind, callee). A value is reported when it is at least 4 characters long, appears 3 times in 2 files, and is compared in 2 files; one finding at its first use naming the other places. Counted kinds: argument, subscript, compare, value (key and jsx opt-in). Exempt by construction: docstrings, directives, f-string and template parts, annotations and TypeScript types, import specifiers and loaders, `__all__`, UPPER_SNAKE_CASE definitions, log / exception messages (`message_callees`, callee suffix Error/Exception/Warning), and an `allowed` list. Severity review (mode = 'fail' makes it error; the spec's "never hard-fail by default until calibrated"). Measured on the 790-file corpus analyzed as one tree: 956 repeated values without the comparison requirement, 395 with one comparison, 179 with comparisons in two files, 171 after the message and allowed exemptions; most are platforms, modes, phases and error codes, generic words remain |
| 32 | DOM002 shape (2026-10-17, implemented): a floating control a press handler treats as outside | From MetaList's backup-reminder bug. Opt-in: `rules.dom.press_exclusions` names the functions holding the skip lists (`path:function`) of page-level press handlers that act on presses outside; empty by default, because measured handlers mostly close their own widget (Trilium's context menu and tooltips, select2, summernote), for which every other element is meant to be outside. Skip lists: `closest`/`matches` arguments, `[...].join(',')`, constants in the file or imported, and plain helper calls followed through imports. Controls: pressable elements attached to `document.body`, or appended into what a function that attaches and returns an element gives back; helpers (removed, clicked or submitted by the code, file/hidden inputs) excluded. Matched on each selector's last compound. Review, approximate, vanilla DOM. Measured: MetaList before its fix 5 findings (the bug's two buttons, a later-fixed surface, a likely banner, one probable false alarm); ten open-source front ends hold one vanilla body-attached control between them (they use jQuery or frameworks) |
| 33 | Annotations that nothing checks: TYPE002 (2026-10-19, implemented) | From MetaList, which was 96% annotated with no type checker (it has since configured mypy). TYPE002 (review, Python, rules.types) reports once per run when at least `annotated_share` (0.5) of the production functions, and at least `min_annotated_functions` (20), carry an annotation and the analysis root configures no checker (mypy, pyright, basedpyright, pyre, ty: their files, their pyproject tables, `[mypy]` in setup.cfg or tox.ini). The minimum keeps scripts and small tools out: without it every annotated example and eval task was reported. Not built from the first proposal: TYPE001 saying when no checker is configured, because TYPE001 is cached per file and the checker's configuration is not in that key (TYPE002 says it once instead); and TypeScript, because a TypeScript project that builds has a tsconfig.json. Configuration only: a checker CI never runs is not seen. |
| 34 | DEF002 statement forms and fallback helpers (2026-10-17, implemented) | From MetaList (an edit reset 11 server-kept reminder fields through `_mapping_value_or(mapping, key, default)`, 26 literal defaults) and a side session's measurement. DEF002 version 2 reports the two Python `return` statement forms of the membership fallback (`if k in m: return m[k]` then `return v`; `if k not in m: return v` then `return m[k]`) under `missing_value_fallbacks` (error in strict), like the ternary: the form was mostly written under ShockHarness's own rule (MetaList 21, ShockHarness `src` 8, corpus 1). A fallback helper (a module-level function whose body, after a docstring and raise-only checks, is a lookup with a parameter as its default) is followed to its calls by name in the same file and reported at each call with the argument as the fallback, under the new `fallback_helpers` mode, review for one release (decision 9). The skill's endorsed remedy changed with it: a helper returning a stand-in is the fallback again; branch where the absence matters, or record a real stand-in with a reasoned suppression. ShockHarness's own 8: four rewritten as explicit branches or `.get(k)`, four total-map lookups suppressed with their reasons |
| 35 | Tests and agent-made policy changes (2026-10-17, implemented; `docs/proposal-gate-loosening.md`) | From under-the-gate round 2, where two builds added the test exemption the skills recommend, mid-task and unasked. (1) `init` and `skills install` write the test exemption (`roles = ["test"]`, `disable = ["MAGIC001", "DEF001"]`) that ShockHarness's own configuration has; the bundled default changes only after measuring what the two rules report in test files. (2) `check` and the edit hook compare the configuration with the last accepted one (the merge base with `origin/HEAD`, else `HEAD`, else the named profile); every rule-switching change is a VERIFY003 error telling the agent to undo it or ask. Rule-switching is every loosening except a catch boundary naming one file; a glob boundary counts. (3) A person committing the change is approval; `skills install --hook --lock` (a policy file outside the project) is opt-in. (4) In `diff` / `gate --base`, rule-switching VERIFY003 findings are `error` by default, narrowing decision 9 for this class; workflow and baseline findings stay `warning`. |
| 36 | Named constants in strict MAGIC001, and MAGIC004 (2026-10-17, implemented) | From three rounds of the under-the-gate experiment, where strict MAGIC001 refusing even a named module-level constant (`FIRST_DATA_ROW = 2`, `JSON_INDENT = 2`) was the main remaining driver of disguised numbers (`HEADER_ROW + 1`, `"  "`, `len(calendar.month_name)`, `REPORT_INDENT = True`). `rules.magic_numbers.named_constant_definitions = "allow"` is the default of every profile (it was `report` in strict, §19 decision 15); `report` is an ordered tightening. MetaList already set `allow` under strict by hand. Measured before the change: 965 MetaList findings (843 constants), all 35 in ShockHarness's own `src`, 5 in the skill-eval references and 58 in the experiment's agent-written builds go away; none of those constant names only spells a number. MAGIC004 (magic_numbers family, `magic004_severity`, review) reports a constant whose name is only number words or digits after filler (`TWO`, `ONE_HUNDRED`, `VALUE_100`), the evasion the change could invite. Suppressions of MAGIC001 on named constants become SUPP002 warnings, never a gate failure. A literal where a number is used is reported as before. |
| 37 | DEF005 and an entry point's exit status (2026-10-17, implemented; `docs/proposal-def005-boundaries.md`) | From under-the-gate round 3, where DEF005 on `return EXIT_UNREADABLE` in `main()` pushed agents to `raise SystemExit` or a `SystemExit` subclass. Inside a declared boundary that approves the caught type, an entry point's handler returning a module-level constant bound to a non-zero int is not a DEF005 finding. The entry point is a top-level function named `main`, one called under `if __name__ == "__main__":`, or one in `[project.scripts]` of the root pyproject.toml (read with the configuration and part of its digest). A zero, a bare literal, other functions and unapproved catches are still reported; `return None` stays a finding, and the remediation now says not to re-implement a library's validation to avoid its exception. Python only. |
| 38 | Dead code: DEAD001 and DEAD002 (2026-10-19, implemented) | From MetaList (`build_note_tree` had no callers; `highlight_search_terms`, in its 400-line cluster, was the only search highlighting, and its loss went unnoticed for a year). Opt-in (`rules.dead_code`), review, Python and JavaScript. A reachability judgment from roots (module and class bodies, registering decorators, `__all__`, dunders, JS constructors, methods of classes with a base the project does not define or nested in a function, `entry_points` globs) over call-graph edges, same-name unresolved calls and attribute uses, value references, used imports and nesting, with method families alive together. Tests are separate roots: what only they reach is DEAD002. One finding per dead head with its cluster. Judged only when the run analyzed every included file. Measured on MetaList before building: graph edges alone gave 441 heads, about half dead; value references, bound handlers, override families and getters cut that to 154 (two random samples of 30 heads: 26 and 24 dead, and the false positives found became roots). Counting any textual mention of a name as a use was rejected: it hid the motivating cluster, which tests and docs name. Off by default because the judgment needs the project's entry points. |
| 39 | Duplicated helpers: DUP001 and DUP002 (2026-10-19, implemented) | From MetaList ("rule D": twenty HTML escapers, one per dialog; some returned `''` for a non-string where the others threw). Opt-in (`rules.duplicates`), review, Python and JavaScript. Function shapes per file: a named function's body as syntax tokens with comments, layout, docstrings and its own local names set aside, and a string's mention of the file's own path or the function's own name replaced (MetaList's per-file catch-boundary labels otherwise hid exact copies). DUP001: identical shapes in two or more files, one finding per group. DUP002: same name once leading underscores and case are set aside, alike by a difflib ratio of at least `similarity` (0.85) but not identical, one finding per group with the first differing line; constructors and overrides within one class family are left out. Measured before building: the pre-merge escapers were found as an exact group and as drift (pairing by exact name missed the drift); on MetaList HEAD, outside browser test scripts, 43 DUP001 and 24 DUP002, about 21 of the DUP002 worth acting on. Judged only when the run analyzed every included file. |

### 21.2 Milestones (in order; one session each, after 0.1.0)

| Milestone | Scope | Brief's phase |
|---|---|---|
| H1 | Finding state `unknown` + per-family `fail_on_unknown`; file-role classification; schema_version bump if the report shape changes | A1, A4 |
| H2 | Verification integrity: diff-based VERIFY001 (added skips/only/focus), VERIFY002 (new blanket suppressions and ignore-list edits, including `# shockharness:` suppressions), VERIFY003 (semantic diff of protected paths against the trusted base: thresholds, disabled rules, allowlists, baselines, workflow pins, removed jobs), VERIFY004 (neutralized assertions, known patterns only); `--policy FILE` tier; `verification-integrity` skill; adversarial PR fixtures | B |
| F4 (0.5.0) | Feedback round from `docs/shockharness-suggestions-4.md` items 1-9 (decisions 12, 13, 18): DEF002 precision (decorator `.get`, checked-then-raise, discarded `pop`, grouping idiom, remediation text); `recommended` stops gating on unknown `DEF*` findings; `shockharness exceptions`; skill guidance; docs. Released as 0.5.0 before H3 starts | — |
| H3 | Syntax-level rules: STUB001, STUB002, ASSERT001, BOOL001, STATE001, IMPORT001, and EXC004 (`return`/`break`/`continue` in `finally`, decision 14); all role-scoped; conservative severities per decision 9 | D1, D4, part of E5 |
| H4 | Async lifecycle: coroutine/task and Promise ownership facts; ASYNC001-ASYNC003 with `unknown` for unresolved producers; supervisor adapters (`TaskGroup`, `Promise.all`/`allSettled`, configured frameworks); uninspected `gather(return_exceptions=True)` and `allSettled` results (decision 15); `async-lifecycle` skill | C |
| H5 | API-catalog rules: PROCESS001 (including `check=False` and a missing `check=True`, decision 15), RETRY001, SLEEP001, BATCH001, RESULT001 (`must_use` registry), TYPE001 Python half, STUB003 advisory | D2, D3, E4, E5 |
| H-TS | TypeScript adapter (`tree-sitter-typescript`, approved 2026-10-16, decision 8); every JavaScript rule on `.ts`/`.tsx`; TYPE001 TypeScript half. Done 2026-10-16 (decision 25) | — |
| H6 | INPUT001-INPUT002 bounded taint tracking with source/sink/validator catalogs; cross-site consistency rules: argument provenance for registry-issued identifiers and majority guard inference (decisions 20, 21), at review; advisory until precision is measured. Part one (INPUT001-INPUT002) done 2026-10-16 (decision 26); part two (PROV001, GUARD001) done 2026-10-16 (decision 29) | E1-E3 |
| H7 | Research (the former Milestone H): calibrated historical risk, abstraction quality, agent regression benchmarks, optional private LLM review | G |

Each milestone follows §15: a session brief, STATUS.md evidence, one commit, no threshold changes to get green, and the self-gate must pass with every new rule enabled on the tool's own code.

---

**End state:** A reusable MIT-licensed static analysis project with default-on hard correctness/explicitness invariants, separate structural/architectural complexity analytics, explainable CI gates, and agent skills designed to prevent and remediate violations without masking behavior.
