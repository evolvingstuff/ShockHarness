# ShockHarness: Distribution and Multi-Repository Integration

**Status:** Design brief, reviewed 2026-10-14. Binding decisions are in `agent_code_integrity_project_spec.md` section 20; where this brief and the specification differ (command names, exit codes, config key names, profile names, skill names), the specification wins.  
**Scope:** How to package, version, install, configure, and update ShockHarness across independent Python, JavaScript, and mixed-language repositories.  
**Naming:** `shockharness` is a working package/CLI name, subject to registry availability.

## 1. Decision

Distribute ShockHarness as a **standalone, versioned Python CLI package**, with an optional **reusable GitHub Actions workflow** and **versioned agent skills**. Do **not** use Git submodules as the default integration mechanism.

ShockHarness runs as a **development-time tool**, not as part of the application's runtime. A JavaScript-only repository can run it through an isolated Python tool environment without adopting Python as an application dependency.

**Goals:**
- Maintain one canonical analyzer implementation.
- Allow each consumer repository to pin and independently upgrade its version.
- Propagate releases through automated dependency/update PRs.
- Keep per-repository policy choices in local configuration.
- Provide stable machine-readable diagnostics and deterministic CI failure behavior.
- Update bundled agent instructions without overwriting local customizations.

## 2. Publishing and invocation

Build a standard Python package (`pyproject.toml`) with a console entry point named `shockharness`. Publish tagged releases to PyPI after CI and release checks. Use semantic versioning and a changelog; document any rule or default-policy changes prominently.

Example installation and one-off invocation (once published):

```bash
uvx --from shockharness==0.3.0 shockharness check .
# or install in a dedicated tooling environment:
uv tool install 'shockharness==0.3.0'
shockharness check .
```

For development before publication, support installation from an **immutable Git commit** or local checkout, but keep the CLI contract identical. Do not treat branch-tip installation as a reproducible CI pin.

Required CLI surface:

```text
shockharness check PATH [--config FILE] [--format text|json|sarif]
shockharness diff BASE...HEAD [--config FILE] [--format text|json|sarif]
shockharness gate [--base REF] [--config FILE]
shockharness explain RULE_ID
shockharness version
shockharness skills install --agent codex|claude [--project PATH]
shockharness skills update --agent codex|claude [--project PATH]
shockharness config validate [--config FILE]
```

Clearly document exit codes. Adopted (spec section 10): `0=pass`, `1=policy violations`, `2=invalid configuration or invocation`, `3=internal error or strict-mode parse failure`. Ensure failures in parsing, rule execution, or config loading do **not** silently return success.

## 3. Per-project configuration and shared profiles

Each consuming repository owns a checked-in `shockharness.toml` (or equivalent supported format). Default policy should be strict, with the magic-number rule **enabled** and only `0` and `1` permitted as numeric literals in executable code by default. Declarative files such as CSS and explicitly selected configuration/fixture paths are outside that rule's normal scope.

Illustrative configuration **(proposed schema, not yet implemented)**:

```toml
[shockharness]
profile = "strict-agent"

[rules.magic_numbers]
enabled = true
allowed_values = [0, 1]

[rules.exception_handling]
enabled = true
mode = "whitelist"

[rules.implicit_defaults]
enabled = true

[rules.complexity]
enabled = true
max_cognitive = 15
```

Ship versioned built-in profiles with the package, such as `strict-agent`, `recommended`, and `minimal`. Define merge precedence explicitly: **built-in defaults < named profile < repository config < explicit CLI overrides**. Expose `config show --effective` or equivalent so agents and users can inspect resolved policy. No remote mutable profile fetch during ordinary CI checks.

For narrowly scoped exemptions, require explicit rule IDs, a code location/path pattern, and a human-readable rationale. Avoid blanket disabling to make a failing build pass.

## 4. CI integration

Provide two supported approaches:

**A. Direct CLI invocation (simplest and most portable).** Each repository installs a pinned ShockHarness version and runs `shockharness gate`. This should work with GitHub Actions, GitLab CI, local hooks, and other CI systems.

**B. Reusable GitHub Actions workflow (optional convenience).** Publish `.github/workflows/check.yml` in the ShockHarness repo using `workflow_call`. Example consumer:

```yaml
jobs:
  shockharness:
    uses: evolvingstuff/ShockHarness/.github/workflows/check.yml@v0.3.0
    permissions:
      contents: read
```

The example is a proposed workflow and assumes it has been implemented and released. For strongest reproducibility/security, pin the workflow to a full commit SHA instead of a movable tag. The workflow should accept inputs for analyzer version, config file, and diff base. Keep its permissions minimal; untrusted pull-request code must not gain access to secrets.

