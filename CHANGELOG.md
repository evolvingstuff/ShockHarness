# Changelog

All notable changes to ShockHarness. Format follows Keep a Changelog; versions
follow Semantic Versioning. The report `schema_version` is tracked separately.

## [Unreleased]

### Added
- Milestone G: four vendor-neutral agent skills shipped as package data
  (`shockharness/skills/<name>/SKILL.md`, open Agent Skills format with
  `name`/`description` frontmatter): `write-compliant-code`,
  `fix-violations`, `refactor-complexity`, `pre-commit-review`. Each has
  compliant and non-compliant Python and JavaScript examples, exact CLI
  invocations, a corrective workflow, a checklist, and an "Adopting
  ShockHarness" section identical to the README's (enforced by a test).
  `refactor-complexity` states that `CPLX001`-`CPLX005` are not implemented.
- `shockharness skills list|show|install|update`. `install --agent
  claude|codex|generic [--project PATH] [--user] [--force]` writes the skills
  (claude: `.claude/skills`, codex: `.agents/skills`, generic: `--project DIR`
  itself plus a printed `AGENTS.md` pointer line) and a manifest
  `.shockharness-skills.json` (schema version 1: agent, package version,
  SHA-256 per file); it refuses to overwrite without `--force` (exit 2) and
  touches nothing outside the destination. `update` rewrites files whose hash
  still equals the manifest, restores missing ones, adds new skills, reports
  removed ones, leaves edited files alone and reports each as a conflict with
  the remediation (exit 1 while a conflict remains); `update --check` writes
  nothing and exits 1 on any drift. Three new declared exception boundaries in
  `skills/install.py` (`OSError`, `UnicodeDecodeError`,
  `json.JSONDecodeError`).
- Skill evaluation corpus under `evals/`: eight paired tasks (four Python,
  four JavaScript) with prompt, starting files, behavioral tests, expected
  outcome and a clean reference solution; `evals/run_evals.py` (standard
  library only, one declared `MAGIC001` override) scores candidate directories
  by unsuppressed findings per rule, test exit code and suppressions added,
  and writes a JSON scorecard. CI scores the reference solutions and
  round-trips `skills install` / `update --check` for all three agents on
  ubuntu. The sdist carries `evals/`.
- README "Adopting ShockHarness": a self-contained guide for an agent reading
  the README over HTTP (pinned `uv tool install` / `uvx` / `pip` forms,
  `init`, the four onboarding paths, direct and reusable CI steps with the
  Dependabot snippet, `skills install`, and a verification table), with
  absolute links only. `docs/skills.md` is new; `docs/integration.md` gains a
  skills section.
- `--exit-zero` on `check` (and the `scan` alias) and `gate`: an advisory
  run. The report, severities, gate verdict text and every count are
  unchanged; only the process exit code is 0 where the verdict would have
  returned 1. Exit 2 (configuration, usage) and exit 3 (tool failure, strict
  parse failure) are never masked. The run is visible as `gate.advisory`
  (JSON and diff reports, both schemas, additive), a `shockharness: advisory
  run (--exit-zero): gate verdict FAIL reported as exit 0` line in text, and
  the `advisory` SARIF run property; the SARIF invocation `exitCode` is the
  process exit code while `properties.gate.exit_code` keeps the verdict's.
  Deliberately a CLI-only flag, not a configuration key: the configuration
  form is `gates.new_hard_violations = "warn"`. `docs/configuration.md` gains
  "Adopting ShockHarness on an existing codebase" comparing the four onboarding
  paths (baseline, `gates.new_hard_violations = "warn"`, `profile =
  "minimal"`, `--exit-zero`).
- Milestone F (distribution half). `shockharness check` is the canonical
  analysis command (identical arguments and behaviour to `scan`, which stays as
  a hidden alias); `shockharness version` prints the same string as
  `--version`.
- Built-in profiles shipped as package data (`shockharness/profiles/*.toml`),
  selected with `profile = "strict" | "recommended" | "minimal"`: `strict` is
  the bundled defaults; `recommended` reports `DEF003`/`DEF004` at review;
  `minimal` caps `MAGIC001`, `EXC001`-`EXC003` and `DEF001`-`DEF006` at
  review, sets `parse_errors = "warn"` and disables complexity. Precedence:
  bundled defaults < profile < repository configuration < command-line
  overrides. Every profile below `strict` is a policy deviation in every
  report and in `config validate`; `config effective` records profile keys
  with origin `profile:<name>`.
- `rules.magic_numbers.severity`, `rules.exceptions.severity`,
  `rules.defaults.severity` (`"error"` | `"review"`): a per-section cap that
  turns error findings into review findings; each cap is a reported deviation.
- The only two command-line overrides, on every configuration-loading command:
  `--profile NAME` (replaces the profile layer; the repository's other keys
  still apply) and `--parse-errors fail|warn`. Both are recorded with origin
  `cli_override`, noted in the report, and part of the configuration digest.
