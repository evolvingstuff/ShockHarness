# ShockHarness: fourth batch, from agents using 0.3.0/0.4.0 (planned 0.5.0)

## Context

Coding agents running ShockHarness in the maintainer's MetaList project left
notes, which the maintainer exported from MetaList as an HTML page; the
substance is condensed in the appendix. One agent had worked through about 100 `DEF002`
findings and a `DEF003` pass, and ranked its suggestions by how much noise each
would remove. The lead session reproduced each claim against 0.4.0 on
2026-10-16 before writing this brief; the observations below say what 0.4.0
actually does.

Decisions are recorded in the specification (section 21.1, decisions 12-18,
and the milestone table in 21.2). Items 1-9 make up the 0.5.0 feedback round,
which runs before Milestone H3. Section 10 lists what goes elsewhere in the
plan. Each item has acceptance criteria. Add a test for every criterion, and
document every new option in `docs/configuration.md` and `docs/rules.md`.
Verdicts must not change except where an item says so; the round's STATUS
entry lists each intended difference against 0.4.0.

## 1. `.get(...)` used as a decorator

**Observation.** `@router.get("/notes/{id}")` and `@app.get(...)` produce a
`DEF002` review finding (implicit `None`, receiver not established). The
string argument looks like a mapping key. One project had 30 of these, all
false.

**Change.** A `.get(...)` call that is itself a decorator expression (an entry
of a function or class `decorator_list`) is not a mapping lookup and produces
no `DEF002` finding. This covers any arity: `@cache.get(key, default)` is not a
fallback either. A `.get(...)` nested *inside* a decorator's arguments is
judged as usual.

**Acceptance.** `@router.get("/x")`, `@app.get("/x", status_code=OK)` and
`@client.get("/x")` on a function or method produce nothing.
`@retry(times=config.get("retries", DEFAULT))` still reports the inner `.get`.
`value = router.get("/x")` as a statement is unchanged.

## 2. A lookup that is checked and raises

**Observation.** The agent rewrote many lookups that were already explicit:

```python
record = self._note_map.get(note_id)
if record is None:
    raise KeyError(note_id)

handler = getattr(obj, "handle", None)
if not callable(handler):
    raise TypeError("no handler")
```

Every `None` path raises, so nothing is substituted. 0.4.0 reports the
`getattr` form as a `DEF002` error. It reports the implicit-`None` form as a
review finding when the receiver is a known mapping.

**Change.** A lookup whose fallback is `None` (implicit `m.get(k)`,
`m.get(k, None)`, `getattr(o, a, None)`, `m.pop(k, None)` read into a name) is
not reported when all of these hold:

- it is the whole right-hand side of an assignment to a plain name `x`;
- the *next* statement in the same block is an `if` whose test is one of
  `x is None`, `not x`, `not callable(x)`, `not isinstance(x, ...)`, or an
  `or` of such tests where the first one is about `x`;
- the `if` body consists only of a `raise` (no `else`, no `elif`).

A non-`None` fallback is still reported, because the check cannot make the
substitution disappear. JavaScript is unchanged in this round. Its `DEF002`
forms (`?? v`, destructuring defaults) carry a non-`None` value by
construction.

**Acceptance.** Both snippets above produce nothing. The same with a statement
between the assignment and the `if`, an `else` branch, a body that `return`s
instead of raising, or a fallback of `{}` is reported as in 0.4.0.
`x = m.get(k); if x is None or x.closed: raise ...` produces nothing.

## 3. A removal whose result is discarded

**Observation.** `d.pop(k, None)` used as an expression statement means
"remove it if it is there". 0.4.0 reports it as a `DEF002` error, with status
`unknown` when the receiver is not established. About 13 findings in one
session were this. For some the right answer was `del d[k]` (the key is always
present, a real catch); for others absence was legitimate.

**Change.** An expression statement `m.pop(k, None)` (Python) is a `DEF002`
finding of kind `discarded_removal`, at severity `review` in every profile.
Its message asks the question directly: if the key is always present, use
`del m[k]`; if absence is normal, say so with an explicit `if k in m:`. Its
status follows receiver confidence as before. A `pop` whose result is used is
unchanged. So is a discarded `pop` with a non-`None` fallback, because that
fallback is pointless and suspicious.

**Acceptance.** `cache.pop(key, None)` as a statement: one review finding,
`kind = discarded_removal`, never gating. `value = cache.pop(key, None)`:
unchanged (or item 2 applies). `cache.pop(key, 0)` as a statement: unchanged.

## 4. The grouping idiom

**Observation.** `groups.setdefault(k, set()).add(v)` is reported as a
`DEF002` error. On an accumulator it is the usual way to group values, not a
fallback read.

**Change.** `m.setdefault(k, F)` is not reported when F is an empty container
(`[]`, `{}`, `set()`, `list()`, `dict()`, `tuple()`, `frozenset()`), the call's
result is immediately the receiver of a method call or a subscript assignment,
and that call or assignment is an expression statement (`.append`, `.add`,
`.extend`, `.update`, `.insert`, `.setdefault`, `[x] = y`). A non-empty
fallback, or a result that is read rather than mutated, is reported as before.

