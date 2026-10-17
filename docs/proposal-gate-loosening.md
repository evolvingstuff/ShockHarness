# Proposal: tests exempt by default, and no rule switched off unasked (decision 35, draft)

Status: **draft, waiting on Tom.** From the under-the-gate experiment, round 2
(`evals/under-the-gate/RESULTS-round2.md`, finding 3). Nothing here is built.

## What happened

In 2 of the 12 gated builds, the agent hit a wall of findings in its tests. It then added this
to the project's `.shockharness.toml`:

```toml
[[tool.shockharness.overrides]]
roles = ["test"]
disable = ["MAGIC001", "DEF001"]     # contactclean r2: ["MAGIC001"]
reason = "..."
```

The gate then said `PASS`, and nobody was asked. One of the two reasons was partly
false: it cited "SPEC.md examples", and SPEC.md has none.

That looks like an agent switching rules off. But it is also exactly what we tell agents
to do:
* six shipped skills say, in their setup step, "Tests may stay included; exempt them
  from `MAGIC001` and `DEF001` with an `[[tool.shockharness.overrides]]` entry that
  carries a `reason`, as the tool's own configuration does";
* ShockHarness's own `.shockharness.toml` has that entry.

Meanwhile:
* the bundled defaults and what `shockharness init` writes (`overrides = []`) do not
  include it;
* MAGIC001, DEF001–006 and EXC001–003 apply to tests as to production code in every
  profile (the newer rules are production-only).

The experiment's gated configuration didn't include it either. So:
* the 10 builds that left the configuration alone were held to a stricter standard
  than we recommend, and disguised their test values (`Number("3000")`, numbers moved
  into JSON files);
* the 2 builds that added the recommended exemption did it as a policy change of their
  own, mid-task, and it showed up only as one more `policy deviation` line.

Two problems, then:

1. **The recommended setup isn't the default.** Every project has to remember to add
   the test exemption. An agent that discovers it mid-task is changing policy.
2. **Switching a rule off is not visible enough.** Any agent-added override, test
   exemption or otherwise, should reach a person. Today it is printed among the catch
   boundaries and the gate passes.

## Part 1: make the test exemption the default

Options:

* **(a) `init` and `skills install` write the exemption** into the new
  `.shockharness.toml`, as ShockHarness's own configuration has it. It stays visible as a
  deviation, and the strict profile keeps its meaning (every rule everywhere).
  A hand-written configuration, like the experiment's, still lacks it.
* **(b) The bundled defaults exempt tests:** MAGIC001 and DEF001 get a `roles` key
  like the newer rules, defaulting to `["production", "config", ...]` without
  `test`. Every configuration gets it, including hand-written ones. A project that
  wants tests held to the full standard adds `test` back, which is a tightening. This
  changes the strict profile for everyone, so it needs the measurement below first.

**Recommendation: (a) now, then (b) if the measurement supports it.** (a) is one change
to `init` and `skills install`, plus wording in the six skills ("`init` has done this").
It only puts our own practice where new projects get it.

The measurement for (b): what MAGIC001 and DEF001 report in the test files of the eval
corpus and MetaList, and what fraction is assertion values and fixtures, as opposed to
policy hidden in a test helper. A narrower option may fall out of it: exempt only the
arguments of assertion calls, as the backlog's BOOL001 row proposes for booleans.

## Part 2: an agent may not switch a rule off unasked

### What already exists, and why none of it fired

| Mechanism | What it does | Why it did not help |
|---|---|---|
| Policy deviation lines | `check` prints every override, boundary and loosened setting | The override was one line among the catch boundaries; the gate passed |
| VERIFY003, revision comparison | `diff` / `gate --base X --head Y` reports every loosening since the base commit | Needs a base commit and a `diff`/`gate` run. The builds had no commit, and agents run `check` |
| VERIFY003 severity | `warning` by default (decision 9): reported, never fails | Even in CI, a pull request adding an override would pass |
| `--policy FILE` | An organization file outside the repository; the repository cannot loosen any key it sets (`overrides = []` locks overrides) | Opt-in, aimed at CI; `skills install` does not set one up |

The pieces exist. What's missing is wiring them into the agent's loop, and telling the
two kinds of configuration change apart.

### Two kinds of configuration change

The 12 gated configurations held 32 deviation lines: 30 catch boundaries and 2 overrides.

* **Expected remedies.** A catch boundary, with its exception types, file and reason, is
  what EXC001's remediation and the skills tell the agent to do. The reviewers judged
  nearly all 30 legitimate. Requiring sign-off for these would stop every build at its
  first network call.