**Pin analyzer and workflow versions separately.** A reusable workflow tag alone must not imply that the analyzer binary is pinned unless the workflow explicitly pins it. Document which source of truth controls the analyzer version.

## 5. Updating multiple repositories

Preferred update sequence:

1. Develop and test a change in the standalone ShockHarness repository.
2. Release a versioned package and, when relevant, a corresponding reusable-workflow tag.
3. Let Dependabot or Renovate create version-bump PRs in consuming repositories. Explicitly configure updates for whatever version references you choose (for example, Python tooling dependencies, GitHub Actions refs, and centrally managed config).
4. Run consumer CI against the new analyzer, including existing tests and ShockHarness gates.
5. Merge after review; allow individual repositories to defer policy-changing upgrades.

Do not update every repository to `latest` automatically. For intentional broad rollouts, use a separate scripted PR creation workflow that opens reviewable PRs across repositories rather than directly committing updates.

If using `uvx` with literal version references in workflows, verify that the chosen updater recognizes that syntax. If it does not, centralize the pin in an updateable dependency manifest or automate explicit PR-based replacements; don't assume Dependabot will discover arbitrary shell strings.

## 6. Agent skills distribution

Ship agent skills inside the package under a stable resource directory. Offer explicit installation/update commands for supported agents. At minimum, include:

- `write-compliant-code`: generate code that honors exception, fallback, and literal rules.
- `fix-violations`: interpret analyzer findings; don't conceal errors merely to make the check pass.
- `complexity-refactoring`: improve complexity without superficial extraction or behavior changes.
- `pre-commit-review`: run checks and tests before claiming work is complete.

Installation should copy or link to documented locations appropriate for each supported agent, and must not overwrite local user edits silently. Use a manifest recording installed skill names, source package version, and file hashes. `skills update` should safely update unchanged generated files, preserve edited files, and report conflicts with remediation instructions. Keep project-specific agent instructions separate from generated skills.

## 7. Version and compatibility contracts

Version these interfaces deliberately:

- CLI commands/flags and exit codes.
- JSON/SARIF finding schema, rule IDs, severities, and source locations.
- Config schema, profile names, merge semantics, and suppressions.
- Rule behavior and defaults (especially new hard failures).
- Agent skills and their installation manifests.
- Supported Python/JavaScript language syntax and runtime/tool prerequisites.

Include `tool_version`, `schema_version`, and `effective_profile` in machine-readable output. Treat tightening a default hard gate as a potentially breaking change and communicate it accordingly. Support a mechanism to compare results to a checked-in baseline for incremental adoption of legacy codebases.

## 8. Minimum acceptance tests

- Package builds a wheel, installs into a fresh environment, and exposes `shockharness` on PATH.
- Analyzer runs on a Python-only repository and a JavaScript-only repository without becoming an application runtime dependency.
- `check`, `gate`, and `diff` return predictable exit codes and machine-readable output.
- Default magic-number policy rejects a literal `2` in executable code but permits `0` and `1`; project config can turn this rule off.
- Exception and implicit-default checks follow configured policy.
- Invalid configuration and analyzer crashes fail closed with actionable error messages.
- A sample GitHub Actions caller executes a pinned released analyzer.
- A simulated version upgrade changes analyzer output only as documented; CI shows regressions clearly.
- Skills install and update reproducibly, preserving user modifications.
- CI verifies source distributions, wheels, and published version metadata.

## 9. Coding-agent implementation order

1. Implement packaging, console entry point, configuration parsing, and deterministic exit codes.
2. Implement `check` and structured findings; wire up Python/JavaScript analysis engines.
3. Implement default strict rules and fixture-based tests.
4. Add project config, built-in versioned profiles, suppression policy, and `config validate`.
5. Add baseline/diff gates and JSON/SARIF schemas.
6. Add release automation and integration examples for Python/JavaScript projects.
7. Add reusable GitHub Actions workflow and version-pin/update documentation.
8. Add versioned agent skills and safe installation/update workflows.
9. Test a real staged upgrade through two independent example consumer repositories.

**Do not implement Git submodule integration unless a concrete consumer has a requirement that the package/workflow distribution cannot meet.**

## 10. Definition of done

A developer can add ShockHarness to a new Python or JavaScript repository with a pinned tool version, a small checked-in policy file, and one CI command. A new ShockHarness release can trigger reviewable upgrade PRs across participating repositories, and agent skills can be refreshed safely. Consumer projects keep their own policy overrides and remain independently reproducible.
