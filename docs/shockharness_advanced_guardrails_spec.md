# ShockHarness — Advanced Agentic-Coding Guardrails

**Implementation specification and coding-agent handoff**  
**Status:** Design brief, reviewed 2026-10-14. Binding decisions and the milestone order are in `agent_code_integrity_project_spec.md` section 21; where this brief and the specification differ (config key names, exit code 3, profile and skill names, rule ID `DEFAULT001`), the specification wins.  
**Primary languages:** Python and JavaScript (with TypeScript support where practical)  
**License target:** MIT  
**Companion documents:** `agent_code_integrity_project_spec.md`, `shockharness_distribution_integration.md`, and the earlier complexity-analyzer implementation plan.

> **Product promise:** Constrained Agents. Safer Code.
>
> ShockHarness enforces explicit, auditable engineering invariants on code produced by humans or coding agents. It is complementary to Ruff, ESLint, type checkers, tests, and security scanners. The main value is a coherent, opinionated, independently enforceable policy that makes hidden failure modes difficult to introduce or conceal.

---

## 0. Instructions to the implementing coding agent

1. Read the companion specifications before starting. This document **adds** rules; it does not supersede the established rules for numeric literals (only `0` and `1` by default), exception-catching allowlists, implicit defaults, or complexity metrics.
2. Build a **deterministic, auditable analyzer first**. Do not make LLM judgment necessary for a hard gate.
3. Separate: **detected violation**, **suspected violation**, and **analysis inconclusive**. Never describe a heuristic finding as proved.
4. Treat “fail CI” and “warn” as policy decisions separate from measurement and evidence collection.
5. Favor narrowly scoped, explicit exceptions over hidden exceptions. Any suppression must be discoverable, attributable, and reviewable.
6. Reuse existing tools and libraries when appropriate, but don't assume their rule semantics match ShockHarness's. Check licenses and pin dependencies.
7. Implement production-grade tests, fixtures, docs, CLI responses, and schemas together. Do not mark a milestone complete because a demonstration works.
8. Do not silently weaken tests, gate thresholds, configuration, or the CI workflow to achieve a green build. Report constraints or unresolved ambiguity.
9. No unrestricted auto-fixes of contracts, error handling, or asynchronous lifecycles. A fix must preserve intended behavior, or explicitly identify behavior changes for review.
10. Scope v1 to Python and JavaScript; use language-neutral intermediate representations and versioned rule IDs to facilitate future language adapters.

### Non-negotiable existing baseline

- **MAGIC001:** In executable code, numeric literals other than `0` or `1` fail under the default strict profile; semantic exceptions belong in declared configuration/specification contexts or explicitly documented policy exceptions. Detection must also cover negative numbers, scientific notation, and compound syntax. `-1` is not permitted merely because it includes `1`. Mathematical and protocol constants should be referenced symbolically, not scattered as literals.
- **EXC001–003:** Catching exceptions is prohibited unless an approved external-system boundary and allowed failure class/operation are established. Merely catching and logging can still destroy failure transparency.
- **DEFAULT001+**: Implicit fallback/default behavior is prohibited by default; absence must not silently become a plausible value.
- **Complexity:** Cognitive, cyclomatic, NPath, nesting, dependency, and change-history metrics remain separate from binary contract-integrity gates and need calibration.
- **Meta-policy:** Rules are configurable (e.g., magic-number gate may be turned off), but modifications to policy in ordinary agent PRs can be protected from unilateral changes.

---

## 1. Product model: three complementary subsystems

| Subsystem | Purpose | Default posture |
|---|---|---|
| **Contract & failure integrity** | Preserve error information, required inputs, async failures, result semantics | Hard gates where evidence is strong |
| **Verification & policy integrity** | Prevent agents from bypassing tests, protections, approvals, or their own analyzer | Hard gates on proven prohibited modifications |
| **Structural & historical analytics** | Detect hard-to-reason-about architectures and costly change patterns | Warnings, trends, and selectively calibrated gates |

Do **not** collapse these into a single numerical “code quality” score. A severe contract-integrity violation is not compensated for by low complexity.

### Finding states

- `violation`: rule triggered with sufficient evidence under a declared analysis contract.
- `warning`: suspicious but not proved, or intentionally advisory rule.
- `unknown`: analysis could not establish the property (missing types, dynamic calls, incomplete dependency graph, unsupported syntax, ambiguous provenance).
- `pass`: analysis was applicable and completed with no matching prohibited behavior.
- `not_applicable`: excluded files/contexts or rule disabled.

