# Integrating ShockHarness into a repository

ShockHarness is a development-time tool distributed as a versioned Python
package. A consumer repository, Python or JavaScript, pins one version, keeps
its policy in a small checked-in file, and runs one command in CI. Nothing here
requires Python as an *application* dependency: a JavaScript project installs
the analyzer into an isolated tool environment.

Two worked consumers live in this repository: [`examples/python`](../examples/python)
and [`examples/js`](../examples/js). `scripts/consumer_upgrade_check.py` turns
each into a throwaway git repository, installs the wheel under test, and proves
the gate passes clean and fails after one injected violation; CI runs it on
every push.

## 1. Install a pinned version

Pick one. In every case the version is an exact pin.

```bash
# Python project: a development dependency (Dependabot-visible)
#   pyproject.toml -> [project.optional-dependencies] dev = ["shockharness==0.13.0"]
#   or requirements-dev.txt -> shockharness==0.13.0
pip install -e ".[dev]"

# JavaScript project or any repository: an isolated tool environment
uv tool install 'shockharness==0.13.0'
pipx install 'shockharness==0.13.0'
```

Runtime dependencies are `tree-sitter` and `tree-sitter-javascript` only.

## 2. Add a policy file

```bash
shockharness init                       # .shockharness.toml, strict profile
shockharness init --profile recommended # a short file selecting the profile
shockharness config validate
```

`.shockharness.toml` or `shockharness.toml` (one of them) or a
`[tool.shockharness]` table in `pyproject.toml`. See
[`configuration.md`](configuration.md) for the schema, the three built-in
profiles and the two command-line overrides.

## 3. Run it

```bash
shockharness check .                                  # exit 0 pass, 1 violations, 2 config, 3 tool failure
shockharness check . --format sarif --output shockharness.sarif
shockharness gate --base origin/main --head HEAD      # exit 1 only on NEW hard violations
```

An empty tree (a freshly scaffolded repository with no `.py`/`.js` files yet)
passes: `check` reports `0 file(s)` and exits `0`. `unsupported_sources`
covers files that are present but unsupported, not the absence of files.

## 4. CI

**Python 3.10 projects.** ShockHarness runs on Python 3.11+ (its configuration
reader is the standard library's `tomllib`, and the runtime stays
dependency-free apart from tree-sitter), but it reads 3.10 code. Static
analysis does not depend on the interpreter the tests run on, so run the gate
as one job of its own on 3.12 rather than on every leg of a 3.10-3.13 matrix:

```yaml
jobs:
  tests:
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12", "3.13"]
    # ... the project's tests, unchanged
  shockharness:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: "3.12"
      - run: pip install -r requirements-lint.txt   # pins shockharness==0.13.0
      - run: shockharness check . --format sarif --output shockharness.sarif
```

The reusable workflow (B below) does the same: its `python-version` input
defaults to 3.12 independently of the project's matrix.

### A. Direct invocation (any CI system)

```yaml
- run: pip install "shockharness==0.13.0"   # or: pip install -e ".[dev]" with the pin in pyproject.toml
- run: shockharness check . --format sarif --output shockharness.sarif
```

Works on GitHub Actions, GitLab CI, local hooks (`.pre-commit-hooks.yaml`
exposes `shockharness check`), anywhere. The pin must be in a manifest, not in
the shell line (see section 5).

The content-hash cache (`.shockharness-cache/`, 0.3.0) makes a second run
over an unchanged tree take only the cross-file phase. On a CI runner it is
optional: restore the directory with your platform's cache action, keyed by the
analyzer version and the configuration file, or leave it out and run cold.
A restored cache from another analyzer version, configuration or interpreter
is invalidated on open, never used, so a stale key cannot change a verdict.

### B. The reusable GitHub Actions workflow

`.github/workflows/check.yml` in this repository is a `workflow_call` workflow.

| Input | Required | Default | Meaning |
|---|---|---|---|
| `shockharness-version` | yes | | Exact version installed from PyPI. **This is the analyzer pin.** |
| `config` | no | `""` | Configuration file path; empty means discovery in the repository root |
| `base` | no | `""` | Base ref: when set the job runs `gate --base <base> --head HEAD`; when empty, `check .` |
| `python-version` | no | `"3.12"` | Python used to run the analyzer |

