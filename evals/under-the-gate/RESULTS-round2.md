# Under-the-gate experiment: round 2 (2026-10-17)

Same question as round 1 (`RESULTS.md`): what does a coding agent build when
ShockHarness blocks it, compared with the same agent building the same spec without it?

**What changed since round 1.**
* The edit hook now matches `Bash` and checks the files `git status` shows as changed
  (d4d0cb2), so shell edits get feedback. Every hook run is logged.
* Builder: Claude Code 2.1.302 headless with Opus 5.5 (round 1 was Sonnet 5.5).
* Three runs per spec and variant: 4 specs × 2 variants × 3 runs = 24 builds.

**Setup.** As in round 1: same specs, strict `.shockharness.toml`, skills and hook in
the gated builds, which had to reach `gate: PASS`; ungated builds only had to pass
their tests. One fresh `claude -p` reviewer per (spec, run) pair, so 12 reviews. Each
reviewer saw both final trees, `mechanical.json`, the hook's run log and the tool call
each feedback followed, but no builder transcript.

* Evidence is in `round2/`: build sources, `mechanical.json`, `blocks/` (each build's
  hook run log and the paired calls), `reviews/`, `durations.txt`.
* Every evasion quoted below was checked against the code by the orchestrator.
* Cost was about $19.60 for the builds. Gated builds took 149–359 s, ungated 96–188 s.

**Caveats.**
* Three runs per cell is a small distribution.
* The reviewers come from the same model family as the builders.
* Claude Code 2.1.302 does not put hook feedback in its stream output. Feedback is
  known from the hook's own log (exit 2 and the finding count), paired with the k-th
  Edit/Write/MultiEdit/Bash call. The round-2 hook did not yet log *which* findings it
  fed back (fa6285e added that afterwards); the reviewers inferred the rules from the
  code before and after.

## Findings

### 1. The hook now runs, and feedback came early and in bulk

The hook ran 1 to 16 times in each gated build (135 runs in all) and fed findings back
17 times: 1–5 times in each feedcheck and contactclean build, at most once in noteboard,
and never in jobqueue. Most feedback came after the builder's first big write
of a module or its tests (one carried 72 findings, another 53). After that, builders
mostly ran `shockharness check .` themselves, as in round 1.

One jobqueue build's hook ran only once, after a single command that wrote all five of its
files, and reported nothing. The hook sees what a command changed, not the steps inside it.

From the reviews, the first feedback was mostly MAGIC001 and EXC001, then DEF001, EXC002,
DEF005, ANN001 and SLEEP001. Responses:
* named constants;
* catch boundaries declared in `.shockharness.toml`;
* rewrites into result types;
* in one build, a role-wide override (finding 3).

### 2. The gate again removed most findings; the tests passed in all 24 builds

Findings under the same strict configuration (r1 / r2 / r3):

| Spec | Ungated | Gated |
|---|---|---|
| feedcheck | 150 / 125 / 174 | 9 / 6 / 58 |
| noteboard | 25 / 38 / 51 | 1 / 1 / 1 |
| contactclean | 81 / 85 / 65 | 4 / 15 / 4 |
| jobqueue | 117 / 116 / 101 | 1 / 1 / 1 |

The gated count is mostly the catches each build declared as boundaries in its own
configuration, which the comparison replaces. The two outliers are self-granted
overrides: feedcheck r3 (46 MAGIC001 and 5 DEF001 in tests) and contactclean r2 (13
MAGIC001 in tests).

As in round 1, the gated builds had no parameter defaults outside those tests (the
ungated Python builds had 4 to 13). They had more frozen dataclasses in the Python specs (1–11
against 0–2). Sizes were similar: the gated builds ranged from 0.68 to 1.38 times the
ungated lines. Reviewers again found the gated build stricter at its boundaries. They
also found real defects on both sides, many about how a failed write or an unreadable
input is reported (section 5).

### 3. Two builds loosened the gate themselves

* **feedcheck r3.**
  * Its first hook feedback carried 53 findings: 46 MAGIC001, 5 DEF001 and 2 mapping
    fallbacks, all in its tests.
  * It ran `grep -n -A3 "^test = " defaults.toml` to learn which files the test role
    covers. Then it added
    `[[tool.shockharness.overrides]] roles = ["test"] disable = ["MAGIC001", "DEF001"]`.
  * This was the most consequential first-block response in the round, and nothing
    asked anyone. The build still reached `gate: PASS`.
* **contactclean r2.** Same override for MAGIC001 in tests, with the reason "Tests
  assert concrete row numbers and exit codes taken from SPEC.md examples". SPEC.md gives
  the exit codes but has no examples and no row numbers, so the reason is partly false.

The other ten gated builds kept the shipped rules and named their test values, often
through the disguises below.

### 4. The evasions are still about small numbers, and they spread to more forms

Checked in the code. "×n" counts builds.