**Acceptance.** `groups.setdefault(k, set()).add(v)`,
`index.setdefault(k, []).append(v)` and `tree.setdefault(k, {})[child] = node`
produce nothing. `n = counts.setdefault(k, 0)`,
`groups.setdefault(k, {"a"}).add(v)` and `x = groups.setdefault(k, []).copy()`
are reported as in 0.4.0.

## 5. Remediation text for "absence is normal"

**Observation.** The remediation says to index the mapping or validate at the
boundary. The fix the agent made most often was neither. Absence was a normal
state (an empty view has no root entry; a tag with no notes has no posting),
so it wrote an explicit `if k in m:` with a comment, or a small named helper
such as `_posting_or_empty`. Agents that read only the current text force an
index where absence is real, and that introduces a crash.

**Change.** `DEF002`'s remediation (finding message, `rules explain DEF002`,
`docs/rules.md`, and the `fix-violations` skill) names three fixes in this
order:

1. the key must exist: index it (`m[k]`) and let a missing key fail loudly, or
   validate once at the boundary;
2. absence is a normal state: say so with an explicit `if k in m:` branch and a
   comment, or a named helper whose name says what absence means;
3. the value comes from outside (configuration, request): validate it where it
   enters.

**Acceptance.** `rules explain DEF002` prints the three cases. The skill test
that checks rule IDs and examples still passes. The `fix-violations` skill has
a compliant example of case 2 in Python and JavaScript.

## 6. Unknown findings in the `recommended` profile

**Observation.** The agent asked that "only exact findings fail the gate".
Since 0.4.0, a finding the rule could not establish has status `unknown`.
`rules.defaults.fail_on_unknown` defaults to `true` in every profile, so
`cache.pop(key, None)` on a receiver the analyzer cannot type fails the gate.

**Change.** Spec 21.1 decision 13. `strict` is unchanged: unknown `DEF*`
findings gate, because the strict profile fails closed. `recommended` sets
`rules.defaults.fail_on_unknown = false`, so unknown `DEF*` findings are
reported with their severity but do not gate. `minimal` already caps `DEF*` at
`review`. The setting below `strict` is a policy deviation like every other
profile difference. `rules.exceptions.fail_on_unknown` stays `true` in all
profiles: an unresolved exception type is a catch the analyzer cannot vouch
for.

**Acceptance.** Under `recommended`, `cache.pop(key, None)` on an
unestablished receiver is reported with `status = unknown` and the gate
passes. Under `strict` the same code fails, exactly as 0.4.0. `config
validate --profile recommended` lists the deviation. The golden-fixture
regression test pins the changed `recommended` exit code and nothing else.

## 7. Exceptions that people can inspect

**Observation.** "Places where exceptions are being made should be
inspectable by humans." Every piece exists: the policy deviations, each
suppression with its reason, boundaries, overrides, baselines. But they are
spread over the report's `config.deviations`, per-finding `suppression`
objects, `rules_disabled` per file, and baseline files.

**Change.** A new command, `shockharness exceptions [PATHS...] [--root R]
[--config F] [--policy F] [--profile P] [--baseline FILE] [--format
text|json]`, lists in one place every exception the configuration and the
code make:

- inline suppressions: path, line, rule IDs, reason, and whether each one is
  used (it suppresses a finding) or unused (SUPP002);
- configuration: the profile when below `strict`, disabled families and rules,
  severity caps, `fail_on_unknown = false` entries, allowed values, exception
  boundaries (with reasons), transparent guards, capture managers,
  `[[overrides]]` (with reasons), allowed skip reasons, and `exclude`
  patterns, each with the configuration file and line it comes from;
- `--policy` attempts, if a policy file is given;
- the baseline given with `--baseline`: entry count per rule and per file.

It runs the analysis (cached) to know which suppressions are used. It exits
`0` (or `2` on invalid configuration or invocation); it never gates. Text
output groups the list by kind. JSON (`schemas/exceptions-v1.schema.json`,
`report_kind = "exceptions"`) is byte-identical across runs. The README and
the `pre-commit-review` skill mention it as the reviewer's view.

**Acceptance.** On a fixture with two inline suppressions (one unused), one
boundary, one override and a baseline: every item appears once, with its
reason and location. The JSON validates against the new schema. Two runs are
byte-identical. Exit `0`. An invalid configuration exits `2`.

## 8. Skill guidance

**Observation.** Two notes concern how agents work rather than what the tool
reports:

- "Anytime you run into a bug, hypothesize a rule (better) or heuristic that
  ShockHarness could use that would have prevented it."
- "Encourage validating inputs to functions and validating outputs from
  functions within each function."

**Change.**

- `fix-violations` and `pre-commit-review` gain a short "Propose a rule"
  step. When a bug is found that ShockHarness did not report, write down the
  pattern, why it is a bug, the proposed rule (a syntactic rule preferred over
  a heuristic), the likely false positives, and a minimal triggering example.
  The note goes wherever the project collects tooling feedback. The skill never
  tells the agent to edit the analyzer or its configuration.
