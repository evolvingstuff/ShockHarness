# Related work: tools that guard against agent shortcuts

Three tools cover the same tamper-detection layer as ShockHarness. What is said
about them here comes from their own documentation (read 2026-10-17), and goes
no further:

* **agent-code-guard** (github.com/stef-k/agent-code-guard, command `code-guard`):
  "deterministic maintainability guardrails". Its guards are file size, callable
  size, nesting, cyclomatic complexity, Markdown document and section size, and a
  runner-owned check for policy relaxation in git modes. Verdicts are
  PASS / REVIEW / FAIL. It ships a skill ("never game a metric") and documents a
  post-edit command, but does not install hooks.
* **dunnit** (pypi.org/project/dunnit, 0.3.0): "definition-of-done as code". It
  re-runs proof commands and inspects the git diff, including untracked files, for
  test gaming and stubs. It protects its own contract file, and its only escape
  hatch is a CLI flag meant for humans (`--allow`). Its Claude Code integration is
  a `Stop` hook that exits 2.
* **slopwatch** (nuget.org/packages/slopwatch.cmd, 0.4.2): a .NET tool that
  "detects LLM 'reward hacking' behaviors in code changes". Its Claude Code
  integration is a `PostToolUse` hook that exits 2, analyzing dirty files.

## Gap table

| Pattern | Detected by | ShockHarness | Decision |
|---|---|---|---|
| Skip / ignore / xfail markers added to tests | dunnit (`tamper:added-skips`), slopwatch (SW001) | VERIFY001 | covered |
| Focus markers (`.only`, `fit`, `fdescribe`) | dunnit (`tamper:focused-tests`) | VERIFY001 (skip, xfail or focus markers) | covered |
| Test files deleted, or renamed to non-test paths | dunnit (`tamper:deleted-tests`) | VERIFY004 reports emptied tests; ROLE001 in a diff reports files newly classified as tests | **to verify**: whether deleting a whole test file is reported. The behavior suite's `test_edits` signal records it either way |
| Net loss of assertions in tests | dunnit (`tamper:removed-assertions`) | VERIFY004 (an assertion the change makes unable to fail) | partial: removing an assertion outright is not the same as weakening one. **rule candidate** |
| Trivial assertions added (`assert True`) | dunnit (`tamper:trivial-assertions`) | VERIFY004 | covered |
| Deselection in test-runner config (`--ignore`, `--deselect`, `collect_ignore`, `testPathIgnorePatterns`, coverage `omit`) | dunnit (`tamper:test-config`) | VERIFY003 (loosened pytest, coverage and ESLint settings) | covered for the settings VERIFY003 reads; the list of keys is worth comparing |
| The contract file itself edited | dunnit (`tamper:protected-path`, `dod.yaml`) | VERIFY003 reports a looser configuration; a `--policy` file outside the root cannot be loosened by the repository | covered by a different mechanism |
| "Done includes a test": every configured glob matches at least one changed file | dunnit (`require.changed`) | none | **adopt (rule candidate)**: a diff-mode rule, "a change under `src/**` with no change under `tests/**`", at review |
| Diff must not be empty | dunnit (`non_empty_diff`) | none | out of scope: a task check, not a code property |
| TODO / FIXME left in changed code | dunnit (stubs) | STUB001 (configured comment markers) | covered |
| `NotImplementedError` / `todo!()` stubs | dunnit (stubs) | STUB001 | covered |
| Swallowed exceptions (`except: pass`, empty `catch {}`) | dunnit (stubs), slopwatch (SW003) | EXC001, EXC002, DEF005 | covered (ShockHarness also forbids non-empty handlers that return a fallback) |
| Suppression comments added (`# noqa`, `eslint-disable`, `@ts-ignore`) | dunnit (stubs) | VERIFY002 | covered |
| `# type: ignore` added | dunnit (stubs) | TYPE001 | covered |
| `# pragma: no cover` added | dunnit (stubs) | none | **adopt (rule candidate)**: a coverage escape, the same kind as a blanket suppression; VERIFY002's catalog could list it |
| Warning suppression in .NET (`#pragma warning disable`, `SuppressMessage`) | slopwatch (SW002) | none | out of scope (C#) |
| Arbitrary delays in test code (`Task.Delay`, `Thread.Sleep`) | slopwatch (SW004) | SLEEP001 (a fixed sleep where a condition is needed) | partial: SLEEP001 targets polling loops. Whether a bare sleep in a test is reported is **to verify** |
| Project-file slop (`NoWarn`, `TreatWarningsAsErrors=false`) | slopwatch (SW005) | VERIFY003 for the tool configs it reads | out of scope for .NET; covered in spirit for ruff, flake8, pytest, coverage, ESLint |
| Central package management bypass (`VersionOverride`) | slopwatch (SW006) | none | out of scope (.NET packaging) |
| File length | agent-code-guard (`loc`) | none (CPLX006 measures units) | declined for now: a module body is exempt on purpose |
| Callable size, nesting, cyclomatic complexity | agent-code-guard | CPLX006, CPLX003, CPLX001 | covered (advisory in both) |
| Markdown document and section size | agent-code-guard | none | out of scope |
| Policy relaxation in a diff (config or baselines loosened) | agent-code-guard (`policyRelaxation`) | VERIFY003, including baseline growth | covered |
| Fail-closed configuration (unknown keys are errors) | agent-code-guard, dunnit | the schema rejects unknown keys | covered |
| An escape hatch the agent cannot grant itself | dunnit (`--allow` as a CLI flag, not a config key) | the `--policy` file; inline suppressions are reported by VERIFY002 in a diff | covered differently; worth a sentence in the skills |
| Hint per failure, written for the agent | dunnit ("verdicts teach") | every finding's `remediation` | covered; the behavior suite will test whether the wording works |
| Blocking hook after an edit | slopwatch (`PostToolUse`, exit 2) | `shockharness hook claude-code post-edit` (4583bee) | **adopted** |
| Blocking hook before the agent stops | dunnit (`Stop`, exit 2) | none | **adopt (candidate)**: needs the diff against a base, so findings in untouched code do not block |

Rows marked **adopt** are recorded in [`ideas.md`](ideas.md) as candidates. None
is implemented here.