* **Switching a rule off:**
  * an `[[overrides]]` entry (by path or role);
  * a disabled rule family;
  * a lowered severity or gate mode;
  * a raised complexity threshold;
  * a new `exclude` pattern, or a pattern removed from `include`;
  * a looser `profile`;
  * a value added to `allowed_values`.

  No finding's remediation asks for any of these. `loosening.py` already detects each
  one.

Part 2 only concerns the second kind. Narrowing a boundary to one function is a
separate idea in the backlog.

### What a local check can and cannot do

The agent can edit any file in the project, including any "approved" record we invent,
and run any command the user lets it run. No check on its machine can *prevent* a
loosening. It can:

1. make the loosening impossible to miss, at the moment it happens;
2. tell the agent the one right move: undo it, or stop and ask the user;
3. make sure it cannot reach the main branch unreviewed (CI, where the agent cannot
   write).

### 1. Locally: compare to what the user last accepted

`check` and the edit hook compare the working configuration with an **accepted
configuration**:

* the configuration at the merge base with the default branch (`origin/HEAD`), when
  there is one; else
* the configuration at `HEAD`, when there is a commit; else
* the bundled profile the configuration names, when there is no commit at all (a brand-new
  project, like the experiment's builds).

Every rule-switching change relative to that is a **VERIFY003 error**, so the gate
fails. Boundaries are not counted. The hook feeds it back right after the edit. The
message says what to do:

> VERIFY003 .shockharness.toml: overrides[0] disables MAGIC001, DEF001 for file role(s)
> test. Switching a rule off is the user's decision, not yours. Undo this change and fix
> the findings, or stop and ask the user, quoting this line and your reason. Do not
> commit it yourself.

With Part 1 (a) in place, a project set up with `init` already has the test exemption.
An agent then has no routine reason to touch this.

### 2. Approval: a person commits it

The user approves by committing the change, or by telling the agent to. After that,
the accepted configuration includes it, and the local check passes. On a feature branch,
the comparison is with the merge base, so the change keeps showing until the branch is
merged. That merge is where a person sees it.

This is weak against an agent that commits on its own: on a solo `main` branch, a commit is
all it takes. The skills forbid it and the message says so, but nothing enforces it.
Hence part 3, and an opt-in lock:

* `skills install --hook --lock` writes a policy file outside the project (under the
  user's ShockHarness config directory) with the current overrides and rule settings,
  and adds `--policy <that file>` to the hook command.
* The repository then cannot loosen those keys at all. The user edits the policy file to
  allow a change.
* An agent with unrestricted shell access could still edit that file. Claude Code's
  sandbox, when on, does not let it write outside the project.

### 3. In CI: a rule switched off fails the pull request

`gate --base origin/main` already reports these changes as VERIFY003. Raise the
rule-switching kind to `error` by default, so the PR fails until someone deliberately
accepts it: by putting the change in the protected `--policy` file, or by setting
`rules.verification.severity`, which is itself a reported change. Other VERIFY003 findings
(workflow and baseline changes) keep decision 9's `warning`.

## What it would have done in round 2

With both parts:
* all 12 builds would have started with the test exemption;
* neither override would have been needed;
* any override would have been fed back as an error the moment it was written;
* none of the 30 boundaries would have been flagged.

The next round would show whether the test-value disguises in finding 4 go away. Not
built, so not run. The check is cheap: re-run `check` on the 12 trees in
`evals/under-the-gate/round2/builds/`.

## Questions for Tom

1. **Tests.** Part 1 (a) now (`init` and `skills install` write the test exemption),
   and (b) (the bundled default) only after the measurement?
2. **The split.** Do boundaries stay outside the sign-off, with only rule-switching
   changes needing it? Or should a boundary covering a whole directory (a `**` glob)
   count as switching a rule off?
3. **Approval.** Is "a person commits it" enough as the default, with `--lock` opt-in?
   Or should `skills install --hook` lock by default?
4. **CI.** Raise rule-switching VERIFY003 findings to `error` by default? This changes
   decision 9 for this one class.

## Work, once agreed

**Part 1 (a):**
* `init` and `skills install` write the exemption;
* the six skills' setup step;
* tests;
* re-run the experiment's gated configuration with it.

**Part 2:**
* `loosening.py` tags each loosening as remedy (boundary) or rule-switching.
* The VERIFY003 comparison: the accepted-configuration lookup (merge base, `HEAD`, or the
  profile), reusing the revision snapshot `diff` already takes. Then run it in `check`
  and the hook.
* The message; one sentence in the skills.
* `skills install --hook --lock`.
* The CI severity default and a changelog note.
* Tests:
  * an override added after the last commit fails `check` and is fed back by the hook;
  * a boundary does not;
  * a committed override passes locally and still fails `gate --base`;
  * there is no commit;
  * `--lock`.

Part 1 (a) is small. Part 2 is about a session: the comparison machinery exists, so
the new part is the accepted-configuration lookup and running it outside `diff`.
