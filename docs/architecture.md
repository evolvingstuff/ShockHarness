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
Per-unit metrics over the control tree -> CPLX001-CPLX004, CPLX006     (complexity/{cyclomatic,cognitive,nesting,npath,size,metrics}.py, rules/complexity.py)
    |
Content-hash cache: per-file facts, findings and unit metrics, keyed by  (cache/store.py, cache/codec.py)
  tool version + config digest + host + language + SHA-256 of the bytes
    |
Cross-file pass: call graph, module edges, cycles, fan-in/out -> CPLX005 (complexity/{callgraph,coupling,assemble}.py)
    |
Suppressions -> attach / SUPP001 / SUPP002                            (suppressions.py)
    |
Fingerprints: rule + path + scope + evidence, occurrence index         (gating/baseline.py)
Baseline file / base revision -> legacy markers on findings            (gating/baseline.py, gating/diff.py)
Gate: counts, never averages; new hard violations drive the verdict    (gate.py)
Report: schema-versioned, deterministic ordering                       (report.py)
History: local git log -> churn, co-change, hotspots (file granularity) (history/git.py, hotspots.py, cochange.py)
Revision diff: per-unit complexity regressions, abstraction displacement (complexity/regressions.py)
    |
Renderers: text, JSON, SARIF 2.1.0                                     (output/)
```

Revision diff (`diff`, `gate --base/--head`): `gating/diff.py` resolves both
refs with local git, exports each whole tree with `git archive` into a
temporary directory, runs the per-file pipeline on each, and classifies
findings by fingerprint (new / fixed / unchanged). Unchanged findings are
marked legacy exactly like baseline matches before the gate runs.

## Design rules the code follows

**Fail visibly.** Every failure mode has a named, visible outcome: config
problems raise `ConfigError` (exit 2); bad invocations raise `UsageError`
(exit 2); unreadable, undecodable, or unparseable files get a per-file status
and zero findings, and `parse_errors = "fail"` turns any of them into exit 3;
anything unexpected prints a traceback and exits 3. No path turns a failure
into a passing result.

**Observations before policy.** Parser adapters produce `ModuleFacts`
(numeric literals with folded sign, comments, catch facts, default facts,
function facts, import facts, module bindings, parse failure). A function fact
is one *unit* (module body, class body, function, method, lambda, arrow) with
its language-neutral control tree, size counts, call sites as written, locals
and writes; the metrics read only the tree, so equivalent Python and
JavaScript produce equal numbers. A catch fact records the resolved exception identities with a
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
column, rule ID, message; IR literals by span; baseline entries by path, rule,
scope, evidence, occurrence; diff entries by finding then status. JSON and
SARIF output have sorted keys and no timestamps; the only dates are git commit
dates inside `metrics.history`, which are data, and the history horizon is
anchored on the head commit rather than the clock. Two runs over the same
inputs are byte-identical, with one declared exception: `coverage.cache`
(the cache's status and counters) differs between a cold and a warm run, and a
cache hit must reproduce the file's findings and metrics byte for byte; the
tests compare reports with that block removed.

**Positions.** Both parsers report UTF-8 byte columns. `SourceText` maps them to
1-based character columns; `end_column` is exclusive. Line breaks are CRLF, CR,
or LF. A UTF-8 BOM is stripped before parsing.

**Iterative traversal.** Both adapters walk with an explicit stack so deeply
nested input cannot exhaust the Python recursion limit; the control-tree
builders, the metric walks, NPath's post-order evaluation and Tarjan's SCC are
iterative for the same reason.

**Two-phase analysis.** `analysis.py` runs the per-file rules and measures the
units first, then builds the call graph over every parsed file (`CPLX005`
needs it), and only then applies suppressions and fingerprints, so a graph
finding is suppressed and baselined like any other. Metrics never reach the
gate except as `complexity_regressions`, a count the revision diff passes in.

**JavaScript parse failures.** tree-sitter recovers from errors; any `ERROR` or
`MISSING` node is a parse failure with the span of the first such node, and the
tree is not analyzed further.

**Git is a boundary.** `history/git.py` is the only module that runs a
subprocess. Every call is local and every failure comes back as data (a
`GitResult` with a reason): `diff`/`gate` turn it into a `UsageError`, history
metrics into `status = "unavailable"`. Reading a baseline file is the other
Milestone F boundary (`gating/baseline.py`).

**Self-compliance.** ShockHarness checks its own `src/`, `tests/` and
`scripts/` as a hard CI gate with `.shockharness.toml`. The only MAGIC001 exemption is
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
`hashlib`, `subprocess` and `tarfile` for git). Development: `pytest`, `hypothesis`, `ruff`, `build`.

`tree-sitter` 0.26.0 is excluded on purpose: with CPython 3.14 it segfaults when
walking trees nested deeper than about 200 levels. CPython 3.13 with 0.26.0 and
CPython 3.14 with 0.25.2 both work. A 300-deep nesting test guards this.

## Module map

| Module | Responsibility |
|---|---|
| `constants.py` | Every numeric constant (exit codes, schema version, caps); the one MAGIC001 exemption |
| `errors.py` | `ShockHarnessError`, `ConfigError`, `UsageError`, `UnsupportedFeatureError` |
| `defaults.toml` | Bundled defaults (the `strict` profile) |
| `profiles/*.toml` | Built-in profile overlays (`strict` empty, `recommended`, `minimal`) |
| `schema.py` | Field descriptors and shape validation with key paths; profile names and section severities |
| `config.py` | Source discovery (both dedicated filenames), layers (defaults < profile < source < CLI overrides) with origins, semantic checks, deviations, digest |
| `globs.py` | Glob validation and compilation |
| `roles.py` | File roles (H1): the six roles, their precedence, and the classifier over `file_roles` globs |
| `discovery.py` | Target resolution, walking, pruning, language routing |
| `source.py` | Line splitting, byte-to-character columns, evidence excerpts |
| `ir/model.py` | `Span`, `NumericLiteral`, `Comment`, `CatchFact`, `ExceptionIdentity`, `HandlerBody`, `TryStatement`, `DefaultFact`, `ControlNode`, `CallSite`, `FunctionFact`, `ImportFact`, `ModuleBinding`, `ParseFailure`, `ModuleFacts` |
| `ir/lines.py` | Logical line counting shared by both adapters |
| `ir/python_functions.py` | Python units: control tree, size, calls, locals, writes; imports and module bindings |
| `ir/javascript_functions.py` | JavaScript units, imports (`import`/`export ... from`/`require`) and module bindings |
| `complexity/cyclomatic.py`, `cognitive.py`, `nesting.py`, `npath.py`, `size.py` | One versioned convention each, over the control tree |
| `complexity/metrics.py` | Per-unit measurement, stable unit keys, file aggregates, the conventions block |
| `complexity/callgraph.py` | Import resolution among analyzed files, call-site classification (resolved / probable / unresolved), edge aggregation |
| `complexity/coupling.py` | Fan-in/out, iterative Tarjan SCC for module cycles, shared-mutable-state notes, `metrics.graph` shape |
| `complexity/assemble.py` | `metrics.complexity` + `metrics.graph` for one run, CPLX005 findings, disabled shapes |
| `complexity/regressions.py` | Per-unit regressions between two revisions; the experimental abstraction-displacement heuristic |
| `ir/python.py`, `ir/javascript.py` | Parser adapters |
| `ir/python_catches.py` | Python symbol table, exception identity resolution, handler classification, try-body attribution |
| `ir/javascript_catches.py` | JavaScript catch clauses, promise rejection handlers, instanceof guards, handler classification |
| `ir/python_defaults.py` | Python parameter/dataclass defaults, mapping/attribute fallbacks, `or`/`is None` fallbacks, environment fallbacks, DEF005 traces |
| `ir/javascript_defaults.py` | JavaScript parameter/destructuring defaults, `||`/`??`/ternary fallbacks, `process.env` fallbacks, DEF005 traces |
| `rules/registry.py` | Every rule ID with metadata and implementation status |
| `rules/severity.py` | The per-section `severity` cap shared by the rule families |
| `rules/magic_numbers.py` | MAGIC001 |
| `rules/exceptions.py` | EXC001-EXC003: boundary matching and the three verdicts |
| `rules/defaults.py` | DEF001-DEF006: mode-to-severity mapping, messages, DEF005/EXC002 hand-off, mode deviations |
| `rules/complexity.py` | CPLX001-CPLX004 and CPLX006 per unit, CPLX005 from the graph (one finding per cycle); messages carry value, threshold and convention |
| `suppressions.py` | Inline suppression parsing and SUPP001/SUPP002 |
| `findings.py` | `Finding` (with `status` violation/unknown, `fingerprint` and `baseline` marker), `SuppressionRecord` |
| `gating/baseline.py` | Fingerprints, baseline file model and validation, legacy marking under `gates.legacy` |
| `gating/diff.py` | Revision export and analysis, new / fixed / unchanged classification, `DiffReport` |
| `history/git.py` | The git subprocess wrapper (the only `subprocess` user) and log parsing |
| `history/hotspots.py` | `metrics.history`: per-file churn, horizon, explicit statuses, the hotspot score |
| `history/cochange.py` | Co-change pairs with support and directional confidence |
| `analysis.py` | Per-file phase, cross-file phase, suppressions/fingerprints phase; file roles, rule-disable resolution (config, overrides by path or role, the config-role exemption) |
| `gate.py` | Verdict and exit code; `gate.unknown` and per-family `fail_on_unknown` |
| `report.py` | Report assembly, coverage, sorting |
| `output/text.py`, `output/json.py`, `output/sarif.py` | Renderers (check reports and diff reports) |
| `api.py` | `analyze_source`, `analyze_paths`, `apply_baseline`, `evaluate_gate`, `with_history` |
| `cli.py` | Argument parsing (`check`, hidden `scan`, `version`, `--profile`/`--parse-errors`), dispatch, process boundary |
