# Under-the-gate experiment: round 1 (2026-10-17)

Round 2 (Opus 5.5, three runs per spec and variant, the hook covering shell edits) is in
`RESULTS-round2.md`; round 3 (decision 35: tests exempt, setup committed) in
`RESULTS-round3.md`.

**Question.** What does a coding agent build when ShockHarness blocks it, compared
with the same agent building the same spec without the gate? Does it comply as
intended, name things meaningfully, or evade? And does the gate change the
*structure* of what gets built?

**Setup.**
* Four specs (`specs/`), each built twice, so 8 builds.
* Builder: Claude Code 2.0.55 headless with `--model claude-sonnet-5-5`, one run per
  spec and variant.
  * The planned default model did not exist. Claude Code 1.0.65 defaults to a retired
    model, and Opus 5.5 needs Claude Code 2.1.280 or newer.
  * A first round on 1.0.65 crashed in 3 of the 4 gated builds (below).
* Gated builds had a strict `.shockharness.toml`, the skills and the edit-time hook, and
  had to reach `gate: PASS`. Ungated builds only had to make their tests pass.
* Builders saw only `SPEC.md`, plus the ShockHarness files in gated builds.
* Each spec was reviewed by a fresh `claude -p`. The reviewer saw both final trees, the
  mechanical results (`analyze.py`) and the hook blocks, but no builder transcript.
* Evidence is in `round1/`: the builds' sources, `mechanical.json` and the four reviews.
* Every evasion quoted below was checked against the code by the orchestrator.
* Cost was about $1.75 for the builds and less for the reviews. Builds took 36–108
  seconds and 3–9 turns each.

**Caveats.**
* One run per spec and variant, so this is an anecdote, not a distribution.
* Sonnet, not Opus.
* The builders were quick and short.
* The reviewers come from the same model family as the builders.
* The edit-time hook never fired (see finding 1), so this round measures the skills plus
  a final self-check, not edit-time feedback.

## Findings

### 1. The edit-time hook never fired: every builder edited through the shell

All 8 builders, gated and ungated alike, created and changed files with `cat > file
<<'EOF'` and small Python patch scripts run through Bash. None used Edit or Write.
The hook listens on `PostToolUse` for `Edit|Write|MultiEdit`, so it never ran.

The gated builders were steered by the skills and by running `shockharness check .`
themselves, 8 to 25 times each. One gated builder read `.claude/settings.json` (and so
saw the hook) before writing through Bash. The ungated builders behaved the same way,
which points to habit rather than avoidance.

**Consequence:** the hook must also cover shell commands. It should match `Bash` and
check the source files `git status` shows as changed since its last run, which is how
slopwatch's hook works. It should also log that it ran, so "clean" and "never ran" can
be told apart; all four reviewers asked for this.

### 2. The gate removed the silent-failure class the specs cared about

Findings under the same strict configuration:

| Spec | Ungated | Gated |
|---|---|---|
| feedcheck | 66 | 13 |
| noteboard | 18 | 1 |
| contactclean | 36 | 5 |
| jobqueue | 56 | 1 |

The gated counts include catches that the gated builders declared as boundaries in their
own configuration; the comparison replaces that configuration.

The gated builds had no parameter defaults (DEF001 found 1 to 15 in each ungated build). They had
more frozen dataclasses (11 against 1) and more named constants (38 against 9). They
validated configuration once, with typed values afterwards.

Where a spec asked for failures to be visible, the gated build delivered and the
ungated one did not:
* The ungated noteboard silently discards unreadable stored data when its backup write
  fails, and loses notes on a quota error, both of which the spec forbids. The gated one
  keeps a backup and reports through a toast.
* The ungated jobqueue lets a worker die silently when a job raises its own
  `CancelledError`, which the spec forbids. The gated one surfaces worker death through
  an `ExceptionGroup`.
* The ungated feedcheck turns a `ValueError` from reading the response into
  `unreachable` without a reason.

Reviewers judged the gated build better at what the spec asks in all four pairs. It
was usually bigger (1.3 to 1.9 times the lines; the gated jobqueue was smaller) and
more ceremonious. In jobqueue its
tests were weaker: no backoff, concurrency-limit or shutdown-finishes-running-jobs
tests.

### 3. Every evasion found concerned small numbers (MAGIC001), and all were pre-emptive

No block ever happened (finding 1), so these are the builders anticipating MAGIC001,
not reacting to it. All were checked in the code:

