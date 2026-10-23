# Agent skills

ShockHarness ships eight vendor-neutral agent skills as package data
(`src/shockharness/skills/<name>/SKILL.md`), in the open Agent Skills format:
YAML frontmatter with `name` and `description`, then a Markdown body. The
files mention no agent's internals; the `skills` command knows where each
supported agent expects them. Installing is opt-in and never touches a file
outside the chosen destination.

## The eight skills

| Skill | Use it when | What it enforces |
|---|---|---|
| `write-compliant-code` | Writing new Python or JavaScript | Clear contracts: required, validated inputs; no catch outside a declared boundary; no parameter defaults or fallback values; no numeric literal other than `0`/`1`; a named constant for a `0` or `1` that carries meaning (exit code, sentinel); data, configuration and specification kept out of executable source |
| `fix-violations` | `shockharness check` or `gate` exits 1 | Run the analyzer, identify the intended contract behind each finding, add a characterization test, change the code, rerun tests and analyzer. Never delete a `try`/`except`, replace `.get` with indexing or add a suppression without a contract review; a suppression needs an exact rule ID and a cited reason |
| `refactor-complexity` | Simplifying or untangling code | Address repeated cognitive work and coupling rather than a metric; record call structure and behavior tests before and after. Quotes the real rules `CPLX001`-`CPLX006`, their thresholds, the report fields and the commands |
| `pre-commit-review` | Before a commit or pull request | Run `shockharness gate --base <default branch> --head HEAD` (or `check .`), report unsupported analysis, policy deviations, suppressions and remaining warnings, run the tests; never claim a pass without the quoted output |
| `verification-integrity` | A test, linter or gate fails and it is tempting to skip, suppress or loosen instead of fixing; editing `.shockharness.toml`, a baseline, a CI workflow or another tool's settings; a `VERIFY00x` finding | Fix the cause or stop and say what could not be fixed; never make a check pass by weakening it. Explains each of `VERIFY001`-`VERIFY004`, why they cannot be suppressed inline, the `--policy` floor and the strictest-of-base rule, and how to propose a policy change as its own reviewed change |
| `async-lifecycle` | Writing or changing async Python or JavaScript; an unawaited call, a background task, `gather(return_exceptions=True)` or `Promise.allSettled`; an `ASYNC00x` finding | Every coroutine, task and Promise has an owner that waits for it and sees its failure: await, return, a `TaskGroup`, or `Promise.all` whose result is awaited; settled batches are checked for failures; no `void`; entry points end in a reporting `.catch` |
| `property-contracts` | A repository enables `rules.property_contracts`; a value must carry a fact the code cannot see (normalized, redacted, sanitized HTML, a validated path); a `PROP00x` finding; writing the catalog, a predicate or a test bootstrap; `enforcement = "complete"` | Choose properties that are facts not observable from the value; put a parameter's `requires` first, `produces` only where the property is established (with a test), `preserves` for pass-through; never remove a `requires` to satisfy `PROP001`; call `enable` once from test code (`conftest.py`, a test-only entry script, a test-entry page or an init-script pre-load), never production; read `requires(x)` declarations as the sorry count |
| `adopt-shockharness` | Adding ShockHarness to a repository, upgrading its pin or wiring it into CI; a check or gate that cannot run because ShockHarness is not set up | Install a pinned version, write and validate the policy file, take an existing codebase on with a baseline, the minimal profile or warn mode, add the CI gate and Dependabot, install the skills, and verify each step. Holds the README's "Adopting ShockHarness" section byte for byte |

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
CLI invocations, a corrective workflow and a checklist. The setup guide, the
README's "Adopting ShockHarness" section, lives in `adopt-shockharness` alone,
byte-identical to the README's, so an agent with the skills installed never needs
to fetch the README; the other skills end with a pointer to it (until the
split, each of the seven carried its own 151-line copy). The test suite checks
the frontmatter of every shipped skill, that every rule ID a skill mentions exists
in the registry (any family), and that the adoption skill's section matches the
README.

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

Writes `<destination>/<name>/SKILL.md` for each of the eight skills, byte for
byte as shipped, then `<destination>/.shockharness-skills.json`. If any of
those files already exists the command refuses (exit 2) and writes nothing;
`--force` replaces them all. Besides the skills, only four files are ever
written:

