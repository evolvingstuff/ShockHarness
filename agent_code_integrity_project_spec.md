# Agent-Ready Specification: Explicit-Code Integrity and Complexity Analyzer

**Status:** Implementation blueprint, v1.1 (v1.0 reviewed and decisions resolved; see §19)  
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

Use `pyproject.toml` under `[tool.shockharness]` OR a `.shockharness.toml` dedicated file, with a documented priority order: CLI explicit config > dedicated file > pyproject > bundled defaults. Multiple config sources at a single tier are errors rather than silently combined. No implicit environment fallback. Support `--print-effective-config` with origins and `config validate`.

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
- A declaration like `ITERATIONS = 2` **is still a numeric literal** and should be flagged in executable source unless the file is explicitly a configuration/specification location or a narrow documented suppression is granted. A named constant is not automatically justified.
- A reference to `math.pi` is permitted; `3.14` is not. A standard-library named constant conveys meaning without copying the numeric literal.
- A well-defined protocol numeric constant should be represented in designated spec/configuration source or through a documented suppression, not granted a universal number exemption.

**Directive to remediation agent:** For a numeric violation, determine the business/mathematical/protocol reason for the value. Prefer a required, validated configuration parameter for variable policy; a named authoritative constant for invariant math/specification; never silently move it into a meaningless constant or add an implicit fallback.

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
shockharness config validate
shockharness config effective
shockharness scan src/ --format text
shockharness scan src/ --format json --output report.json
shockharness scan src/ --format sarif --output report.sarif
shockharness baseline create src/ --output .shockharness-baseline.json
shockharness diff --base main --head HEAD
shockharness gate --base main --head HEAD --format text
shockharness rules list
shockharness rules explain MAGIC001
shockharness skills install --agent codex
```

Commands are **requested implementation**, not extant tools. `init` writes a config but never overwrites an existing config without explicit confirmation; CI must be noninteractive. `baseline create` requires explicit user invocation. Diff works with changed files and stable baseline comparison; perform whole graph analysis as needed to avoid missing cross-file effects. Respect `.gitignore` only if configured; explicit includes/excludes take precedence.

## 12. Agent skills and integration

Bundle four vendor-neutral skills with YAML frontmatter (name, description) and a `SKILL.md` in each subdirectory:

1. `write-compliant-code`: require clear contracts, no arbitrary catches/defaults/non-0/1 numeric literals; distinguish data/config/spec and source.
2. `fix-violations`: run analyzer; for each finding determine intended contract, add characterization tests, modify code, rerun suite and analyzer; never blindly delete `try/except` or replace `get` with indexing without contract review.
3. `refactor-complexity`: address repeated cognitive work and coupling rather than metric gaming; require before/after call graph and behavior tests.
4. `pre-commit-review`: run diff gate, show unsupported analysis and suppressions, tests, and remaining warnings; never claim passes without running.

Skills contain concrete examples of compliant and noncompliant Python/JS, exact CLI invocations, corrective workflow, and a checklist. `skills install` should support user-specified target directory and documented Codex/Claude adapters; never modify agent config without explicit invocation, and never overwrite user-customized skill files silently. No mandatory MCP server in v1.

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

### Milestone E — Complexity + graph

- Per-function cyclomatic/cognitive/nesting, approximate NPath; call graph with unresolved-edge reports; coupling and cycles.
- **Done when:** validated fixtures agree with documented counting conventions; don't state unsupported resolutions as exact.

### Milestone F — Git + gates + reports

- Baseline, diff, policy evaluation; file churn, hotspots and co-change; JSON + SARIF; deterministic ordering and stable fingerprints.
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
| 9 | Dependencies | `tree-sitter` + `tree-sitter-javascript` only at runtime; stdlib `argparse`/`tomllib`; `uv` for environments | §3 |
| 10 | JS parse errors | Any tree-sitter `ERROR`/`MISSING` node is a parse failure | §3 |
| 11 | CI matrix | GitHub Actions on ubuntu, macos, windows × Python 3.11–3.14 | §14 Milestone A |

---

**End state:** A reusable MIT-licensed static analysis project with default-on hard correctness/explicitness invariants, separate structural/architectural complexity analytics, explainable CI gates, and agent skills designed to prevent and remediate violations without masking behavior.
