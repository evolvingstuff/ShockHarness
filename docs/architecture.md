# Architecture

```text
CLI (cli.py) / Python API (api.py)
    |
Config: discovery + precedence + schema validation + merge + digest   (config.py, schema.py, globs.py)
    |
Discovery: targets -> include/exclude -> language router               (discovery.py)
    |
Per-file analysis                                                      (analysis.py)
    read bytes -> decode UTF-8 -> parser adapter -> ModuleFacts
    Python: ast + tokenize                                             (ir/python.py, ir/python_catches.py, ir/python_defaults.py)
    JavaScript: tree-sitter + tree-sitter-javascript                   (ir/javascript.py, ir/javascript_catches.py, ir/javascript_defaults.py)
    |
Rules over facts -> Findings                                           (rules/magic_numbers.py, rules/exceptions.py, rules/defaults.py)
Suppressions -> attach / SUPP001 / SUPP002                            (suppressions.py)
    |
Gate: counts, never averages                                           (gate.py)
Report: schema-versioned, deterministic ordering                       (report.py)
    |
Renderers: text, JSON                                                  (output/)
```

## Design rules the code follows

**Fail visibly.** Every failure mode has a named, visible outcome: config
problems raise `ConfigError` (exit 2); bad invocations raise `UsageError`
(exit 2); unreadable, undecodable, or unparseable files get a per-file status
and zero findings, and `parse_errors = "fail"` turns any of them into exit 3;
anything unexpected prints a traceback and exits 3. No path turns a failure
into a passing result.

**Observations before policy.** Parser adapters produce `ModuleFacts`
(numeric literals with folded sign, comments, catch facts, default facts, parse
failure). A catch fact records the resolved exception identities with a
confidence, the handler body classification, and each statement of the protected
`try` body with the one operation it could be attributed to. A default fact
records one value substitution: its family (parameter, mapping, truthiness,
nullish, exception, configuration), concrete kind, subject, fallback text,
whether the fallback is constant-shaped, the syntactic context (assignment,
return, argument, test, declaration), a confidence, and a one-line explanation.
Rules consume facts and never touch parser nodes; the boundary policy lives
entirely in `rules/exceptions.py` and the mode-to-severity mapping in
`rules/defaults.py`. The gate consumes findings and file statuses and never
re-reads source.

**Determinism.** Files are sorted by relative path; findings by path, line,
column, rule ID, message; IR literals by span. JSON output has sorted keys and
no timestamps. Two runs over the same inputs are byte-identical.

**Positions.** Both parsers report UTF-8 byte columns. `SourceText` maps them to
1-based character columns; `end_column` is exclusive. Line breaks are CRLF, CR,
or LF. A UTF-8 BOM is stripped before parsing.

**Iterative traversal.** Both adapters walk with an explicit stack so deeply
nested input cannot exhaust the Python recursion limit.

**JavaScript parse failures.** tree-sitter recovers from errors; any `ERROR` or
`MISSING` node is a parse failure with the span of the first such node, and the
tree is not analyzed further.

**Self-compliance.** ShockHarness scans its own `src/` and `tests/` as a hard
CI gate with `.shockharness.toml`. The only MAGIC001 exemption is
`constants.py`; declared exception boundaries list each `try/except` in the
tool with the exception it catches and why, and `EXC001`-`EXC003` enforce them:
every `try` in the tool wraps exactly one external call. `DEF001`-`DEF006`
enforce the absence of parameter defaults, mapping fallbacks, `or`/`is None`
fallbacks and environment defaults in the tool itself (tests may use parameter
defaults, by override). Where a tree-sitter or `ast` field is Optional only in
the type stubs, the code asserts the grammar invariant instead of substituting
a value.

## Dependencies

Runtime: `tree-sitter` 0.25.x and `tree-sitter-javascript` 0.25.x. Everything
else is the standard library (`argparse`, `tomllib`, `ast`, `tokenize`, `json`,
`hashlib`). Development: `pytest`, `hypothesis`, `ruff`, `build`.

`tree-sitter` 0.26.0 is excluded on purpose: with CPython 3.14 it segfaults when
walking trees nested deeper than about 200 levels. CPython 3.13 with 0.26.0 and
CPython 3.14 with 0.25.2 both work. A 300-deep nesting test guards this.

## Module map

| Module | Responsibility |
|---|---|
| `constants.py` | Every numeric constant (exit codes, schema version, caps); the one MAGIC001 exemption |
| `errors.py` | `ShockHarnessError`, `ConfigError`, `UsageError`, `UnsupportedFeatureError` |
| `defaults.toml` | Bundled strict profile |
| `schema.py` | Field descriptors and shape validation with key paths |
| `config.py` | Source discovery, precedence, semantic checks, merge with origins, digest |
| `globs.py` | Glob validation and compilation |
| `discovery.py` | Target resolution, walking, pruning, language routing |
| `source.py` | Line splitting, byte-to-character columns, evidence excerpts |
| `ir/model.py` | `Span`, `NumericLiteral`, `Comment`, `CatchFact`, `ExceptionIdentity`, `HandlerBody`, `TryStatement`, `DefaultFact`, `ParseFailure`, `ModuleFacts` |
| `ir/python.py`, `ir/javascript.py` | Parser adapters |
| `ir/python_catches.py` | Python symbol table, exception identity resolution, handler classification, try-body attribution |
| `ir/javascript_catches.py` | JavaScript catch clauses, promise rejection handlers, instanceof guards, handler classification |
| `ir/python_defaults.py` | Python parameter/dataclass defaults, mapping/attribute fallbacks, `or`/`is None` fallbacks, environment fallbacks, DEF005 traces |
| `ir/javascript_defaults.py` | JavaScript parameter/destructuring defaults, `||`/`??`/ternary fallbacks, `process.env` fallbacks, DEF005 traces |
| `rules/registry.py` | Every rule ID with metadata and implementation status |
| `rules/magic_numbers.py` | MAGIC001 |
| `rules/exceptions.py` | EXC001-EXC003: boundary matching and the three verdicts |
| `rules/defaults.py` | DEF001-DEF006: mode-to-severity mapping, messages, DEF005/EXC002 hand-off, mode deviations |
| `suppressions.py` | Inline suppression parsing and SUPP001/SUPP002 |
| `findings.py` | `Finding`, `SuppressionRecord` |
| `analysis.py` | Per-file pipeline and rule-disable resolution |
| `gate.py` | Verdict and exit code |
| `report.py` | Report assembly, coverage, sorting |
| `output/text.py`, `output/json.py` | Renderers |
| `api.py` | `analyze_source`, `analyze_paths`, `evaluate_gate` |
| `cli.py` | Argument parsing, dispatch, process boundary |
