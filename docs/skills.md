# Agent skills

ShockHarness ships six vendor-neutral agent skills as package data
(`src/shockharness/skills/<name>/SKILL.md`), in the open Agent Skills format:
YAML frontmatter with `name` and `description`, then a Markdown body. The
files mention no agent's internals; the `skills` command knows where each
supported agent expects them. Installing is opt-in and never touches a file
outside the chosen destination.

## The six skills

| Skill | Use it when | What it enforces |
|---|---|---|
| `write-compliant-code` | Writing new Python or JavaScript | Clear contracts: required, validated inputs; no catch outside a declared boundary; no parameter defaults or fallback values; no numeric literal other than `0`/`1`; a named constant for a `0` or `1` that carries meaning (exit code, sentinel); data, configuration and specification kept out of executable source |
| `fix-violations` | `shockharness check` or `gate` exits 1 | Run the analyzer, identify the intended contract behind each finding, add a characterization test, change the code, rerun tests and analyzer. Never delete a `try`/`except`, replace `.get` with indexing or add a suppression without a contract review; a suppression needs an exact rule ID and a cited reason |
| `refactor-complexity` | Simplifying or untangling code | Address repeated cognitive work and coupling rather than a metric; record call structure and behavior tests before and after. Quotes the real rules `CPLX001`-`CPLX006`, their thresholds, the report fields and the commands |
| `pre-commit-review` | Before a commit or pull request | Run `shockharness gate --base <default branch> --head HEAD` (or `check .`), report unsupported analysis, policy deviations, suppressions and remaining warnings, run the tests; never claim a pass without the quoted output |
| `verification-integrity` | A test, linter or gate fails and it is tempting to skip, suppress or loosen instead of fixing; editing `.shockharness.toml`, a baseline, a CI workflow or another tool's settings; a `VERIFY00x` finding | Fix the cause or stop and say what could not be fixed; never make a check pass by weakening it. Explains each of `VERIFY001`-`VERIFY004`, why they cannot be suppressed inline, the `--policy` floor and the strictest-of-base rule, and how to propose a policy change as its own reviewed change |
| `async-lifecycle` | Writing or changing async Python or JavaScript; an unawaited call, a background task, `gather(return_exceptions=True)` or `Promise.allSettled`; an `ASYNC00x` finding | Every coroutine, task and Promise has an owner that waits for it and sees its failure: await, return, a `TaskGroup`, or `Promise.all` whose result is awaited; settled batches are checked for failures; no `void`; entry points end in a reporting `.catch` |

Since 0.5.0, `fix-violations` and `pre-commit-review` also ask for a written
rule proposal whenever a bug turns up that ShockHarness did not report (the
pattern, why it is a bug, the rule, the expected false positives), and
`write-compliant-code` asks for a check of a function's result where the
contract promises something about it, and since 0.6.0 (principle 8) for immutable values:
frozen records, tuples and frozensets, `Object.freeze`, and new values preferred
over mutated inputs (discouraged, not forbidden; local mutation is fine), and
since 0.7.0 (principle 9) for asserting internal invariants where they must hold,
with typed errors for expected failures and one startup refusal of `python -O`. `pre-commit-review` reads `shockharness
exceptions .` as the reviewer's list of everything the code and configuration
exempt.

Every skill contains compliant and non-compliant Python and JavaScript
examples (the worked examples are `examples/python` and `examples/js`), exact
CLI invocations, a corrective workflow, a checklist, and an "Adopting
ShockHarness" section that is byte-identical to the README's, so an agent with
the skill installed never needs to fetch the README. The test suite checks the
frontmatter of every shipped skill, that every rule ID a skill mentions exists
in the registry, and that the adoption sections match the README.

```bash
shockharness skills list                 # names and descriptions
shockharness skills show fix-violations  # print one shipped SKILL.md
```

## Where they go: the adapter table

| `--agent` | Project destination (`--project PATH`, default: current directory) | `--user` destination | Discovery | Verified against |
|---|---|---|---|---|
| `claude` | `<PATH>/.claude/skills/<name>/SKILL.md` | `~/.claude/skills/<name>/SKILL.md` | automatic | https://code.claude.com/docs/en/skills (2026-10-14) |
| `codex` | `<PATH>/.agents/skills/<name>/SKILL.md` | `~/.agents/skills/<name>/SKILL.md` | automatic: Codex scans `.agents/skills` from the working directory up to the repository root, and `$HOME/.agents/skills` | https://developers.openai.com/codex/skills, which redirects to https://learn.chatgpt.com/docs/build-skills (2026-10-14) |
| `generic` | `<PATH>/<name>/SKILL.md`; `--project PATH` is required | not supported (exit 2) | none: `install` prints the pointer line to add to the agent's instruction file (for example `AGENTS.md`) | https://agentskills.io/specification (2026-10-14) |

