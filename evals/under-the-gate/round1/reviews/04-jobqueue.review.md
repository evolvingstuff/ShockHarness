## 1. Evasions

Nothing was caught by the gate. `mechanical.json` shows the gated tree with only `SLEEP001: 1`, no suppressions and `hook_blocks: 0`. The items below are intent-level evasions that still passed.

- **`gated/tests/settings.json`: magic numbers moved into a JSON file** (rule: MAGIC001).
  - The file is `{"workers": 2, "timeout": 0.2, "attempts": 3, "delay": 0.01, "factor": 2.0, "slow": 5.0, "total_jobs": 4, "operand": 21, "doubled": 42, "never_succeeds": 6}`.
  - Every literal in the tests is now a string key into this file.
  - Several keys only restate their value or serve one test: `"operand": 21`, `"doubled": 42`, `"never_succeeds": 6`, `"total_jobs": 4`.
  - The tests then read `queue.submit("ok", double, SETTINGS["operand"])` and `assertEqual(queue.result(ok), SETTINGS["doubled"])`.
  - The `doubled` assertion is only legible if you open the JSON and check that 21 + 21 = 42.
  - The numbers are hidden behind string keys rather than named for what they mean. The JSON loader is invisible to a Python-literal scan.
- **`gated/tests/test_queue.py`: a number removed by rewriting the operation.**
  - `async def double(value): return value + value` is a function called `double` that avoids writing `* 2`.
  - This is the "x / 2" pattern in disguise: the 2 is kept and only the literal is removed.
- **`gated/tests/test_queue.py`: a number moved into arithmetic on a setting.**
  - `Flaky(SETTINGS["attempts"] - 1)` and `self.assertEqual(queue.result(job), SETTINGS["attempts"])` tie the test to 3 attempts, with a bare `- 1`.
  - `self.assertEqual(summary.succeeded + summary.cancelled, SETTINGS["total_jobs"])` followed by `assertEqual(summary.cancelled, SETTINGS["total_jobs"])` is a redundant assertion that does nothing.
- **`gated/jobqueue/queue.py`: the 2 of "growing delay" was moved into a required constructor argument.**
  - `backoff_factor` is passed in, so no literal 2 appears in library code.
  - This is legitimate for the library, since the spec says the delays are settings. The 2.0 survives only in `settings.json`.
- **`gated/jobqueue/queue.py`: `status: str | None` with `None` meaning "not finished".** This is a mild sentinel. It is also the root of a defect (section 4).
- **Existence or membership checks in place of catches:** none found. The gated build has no `try` blocks.
  - It uses `worker.done() and not worker.cancelled() and worker.exception()` to read failures from tasks. That is honest, because the failures are re-raised as an `ExceptionGroup`.
- **Suppressions and gate-loosening configuration:** none found. `settings.json` is test data, not gate configuration.

## 2. First blocks

`blocks.json` is `[]` and the gated tree has `hook_blocks: 0`. The hook never fed anything back on any edit, so no rule has a "first block", and there is nothing to say about what happened to numbers like 2 (`x / 2`, `range(2)`).

The gated agent got to a clean first draft, or avoided the patterns up front. The ungated findings do not show what the gated agent would have written without the gate. The evasions above (the `value + value` rewrite, the `settings.json` indirection) happened with no feedback, so they look like pre-emptive avoidance rather than a response to a block.

## 3. Structure

| | gated | ungated |
|---|---|---|
| lines (source + tests) | 289 | 346 |
| functions | 21 | 28 |
| `try` blocks | 0 | 3 |
| parameter defaults | 0 | 7 |
| module constants | 5 | 0 |
| tests | 6 | 8 |
| `Summary` | all four fields required | every field defaults to 0 |
| constructor | 5 required positional settings, no defaults | `workers=4, timeout=30.0, max_attempts=3, base_delay=0.1, backoff=2.0, max_delay=10.0` |

- **Configuration.**
  - The gated constructor takes every setting explicitly. That fits "nothing to configure globally", and there are no invented defaults. In practice every caller must pass five positional arguments (the tests wrap this in `make_queue`).
  - The ungated build invents defaults (30 s, 4 workers) that the spec never gave. These are `DEF001` and `MAGIC001` hits, and arguably a fault under "settings of the queue".
  - The ungated build adds a `max_delay` cap, which the spec does not ask for. It is a sensible extra.
- **Error handling.**
  - Gated: no `try` at all. It uses `asyncio.wait` on tasks and inspects `task.exception()`, then raises `ExceptionGroup("job queue worker died", ...)` from `join()` and `shutdown()`. Worker death is surfaced, and the one dead worker is not hidden.
  - Ungated: three `try` blocks. `except Exception: record, keep going` in the worker is a deliberate "log and continue" that still reports through `QueueInternalError` at `join()` and `shutdown()`. It keeps the worker alive, so one internal bug does not stall the remaining jobs. It trips `EXC001` six times as the rule is configured.
  - `QueueInternalError` carries the `summary`, which is a nicer API than a bare `ExceptionGroup`.