A `pass` must not mean “the analyzer did not know how to analyze this.” Surface `unknown` explicitly and provide an optional project policy `fail_on_unknown` by category, not a misleading global green state.

---

## 2. New high-value rules: overview and rollout defaults

| ID | Rule | Suggested default | Requires |
|---|---|---|---|
| `ASYNC001` | Unowned async operation / discarded promise | Error when resolved confidently | Symbol resolution, async API catalog |
| `ASYNC002` | Detached task without a supervisor | Error when proved | Async lifecycle contracts |
| `ASYNC003` | Async error swallowed or transformed into success | Error | Control-flow + error mapping |
| `VERIFY001` | Added test skip / only / focus in protected tests | Error on diff | Git diff + test framework patterns |
| `VERIFY002` | New blanket lint/type/coverage suppression | Error on diff | Directive parsing |
| `VERIFY003` | Policy, workflow, or baseline weakened without approval | Error on diff | Trusted policy baseline + CI protections |
| `VERIFY004` | Assertion neutralized or replaced by tautology | Error for known patterns; warning otherwise | Test AST diff |
| `STUB001` | Known placeholder or unimplemented code in production | Error for exact known forms | AST + path classification |
| `STUB002` | Test fixtures/mocks wired into production paths | Error if dependency proven | Import resolution |
| `STUB003` | Success-shaped hardcoded placeholder | Warning unless provable from contracts | Optional semantic analysis |
| `INPUT001` | Unvalidated external data reaches typed/privileged sink | Error when traced | Dataflow + validators catalog |
| `INPUT002` | Required environment/config input implicitly optional | Error | Source catalog + policy |
| `TYPE001` | Type escape hatches | Configurable error | TypeScript/Python syntax |
| `RESULT001` | Discarding must-use operation result | Error for annotated/configured APIs | Contracts + call resolution |
| `PROCESS001` | Shell interpolation/dangerous subprocess mode | Error for proven unsafe patterns | Command parsing + taint |
| `STATE001` | Forbidden mutable globals/singletons | Configurable error | AST + binding resolution |
| `RETRY001` | Retry without explicit limit and error handling | Error for known patterns; warn otherwise | CFG + retry library contracts |
| `SLEEP001` | Sleep used as synchronization workaround | Warning by default | AST + contextual classifier |
| `ASSERT001` | Runtime correctness depends on removable Python `assert` | Error in protected production contexts | Python AST |
| `IMPORT001` | Forbidden import-time effects | Error for configured operations | Top-level call analysis |
| `BOOL001` | Positional Boolean flags obscure meaning | Configurable error | Call signature resolution |
| `BATCH001` | Failed batch elements are discarded while reporting success | Warning until fully modeled | CFG + domain contract |

**Rollout note:** Recommended default modes are *policy proposals*. Do not hard-fail using unreliable inference. Ship a `strict-agent` profile with calibrated coverage and clear uncertainty behavior.

---

## 3. Async lifecycle and failure integrity

### Rationale

An unawaited Promise or detached task can return apparent success before downstream work finishes; exceptions may become detached from the initiating request. This mirrors swallowed exceptions and defaults: causal evidence is lost.

### Python patterns

Flag when `asyncio.create_task(coro())` (or recognized equivalents) is discarded or not owned by a configured supervisor. Flag bare coroutine-producing calls when the analyzer can resolve them. An `await`, `return` of a coroutine (from a supported async context), `TaskGroup` ownership, or recognized supervisor transfer is acceptable as defined by the contract.

```python
# ASYNC002: unowned task
async def save_record(record):
    asyncio.create_task(db.write(record))
    return True

# Approved: structured lifecycle
async def save_record(record):
    async with asyncio.TaskGroup() as group:
        group.create_task(db.write(record))
```

Do not mistake a callback schedule, `TaskGroup`, or deliberate, supervised daemon operation for an orphan. Recognize Python versions supported by the target runtime; record `asyncio.TaskGroup` minimum-version compatibility.

### JavaScript patterns

```javascript
// ASYNC001 if writeRecord is known to return Promise
function saveRecord(record) {
  writeRecord(record);
  return true;
}

// Allowed: failure remains observable
async function saveRecord(record) {
  await writeRecord(record);
  return true;
}
```