Older third-party guides place Codex skills under `~/.codex/skills`; the
official documentation on the verification date lists only `.agents/skills`
locations, which is what the adapter writes. `--project` and `--user` are
mutually exclusive. Usage errors (missing `--project` with `generic`, `--user`
with `generic`, an unknown agent) exit 2 and write nothing.

## `skills install`

```bash
shockharness skills install --agent claude|codex|generic [--project PATH] [--user] [--force] [--hook [--lock]]
```

Writes `<destination>/<name>/SKILL.md` for each of the six skills, byte for
byte as shipped, then `<destination>/.shockharness-skills.json`. If any of
those files already exists the command refuses (exit 2) and writes nothing;
`--force` replaces them all. Besides the skills, only three files are ever
written:

* **`.shockharness.toml`**, when the project (not `--user`) has no ShockHarness
  configuration at all: the file `shockharness init` writes, strict profile with
  the test exemption (spec 21.1 decision 35). An existing configuration is never
  changed.
* **`.claude/settings.json`**, with `--hook` (`--agent claude`): the edit-time
  hook is appended to the `PostToolUse` hooks, once.
* **The lock**, with `--hook --lock`: the project's effective configuration,
  minus `rules.exceptions.boundaries`, written as a `--policy` file to
  `~/.config/shockharness/locks/<project>-<digest>.toml`; the hook command gets
  `--policy "<that file>"`. The project's configuration can then tighten those
  keys but not loosen them; a loosening is reverted to the lock's value and fed
  back as `VERIFY003`. To accept a change, edit the lock. An existing lock is
  kept unless `--force` is given. An agent with unrestricted shell access can
  still edit a file in the home directory, so the lock is a strong signal, not a
  guarantee; Claude Code's sandbox, when on, keeps writes inside the project.

It never touches `AGENTS.md`, `CLAUDE.md` or other agent configuration. For
`generic` it prints the line to add by hand:

```text
Add this line to the agent's instruction file (for example AGENTS.md):
  Before writing, fixing, refactoring or reviewing code, read the matching ShockHarness skill in docs/agent-skills/<name>/SKILL.md (write-compliant-code, fix-violations, refactor-complexity, pre-commit-review, verification-integrity, async-lifecycle).
```

## The manifest

`.shockharness-skills.json`, sorted keys, two-space indent, trailing newline:

```json
{
  "agent": "claude",
  "schema_version": "1",
  "skills": {
    "fix-violations": {
      "path": "fix-violations/SKILL.md",
      "sha256": "<hex SHA-256 of the file as written>"
    }
  },
  "tool_version": "0.9.0"
}
```

`tool_version` is the package version that last wrote the manifest; each
`sha256` is the hash of the content **the tool generated** for that file. A
file whose current hash equals its manifest hash is unedited; one that differs
was edited by someone. A manifest with an unknown `schema_version`, a missing
field or malformed JSON is a usage error (exit 2).

## `skills update`

```bash
shockharness skills update --agent claude|codex|generic [--project PATH] [--user] [--check]
```

Requires the manifest (otherwise exit 2 telling you to run `install`), and
refuses a manifest written for a different `--agent`. For every skill the
package ships and every skill the manifest records:

| Status | Meaning | `update` does | `update --check` |
|---|---|---|---|
| `up-to-date` | file equals the manifest hash, and the package ships the same content | nothing | ok |
| `stale` | file equals the manifest hash; the installed package ships newer content | rewrites the file, records the new hash | drift |
| `edited` | file differs from the manifest hash (or exists without a manifest entry) | leaves the file alone, keeps the old hash, reports a **conflict** with the remediation | drift |
| `missing` | in the manifest, absent on disk | restores it from the package | drift |
| `new` | shipped by the package, not in the manifest | writes it, adds it to the manifest | drift |
| `removed` | in the manifest, no longer shipped | reports it and drops it from the manifest; the file is not deleted | drift |

`update` exits 0 when it left no conflict, 1 when an edited file blocked its
update. `--check` writes nothing (not even the manifest) and exits 1 when any
skill drifted from the installed package, 0 when all are `up-to-date`, so a
consumer CI job can detect that an analyzer upgrade changed the skills or that
someone edited an installed copy:

```yaml
- run: shockharness skills update --agent claude --check
```

The conflict remediation printed for an edited file: save your edits, delete
the file, run `skills update` again (the file is restored from the package),
then re-apply your edits; `shockharness skills show <name>` prints the shipped
version for comparison. `skills install --force` replaces every file,
including edited ones, and is the only command that overwrites an edited skill.

## Evaluation corpus

`evals/` holds eight paired tasks (four Python, four JavaScript) with a
prompt, a starting file set, the task's own tests, an expected outcome and a
reference solution, plus `evals/run_evals.py`, a standard-library scorer that
counts unsuppressed findings by rule, runs the tests and counts added
suppressions, and writes a JSON scorecard. CI scores the reference solutions
on every push. `evals/README.md` explains how to compare agent runs with and
without the skills installed.
