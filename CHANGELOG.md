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