- `shockharness.toml` is accepted alongside `.shockharness.toml` at the
  dedicated tier; both present in one root is a configuration error naming
  both files.
- `init --profile recommended|minimal` writes a short file selecting the profile.
- Release automation: `.github/workflows/publish.yml` (tag `v*` -> full CI
  workflow -> build wheel and sdist -> tag equals `version.py` -> PyPI trusted
  publishing with `id-token: write`, environment `pypi`, no stored token);
  `docs/releasing.md` with the one-time PyPI steps and the per-release steps.
- Reusable consumer workflow `.github/workflows/check.yml` (`workflow_call`;
  inputs `shockharness-version` (required), `config`, `base`,
  `python-version`; SARIF upload to code scanning; permissions
  `contents: read`, `security-events: write` only); `.github/dependabot.yml`
  for this repository; `docs/integration.md` (pinning to a tag and to a SHA,
  Dependabot snippet, where the pin may live).
- Consumer examples `examples/python` (dev dependency pinned to `0.1.0a1`)
  and `examples/js` (analyzer in an isolated tool environment, never an npm
  dependency), each with a policy file, a workflow and one deliberate
  suppressed finding; `scripts/consumer_upgrade_check.py` (stdlib only)
  copies each into a throwaway git repository, installs the wheel built from
  the checkout, and asserts `check` exits 0, then 1 after one injected
  violation, and `gate --base HEAD~1 --head HEAD` exits 1; run by CI on ubuntu.
- `effective_profile` is also in SARIF run properties, next to
  `config_deviations`.
- Milestone F (analysis half): stable finding fingerprints (`findings[].fingerprint`;
  rule ID, path, enclosing scope, whitespace-free evidence, occurrence index)
  that survive line moves and reformatting; `shockharness baseline create PATH...
  --output FILE` writing a reviewed, byte-stable baseline
  (`schemas/baseline-v1.schema.json`) that is never updated automatically;
  `--baseline FILE` on `scan` and `gate` with `gates.legacy` semantics
  (`baseline`: matched findings listed and counted but not gating; `ignore`:
  listed, not counted; `fail`: baseline recorded but not applied); stale
  baseline entries reported under `gate.baseline.stale`; `evaluate_gate` and
  `apply_baseline` in the library API.
- `shockharness diff --base REF --head REF` (reporting only) and
  `shockharness gate --base REF --head REF` (exit 1 only on new hard
  violations): both revisions resolved and exported with local git only, full
  trees analyzed, findings classified new / fixed / unchanged by fingerprint,
  provenance (both commits, config digest, tool version) in the report
  (`schemas/diff-v1.schema.json`).
- SARIF 2.1.0 output (`--format sarif`) for `scan`, `diff`, and `gate`: one
  run, every registered rule with full descriptions, results with level mapping
  (error, warning, review/note -> note), root-relative URIs, exclusive end
  columns, `partialFingerprints` carrying the baseline fingerprint, in-source
  suppressions, and `baselineState` when a baseline or base revision applies.
- `metrics.history` in every CLI report: per-file commit count, author count,
  first and last change, and co-change pairs with support and directional
  confidence, read from local `git log` over `history.horizon_days` anchored
  on the head commit date; `history.enabled`, `history.horizon_days`,
  `history.min_support` configuration keys; explicit `unavailable`,
  `disabled`, and `not_collected` statuses with reasons; `hotspots` is `null`
  with a reason until Milestone E provides complexity.
- Six declared exception boundaries: reading a baseline file (`OSError`,
  `UnicodeDecodeError`, `json.JSONDecodeError`) and the git subprocess
  (`subprocess.CalledProcessError`, `OSError`, `UnicodeDecodeError`).