Avoid claiming an arbitrary JavaScript call returns a Promise without type information, an inferred `async` declaration, a JSDoc signature, or an approved API catalog. `void promise` is **not automatically an acceptable supervisor**. A `.catch()` handler is not automatically sufficient if it swallows the error.

### Detection algorithm

1. Parse AST and resolve local/imported async declarations and configured external APIs.
2. Track Promise/coroutine/task-producing expressions through assignment, return, `await`, combinators, and recognized supervisors.
3. Mark a result `owned`, `propagated`, `awaited`, `discarded`, or `unknown`.
4. Report the shortest evidence trace with call source, owner/consumer, and failure-observation status.
5. Handle `Promise.all`, `Promise.allSettled`, `TaskGroup`, framework background-job queues, callback-based APIs, and event emitters via explicit adapters.
6. Flag `catch {}` and handlers returning success-shaped values under the existing exception/fallback policy.

### Tests

Positive/negative fixtures for `Promise.all`, returned Promises, detached `void`, Promise chains, `asyncio.gather`, `TaskGroup`, callbacks, frameworks, async generators, unresolved imports, and deliberately supervised tasks.

---

## 4. Verification integrity: agent-proofing the gates

### Threat model

The agent may accidentally or opportunistically make checks pass by weakening tests, configs, thresholds, ignore files, generated baselines, or CI. The repository cannot be its own sole authority if the agent can edit both implementation and enforcement.

### `VERIFY001` — added skips/focused tests

Inspect newly added or modified AST nodes and framework annotations/directives:

- Python: `pytest.mark.skip`, `skipif`, `xfail`, `unittest.skip`, and conditional skip calls.
- JS: `describe.skip`, `it.skip`, `test.skip`, `describe.only`, `test.only`, `xit`, `xdescribe`, framework-specific equivalents.

Distinguish **existing baseline debt** from new suppressions. Handle intentionally conditional platform skips by declared policy exception, not an opaque global bypass.

### `VERIFY002` — suppressions / disabled checks

Check newly added directives and modified ignore lists, including `# noqa`, `# type: ignore`, `# pylint: disable`, `// eslint-disable`, `// @ts-ignore`, `// @ts-nocheck`, analyzer ignore config, coverage exclusions, test-runner ignore patterns. Distinguish narrow rule-specific suppression with expiry/justification from blanket suppression.

### `VERIFY003` — policy downgrades

Protected paths may include:

- `shockharness.toml` and inherited policy profiles;
- analyzer's CI workflow or reusable workflow pin;
- `pyproject.toml`, `eslint.config.*`, `tsconfig.json`, lint/type-check/coverage configuration;
- `.github/workflows/**`, test runner configuration;
- ignore lists, allowlists, approved boundary declarations, baseline files, `.gitmodules`, dependency/version pins.

Compute a **semantic diff** where possible: a lowered threshold, disabled rule, additional allowlist entry, changed scope, removed required job, or reduced test coverage requirement. Syntactic edits are not necessarily weakening. Provide explicit, reviewable findings.

**Trust boundary:** For enforceability, store the authoritative policy in a protected repository or pinned released profile, run an independently protected CI workflow, use branch protection and required checks, and require review by CODEOWNERS for policy-sensitive changes. A local CLI cannot prevent a fully privileged actor from editing or skipping it. Do not claim otherwise.

### `VERIFY004` — neutered tests

Recognize direct `assert True`, tautologies, deleted/disabled asserts, intentionally empty tests, unconditional success branches, and substantially decreased assertions in diff. Distinguish a behavior-preserving refactor from elimination of coverage; report confidence and require human approval for semantic judgments.

### Enforcement workflow

1. Obtain trusted baseline ref from CI event or explicit `--base`.
2. Collect changed files and structural AST diffs.
3. Inspect policy-sensitive paths and determine semantic effect.
4. Emit findings and an approval request; avoid implementing an in-repo magic comment that gives agents unrestricted permission.
5. CI only accepts policy exceptions issued through a protected authorization mechanism (review + merge permissions, signed permit, centrally controlled allowlist, etc.).

### Adversarial tests

Create PR fixtures where a simulated agent: disables magic numbers, edits a reusable workflow SHA, excludes `src/`, adds `test.only`, converts an assert to tautology, changes rules through inherited config, or deletes the gate job. Required CI checks should catch relevant changes under the configured trust model.

---

