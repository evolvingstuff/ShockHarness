# ShockHarness

A strict, deterministic static-analysis quality gate for Python and JavaScript.
Its one idea: unexpected failures, missing information, and unexplained
decisions must not silently become apparently valid program behavior.

Three default-on hard policies:

1. **Exception transparency.** No catch except at narrow, explicitly approved
   external boundaries. No catch-and-continue, no success-shaped fallbacks.
2. **No implicit defaults.** No fallback values for missing required data, no
   function-parameter defaults in strict mode.
3. **No magic numbers.** Every numeric literal in executable code must be
   exactly `0` or `1`. `range(2)` is a violation. The tool invents no exemptions.

Plus a separate, advisory complexity family (cyclomatic, cognitive, nesting,
NPath, call graph, churn). Hard violations are never averaged into a score.

ShockHarness complements Ruff and ESLint; it is not a formatter or a general
linter. It runs offline, needs no LLM, and never uploads source.

## Status

Pre-release. Milestones A (skeleton and contracts) and B (parsers and
`MAGIC001`) are implemented. Exception rules, default rules, complexity,
baselines, SARIF, and agent skills are registered but **not yet implemented**;
every report lists them under `rules_not_implemented` so a clean run never
implies coverage the tool does not have. See `STATUS.md` for exact evidence.

## Install

Requires Python 3.11+. Runtime dependencies are `tree-sitter` and
`tree-sitter-javascript` only.

```bash
pip install shockharness
```

From a checkout:

```bash
uv pip install -e ".[dev]"
```

## Use

```bash
shockharness init                       # writes .shockharness.toml (strict profile)
shockharness config validate            # exit 0 if the configuration is valid
shockharness config effective           # merged config with per-key origins
shockharness scan src/                  # human-readable report, exit = gate status
shockharness scan src/ --format json --output report.json
shockharness rules list
shockharness rules explain MAGIC001
```

Exit codes: `0` gates pass, `1` policy violations, `2` invalid configuration or
invocation, `3` internal error or (with `parse_errors = "fail"`) a file that
could not be parsed. A report is still produced when the gate fails.

Example:

```text
src/client.py:12:11: MAGIC001 error: Numeric literal 30 has no permitted justification in executable code  [timeout = 30]
src/client.py:20:16: MAGIC001 error: Numeric literal 2 has no permitted justification in executable code  [for i in range(2):]

shockharness 0.1.0: 1 file(s), 1 analyzed, 0 failed; 2 finding(s), 0 suppressed
  by severity: error=2
  rules applied: MAGIC001, SUPP001, SUPP002
  rules not implemented (not analyzed): MAGIC002, EXC001, EXC002, EXC003, DEF001, ...
gate: FAIL (exit 1)
  2 hard violation(s) and gates.new_hard_violations = "fail"
```

## Configuration

Either `.shockharness.toml` or a `[tool.shockharness]` table in
`pyproject.toml` (the dedicated file wins and the shadowed table is reported).
Unknown keys, bad types, unknown rule IDs, and invalid globs are errors, never
ignored. Every rule can be disabled; every disable is listed in the report.

```toml
[tool.shockharness]
profile = "strict"
include = ["src/**/*.py", "src/**/*.js"]
exclude = ["**/node_modules/**", "**/.venv/**"]
parse_errors = "fail"

[tool.shockharness.rules.magic_numbers]
enabled = true
allowed_values = [0, 1]
allow_unary_negative_one = false

[[tool.shockharness.overrides]]
paths = ["tests/**"]
disable = ["MAGIC001"]
reason = "Fixtures encode literal expected outputs"
```

Inline suppressions need an exact rule ID and a reason, on the same line:

```python
status = 404  # shockharness: ignore[MAGIC001] reason="RFC 9110 section 15.5.5"
```

A malformed suppression is a `SUPP001` error; one that silences nothing is a
`SUPP002` warning. `--no-inline-suppressions` disables them for centrally
governed policies.

See `docs/` for configuration, rules, architecture, and limitations.

## Library

```python
from pathlib import Path
from shockharness import analyze_paths
from shockharness.analysis import AnalysisOptions
from shockharness.config import load_config

config = load_config(Path("."), None)
report = analyze_paths([Path("src")], Path("."), config, AnalysisOptions(inline_suppressions=True))
print(report.gate.status, len(report.findings))
```

## Development

```bash
uv pip install -e ".[dev]"
pytest -q
ruff check src tests && ruff format --check src tests
shockharness scan src tests     # the tool gates its own source
```

ShockHarness runs on itself as a hard CI gate. Its one `MAGIC001` exemption is
`src/shockharness/constants.py`; its declared exception boundaries are listed in
`.shockharness.toml` with reasons.

## License

MIT. See `LICENSE`.