### Changed
- **`policy_profile` is renamed to `effective_profile`** in the JSON report,
  the diff report, both JSON schemas and SARIF run properties (specification
  section 20, decision 13). `schema_version` stays `"1"`: no tagged release
  has shipped the old field (0.1.0a1 was published only to claim the name and
  predates the schema's first tagged release), so the rename is made before
  schema v1 is published rather than versioned around.
- The text report's `config:` line names the effective profile; `config
  validate` prints it.
- CI, the pre-commit hook, the README and the docs invoke `shockharness
  check`; the self-gate and Ruff also cover `scripts/`.
- Report schema (still `schema_version` 1, additive): `findings[].fingerprint`,
  `findings[].baseline`, `gate.baselined`, `gate.new_hard_violations`,
  `gate.baseline`, `execution_summary.baselined`, `metrics.history`. The gate
  verdict is driven by `new_hard_violations`; without a baseline it equals
  `hard_violations` as before.
- `--format sarif` no longer exits 2; `evaluate_gate` no longer raises
  `UnsupportedFeatureError` for a baseline (it rejects anything that is not a
  `Baseline` with a `UsageError`).

## [0.1.0a1] - 2026-10-14

First public alpha, published to PyPI to claim the `shockharness` name.
Contains Milestones A through D: MAGIC001, EXC001-EXC003, DEF001-DEF006,
SUPP001/SUPP002, configuration validation, text and JSON reports, and the
`scan`, `config`, `rules`, and `init` commands. No baselines, diff, SARIF,
complexity metrics, or skills yet; see `coverage.rules_not_implemented` in
every report.

Everything listed under "Added" below shipped in this version.

### Added
- Milestone A: package skeleton, MIT license, configuration schema with full
  shape and semantic validation, precedence (`--config` > `.shockharness.toml` >
  `pyproject.toml` > bundled defaults), rule registry with every specified rule
  ID, diagnostic and report models, `scan`, `config validate`, `config effective`,
  `rules list`, `rules explain`, `init`, exit-code contract, GitHub Actions matrix.
- Milestone B: Python (`ast`) and JavaScript (tree-sitter) adapters with
  byte-to-character column mapping, explicit parse-failure propagation,
  `MAGIC001` (value-based 0/1, folded unary sign, annotations flagged),
  `SUPP001`/`SUPP002` inline suppression checks, per-path overrides,
  configuration-file exemption, JSON report (`schema_version` 1) and text output.
- Milestone C: catch facts in the IR (exception identities with
  exact/approximate/unresolved confidence, handler body classification,
  try-body operation attribution) for Python `except`/`except*` and JavaScript
  `catch`, `.catch(handler)`, `.then(ok, handler)`; `EXC001` forbidden catch
  (boundary whitelist, fail-closed on bare/unresolved identities, JavaScript
  instanceof-guard convention), `EXC002` suppressed or converted exception,
  `EXC003` broad try scope; `rules.exceptions.transparent_rethrow` (default
  false); boundary `exception` names validated as dotted class names; every
  boundary and `transparent_rethrow` reported under `config.deviations`.
- Milestone D: default facts in the IR (`DefaultFact`: family, kind, subject,
  fallback, constant-shapedness, syntactic context, confidence) extracted by
  `ir/python_defaults.py` and `ir/javascript_defaults.py`; `DEF001` parameter
  and dataclass-field defaults, `DEF002` mapping/attribute/property fallbacks
  (plus the implicit `None` of `.get(key)` as a review finding), `DEF003`
  truthiness fallbacks (review by default; Boolean logic excluded), `DEF004`
  nullish fallbacks, `DEF005` exception-to-default (literal returns and
  one-step static traces to module constants and one-return helpers), `DEF006`
  configuration fallbacks (`os.getenv`/`os.environ`/`process.env` in every
  spelling); new `rules.defaults` keys `dataclass_fields`, `nullish_fallbacks`,
  `configuration_fallbacks` (all `forbid`); loosened modes reported under
  `config.deviations`; 13 golden fixtures and 25 unit tests; `safe_autofix` is
  false for every finding.

### Changed
- `EXC002` no longer reports the `return_fallback` classification while `DEF005`
  is active: the handler is reported once, as `DEF005`, with the EXC002
  classification named in the message. Disabling `DEF005` restores the EXC002
  finding. Golden expectations for the eleven affected handlers changed rule ID
  only.
- The tool's own code was brought under `DEF002`/`DEF004`: three `setdefault`
  accumulators became explicit membership checks, the report's
  `discovery`/`explicit_targets_excluded` fields are built with an explicit
  branch, and nineteen `x if x is not None else v` expressions on parser fields
  became either explicit branches (genuinely optional values: import aliases,
  `from . import`, source segments) or assertions of grammar invariants (fields
  tree-sitter and `ast` always populate). A Python `SyntaxError` position is now
  recorded only when the interpreter reports both a line and a column; before,
  a missing column was silently replaced by column 1.
- The arities that distinguish `getattr(o, a, v)` and `m.get(k, v)` from plain
  lookups are named in `constants.py`.
- The tool's own boundaries were narrowed to satisfy `EXC003`: config decoding
  and TOML parsing are two `try` blocks, analyzed-file decoding is bound before
  the result is returned, and comment tokenization materializes the token list
  in the one protected call. Behaviour is unchanged.

### Dependencies
- `tree-sitter` 0.25.x (MIT) and `tree-sitter-javascript` 0.25.x (MIT). Pinned
  as a tested pair; language ABI 15. `tree-sitter` 0.26.0 is excluded: with
  CPython 3.14 it segfaults when walking trees nested deeper than about 200
  levels (CPython 3.13 with 0.26.0 and CPython 3.14 with 0.25.2 are both fine).
  The 300-deep nesting test in `tests/unit/test_javascript_adapter.py` guards this.
