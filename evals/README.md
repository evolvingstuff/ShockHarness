# Skill evaluation corpus

Paired coding tasks for measuring whether the four ShockHarness agent skills
(`write-compliant-code`, `fix-violations`, `refactor-complexity`,
`pre-commit-review`) change what a coding agent produces. The corpus and its
runner are reproducible and need nothing but Python, `node` and an installed
`shockharness`; **no agent is run by anything here**. You (or your agent
harness) produce candidate solutions; `run_evals.py` scores them.

## Layout

```text
evals/
  run_evals.py                 # the scorer (standard library only)
  tasks/<task>/
    task.md                    # the prompt to give the agent
    start/                     # the starting file set, including .shockharness.toml
    tests/                     # the task's own behavioral tests (unittest or node --test)
    expected.json              # language, max_findings, max_suppressions_added, tests_must_pass
    reference/                 # one solution that scores clean (CI runs it)
```

Eight tasks ship: four Python (`py-01-http-settings`, `py-02-mapping-fallbacks`,
`py-03-json-boundary`, `py-04-pagination-numbers`) and four JavaScript
(`js-01-config-env`, `js-02-catch-fallback`, `js-03-pagination-defaults`,
`js-04-status-codes`). Each starting file set passes neither the analyzer nor
the task's tests; each reference passes both. Two tasks (`py-03`, `js-02`)
require editing `.shockharness.toml` to declare one exception boundary; two
(`py-01`, `js-04`) allow a bounded number of cited suppressions for protocol
constants and reject more.

## Scoring

For every (task, candidate) pair the runner copies the candidate into a fresh
workspace, adds the task's `tests/`, and records:

| Dimension | How | Field in the scorecard |
|---|---|---|
| Rule violations | `shockharness check . --format json`; findings minus suppressed, by rule ID | `analyzer.unsuppressed_findings`, `analyzer.by_rule`, `analyzer.exit_code` |
| Behavioral regressions | `python -m unittest discover -s tests` with `PYTHONPATH=src`, or `node --test tests/*.test.js` | `tests.exit_code`, `tests.detail` |
| Suppressions added | `shockharness: ignore[` comments in the candidate's sources minus those in `start/` | `suppressions.added` |

A task **passes** when the analyzer exited 0, the tests exited 0 (when
`tests_must_pass`), `unsuppressed_findings <= max_findings` and
`suppressions.added <= max_suppressions_added`. The runner prints one line per
task, writes a JSON scorecard (`--output`), and exits 0 only when every scored
task passed.

```bash
python evals/run_evals.py --reference --output scorecard.json          # the shipped solutions: all pass
python evals/run_evals.py --candidates runs/with-skills --output with.json
python evals/run_evals.py --candidates runs/without-skills --output without.json
python evals/run_evals.py --task evals/tasks/py-01-http-settings --candidate runs/x/py-01-http-settings
```

`--candidates DIR` expects one `DIR/<task>/` per task with the same layout as
`start/`. `--python` selects the interpreter that has `shockharness`
installed; `--node` the Node executable; `--keep` keeps the workspaces.

## Comparing with and without the skills

1. For each task, copy `start/` to a working directory, give the agent the
   `task.md` text, and let it edit the copy. Do this once in a session **with**
   the skills installed (`shockharness skills install --agent <agent>` in that
   working directory or `--user`) and once **without** (a fresh session, no
   skills directory). Keep the agent, model and prompt otherwise identical;
   repeat each arm several times, since agent output varies.
2. Collect the results as `runs/with-skills/<task>/` and
   `runs/without-skills/<task>/`.
3. Score both arms and compare the `summary` blocks: `passed`,
   `unsuppressed_findings`, `test_failures`, `suppressions_added`. Then read
   the per-task `by_rule` counts: the skills are meant to remove `DEF*` and
   `EXC*` findings by making contracts explicit, not by adding suppressions,
   so a run that lowers `unsuppressed_findings` while raising
   `suppressions_added` beyond the task's allowance fails that task on purpose.
4. Review accuracy (for `pre-commit-review`) is not scored automatically:
   compare the agent's written verdict against the scorecard's analyzer and
   test results by hand. Agents are not correctness oracles; the tests and a
   human reader remain necessary.

Candidate solutions produced by agents are not committed to this repository;
only the tasks, the tests and the reference solutions are.