## 5. Production placeholder and fake-implementation rules

**Caution:** Automatically recognizing “fake behavior” in arbitrary code is undecidable in general. Never reject normal business functions merely for returning a constant. Split proof-based checks from advisory heuristics.

### `STUB001` deterministic

Catch production occurrences of `NotImplementedError`, `raise NotImplemented`, `throw new Error('Not implemented')` if configured, `TODO`/`FIXME` markers in protected source paths, empty production function bodies (`pass`) where prohibited, and known stub decorators. Tests/docs/examples may opt into a scoped exception profile. An intentionally abstract API is not automatically a prohibited stub.

### `STUB002` production-to-mock dependency

Trace imports/references to configured `tests/`, `fixtures/`, `mock/`, `faker/` modules (accounting for aliases). Confirm dependency direction. A library that legitimately exports mock utilities should be classified explicitly.

### `STUB003` advisory

Identify suspicious success-shaped constant returns that replace missing implementations, e.g. authorization always true or network calls returning synthetic data. Mark `warning` unless a contract explicitly prohibits the output or imports prove fixture use. Include a trace and avoid pretending this is reliably decidable by regex.

### Agent remediation contract

Agent must implement the intended behavior, delete the prohibited code, or report that the expected behavior remains underspecified. Never generate a plausible fake replacement merely to pass the analyzer.

---

## 6. External input and contract validation

### Principle

Values crossing an external trust boundary must be validated before use where the contract requires it. Validity is context-specific: validation at the wrong layer or against the wrong schema doesn't help.

### Sources

Configurable source catalog: `os.environ`, `process.env`, HTTP request parameters/body, parsed JSON from untrusted providers, queue messages, user uploads, database fields under differing trust assumptions, network responses, CLI arguments.

### Sinks

Configurable sink catalog: database writes, payment/authorization decisions, shell execution, filesystem paths, redirects/URLs, deserialization, critical API calls, feature-gate decisions, typed application domain constructors.

### Validators

Recognize explicit Pydantic/dataclass/custom validators, JSON Schema/Ajv/Zod, hand-written guards, or declared contract-returning functions. Recognition must be based on known APIs or validated annotations, not on method names like `validateSomething` alone.

### Minimal interprocedural taint domain

`ExternalUnvalidated -> Validated(schema/context) -> SensitiveSink`, with `Unknown` for unresolved dynamic paths. Track return values, parameters, simple assignments, attribute/subscript access, and call edges up to a bounded depth. Require stable evidence paths in reports.

```javascript
// INPUT001: untrusted request value reaches configured privileged operation
const command = req.body.command;
runShell(command);
```

Do not make “all JSON must be validated” a universal hard gate independent of source/trust/sink context. Permit explicit trusted schemas and avoid duplicate validation when a strong validation boundary has already been established.

### Required configuration

- Source and sink inventories, optionally built-in adapters.
- Validators and schema identities.
- Severity when provenance is unresolved.
- Max propagation depth and analysis budget.

---

## 7. Type-escape hatches and ignored results

### `TYPE001`

Python: prohibit or review `Any`, `typing.cast`, `# type: ignore`, and unchecked runtime cast patterns based on configured scope; built-in `Any` and typing package types should not be blindly equated with runtime safety violations. JS/TS: `any`, `as any`, `@ts-ignore`, `@ts-nocheck`, unsafe non-null assertions, unchecked assertions. Configurable allowlists for boundaries with runtime validators. Type checking itself remains delegated to mypy/pyright/TypeScript, not reimplemented wholesale.

### `RESULT001`

Introduce a `must_use` contract registry. If a function's return value communicates an operation result, failure state, resource handle, or transaction outcome, discarded results should fail. Resolve the callee and annotate with reliable evidence. Not every function returning a value is `must_use` (logging, callbacks, fluent APIs, etc.).

```python
# RESULT001 when commit() has a configured must_use result contract
transaction.commit()
```

Do not assign semantic meaning to an unresolved call. Emit `unknown` when relevant and configurable.

---

## 8. Process execution and shell safety

### `PROCESS001`

Cover Python `subprocess.*`, `os.system`, JS `child_process.exec`, `execSync`, and configured shell wrappers. Detect `shell=True`, interpolated shell command construction, tainted commands, and direct dangerous command templates. A fixed `argv` array with no shell and validated arguments is often safer, but not automatically correct.

