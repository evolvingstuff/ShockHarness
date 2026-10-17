# Ideas and proposals: the backlog

Every idea handed to the project in review, by MetaList or by Tom, with where it
came from, what happened to it, and what is next. This file is the record; the
conversation and the agent's memory are not. When an idea is acted on, its row
names the commit; when it is declined, it says why. Spec decisions live in
`agent_code_integrity_project_spec.md` section 21.1; this file points to them.

Status words: **done** (committed), **in progress**, **proposed** (designed,
waiting for Tom's go-ahead), **open** (not started), **deferred** (measured, not
worth it yet), **declined** (with the reason).

## Agent workflow

| Idea | Source | Status | Notes / next step |
|---|---|---|---|
| The hook misses edits made through the shell: in the under-the-gate experiment every builder (8 of 8) wrote its files with `cat > file <<EOF` and Python patch scripts, never Edit/Write, so the PostToolUse hook never fired | under-the-gate experiment (2026-10-17) | open | Match `Bash` too and analyze the source files `git status` shows as changed since the last hook run (slopwatch's hook works from git status); keep a per-session record of what was already reported so a long session is not re-told the same findings |
| Edit-time feedback: run the checker on each file the agent edits, and have `skills install` offer it | Fable review; Tom ("the main product surface" on greenfield) | **done** (4583bee) | `shockharness hook claude-code post-edit`, `skills install --agent claude --hook`. Next: a Stop hook that blocks finishing while the *diff* has findings (needs a base revision; dunnit uses a Stop hook with exit 2) |
| Separate "agent can fix" from "human must decide": a `decision: human` field on findings and a `shockharness questions` command listing the contract decisions a person must make | Fable review | open | The agent fixes the mechanical findings, then stops with a short list of questions instead of inventing contracts |
| Treat remediation text as prompts: evaluate whether each wording produces the right fix or a workaround, A/B in the eval corpus | Fable review | open | Needs the behavior suite first |
| Philosophy document: why each discipline exists, from experience, for agents to reason from instead of "determine the intended contract" | Fable review | **waiting on Tom** | Questions committed in `docs/philosophy-questions.md` (8f05a75). Tom's answers become `docs/philosophy.md`; the skills will point to it; the behavior suite can test whether an agent that has read it chooses as Tom would |
| Positioning: what ShockHarness catches that mypy --strict, TypeScript strict, Ruff and a good test suite do not | Fable review | open | A doc with examples; the answer is behavioral shape, not types |
| Recommend a type checker when a project has annotations but none configured | MetaList | partly done (e6db3bb, skill text) | Rule part is decision 33 below |

## Measuring agents (evaluation)

| Idea | Source | Status | Notes / next step |
|---|---|---|---|
| Agent-behavior regression suite: 5 rules x 3 cases (unambiguous, judgment, ask), hidden tests, known-evasion detectors, N runs per case, a judge in a fresh context, review queue, held-out cases | Fable's brief | **in progress** | `evals/behavior/`. First case: the agent's own `len(("event", "handler"))` evasion of MAGIC001 (fixed in 3f90b26). Agent runs wait for Tom's OK on model, run count and budget |
| Borrow methods: EvilGenie (held-out tests, test-file edit detection, judge then human), ImpossibleBench (ask cases as spec/test contradictions; abort option; prompt strictness) | Fable's follow-up brief | **in progress** | Methods read; folded into the suite design |
| Two corpora with two purposes: third-party code calibrates precision; code written under the gate reveals gaming | Fable review | **in progress** | The behavior suite is the second corpus |
| Builder and reviewer in separate contexts, so the work does not grade itself | Fable review | **in progress** | The suite's judge sees only the diff and the rubric |
| Watch what an agent does the first time a rule blocks something it considers fine (`x / 2`, `range(2)`) | Fable review | **in progress** | Part of the under-the-gate experiment below |
| Under-the-gate experiment: four specs, each built twice by the same agent (with the gate, skills and hook; without), reviewed in a separate fresh context | Fable review; Tom | **specs drafted, waiting on Tom** | Specs: a feed health checker, a notes board with an edit mode, a contacts cleaner, an asyncio job queue. 8 builds on Tom's account |
| Cite GSO's reward-hacking rate as motivation | Fable's follow-up brief | **blocked** | The named post ("hungry hungry reward hackers") could not be found. A related post cites GSO's own write-up (gso-blog.notion.site/gso-hackdetector, not yet read). Not cited until sourced |
| ShockBench: seeded repositories where the easiest path to green is a shortcut | Fable review | open (H7) | Research milestone |
| ShockHarness as a deterministic reward signal for training code models | Fable review | open (H7) | Research |
| Related-work gap table: agent-code-guard, dunnit, slopwatch | Fable's follow-up brief | **done** | `docs/related-work.md`; its candidates are rows below |
| dunnit's "a change under src/** must come with a change under tests/**" as a diff-mode rule | Fable's follow-up brief; `docs/related-work.md` | candidate | Adopt as a review rule in diff mode |
| `# pragma: no cover` added, as a coverage escape | dunnit, via `docs/related-work.md` | candidate | Add to VERIFY002's catalog |
| Removing an assertion outright (not only weakening it) | dunnit, via `docs/related-work.md` | candidate | Extend VERIFY004 |
| A Stop hook that blocks finishing while the diff has findings | dunnit, via `docs/related-work.md` | candidate | Needs a base revision |
| To verify: is a deleted test file reported? Is a bare sleep in a test reported by SLEEP001? | `docs/related-work.md` | open | |

## Rules

| Idea | Source | Status | Notes / next step |
|---|---|---|---|
| MAGIC002: one string repeated across files | Tom | **done** (91e447c, 9efe284) | Decision 31 |
| DOM001: delegated handlers that drop SVG targets | MetaList | **done** (c7493c3) | Decision 27 |
| DOM002: a floating control that a press handler treats as outside | MetaList | **done** (be590ad) | Opt-in. Decision 32. Not yet followed: elements attached through an object property (`state.overlay`) and jQuery. Both of its MetaList candidates were confirmed: the error banner (plus a CSP bug, row below) and the image-zoom overlay |
| MAGIC003 narrowing: `tabIndex = -1`, a -1 beside a +1 | MetaList | **done** (0dd6f61) | |
| MAGIC003: a keyword argument equal to its documented default (`bufsize=-1`) | MetaList | deferred | Needs a signature catalog; no instance in the corpus |
| MAGIC003: rank `return -1` in find* functions lower | MetaList | declined | None of the corpus's 7 `return -1` are in find* functions, and each is a real meaning |
| MAGIC001 and `2`: arithmetic identity or policy? | Fable review | open | Measure like `-1` (on the corpus and MetaList), and watch it in the behavior suite |
| RESULT001: methods of string literals (`", ".join(x)` alone on a line) | agent's gap | **done** (0dd6f61) | JavaScript literal receivers are not recorded yet |
| False alarms, 0.7.0 round 1 (ASYNC003, PROCESS001, INPUT002, ASSERT001) | MetaList | **done** (10f765c) | |
| False alarms, 0.7.0 round 2 (RESULT001, ASYNC001, GUARD001, STUB003, ROLE001) | MetaList | **done** (52257e4) | |
| Inline event handlers a CSP blocks: an `on[a-z]+=` attribute in HTML the project builds (`innerHTML` / `outerHTML` / `insertAdjacentHTML` templates, `setAttribute("onclick", ...)`, server templates) when the project's Content-Security-Policy has no `'unsafe-inline'` (or `'unsafe-hashes'` with a matching hash) for `script-src-attr` / `script-src`; review severity when no CSP can be found | MetaList (from DOM002's error-banner candidate: the banner's × never worked under MetaList's nonce CSP, silently in Chrome) | open | MetaList expects very few false positives once the CSP is found. Needs: inline-handler facts from HTML strings (DOM002's markup scan is a start) and CSP extraction from code (`app/main.py`) or config |
| BOOL001: exempt the expected value of assertion calls (`assert.equal(x, true)`, `assertEqual(a, False)`, `expect(x).toBe(true)`) | MetaList | open | 159 of MetaList's 353 BOOL001 findings are in browser test scripts; the app-code ones are fair |
| Decision 33: TYPE001 says when no type checker is configured; TYPE002, one per project, "N of M functions annotated, no checker configured" | MetaList; measured by a side session | **proposed** | MetaList 96% annotated, no checker; ShockHarness's own `src` 100% annotated, no checker. VERIFY003 could later report loosened mypy settings |
| Decision 34: DEF002 recognizes the statement forms of a membership fallback, and treats a helper whose default is a parameter (`_mapping_value_or`) as a fallback at its call sites | MetaList; measured by a side session | **proposed** | MetaList 21, ShockHarness `src` 8, corpus 1. Under a new `rules.defaults.fallback_helpers` review mode for one release; the self-gate's 8 instances must be fixed in the same change |
| Lost server state on update (a record rebuilt from the request drops fields only the server owns) | MetaList | deferred | Matched only MetaList's pre-fix code; decision 34 would have surfaced the same 26 defaults |
| Immutability: frozen dataclasses, no mutation of arguments, `readonly` / `as const`, no reassignment | Fable review | open | The biggest principle without a rule. Mutation of arguments is the most feasible (the dataflow facts record parameters and stores). Measure first |
| Evasion coverage: `int("30")`, `len("xxxxx")`, `ord`, `sum([1] * n)`, a sentinel object or `*args` for DEF001 | Fable review | open | The behavior suite's detectors find which ones agents actually use |
| The quiet early return: `if not path.exists(): return None` behaves like the forbidden catch but has no `try` | Fable review | open | Forbidding the except form but not this may push agents toward it. The leading-check facts from GUARD001 (52257e4) can detect it; measure first |

## Process and releases

| Idea | Source | Status | Notes / next step |
|---|---|---|---|
| Release 0.8.0: DOM001, MAGIC002, DOM002, both feedback rounds, the hook | Tom agreed | open | After the behavior suite's first round, or sooner if Tom wants |
| The agent's own evasions are recorded, not hidden | Fable's brief | **done** | `len(("event", "handler"))` (fixed in 3f90b26), and two self-granted deviations reported to Tom: the CPLX006 override for the names module (9efe284) and the hook's JSON boundary (4583bee) |