It checks out the repository with full history (the base commit must be
present for `gate`), installs `shockharness==<input>`, runs the command with
`--format sarif --output shockharness.sarif`, and uploads the SARIF to GitHub
code scanning with `github/codeql-action/upload-sarif`. Its only permissions
are `contents: read` and `security-events: write`; the calling job must grant
at least those and no more.

Pinned to a release tag:

```yaml
name: ShockHarness
on:
  pull_request:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  shockharness:
    uses: evolvingstuff/ShockHarness/.github/workflows/check.yml@v0.13.0
    permissions:
      contents: read
      security-events: write
    with:
      shockharness-version: "0.13.0"
      config: .shockharness.toml
      base: ${{ github.event_name == 'pull_request' && github.event.pull_request.base.sha || '' }}
```

Pinned to a full commit SHA (strongest reproducibility; the comment keeps the
human-readable tag next to it, which is also what Dependabot updates):

```yaml
    uses: evolvingstuff/ShockHarness/.github/workflows/check.yml@0123456789abcdef0123456789abcdef01234567  # v0.13.0
```

**The workflow ref and the analyzer version are two separate pins.** The
`uses:` ref decides which copy of `check.yml` runs; the `shockharness-version`
input decides which analyzer it installs. A newer workflow tag does not upgrade
the analyzer and vice versa. Keep the input equal to the pin in your
`pyproject.toml` or requirements file when you have one (the Python example
does; its upgrade check asserts the two agree).

Exit codes are unchanged inside the workflow: the job fails on violations
(exit 1), on an invalid configuration (exit 2) and on a tool failure or strict
parse failure (exit 3). The SARIF file is uploaded whenever it was written,
which includes the violations case, so findings appear in the *Security* tab
of the pull request even when the job is red.

## 5. Keeping up to date with Dependabot

Add `.github/dependabot.yml` to the consumer repository:

```yaml
version: 2
updates:
  - package-ecosystem: pip            # bumps shockharness==X in pyproject.toml / requirements*.txt
    directory: /
    schedule:
      interval: weekly
  - package-ecosystem: github-actions # bumps the `uses:` ref of the reusable workflow
    directory: /
    schedule:
      interval: weekly
```

Rules that make this work:

* **The pin must live where an updater can see it**: `pyproject.toml`
  (`[project.dependencies]` or `[project.optional-dependencies]`), a
  requirements file, or a workflow input. **Never inside a shell string** such
  as `uvx --from shockharness==0.13.0 shockharness check .` or
  `pip install shockharness==0.13.0` in a `run:` line: Dependabot does not
  read shell commands, and that pin would silently rot.
* Dependabot's `github-actions` ecosystem updates the `uses:` ref of the
  reusable workflow. It does **not** rewrite the `shockharness-version` input;
  that bump is yours to make in the same PR (or let the `pip` ecosystem bump
  the `pyproject.toml` pin and copy it over). The JavaScript example therefore
  has exactly one pin, in the workflow input, and documents that it is bumped
  by hand.
* Review every ShockHarness upgrade PR as a policy change: the changelog lists
  rule changes first, and a tightened default is a breaking change for your
  gate. Repositories may defer an upgrade; nothing updates to `latest`.
* For a broad rollout across many repositories, open reviewable PRs with a
  script; do not commit upgrades directly.

## 6. Adopting on a legacy codebase

The four onboarding paths (baseline, `gates.new_hard_violations = "warn"`,
`profile = "minimal"`, `--exit-zero`) and when to use each are compared in
`configuration.md`, "Adopting ShockHarness on an existing codebase". In short:

1. Start with `profile = "minimal"` (everything reported, nothing gating) or
   `recommended`, or run once with `--exit-zero`, and read the report.
2. Create a reviewed baseline: `shockharness baseline create src --output
   .shockharness-baseline.json`, commit it, and pass `--baseline` to `check`.
   Legacy findings stay listed but do not gate; new ones do.
3. Use `gate --base <default branch> --head HEAD` on pull requests so only new
   hard violations fail.
4. Move to `strict` when the baseline is paid down; every deviation from strict
   is printed in every report until then.