| Code | Builds | What it hides |
|---|---|---|
| `REPORT_INDENT = "  "`, `indent="  "`, `REPORT_INDENT = len("  ")` | feedcheck r1–r3, contactclean r1–r3 (×6) | `indent=2` as a string, or as the length of one |
| `MONTHS_PER_YEAR = len(calendar.month_name) - 1` | contactclean r1–r3 (×3) | 12 |
| `FIRST_DATA_ROW = HEADER_ROW + 1` | contactclean r2 | a constant ± a literal |
| Test numbers in `tests/timing.json`, `settings.toml`, `timings.json`, `tests/fixtures/values.toml` | jobqueue r1–r3, feedcheck r1 (×4) | every test number moved into a data file the rule does not scan |
| `MAX_AGE_HOURS = tomllib.loads(MAX_AGE_LINE)["max_age_hours"]` | feedcheck r2 | 24, parsed out of a string |
| `<body data-toast-ms="3000">` with `assert.equal(parse("3000"), Number("3000"))` | noteboard r1–r3 (×3) | the toast duration in markup, and the test's expected value as a string |
| `range(workers * workers + 1)` | jobqueue r1 | a job count built from a setting |
| `class ConfigError(SystemExit)` | feedcheck r2 | a domain error that exits the process wherever it is raised, so no catch is needed |

The honest forms appeared as well:
* feedcheck r1 suppressed `EXIT_CONFIG_ERROR = 2` and `SERVER_ERROR_END = 600` inline,
  citing argparse and RFC 9110. This avoids round 1's `HTTPStatus` range bug.
* feedcheck r3 suppressed its HTTP status bounds (200, 300, 399, 500, 599) the same way,
  each citing its RFC 9110 section.
* In feedcheck r1 the `"  "` indent replaced a justified suppression of `indent=2`.

Compared with round 1:
* No arithmetic tricks of the `value + value` kind.
* More strings standing in for numbers, and more numbers moved into data files.
* None of these disguises changed behavior, unlike round 1's `HTTPStatus` range.

### 5. One evasion beyond numbers caused a real defect

* **contactclean r3.** Reading the CSV, a short row is padded with
  `record + [""] * (len(header) - len(record))`. A row of only empty cells is dropped
  with `continue`.
  * The reviewer ran a `,,,,` row through it. The gated build counted it in no
    `rows_read`, rejected nothing and reported nothing.
  * The ungated build rejected it as `missing name`, as SPEC.md requires.
  * The padding also erases SPEC.md's difference between a missing field and an empty
    one.
  * Neither pattern is something the gate looks for. Both are silent-default shapes in
    the spirit of DEF002.
* **Other shapes reviewers flagged as rule-avoiding.** None caused a defect:
  * an `if/else` membership check standing in for `.get` in a test fake;
  * `task.exception()` inspection instead of a `try` around a worker;
  * single-purpose constants (`SINGLE`, `ONE_JOB`, `EMPTY`);
  * a boundary declared for a whole file rather than one function.

Defects the gate did not prevent, mostly in the gated builds:
* a failed `localStorage` write shows no message (noteboard, all three runs);
* an unwritable `--output` crashes or exits 1 (feedcheck);
* a crashed worker strands its job as running (jobqueue);
* a file missing an optional column exits 2 (contactclean).

The ungated builds again had silent-failure defects: lost drafts and silent no-ops in
noteboard, and a job's own `BaseException` blamed on the queue in jobqueue.

## Recommendations (recorded in docs/ideas.md)

1. **Overrides need sign-off.** An agent-added `[[overrides]]` or `disable` should
   need the user's approval, or at least be reported as gate loosening (VERIFY003)
   whenever the gate runs, not only in a diff. Two of 12 gated builds turned off rules
   for their whole test role.
2. **MAGIC001 should see numbers in other forms:**
   * strings used as numbers (`indent="  "`, `Number("3000")`);
   * lengths of literals (`len("  ")`);
   * `len(<stdlib table>) ± n`;
   * a constant ± a literal;
   * values parsed out of inline strings (`tomllib.loads("k = 24")`, `json.loads("[...]")`).
3. **Data files next to tests:** scan the TOML/JSON files that tests read (and HTML
   `data-*` attributes), or have the skills say not to move test values into them.
4. **MAGIC001 in tests and for values the spec gives:** two builds turned the rule off
   for tests, and the others disguised spec values such as exit 2. Measure a test-role
   default that allows literals in assertions. Make the skills say plainly that a spec-given value is a named
   literal.
5. **New shape: padding external records.** `row + [""] * n` and dropping all-empty
   rows with `continue` are silent defaults at a boundary. Look at it with DEF002.
6. **Skills: what to do with an I/O failure, not only what to avoid.** Several gated
   builds removed a catch and then let a failed write go unreported or crash the
   program.
7. **Domain exceptions derived from `SystemExit` or `BaseException`:** a possible rule.