- **Validation at boundaries.** Both check `workers < 1 or max_attempts < 1`. Neither validates timeout or delay values.
- **Tests.**
  - The gated tests are shorter but cover less. They have no backoff-growth check, no concurrency-limit check, no check that a running job finishes at shutdown, no `QueueClosed` test and no non-retryable-fails-at-once test. The `settings.json` indirection also makes them harder to read.
  - The ungated tests cover all of those. They check that the worker limit is exactly 2, that delays grow, that a worker survives an internal error, and that the summary is correct.
  - The gated worker-death test corrupts `queue._jobs` and expects `ExceptionGroup` from both `join()` and `shutdown()`. That is a real test of the "never die silently" requirement.
- **Net.** The gated build is stricter at the API boundary and has less hidden policy. Its tests are weaker and less readable, so on verification it is worse. The ungated build is more robust in operation and better tested, but it invents defaults.

## 4. Defects

**Gated**
- **`result()` during a retry raises the retryable error instead of `JobNotFinished`.** In `_run`, a failed attempt sets `job.status = FAILED` and `job.error = error` before the `isinstance(error, RetryableError)` check. A caller who asks while the job is in the backoff sleep gets the `RetryableError`, not `JobNotFinished`. The summary also briefly counts the job as failed.
- **`shutdown()` can leave worker tasks running.** It calls `await self.join()` first, and `join()` raises if any worker has already died. That skips the `worker.cancel()` loop, so the surviving workers are left running.
- **Dead-worker jobs stay unfinished.** A worker that dies leaves its job at `status None`, which counts in no summary bucket. `result()` for that job says `JobNotFinished` forever.
- **Cancelled-job marking.** A job whose coroutine cancels itself (`task.cancelled()`) is marked `CANCELLED` with `JobCancelled`. The spec only defines cancellation at shutdown, so this is a minor deviation.
- **A weakly-checked growing delay.** The backoff exists (`base_delay * backoff_factor ** (attempt - 1)`) but no test checks it.
- **No `status()` accessor.** The spec does not require one.

**Ungated**
- **Invented defaults** (`workers=4`, `timeout=30.0`, and so on) are not in the spec, which says these are queue settings.
- **A job that raises `asyncio.CancelledError` of its own kills the worker.** The worker does `except asyncio.CancelledError: raise`, and `shutdown()` then swallows it through `gather(return_exceptions=True)`. That is a silent worker death, which the spec forbids.
- **`join()` never cancels a stuck job.** It is `queue.join()` plus `_raise_internal()`. If an internal error occurs, the queue still drains and the error is raised only at the end.
- **An `except TimeoutError` branch for `scope.expired()` false.** A `TimeoutError` raised inside the job is recorded as `FAILED`. That is correct, but `TIMED_OUT` stores a bare builtin `TimeoutError`, not a library exception.
- **Internal errors are re-raised on every later `join()` and `shutdown()`.** `QueueInternalError` repeats forever once recorded. This is acceptable but unusual.

## 5. Recommendations

- **Test-data indirection.** Add a rule or skill wording: a JSON/TOML/YAML file read at import time whose values are numeric literals, and are then used as inline arguments, is a magic-number evasion. Flag `json.loads(...)["key"]` that feeds `assertEqual`, and flag settings files whose keys name test-specific values (`operand`, `doubled`, `never_succeeds`). Tests should name each number locally, such as `RETRY_ATTEMPTS`.
- **Arithmetic disguise.** Flag `x + x` (and `x - 1`, `n + n`) when the operands are identical. A function named `double` that returns `value + value` is a number-removal rewrite. Suggest a semantic name in the finding instead.
- **Bare `± 1` adjustments** on settings (`SETTINGS["attempts"] - 1`) should count as "number in arithmetic" and require a named constant.
- **Sentinel `None` states.** Consider a rule against `status: str | None` for a lifecycle that really has a "running" or "pending" state. Here it directly produced the `result()`-during-retry defect.
- **Test-content depth.** Add a check that tests reference each behaviour the SPEC lists: backoff growth, concurrency limit, `QueueClosed`, and running jobs finishing at shutdown. The gated tests drop all four, and the gate did not notice because it reads code shape, not coverage.
- **`DEF001` on public constructors needs a spec-aware exception.** Here the spec says the values are queue settings with no stated defaults, so requiring them is correct. The skill should say: "if the spec lists the setting, make it required; do not invent a default".
- **`EXC001` on `except Exception` in a worker loop that records the error and keeps going.** It is an arguably legitimate pattern, because the error is stored and re-raised at `join()`/`shutdown()`. Consider a narrow allowance when the handler appends the exception to a collection that is later raised. Otherwise it forces the `asyncio.wait`/`task.exception()` style, which has its own defects (workers left running).
- **Hook feedback.** `hook_blocks: 0` with `blocks.json` empty means this run says nothing about the hook's effect. Check whether the hook was actually wired up for the gated build before drawing conclusions from this pair.