High-risk examples: untrusted values incorporated into shell commands; privileged or destructive commands derived from external inputs. Do not implement a naïve blacklist as the sole safety proof. Need context-aware call analysis and approved command execution contracts.

The ShockHarness mascot's `rm -rf /` example should be a documentation fixture and must **never** be executed by tests, demos, or a tool fix suggestion. Use fixtures that parse strings without executing them.

---

## 9. State, imports, retries, waits, assertions, Boolean flags, batches

### `STATE001` — mutable shared state

Detect module-global reassignment, mutable global containers, singleton mutation, and configured forbidden store access. Allow explicitly declared caches and process state where policy permits, with concurrency/lifecycle requirements. Python `global` and `nonlocal` are high-signal syntax; JS module-scoped `let` mutation and shared exported objects require binding analysis.

### `IMPORT001` — import-time effects

Flag known side-effectful calls executed at module load: opening sockets, starting threads, spawning processes, serving HTTP, destructive filesystem operations, or network requests (based on call resolution). Defer uncertain framework metaprogramming to warnings.

### `RETRY001` — retries without policy

Require, for recognized retry loops/wrappers: finite limit, explicit retryable failures, backoff or synchronization strategy where applicable, error propagation after exhaustion, and observability. Avoid hard-rejecting normal bounded algorithmic loops. The operational policy should be declared in configuration, consistent with the project's numeric literal rule.

### `SLEEP001` — arbitrary waits

Warn when `time.sleep`, `asyncio.sleep`, or JS timer waits appear to substitute for readiness/coordination. A sleep can be legitimate for pacing, rate limiting, or tests, so only hard-fail specifically prohibited contexts (e.g. newly introduced wait in a protected synchronization module) or explicitly configured APIs.

### `ASSERT001` — Python production assertions

Python optimizations can remove `assert`; forbid use as essential production input/security validation. Since static analysis cannot always know intent, a strict profile may simply forbid runtime `assert` in protected application paths while permitting test code and declared internal invariants. Prefer explicit validation and appropriate exceptions for public contract failures.

### `BOOL001` — ambiguous positional Booleans

Detect `f(x, True, False)` when a resolved parameter is a Boolean feature flag or configured API. Prefer Python keyword arguments or JS named options. Do not ban Boolean literals universally, or reinterpret every flag as a defect.

### `BATCH001` — partial failure concealment

Flag known per-item `try/catch` patterns that discard errors and return an unqualified “success” for the batch. Require either atomic failure propagation or an explicit partial-success result that reports failed items. Until cross-function result contracts are available, use advisory severity for more complex patterns.

---

## 10. Rule-definition framework

Each rule declares:

```yaml
id: ASYNC001
version: 1
languages: [python, javascript, typescript]
category: failure-integrity
confidence_model: proven_with_resolved_contract
severity_default: error
requires: [ast, symbols, async_contracts]
excludes: [generated, declared_test_fixtures]
unknown_policy_default: report
remediation_mode: guided_no_autofix
```

Required metadata: stable rule ID, semantic version, supported parser adapters, evidence obligations, applicability, false-positive examples, severity, exceptions, safe autofix classification, cost class, and reference docs.

### Configuration example (proposed, not an implemented API)

```toml
[shockharness]
profile = "strict-agent"
include = ["src/**"]
exclude = ["**/node_modules/**", "**/.venv/**", "**/dist/**"]

[rules.magic_numbers]
enabled = true
allowed_values = [0, 1]

[rules.exception_handling]
enabled = true
mode = "external-boundary-allowlist"

[rules.implicit_defaults]
enabled = true

[rules.async_unowned]
enabled = true
fail_on_unknown = false

[rules.verification_integrity]
enabled = true
protected_paths = ["shockharness.toml", ".github/workflows/**"]

[rules.fake_implementations]
enabled = true
heuristics = "warn"

[rules.external_input]
enabled = true
unresolved_provenance = "warn"

[rules.complexity]
enabled = true
mode = "advisory"
```

All config should be validated against a versioned schema, with reproducible precedence: built-in profile -> org-level immutable profile -> project config -> trusted CLI overrides. Ordinary agents should not be able to supply unchecked CLI switches that disable protected rules in CI.

### Suppression mechanism

If suppressions are supported, require rule ID, reason, location and narrow scope; optional expiry and ticket; repository policy determines who can approve. Unknown rule IDs and broad `ignore-all` should error. Inline comments cannot override centrally protected CI rules. Report active suppressions in the result.

