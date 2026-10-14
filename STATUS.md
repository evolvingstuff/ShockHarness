# STATUS

Implementation log for ShockHarness, kept per the specification's completion
protocol (section 15). Every claim below was produced by running the command
shown; nothing is reported as passing that was not run.

## Milestone A: skeleton + contracts — DONE (2026-10-14)

Delivered: `pyproject.toml` (hatchling, Python 3.11+, MIT), `LICENSE`,
`README.md`, `CHANGELOG.md`, GitHub Actions matrix (ubuntu/macos/windows x
3.11-3.14 plus a wheel build job), `.pre-commit-hooks.yaml`, configuration
schema with full shape and semantic validation, precedence
(`--config` > `.shockharness.toml` > `pyproject.toml` > bundled defaults),
rule registry with every specified rule ID and implementation status,
diagnostic/report models, `schemas/report-v1.schema.json`, CLI `scan`,
`config validate`, `config effective`, `rules list`, `rules explain`, `init`,
exit-code contract (0/1/2/3), text and JSON renderers, library API
(`analyze_source`, `analyze_paths`, `evaluate_gate`).

## Milestone B: parsers + MAGIC001 — DONE (2026-10-14)

Delivered: Python adapter (`ast` + `tokenize`, iterative traversal, byte to
character columns, scope names, annotation marking), JavaScript adapter
(tree-sitter, any `ERROR`/`MISSING` node is a parse failure, iterative
traversal, JSX/template/BigInt/legacy-octal/separators), `MAGIC001` (value-based
0/1, folded unary sign, `-0` flagged, annotations flagged), `SUPP001`/`SUPP002`
inline suppression rules, per-path overrides with recorded origin,
configuration-file exemption with recorded reason, golden fixture corpus (26
files, expectations reviewed by hand), property/metamorphic/fuzz tests, CLI
tests, self-compliance test.

Acceptance criterion from the spec, verified by
`tests/cli/test_cli.py::test_milestone_b_acceptance_python_and_js`:
`range(2)` fails in Python; `for (let i = 0; i < 2; i++)` fails in JS; both
pass with `rules.magic_numbers.enabled = false` and the JSON report records
the disable under `coverage.rules_disabled_globally`, `config.deviations`, and
every file's `rules_disabled`.

Milestones A and B were built in one pass because `scan` cannot be exercised
end to end without a parser and a rule; they are committed together.

## Evidence (all run 2026-10-14 on macOS arm64)

```text
$ ruff check src tests && ruff format --check src tests
All checks passed!
48 files already formatted

$ pytest -q                      # CPython 3.14.7
224 passed in 1.45s
$ pytest -q                      # CPython 3.13.1
224 passed in 1.65s
$ pytest -q                      # CPython 3.12.8
224 passed in 1.63s
$ pytest -q                      # CPython 3.11.11
224 passed in 1.39s

$ shockharness scan src tests    # self-compliance, all four interpreters
gate: PASS (exit 0)

$ shockharness config validate
shockharness: configuration is valid (dedicated: .../.shockharness.toml)

$ python -m build
Successfully built shockharness-0.1.0.tar.gz and shockharness-0.1.0-py3-none-any.whl

$ uv venv clean --python 3.12 && uv pip install dist/shockharness-0.1.0-py3-none-any.whl
$ clean/bin/shockharness --version
shockharness 0.1.0
$ clean/bin/shockharness scan src/b.js --format json     # smoke corpus, 8 findings, gate fail
```

Sample text output on a mixed smoke corpus (Python file with violations and
suppressions, JS file, one unparseable file):

```text
src/a.py:2:11: MAGIC001 error: Numeric literal 30 has no permitted justification in executable code  [TIMEOUT = 30]
src/a.py:8:5: MAGIC001 error: Numeric literal 0x1F has no permitted justification in executable code  [w = 0x1F  # shockharness: ignore[MAGIC001] reason="RFC 1234 flag mask"]  (suppressed: RFC 1234 flag mask)
src/a.py:9:8: SUPP001 error: malformed suppression; expected shockharness: ignore[RULEID] reason="..."  [q = 7  # shockharness: ignore[MAGIC001]]
src/b.js:3:13: MAGIC001 error: Numeric literal -0 has no permitted justification in executable code  [const neg = -0; const el = <A size={2} b="3"/>;]
src/c.py:1:12: parse_error: SyntaxError: invalid syntax

shockharness 0.1.0: 3 file(s), 2 analyzed, 1 failed; 19 finding(s), 2 suppressed
  rules applied: MAGIC001, SUPP001, SUPP002
  rules not implemented (not analyzed): MAGIC002, EXC001, EXC002, EXC003, DEF001, ...
  analysis status: failed
gate: ERROR (exit 3)
  1 file(s) could not be analyzed and parse_errors = "fail"
```

## Failures observed during development (and what was done)

1. **Bundled defaults misplaced `overrides`** under `[gates]`; the first `scan`
   exited 3 with a traceback via the process boundary. Fixed; a test now
   asserts the bundled defaults' shape.
2. **Self-gate caught a real violation**: `match.group(2)` in
   `suppressions.py`. Replaced with named groups. The gate works on its author.
3. **Segmentation fault**: py-tree-sitter 0.26.0 on CPython 3.14 crashes when
   walking trees nested deeper than about 200 levels (CPython 3.13 with 0.26.0
   and CPython 3.14 with 0.25.2 are fine). Runtime pin is now
   `tree-sitter>=0.25.1,<0.26`; the 300-deep test guards the regression.
4. **Fuzzer found an undeclared boundary**: CPython's `tokenize` raises
   `UnicodeDecodeError` for `\r` followed by a multibyte character even when
   `ast.parse` succeeds. Now caught at the declared Python-adapter boundary and
   reported as a parse failure.
5. **IR literal order** from the Python adapter was reversed (stack traversal).
   IR literals and comments are now sorted by span in both adapters.
6. **Ruff reformatted two fixtures** before `tests/fixtures` was excluded from
   it, shifting golden lines. Fixtures restored; regenerated expectations
   diffed byte-identical against the reviewed set.

## Known limitations

See `docs/limitations.md`. Headline: only MAGIC001/SUPP001/SUPP002 produce
findings; Python syntax coverage equals the host interpreter; UTF-8 only; JS
bare-`\r` line breaks may shift line numbers; `.gitignore` is not consulted;
SARIF, baselines, diff mode, Git features, and skills are not built.

## Next tasks

- **Milestone C (exceptions)**: `EXC001`-`EXC003` for Python (`ast.Try`,
  `ast.TryStar`, handler type resolution via import/symbol table with
  confidence) and JavaScript (`catch` clauses, `.catch()` handlers), boundary
  matching against `rules.exceptions.boundaries`, broad-try detection. The
  repository's own `.shockharness.toml` already declares its boundaries so the
  self-gate will exercise the rule immediately.
- Decide `.gitignore` handling (spec: only if configured) and `-0` policy wording in docs if challenged.
- CI has not run yet (nothing pushed). The matrix is defined; first push will show Linux/Windows results.
