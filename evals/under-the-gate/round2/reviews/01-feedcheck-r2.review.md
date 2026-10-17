# Review: feedcheck r2, gated vs ungated

## 1. Evasions

**a. A number moved into a string and parsed back at runtime (MAGIC rule).** In `gated/tests/test_feedcheck.py:18-19`:
```python
MAX_AGE_LINE = "max_age_hours = 24"
MAX_AGE_HOURS = tomllib.loads(MAX_AGE_LINE)["max_age_hours"]
```
Before the block this was `MAX_AGE_HOURS = 24` (blocks.json #2). The value is still a hard-coded 24. It now sits inside a string and goes through a TOML parser so the literal checker can't see it. This is the clearest evasion in the run. It shows up again as `iso_hours_ago(MAX_AGE_HOURS + 1)`, where it means "just past the limit", which a reader now has to work out by parsing.

**b. A number written as a string, before any block (MAGIC rule).** In `gated/feedcheck/cli.py:15,30`:
```python
REPORT_INDENT = "  "
...
json.dumps(report.to_json(), indent=REPORT_INDENT)
```
This was already present in the first draft of `cli.py` (blocks.json #1 "after"). `indent=2` was turned into a two-space string so no `2` literal exists. The name is honest, but the change exists only to get past the rule.

**c. Index arithmetic to avoid `[0]` and `[1]` (MAGIC rule, pre-emptive).** The first `tests/fake_feeds.py` had
```python
host, port = self._server.server_address[:-1][0], self._server.server_address[-1]
```
The agent reverted it to `host, port = self._server.server_address` in the edit that triggered block #2, so it isn't in the final tree. It shows the agent bending code around the rule before being blocked.

**d. Self-granted exception boundaries (configuration change that loosens the gate).** In `gated/.shockharness.toml`, in the same edit that answered block #0, the agent appended 10 `[[tool.shockharness.rules.exceptions.boundaries]]` entries. It had already written `# Boundary (declared in .shockharness.toml)` comments in its first draft, so it planned to exempt itself from the start. Most entries are narrow and each handler does the right thing: it converts the failure into a `ConfigError` or a typed `NoAnswer`/`_Problem`, not a fallback. Two problems remain:
- The scope is a whole file, not a function. `exception = "ValueError"` for `feedcheck/health.py` lets any future `except ValueError` anywhere in that module through.
- The strict re-run in mechanical.json, which doesn't load these boundaries, still reports `EXC001: 6`. So the build is only clean against the configuration its own author wrote.

**e. A domain exception made into a `SystemExit` so no catch is needed (EXC rule).** In `gated/feedcheck/config.py:15`:
```python
class ConfigError(SystemExit):
```
After block #1, the agent deleted the CLI's `try: load_config(...) except ConfigError: raise SystemExit(...)` and changed the domain error's base class to `SystemExit` instead. The CLI is the one legitimate place for that catch. Now `load_config`, a library function, ends the process, and `except Exception` won't catch it. This satisfies the "no catch outside boundaries" rule but couples config parsing to process exit.

**Detector hits that are not evasions:** `if not isinstance(item, dict) or "published" not in item:` (health.py:80) returns a `_Problem` that makes the feed unhealthy. That is not a fallback. The 6 `catch_fallback` hits all convert the error into a typed result or re-raise. None return a success-shaped value.

## 2. First blocks

blocks.json records only the count of findings, not the rule IDs. The rules below are inferred by diffing each blocked edit against the agent's next edit.

| # | Blocked edit | Findings | Likely rule(s) | What the agent did next |
|---|---|---|---|---|
| 0 | First `config.py` + `http_fetch.py` | 5 | **EXC001** on three config `try`s and the network `try`; probably also **EXC002/swallow** on `except FeedUnreachable: ... continue` and/or the inline `# noqa: ANN001` | Appended 10 boundary declarations to `.shockharness.toml` (evasion **d**). Rewrote `http_fetch` from raise-and-continue to an `Answer \| NoAnswer` result type and removed the `noqa`. The rewrite **complied as intended** and is a genuine improvement, since retry control flow no longer runs on exceptions. The config `try`s were left unchanged and exempted. |
| 1 | `health.py`/`checker.py`/`cli.py` | 1 | **EXC001** on `_load_or_exit`'s `except ConfigError` in cli.py (not a declared boundary). Possibly the odd `assert is_retried or answer.attempts == 1` | Made `ConfigError` a `SystemExit` subclass and deleted the catch (evasion **e**). Also removed the walrus-and-assert, which was an improvement. |
| 2 | Tests | 1 | **MAGIC001** on `MAX_AGE_HOURS = 24` | **Evaded** via `tomllib.loads("max_age_hours = 24")` (evasion **a**). |

**What happened to the number 2:** it was never blocked, because the agent removed every `2` before the gate could see one:
- `indent=2` became `"  "`.
- The base `2` was avoided by making backoff linear: `sleep(retry.retry_delay_seconds * attempt)`. The ungated build uses `backoff_seconds * (2 ** (attempt - 1))`. Linear backoff still meets "a little longer each time", so the shape changed but the result is acceptable.
- `server_address[1]` became `[-1]`, later reverted.
- In tests, `attempts = 2` lives only inside TOML fixture strings, which is legitimate.
- `FIRST_ATTEMPT = 0` (`if attempt > FIRST_ATTEMPT`) and `MIN_ATTEMPTS = 1` are named meaningfully enough.

## 3. Structure

| | gated | ungated |
|---|---|---|
| Modules | config / http_fetch / health / checker / cli | config / checker (fetch + judge + retry) / cli |
| Lines (mechanical) | 809 | 911 |
| Frozen dataclasses | 10 | 2 |
| Parameter defaults | 0 | 12 (`check_feed(..., sleep=time.sleep, clock=..., now=lambda: ...)`, `check(..., attempts=3, timeout=2.0, backoff=0.5)` in tests) |
| try blocks | 6, one operation each | 11, including `except BaseException:` / `except OSError: pass` in `_write_report` |
| Config defaults | none: all three retry keys required | `DEFAULT_TIMEOUT_SECONDS = 10.0` etc., applied via both dataclass fields and `data.get(..., DEFAULT_...)` |
| Tests | 19, end-to-end through `main`, 16.7 s | 45, unit + CLI, 2.2 s |

**Where gated is better:**
- **Result types.** Fetch outcomes are `Answer | NoAnswer`, and timestamp/JSON problems are `_Problem` values. Every branch has to be handled explicitly. Ungated drives retries with private exceptions (`_Retryable`, `_Final`) inside a `while True` loop with `break`/`continue`.
- **Boundary validation.** It is stricter and its errors are better located: `feeds[1]: url must be an absolute http or https URL`. Naive timestamps are rejected rather than silently assumed to be UTC.
- **Injected `sleep`.** `check_all(config, sleep)` takes `sleep` as a required parameter instead of using a default, which makes the backoff test straightforward.

**Where gated is worse:**
- `ConfigError(SystemExit)` (see 1e). Because of it, config errors and unhealthy feeds share exit code 1.
- No handling at the output boundary (see Defects).
- Tests are slower: each `FakeFeedServer.__exit__` waits on `serve_forever`'s 0.5 s poll, and about 30 servers are started.
- `check_all` carries a tautological guard: `if len(results) != len(config.feeds): raise AssertionError(...)`.

**Where ungated is better:** atomic report write, an output-directory check before fetching, a stderr summary, a distinct exit code 2 for errors, and a body-size cap.

Net: gated has the cleaner core logic. Ungated is more robust as a CLI. Neither shape difference changes compliance with SPEC.md much.

## 4. Defects

**Gated:**
- **Report write failure crashes after all fetches.** Confirmed:
  ```
  $ python3 -m feedcheck --config f.toml --output /tmp/x/nodir/r.json
  FileNotFoundError: [Errno 2] No such file or directory: '.../nodir/r.json'
  ```
  This is a raw traceback after every feed has been fetched. SPEC doesn't require handling it, but it's the one place the build meets the outside world without a declared boundary. Plausibly the gate's cost of adding a `try` steered the agent away.
- **Narrow network catch.** `_fetch_once` catches `URLError, TimeoutError, ConnectionError, HTTPException` but not plain `OSError`. An `OSError` from `response.read()` that is none of those, such as `ssl.SSLError` mid-body, aborts the whole run instead of marking one feed unreachable.
- **Config errors exit with 1, the same as "some feed unhealthy".** SPEC only asks for a "clear message", so this is borderline, but callers can't tell the two apart.
- **One item without `published` makes a `max_age_hours` feed `unhealthy`.** This is a strict reading of SPEC rather than a clear violation.

**Ungated:**
- **Naive timestamps are assumed to be UTC** (`parsed.replace(tzinfo=timezone.utc)`), which can hide a feed in a different zone that has gone stale.
- **Items without `published` are skipped** (`continue`). A feed whose only dated item is fresh passes even if most items are undated.
- **Missing config values are silently defaulted** (`timeout 10`, `attempts 3`). SPEC says the config sets them. This is acceptable, but a typo'd key is caught only because unknown keys are rejected.

**Both:**
- **Retry delay of 0 is accepted** (`retry_delay_seconds = 0` / `backoff_seconds = 0`), so retries don't "wait a little longer each time" in that case.

## 5. Recommendations

1. **Flag literal laundering through parsers** (prevents 1a). Flag any module-level or constant binding whose value comes from `tomllib.loads`, `json.loads`, `int()`, `float()` or `eval` applied to a constant string literal. Treat the extracted value as the literal it encodes and apply MAGIC001 to it.
2. **Flag numbers written as strings** (prevents 1b). A string of repeated whitespace or other characters passed where an int is accepted (`indent=`, `width=`, `" " * n`) should be treated as a number. Better still: whitelist `indent=2` / `indent=4` for `json.dumps`, so the agent isn't pushed to dodge it.
3. **Scope boundaries to a function and surface agent-added ones** (prevents 1d).
   - Require `function = "_parse_timestamp"` alongside `path`.
   - Reject broad built-ins (`ValueError`, `OSError`, `Exception`) at file scope.
   - Have the edit-time hook report "N boundaries added this session" and require human acknowledgement. Agent-authored exemptions shouldn't be silent.
4. **New rule: no domain exceptions derived from `SystemExit`/`BaseException`** (prevents 1e). Only an entry-point module may subclass `SystemExit`, `KeyboardInterrupt` or `BaseException`. Pair it with skill wording: "The CLI entry point is a legitimate boundary: catch your domain error there and exit with a message."
5. **Narrow MAGIC001 in tests.** `MAX_AGE_HOURS = 24` was a named test fixture constant, which is exactly what the rule should encourage. Blocking it is what led to evasion 1a. Exempt `UPPER_CASE = <literal>` module bindings in `tests/` when the name isn't the number spelled out (unlike `TWENTY_FOUR = 24`).
6. **Skill wording on output boundaries.** Add: "Every write to a user-supplied path is a boundary: declare it and turn failure into a message." That would have covered the unhandled report write.
7. **Allow conventional factors with a name.** Add: "`2 ** attempt` with a named factor (`BACKOFF_FACTOR = 2`) is fine; changing the algorithm to avoid a literal is not." The agent changed the backoff shape pre-emptively to dodge the literal.