---

## 11. Architecture: composable analysis passes

```text
shockharness/
  cli/
  config/             # versioned schemas, profile inheritance, trusted-policy resolution
  parsers/            # Python and JS/TS syntax adapters
  ir/                 # nodes, symbols, spans, calls, async values, source/sink facts
  passes/
    local_ast/
    control_flow/
    symbols/
    call_graph/
    data_flow/
    git_diff/
  rules/
    existing/          # MAGIC / EXC / DEFAULT / complexity
    async_integrity/
    verification/
    production_stubs/
    input_contracts/
    type_contracts/
    process/
    state/
    miscellaneous/
  policy/              # gate decisions, suppressions, baseline comparison
  reports/             # JSON, SARIF, terminal, PR annotations
  agent_skills/
  tests/
    unit/
    fixtures/python/
    fixtures/javascript/
    fixtures/typescript/
    integration/
    adversarial/
    performance/
```

Use language-specific adapters to generate normalized facts; preserve original source coordinates and language semantics. Do not claim complete interprocedural resolution where dynamic Python/JS dispatch makes it impossible. Bound analysis with configurable depth, time/memory budget, and report `unknown` upon exhaustion.

### Typical analysis sequence

1. Discover files with exclusions and file-role classification (production, test, config, generated, vendor, docs).
2. Parse with robust parser error reporting.
3. Run local deterministic AST checks.
4. Build import/symbol/call graph with confidence tags.
5. Run bounded CFG/dataflow/async ownership passes.
6. Inspect Git diff for verification/policy integrity.
7. Resolve suppressions and trusted policy.
8. Output evidence-rich findings with stable IDs.
9. Apply gate decisions, update baselines only via explicit trusted command.

---

## 12. CLI, output, and automation contracts

### Proposed CLI

```bash
shockharness check . --format text
shockharness check . --format json --output findings.json
shockharness gate --base origin/main --profile strict-agent
shockharness explain ASYNC001
shockharness profile show --effective
shockharness policy diff --base origin/main
shockharness baseline compare origin/main...HEAD
shockharness skills install --agent codex
shockharness skills install --agent claude
```

**Suggested exit codes:** `0` = gate passed, `1` = confirmed violations, `2` = analysis/config/tool failure, `3` = policy integrity or trusted-baseline failure. Document which failures are fail-open vs fail-closed, and prevent a consumer from treating `2` as success.

### Machine-readable finding example

```json
{
  "schema_version": "1.0",
  "rule_id": "ASYNC001",
  "rule_version": 1,
  "status": "violation",
  "confidence": "proven_with_resolved_contract",
  "severity": "error",
  "file": "src/accounts.js",
  "start_line": 18,
  "start_column": 3,
  "message": "Promise returned by persistAccount is discarded",
  "evidence": [
    {"kind": "resolved_async_call", "symbol": "persistAccount"},
    {"kind": "discarded_expression", "line": 18}
  ],
  "suggested_action": "Await, return, or transfer ownership to an approved supervisor",
  "autofix_safe": false,
  "suppression": null
}
```

Stable sorting, reproducible path normalization, SARIF compliance, and JSON schema tests are required. Include analyzer/toolchain version and effective policy digest in the report envelope.

---

## 13. Agent Skills shipped with ShockHarness

Distribute versioned Agent Skills (`SKILL.md`) as separate resources for:

1. `write-compliant-code`: teach explicit contracts and rules *before* the agent edits.
2. `fix-violations`: resolve deterministic findings without inserting substitutes or disabling policy.
3. `async-lifecycle`: how to propagate async failures and model supervisors.
4. `verification-integrity`: disallow weakening tests or enforcement without approval.
5. `complexity-refactoring`: avoid gaming per-function metrics by merely moving logic.
6. `pre-commit-check`: run changed-file checks, full required tests, and summarize unresolved findings.

### Agent repair loop

1. Read effective policy + relevant rule documentation.
2. Modify code to satisfy intended behavior and contract.
3. Run analyzer, tests, type checker, and project linters.
4. Inspect the Git diff for verification/policy changes.
5. Repeat until no confirmed violations remain (or explicitly report a blocker).
6. Report changes, commands run, results, and any unknown analysis states. Do not claim tests ran if they did not.

Include no blanket “ignore errors and continue” guidance. Never let skills overrule the independent gate.

---