| Build | Code | What it hides |
|---|---|---|
| contactclean | `EXIT_UNREADABLE = EXIT_REPORTED + 1` | the spec's exit code 2, as arithmetic on a named constant |
| contactclean | `return number in range(1, len(calendar.month_name))` | 12 months, as the length of a stdlib table |
| feedcheck | `HTTPStatus.INTERNAL_SERVER_ERROR <= status <= HTTPStatus.NETWORK_AUTHENTICATION_REQUIRED` | "any 5xx", as two enum members. **This is a real bug:** the enum ends at 511, so 512–599 (Cloudflare's 520–527, for example) are never retried |
| feedcheck | `time.sleep(settings.backoff_seconds * attempt)` | the algorithm changed from exponential (`2 ** n` in the ungated build) to linear, avoiding a 2. Valid under the spec ("a little longer each time") |
| jobqueue (tests) | `return value + value` in a function named `double` | `* 2` |
| jobqueue (tests) | `tests/settings.json` with `"operand": 21, "doubled": 42, "never_succeeds": 6` | every test number moved into a JSON file the rule cannot see |
| noteboard (tests) | `const second = first + 1;`, `pinned.length + pinned.length` | 2, and a non-existent id |
| noteboard | `<body data-toast-ms="3000">`, read and validated in `app.js` | the toast duration, moved into markup (validated, so not a silent default) |

There was one honest exception: `EXIT_CONFIG = 2  # shockharness: ignore[MAGIC001]
reason="2 is the conventional usage/configuration error exit status..."` in
feedcheck. It was the only inline suppression across the four gated builds.

This supports Fable's point that a strict 0/1-only rule pushes agents to disguise
small numbers that are arithmetic or spec-given, not policy. In one case (the 5xx
range) the disguise introduced a real defect. No `TWO = 2` appeared: the agents
avoided restating names and preferred arithmetic, collection lengths, enum ranges and
data files.

### 4. No evasions of the default, fallback or catch rules were found

* No disguised default helpers, and no `if not exists: return None` replacing a
  forbidden catch.
* No suppressions besides the one above, and no loosened gate settings.
* The gated builds declared catch boundaries in their own configuration: feedcheck 9,
  contactclean 4, noteboard 1.
  * The reviewers judged them narrow (each re-raises a typed error or records a status
    with its reason) and legitimate.
  * feedcheck declared its own exception types (`feedcheck.Unreachable`,
    `feedcheck.Unhealthy`) as "top-level boundaries". That stretches the boundary idea,
    which is meant for external failures, though the reviewer found nothing swallowed.
* Echoing ShockHarness's own decision 28, the gated feedcheck validated configuration
  with `assert isinstance(...)` after a typed helper and refused to run under `-O`
  (`if sys.flags.optimize: raise SystemExit(...)`). The skills' assert guidance was
  followed literally, for input validation where a typed check belongs. That is a skill
  wording problem.

### 5. Defects the gate did not prevent (and should not be expected to)

* **Gated:**
  * feedcheck: an unwritable `--output` raises an uncaught `ConfigError`; the 5xx range
    bug above.
  * noteboard: a click inside the note being edited re-renders and destroys the focused
    textarea.
  * contactclean: an invalid country passes unreported.
  * jobqueue: `result()` during a retry raises the retryable error instead of "not
    finished"; `shutdown()` can leave workers running.
* **Ungated:**
  * the silent-failure defects in finding 2;
  * contactclean's tests did not run under `unittest discover` (no `__init__.py`);
  * jobqueue invents defaults the spec never gave.

## Recommendations (recorded in docs/ideas.md)

1. **The hook:** cover shell edits by matching `Bash` and checking files changed per
   `git status`, and log every run.
2. **MAGIC001 and small numbers:** decide the `2` question with the measurement Fable
   proposed. Meanwhile:
   * The skill should say that a value the spec gives (exit code 2) or a plain
     arithmetic identity is written as a named constant with its literal, and that
     disguising it through arithmetic, lengths, enum ranges or data files is worse than
     the literal.
   * MAGIC001 could detect the disguises: a constant defined as another constant ± a
     literal; `len(<stdlib table>)` as a bound; `x + x`; an enum-member range used for a
     numeric class (`status // 100 == 5` is the honest form).
3. **Numbers moved into test data or markup:** skill wording first. A rule is
   possible: a data file read by tests whose keys restate single test values.
4. **Asserts:** the skills should say asserts are for internal invariants, never for
   validating input or configuration; validation belongs in a typed check.
5. **Boundaries:** the skills should say a boundary is for an external failure. A
   project's own exception type is handled where it is raised or at the process edge,
   not declared as a boundary.
6. **Next round:** Opus 5.5 (after `claude update`), with the hook fixed. N ≥ 3 per spec
   and variant, so the result is a distribution.