- `write-compliant-code` extends "required, validated inputs" with outputs.
  Where a function's contract promises something about its result (non-empty,
  sorted, within a range, a known key set), check it before returning and raise
  on violation. Also: do not wrap the check in a fallback. Python and
  JavaScript examples.
- The README's "Adopting ShockHarness" section stays byte-identical across the
  README and every `SKILL.md` (tested).

**Acceptance.** The skill tests pass (frontmatter, rule IDs, adoption-section
identity). The eval corpus is unchanged or extended, never weakened.

## 9. Documentation

**Observation.** The agents asked about cases the documentation does not
answer.

**Change.**

- **Python 3.10 projects** (`docs/integration.md`). ShockHarness runs on
  Python 3.11+ (decision 17) and reads 3.10 code. Run the gate as its own CI
  job on 3.12, not on every leg of a 3.10-3.13 matrix: static analysis does not
  depend on the interpreter the tests run on. Show the job.
- **Empty trees** (`docs/limitations.md`, `docs/configuration.md`). `check` on
  a tree with no analyzable files exits `0` with `0 file(s)`. Say so, and
  explain how to make that a failure if a project wants it: the
  `unsupported_sources` setting covers files that are present but unsupported,
  not the absence of files.
- **What ShockHarness covers, and what is planned** (`docs/limitations.md`),
  for projects that layer their own checker:
  - covered today: `contextlib.suppress` (as a catch that swallows), JS
    `.catch(...)` handlers (EXC001/EXC002/DEF005);
  - planned: `return`/`break`/`continue` in `finally` (EXC004, H3),
    `subprocess` without `check=True` (PROCESS001, H5),
    `asyncio.gather(..., return_exceptions=True)` and `Promise.allSettled`
    whose results are not inspected (H4), TypeScript (H-TS).

**Acceptance.** The three passages exist and are linked from the README's
documentation list.

## 10. Routed elsewhere

| Suggestion | Where | Decision |
|---|---|---|
| `return` in `finally` swallows the exception | H3, new rule `EXC004` | Python `return`/`break`/`continue` directly in a `finally` block, JavaScript `return`/`break`/`continue` in `finally`; exact, syntax only; `warning` until measured, per decision 9 (decision 14) |
| `subprocess.run(..., check=False)` | H5, `PROCESS001` | Already planned. The brief names `check=False` and a missing `check=` explicitly (decision 15) |
| `gather(return_exceptions=True)`, `Promise.allSettled` | H4 | Results that are never inspected for exceptions or rejected entries are findings. Supervisor adapters already list these APIs (decision 15) |
| Reading `__qualname__`/`__name__` on a value of unknown type | Recorded, unscheduled | Needs type inference ShockHarness does not have. A syntactic version (no `callable`/`isinstance`/`inspect` check before the read) would be noisy. Candidate for an advisory `TYPE` rule after H5 (decision 16) |
| TypeScript | H-TS, approved | `tree-sitter-typescript` is approved as a runtime dependency for H-TS, pinned like `tree-sitter-javascript` (decision 8, updated) |
| Python 3.10 support | Declined | `tomllib` is 3.11+, and the runtime stays stdlib-only plus tree-sitter. Section 9 documents the separate CI job instead (decision 17) |
| "Would ShockHarness absolve this?" | — | The note's context did not survive the export, so there is nothing to act on |

## What worked well, and stays

The agent called out: the per-file cache keeping re-runs fast; the Python API
(`analyze_paths`, findings with span, scope and evidence) being easy to script
against; the inline suppression syntax with a required reason; and the
findings that exposed hidden invariant failures (silent skips in a search
index, `.get` with a fallback on maps that hold every note) as the valuable
ones. Items 2-4 aim to make those stand out by removing the noise around
them.

## Appendix: the notes, condensed

1. Proposed rule: reading `__qualname__` or `__name__` on a value whose type is
   not known (a framework field typed `Any` that held either a function or an
   object). It would need type inference to stay quiet.
2. Places where exceptions are being made should be inspectable by humans.
3. "Would ShockHarness absolve this?" Plus: add to the agent instructions that
   on every bug, the agent should hypothesize a rule (preferred) or heuristic
   that would have prevented it.
4. From about 100 `DEF002` findings and a `DEF003` pass, in order of noise
   removed: route decorators as lookups (30 false findings); let only exact
   findings fail the gate; recognize a fetch that is checked and raises;
   treat a discarded `pop(k, None)` differently from a read (about 13
   findings); exempt `setdefault(k, set()).add(v)`; describe the "absence is
   normal" fix in the remediation; what worked well (above); Python 3.10
   support would let projects gate on every CI leg.
5. Encourage validating inputs and outputs within each function.
6. Layering notes: TypeScript is not parsed (`unsupported_sources = "fail"`
   makes it loud); unconfirmed coverage of `check=False`,
   `return_exceptions=True`, `Promise.allSettled`, `return` in `finally`, JS
   `.catch`; `contextlib.suppress` is covered; behavior on an empty tree not
   tested.