## 7. Agent skills

If coding agents work in the repository, install the six bundled skills
next to the code so they are versioned with it, and let CI detect drift
after an analyzer upgrade:

```bash
shockharness skills install --agent claude     # .claude/skills/<name>/SKILL.md + .shockharness-skills.json
shockharness skills install --agent codex      # .agents/skills/<name>/SKILL.md + manifest
shockharness skills install --agent generic --project docs/agent-skills   # prints the AGENTS.md pointer line
```

```yaml
- run: shockharness skills update --agent claude --check   # exit 1 when a skill is stale or edited
```

After a Dependabot upgrade of the analyzer, run `shockharness skills update
--agent <agent>` in the same pull request: unedited skill files are rewritten,
edited ones are kept and reported as conflicts. Details, the adapter table
with the verified destination paths, and the manifest format are in
[`skills.md`](skills.md). The README's "Adopting ShockHarness" section is the
short, self-contained form of this document, written for an agent reading it
over HTTP; every skill carries the same section.

### Edit-time feedback (Claude Code)

Pre-commit and CI are late: by then the agent has moved on and the fix is a
second task. With `--hook`, `skills install --agent claude` also adds a
`PostToolUse` hook to the project's `.claude/settings.json`:

```bash
shockharness skills install --agent claude --hook
```

```json
{"hooks": {"PostToolUse": [{"matcher": "Edit|Write|MultiEdit|Bash", "hooks": [
  {"type": "command", "timeout": 60,
   "command": "shockharness hook claude-code post-edit --root \"$CLAUDE_PROJECT_DIR\""}]}]}}
```

After every edit, `shockharness hook claude-code post-edit` reads the tool call
on stdin and analyzes what it changed under the project's configuration (with
the cache: about half a second on this repository). For Edit, Write and
MultiEdit that is the file the call names. For a shell command, which may change
any file, it is the source files `git status` shows as modified, added or
untracked whose content differs from what the hook last analyzed. Agents often
write files through the shell (every builder in the under-the-gate experiment
did), and a hook on Edit/Write alone never sees those. When the files have
findings of `--fail-on` severity or worse (`warning` by default), the hook
writes them to stderr and exits 2, which Claude Code shows to the agent while
the edit is still in its context. A clean file, a file outside the project, a file that is not
source or one the configuration does not include exits 0 silently; malformed
input exits 1 (a notice to you, not to the agent). Outside a git repository,
shell edits are not checked, and the run log says so.

The hook keeps two files in the cache directory (`.shockharness-cache/hook/`):
`state.json` (the content hash of each file it last analyzed, so a file is not
reported twice for the same content) and `runs.jsonl` (one line per run: time,
tool, files analyzed, findings, exit code, notes and I/O problems), so "clean"
and "never ran" can be told apart. `skills install --hook` updates the matcher
of a hook installed by an earlier version. The hook is appended to any `PostToolUse` hooks already
there, never replaces them, and is added once. It needs `shockharness` on the
`PATH` hooks run with; for a virtual environment, edit the command to its
path.

Only the edited file is analyzed, so the cross-file rules see that file alone:
`check` and `gate` in CI stay the authority.

## 8. Acceptance checks this repository runs

* The wheel builds, installs into a fresh venv, and exposes `shockharness` on `PATH` (`package` job).
* The Python example and the JavaScript example pass `check .` with the local
  wheel, fail with exit 1 after one injected violation, and fail
  `gate --base HEAD~1 --head HEAD` on the commit that introduced it
  (`consumer-examples` job, `scripts/consumer_upgrade_check.py`); the install
  uses `--no-index` so the PyPI release can never stand in for the checkout.
* `shockharness version` equals the wheel's version after installation.
* The example workflows call the reusable workflow pinned to a tag, with a
  pinned analyzer version, and the two pins of the Python example agree
  (`tests/unit/test_consumer_script.py`, `tests/unit/test_workflows.py`).
* The seven skills install for `claude`, `codex` and `generic` in a fresh
  directory, `skills update --check` then exits 0, and every reference
  solution of the eval corpus scores clean (`skill-evals` job,
  `evals/run_evals.py --reference`).