## 14. Quality assurance and benchmarking

### Rule-level test matrix

For every rule/language:

- true-positive minimal AST fixture;
- true-negative near-neighbor;
- nested/syntactically unusual form;
- alias/import resolution case;
- unsatisfied or unknown symbol case;
- test/config/generated context exemption;
- permitted boundary/supervisor exception;
- intentional code that looks suspicious but is valid;
- incremental diff case;
- parser error and resilience case;
- suppression and policy-override case.

### Metrics to track

- Precision on human-labeled real code (especially hard gates).
- Recall on targeted synthetic/adversarial patterns.
- `unknown` rate by rule and language.
- CI runtime, memory, incremental reanalysis speed.
- Number of behavioral regressions introduced by suggested fixes.
- Agent task success and violation rates with/without installed skills.
- Stability under formatting, renaming, and function extraction.

Keep false-positive budgets explicit. A deterministic pattern detector can still be wrong about intent; do not assume zero false positives because the rule has an AST implementation.

### Suggested acceptance target

For initial **hard-gated** rules, aim for >= 99% precision on a representative, independently reviewed validation corpus before making them mandatory in unrelated repositories. This is a project target, **not** a claimed empirical result. When that target is infeasible, narrow the rule, default it to warning, or require explicit contracts.

---

## 15. Phased implementation plan / tickets

### Phase A — Extend the rule engine and evidence model

- [ ] A1. Add finding states (`violation`, `warning`, `unknown`, `pass`, `not_applicable`) and clear exit-code mapping.
- [ ] A2. Add rule metadata, versioning, capabilities and source-coordinate evidence.
- [ ] A3. Define the rule configuration schema, strict profile inheritance, and serialization tests.
- [ ] A4. Add file-role classification and language-specific syntax adapters.

**Done when:** every existing rule can emit the new schema and tests demonstrate `unknown` is not a false pass.

### Phase B — Verification integrity (highest priority)

- [ ] B1. Build changed-source AST/semantic diff adapter.
- [ ] B2. Implement `VERIFY001` skips/focus markers.
- [ ] B3. Implement `VERIFY002` suppressions and ignore changes.
- [ ] B4. Implement `VERIFY003` policy and workflow changes against a trusted baseline.
- [ ] B5. Implement `VERIFY004` proof-based test neutralizations.
- [ ] B6. Integrate CODEOWNERS/branch-protection documentation and a protected CI workflow demo.

**Done when:** adversarial PR fixtures cannot weaken required checks without generating a policy-integrity failure, subject to the documented trust model.

### Phase C — Async lifecycle

- [ ] C1. Python coroutine/task ownership fact extraction.
- [ ] C2. JS Promise producer/consumer fact extraction.
- [ ] C3. Approved supervisors and return/await/transfer modeling.
- [ ] C4. `ASYNC001–003` and unknown-state handling.
- [ ] C5. Cross-language fixtures and async framework adapters.

**Done when:** representative dangling operations fail, supervised operations pass, unresolved contracts are `unknown` rather than false positives.

### Phase D — Stub and static contract checks

- [ ] D1. Implement deterministic `STUB001` + `STUB002`.
- [ ] D2. Add advisory `STUB003` findings.
- [ ] D3. Implement `TYPE001`, `RESULT001`, and `ASSERT001` under strict, documented applicability.
- [ ] D4. Implement `BOOL001` and syntax-level `STATE001` checks.

**Done when:** tests cover each rule in Python/JS/TS with false-positive counterexamples.

### Phase E — Dangerous operations and external contracts

- [ ] E1. Build configurable source/sink/validator catalogs.
- [ ] E2. Implement bounded dataflow facts and evidence traces.
- [ ] E3. Implement `INPUT001–002` on supported source/sink pairs.
- [ ] E4. Implement `PROCESS001` with command-argument vs shell-string modeling.
- [ ] E5. Implement `RETRY001`, `SLEEP001`, `IMPORT001`, and `BATCH001` with conservative severities.

**Done when:** each hard violation has a reproducible data/evidence path and analysis limits are surfaced.

### Phase F — Distribution, CI, skills, evaluation

- [ ] F1. Publish versioned Python-package CLI (usable on Python/JS repos via `uvx` or CI).
- [ ] F2. Add reusable GitHub Actions integration pinned by release/SHA.
- [ ] F3. Publish machine-readable JSON/SARIF and policy diff reporting.
- [ ] F4. Ship six versioned Agent Skills and safe install/update commands.
- [ ] F5. Run an evaluation harness on public/fixture repos and an agent task study.
- [ ] F6. Create release checklist, migration notes, and sample strict-policy repositories.