* **`.shockharness.toml`**, when the project (not `--user`) has no ShockHarness
  configuration at all: the file `shockharness init` writes, strict profile with
  the test exemption (spec 21.1 decision 35). An existing configuration is never
  changed.
* **The agent's instruction file**, for a project install of `claude` (`CLAUDE.md`)
  or `codex` (`AGENTS.md`): one pointer line telling the agent to read the matching
  skill before it writes, fixes, refactors or reviews code, appended (the file is
  created when absent). A file that already names the skills directory
  (`.claude/skills`, `.agents/skills`) is kept as it is, so a second install or a
  line of the project's own adds nothing.
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

For `generic`, whose instruction file only its user knows, it prints the line to
add by hand:

```text
Add this line to the agent's instruction file (for example AGENTS.md):
  Before writing, fixing, refactoring or reviewing code, read the matching ShockHarness skill in docs/agent-skills/<name>/SKILL.md (write-compliant-code, fix-violations, refactor-complexity, pre-commit-review, verification-integrity, async-lifecycle, property-contracts, adopt-shockharness).
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
  "tool_version": "0.29.0"
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

## `init` installs them

An agent that adopts ShockHarness by running its commands may never read the setup
guide, so `shockharness init` installs the skills itself: for every coding agent whose
files are in the project (the directory of the configuration file `init` writes), it
runs what `skills install` does there, pointer line included.

| Files found | Agent | Skills | Pointer line in |
|---|---|---|---|
| `.claude/` or `CLAUDE.md` | `claude` | `.claude/skills` | `CLAUDE.md` |
| `.agents/` or `AGENTS.md` | `codex` (Codex and the other agents that read `AGENTS.md`) | `.agents/skills` | `AGENTS.md` |

An agent whose skills are already installed (a manifest in the project's or the home
directory's skills directory) is left alone, and `init` says `skills update` refreshes
them. `--agent claude|codex` (repeatable) chooses instead of the detection;
`--no-skills` writes only the configuration. When no agent's files are there, `init`
installs nothing and prints both install commands.

## Knowing when they are missing

A repository adopted before `init` installed skills, or with `--no-skills`, would never
hear of them. So while the project has a ShockHarness configuration of its own,
`shockharness check` prints one line on stderr after its report for each agent from the
table above whose files are there with no ShockHarness skills installed for it (in the
project, or under the home directory with `--user`):

```text
shockharness: skills: none installed for Claude Code, which works here (CLAUDE.md found); run: shockharness skills install --agent claude (a repository that wants no skills sets notify_missing = false in [tool.shockharness.skills])
```

With no agent's files and no skills installed for either agent, the line names both
commands. `notify_missing = false` under `[tool.shockharness.skills]` records that the
repository wants none (a `generic` install, whose directory ShockHarness cannot know, is
one reason), and the line stops. It never changes the gate or the report.

## Knowing when to update

Nobody has to read the release notes to learn that the skills changed. When a project holds
a skills manifest at a known place (Claude Code's `.claude/skills`, Codex's
`.agents/skills`) and `skills update` would change something there (skills the installed
ShockHarness ships newer, new skills, missing files), `shockharness check` prints one line
on stderr after its report, and the edit-time hook feeds the same line back to the agent
once per upgrade:

```text
shockharness: skills: 7 out of date, 1 new since they were installed with ShockHarness 0.22.0 (0.29.0 is installed); run: shockharness skills update --agent claude
```

It never changes the gate or the report. Edited skills are left out (`update` does not
change them; `update --check` reports them), and so is a `generic` install, whose directory
only its user knows. A manifest that cannot be read asks for `skills install --force`.

## Evaluation corpus

`evals/` holds eight paired tasks (four Python, four JavaScript) with a
prompt, a starting file set, the task's own tests, an expected outcome and a
reference solution, plus `evals/run_evals.py`, a standard-library scorer that
counts unsuppressed findings by rule, runs the tests and counts added
suppressions, and writes a JSON scorecard. CI scores the reference solutions
on every push. `evals/README.md` explains how to compare agent runs with and
without the skills installed.
