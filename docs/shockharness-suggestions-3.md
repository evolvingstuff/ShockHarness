# ShockHarness: third batch, after the 0.2.0 run (planned 0.3.0)

## Context

ShockHarness 0.2.0 was run on the same 906-file Python/JavaScript codebase as
the first two briefs. The maintainer's notes from that run are the source of
this document; the acceptance criteria were written by the lead session from
those notes, in the style of the earlier briefs. Items are in priority order.
Each item has acceptance criteria; add tests for every criterion and document
every new option in `docs/configuration.md` and `docs/rules.md`.

## 1. Capture managers bound to a name

**Observation.** `rules.exceptions.capture_managers` (0.2.0) recognizes a
capture manager only when it is written inline: `with M(T):`. The common form
binds it first, because the capture is inspected afterwards:

```python
capture = CapturedExceptionContext(ProcessLookupError, boundary="main.py:_is_process_running")
with capture:
    os.kill(pid, 0)
if capture.captured_exception is not None:
    ...
```

That codebase writes 81 of its 82 captures this way; 0.2.0 found the one
inline use. The same applies to `suppressor = contextlib.suppress(OSError)`
followed by `with suppressor:`.

**Change.** When the context expression of a `with` item is a plain name,
resolve it to the most recent assignment of that name in the same scope
(function body or module body, walking backwards from the `with`). If that
assignment's value is a call to a listed capture manager or to
`contextlib.suppress`, treat the `with` as that catch, exactly as the inline
form, with these confidence rules:

- assignment at the same block level, no reassignment in between: `exact`;
- assignment inside a branch or loop body between the two, or the name is a
  parameter or a comprehension target: `approximate`, still a catch;
- the name is reassigned to something that is not a listed manager between the
  assignment and the `with`, or no assignment is found in the scope:
  `unresolved`, reported as an untyped catch (like a bare `except`), never
  silently the older binding.

Names bound by `with ... as name` or imported from another module are out of
scope for this item (report `unresolved`).

**Acceptance.** `capture = M(ProcessLookupError); with capture: ...` with `M`
listed: one EXC001 finding on the `with` line unless a boundary approves
`ProcessLookupError`, with `exact` confidence; the same with the assignment
inside an `if`: `approximate`; `capture = M(T)` then `capture = other()` then
`with capture:`: `unresolved`, untyped. `s = suppress(FileNotFoundError)`
then `with s:` behaves as `with suppress(FileNotFoundError):` (EXC001 + EXC002
without a boundary; nothing with one). Fingerprints are stable across
unrelated edits. `with open(p) as fh:` is still an ordinary `with`.

## 2. Literal arithmetic in named constants

**Observation.** Under `named_constant_definitions = "allow"` (0.2.0), a
constant whose value is a single literal passes, but a constant whose value is
arithmetic on literals is reported on every literal:

```python
CHUNK_BYTES = 64 * 1024
MAX_MS = 30 * 60 * 1000
```

The definition is still the remedy; the arithmetic only documents how the
number is built.

**Change.** Under `allow`, accept a module-level constant definition (same
name rules as 0.2.0) whose value is an expression consisting only of numeric
literals, unary `+`/`-`, parentheses, and the binary operators `+ - * / // % **`
(JavaScript: the same set, `**` included). Any name, attribute, call,
subscript, or non-numeric literal in the expression keeps every literal in it
reported, as today. `report` mode is unchanged (every literal reported).

**Acceptance.** `CHUNK_BYTES = 64 * 1024` and `const MAX_MS = 30 * 60 * 1000;`
under `allow`: no finding. `TIMEOUT = BASE * 2`, `SIZE = int(x) * 2`,
`LIMITS = [8, 16]`: every literal reported. `CHUNK_BYTES = 64 * 1024` under
`report`: two findings. Inside a function body: findings, as today.

## 3. The content-hash cache

**Observation.** A run over the codebase takes about 12.5 seconds. Now that
the report is good enough to run at every development startup, that is where
the time is felt. Item 6 of the first brief, deferred from 0.2.0.

**Change.**

- Per-file results (parse facts, rule findings, per-unit complexity metrics)
  are cached under `cache.directory` (default `.shockharness-cache/` under
  the analysis root; relative paths resolve against the root; document that it
  belongs in `.gitignore` and add it to the examples' ignore files).
  `cache.enabled` default true; `--no-cache` bypasses reading and writing for
  one run.
- Key: tool version, effective config digest, language, and the SHA-256 of the
  file's bytes. Any difference is a miss. Cross-file work (call graph, cycles,
  diff, baseline matching, history) is always recomputed.
- A hit must produce byte-identical findings and metrics for that file. A
  corrupt, unreadable, or schema-mismatched cache entry or index is reported
  once in `coverage.cache` (`status`, `hits`, `misses`, `invalidated`,
  `errors`) and ignored; it never fails the run and never yields a partial
  result. Writes are atomic (write to a temp file, then rename).
- The cache is never consulted for `baseline create`, and the report records
  `coverage.cache.status = "bypassed"` under `--no-cache`.

**Acceptance.** A second run over an unchanged tree produces an identical JSON
report and `coverage.cache.hits` equal to the file count; changing one file
re-analyzes only that file (`misses == 1`); changing the config or the tool
version invalidates everything; `--no-cache` bypasses it; a deliberately
corrupted index yields a warning in the report and a correct full analysis;
the self-gate and the consumer upgrade script pass with the cache on. Add a
timing assertion only as a sanity bound (second run at most half the first on
the repository's own tree), marked slow.

## 4. Root-anchored patterns

**Observation.** A pattern with no slash matches its basename anywhere, so
`main.py` in `include` also matched every `main.py` under `.venv-experiments/`
and `build/`. There is no spelling for "this file at the root only": a leading
`/` is a configuration error and `./` is stripped.

**Change.** A leading `/` or `./` anchors the pattern to the analysis root:
`/main.py` and `./main.py` match only the root-level `main.py`; `/src/*.py`
matches only files directly under `src/`. Patterns without either prefix keep
today's semantics (no slash: basename anywhere; with a slash: whole relative
path). This changes the meaning of `./pattern` from "same as `pattern`" to
"root-anchored"; record it in CHANGELOG under a "Changed" heading and in
`docs/configuration.md`. The glob validator accepts the leading `/`.

**Acceptance.** `include = ["/main.py"]` analyzes `main.py` and not
`build/main.py`; `["./src/*.py"]` matches `src/a.py` and not `src/sub/a.py`
or `other/src/a.py`; `["main.py"]` still matches both root and nested
`main.py`; `config validate` accepts `/main.py`; override and
`configuration_files` patterns honour the anchor too.

## 5. EXC002 message for a guard followed by nothing

**Observation.** `catch (error) { rethrowUnexpectedError(error); }` is
reported by EXC002 as swallowing the expected errors. That is the policy as
written and the right reading; the message should say what satisfies it.

**Change.** When a handler consists only of a transparent guard call, the
EXC002 message ends with the three remedies: handle the expected error after
the guard, log it and continue with a stated reason, or suppress the finding
with a reason. No behaviour change.

**Acceptance.** The message for a guard-only handler contains all three
remedies; a handler with statements after the guard keeps today's message.

## Non-goals

No change to which catches are approved: a boundary is still required. No
cross-module resolution of capture-manager bindings. The plugin API (item 5 of
the second brief) still waits for its design document.
