# Changelog

All notable changes to ShockHarness. Format follows Keep a Changelog; versions
follow Semantic Versioning. The report `schema_version` is tracked separately.

## [Unreleased]

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

### Dependencies
- `tree-sitter` 0.25.x (MIT) and `tree-sitter-javascript` 0.25.x (MIT). Pinned
  as a tested pair; language ABI 15. `tree-sitter` 0.26.0 is excluded: with
  CPython 3.14 it segfaults when walking trees nested deeper than about 200
  levels (CPython 3.13 with 0.26.0 and CPython 3.14 with 0.25.2 are both fine).
  The 300-deep nesting test in `tests/unit/test_javascript_adapter.py` guards this.