**Done when:** a fresh Python-only and JS-only repository can install, configure, enforce, and upgrade the tool without submodules or copying its implementation.

### Phase G — Research-level improvements, explicitly post-v1

- [ ] G1. Interprocedural error/invalid-state propagation.
- [ ] G2. Semantic abstraction quality and complexity displacement analysis.
- [ ] G3. Calibrated historical risk prediction based on git and defects.
- [ ] G4. Agent-specific regression benchmarks and guided repair quality.

Do not block a reliable v1 on these exploratory items.

---

## 16. What not to do

- Don't claim that an LLM diagnosis is a proof of noncompliance.
- Don't penalize every `sleep`, every constant return, or every unvalidated JSON parse without meaningful context.
- Don't turn advisory detection into CI failure without precision validation.
- Don't silently exclude dynamic or unresolved code and mark the repository safe.
- Don't treat inline annotations as permission to disable centrally protected gates.
- Don't synthesize defaults, swallows, dummy results, or test skips as “fixes.”
- Don't execute destructive examples from fixtures or generated code.
- Don't replicate Ruff/ESLint/TypeScript wholesale; integrate them as complementary checks.
- Don't require code owners to edit a monolithic tool fork just to adjust rules.
- Don't change behavior or acceptance criteria merely to satisfy tooling.

---

## 17. Repository documentation and user experience

README should explain the project's **strict-by-default but configurable** philosophy and show:

1. Five-line installation and first check.
2. A violation example for magic numbers, arbitrary exception catching, implicit defaults, unowned async failure, and policy weakening.
3. Project-local configuration and override semantics.
4. Safe-agent remediation loop and official skills.
5. CI integration with a protected workflow.
6. Known limits: dynamic Python/JS, heuristic fake-implementation detection, and incomplete soundness.
7. Versioning/migration compatibility policy and supported language versions.

Keep documentation examples deterministic. Do not promise complete bug prevention or formal verification.

---

## 18. Questions to resolve with repository evidence (do not block Phase A)

- Which Python/Node/TypeScript versions and parsers are officially supported?
- Which async frameworks and libraries warrant built-in supervisory contracts?
- Where do consuming projects draw boundaries between production, test, configuration, fixtures, and generated artifacts?
- Which validators, shells, CI platforms, and source/sink patterns need first-class support?
- Is there an organization-level policy repository and protected reviewer group?
- Should `unknown` fail only for specific critical APIs, or for entire critical modules?
- How will authorization and expiry for rule exceptions be audited?
- Which historical repos are available for prospective precision validation?

Document defaults, add explicit schema decisions, and proceed with narrow provable behaviors first.

---

## 19. Copy-paste coding-agent kickoff prompt

> Implement the **ShockHarness Advanced Agentic-Coding Guardrails** specification in this repository. First inspect the existing architecture and the companion ShockHarness specs, then prepare a short mapping from existing components to the new modules. Begin with **Phase A**, then **Phase B**. Build parser/AST and Git-diff-based, evidence-rich enforcement with tests and machine-readable finding states. Keep the existing strict invariants: only numeric literals 0 and 1 in executable code by default, allowlisted external-boundary exception handling, and no implicit defaults. Separate deterministic hard violations from heuristics and unknown results. Never bypass checks or weaken tests to achieve compliance. For each completed ticket, report changed files, commands/tests executed, observed results, remaining limitations, and the next ticket. Do not claim future phases are implemented until their acceptance criteria pass. Keep all new rules independently configurable, while supporting trusted, externally enforced protection of policy changes in CI.

---

## 20. Completion criteria for this expansion

This specification is considered implemented when:

- The existing code-integrity rules remain backward compatible or have documented, tested migrations.
- The new deterministic rules exhibit high precision on representative fixtures and real-code validation.
- Warnings and unknown analysis states are surfaced honestly rather than silently ignored.
- Protected CI verifies that policy changes require authorized review.
- Python/JavaScript projects can consume a versioned CLI and shared rule profiles.
- Agent Skills teach compliant patterns but remain subordinate to independent enforcement.
- Every finding includes actionable evidence, and the documentation describes false-positive controls and trust limits.

**End of specification.**
