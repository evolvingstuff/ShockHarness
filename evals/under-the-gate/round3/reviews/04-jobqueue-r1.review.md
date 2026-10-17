I've finished reading both trees and running probes against them; here is the review.

# Review: 04-jobqueue-r1 (gated vs ungated)

**Short version:** the hook never blocked anything, the gated build changed no configuration, and I found no evasions. The gated build's rule of never catching exceptions in the package does cause a real defect: a broken job callable kills a worker and is reported as a queue bug.

Facts used below:
- `blocks.json` is `[]`.
- `hook/runs.jsonl` has 9 runs, all with 0 findings. `gated/jobqueue/queue.py` passed on its first `Write`.
- `diff setup.shockharness.toml gated/.shockharness.toml` shows no difference.
- Outside tests, the gated build has a single finding, `SLEEP001`. Its severity is `"review"`, so it does not block.
- The gated build's 43 MAGIC001 and 5 DEF001 findings are all in `tests/`, which `init` exempts by design.
- Both test suites pass: 15 gated tests in 0.22s, 31 ungated tests in 1.08s.

## 1. Evasions

None found. I checked the specific patterns you listed:

- **Named constants:** there is only `FIRST_ATTEMPT = 1`. Its name describes what it means (attempts are counted from 1), and it is used for that in `delay_before_retry` (`failed_attempt - FIRST_ATTEMPT`) and in `_run`. It is also borrowed as the lower bound in `if self.max_attempts < FIRST_ATTEMPT:`, while the message next to it still says "at least 1" and `workers < 1` uses the literal. That is inconsistent, but it is not an evasion, because the literal `1` is allowed anyway.
- **Early returns:** `join()` has `if not self._workers: return`, which is a real "nothing was submitted" case, not a fallback. `_start_workers` returns early to avoid starting workers twice.
- **Missing-value handling:** `result()` does the opposite of a fallback:
  ```python
  if job.error is None:
      raise QueueInternalError(f"job {job_id} failed without recording its error")
  ```
- **Defaults:** `_Job(... result=None, error=None)` sets initial state when a job is built; these are not field defaults. `QueueSettings` has no defaults, and all five settings are required keyword arguments.
- **Suppressions and config changes:** there are no suppressions and the configuration is unchanged.
- **One loosening worth noting:** `def _update(self, job_id: int, **changes: object)` sends untyped keyword arguments into `dataclasses.replace`. A misspelled field name only fails at runtime. No rule covers this. The variadic detector flagged `submit(*args)`, which SPEC.md requires, and missed this one.

## 2. First blocks

None found. The hook produced no feedback at any point.

On the number 2: no `/ 2` or `range(2)` appears in the gated production code. Backoff is `base_delay_seconds * delay_multiplier ** (failed_attempt - FIRST_ATTEMPT)`, with the multiplier supplied by the caller. The `2.0` values only appear in tests (`make_queue(... delay_multiplier=2.0)`), where they are exempt.

## 3. Structure

| | gated | ungated |
|---|---|---|
| Lines (all files) | 555 | 758 |
| Functions | 41 | 67 |
| `try` blocks in the package | 0 (the only one is in a test) | 4, with 6 `except` clauses |
| Settings | Frozen `QueueSettings` that validates itself. All 5 settings required. `delay_before_retry` lives on it | Constructor defaults (`workers=4`, `timeout=30.0`, `max_attempts=3`, `retry_delay=0.1`, `backoff=2.0`), plus `max_delay` and `timeout=None` |
| Job state | Frozen `_Job`, changed via `replace()` | Mutable dataclass |
| Internal-error reporting | Workers die, then `join`/`shutdown` read `worker.exception()` and raise `QueueInternalError ... from` it | Worker uses `except Exception` to record the error, fail the job and keep running. A done-callback catches worker crashes. `QueueInternalError` carries `.summary` |
| Tests | 15 | 31 |

**How the gated build works.** Each attempt runs in its own task. The worker waits on it with `asyncio.wait({task}, timeout=...)` and then reads `task.cancelled()`, `task.exception()` and `task.result()`. This avoids writing `except` without swallowing anything, and it is a good design for timeouts. Because the outcome is read from the task rather than from an exception, a job that catches the cancellation and returns is still recorded as `TIMED_OUT`. The ungated build gets this case wrong (see section 4).

**Where it costs.** "Never catch" also removed the boundary between a job's own errors and the queue's errors. Here is the line that crosses it:
```python
task = asyncio.create_task(job.coro_fn(*job.args), name=f"jobqueue-job-{job_id}")
```
If `coro_fn(...)` raises synchronously, or returns something that is not a coroutine, the exception comes from the worker's own frame, not from the job's task. A user's mistake then becomes a dead worker and a `QueueInternalError`.

The ungated build wraps the call in its `try`, so the same mistake is recorded as the job failing. It also has a test for it: `test_non_coroutine_callable_fails_job_not_worker`.

**On the rest of the spec, the gated build is tighter:**
- Every setting must be passed explicitly.
- There is no way to turn the timeout off. SPEC.md says "Each job has a timeout", and the ungated build allows `timeout=None`.

**Test coverage is thinner in the gated build.** It has no tests for:
- a job raising its own `TimeoutError`
- the timeout applying per attempt
- subclasses of `RetryableError` being retried
- a dead worker or a worker crash outside a job
- a callable that is not a coroutine

The last one is exactly the case that breaks it.

**Overall:** the gated build is cleaner and more correct about timeouts, and worse at the "a worker must never die silently, and jobs aren't lost" part of SPEC.md.

## 4. Defects

### Gated

1. **A job's own error kills a worker and is reported as a queue bug.** I ran a probe with 2 workers, submitting `bad` (a function that is not a coroutine, or one that raises synchronously), then `ok`, then `ok2`:
   ```
   join raised QueueInternalError TypeError('a coroutine was expected, got 5')
     result 0 raised JobNotFinishedError     # bad job stuck RUNNING forever
     result 1 1
     result 2 raised JobNotFinishedError     # never ran; join returned early
     shutdown raised QueueInternalError no summary
   ```
   Several things go wrong at once:
   - The job is never recorded as failed.
   - `join()` returns before the other jobs finish (it uses `FIRST_COMPLETED` on the dead worker).
   - The pool loses that worker permanently.
   - `shutdown()` never returns a summary.

   The ungated build records the job as `failed` and returns `Summary(succeeded=2, failed=1, ...)`.

2. **`shutdown()` never returns a summary once anything has gone wrong internally.** `_raise_for_dead_workers()` raises before `_summary()` runs, and `_summary()` would itself raise because a job is left in `RUNNING`. SPEC.md asks for both the report and the summary. The ungated build attaches the summary to `QueueInternalError.summary`.

3. **Shared with ungated: a job that ignores cancellation hangs its worker forever.** After the timeout, the gated build does `task.cancel(); await asyncio.wait({task})` with no bound. The ungated build's `asyncio.timeout` also waits for the coroutine to unwind.

4. **Shared with ungated: delays don't have to grow.** `delay_multiplier >= 1` (ungated: `backoff >= 1`) accepts `1`, which gives a constant delay, while SPEC.md says "growing delay".

### Ungated

1. **A job that swallows its timeout cancellation is recorded as succeeded.** Probe: `async def stubborn(): try: await asyncio.sleep(10) except CancelledError: return "swallowed"`, with a 0.2s timeout, ends as `JobStatus.SUCCEEDED`. `asyncio.timeout` only raises `TimeoutError` if `CancelledError` propagates out of the coroutine. SPEC.md says such a job is "cancelled and recorded as `timed_out`". The gated build gets this right.
2. **`timeout=None` disables the per-job timeout**, which goes against "Each job has a timeout". Its defaults (`timeout=30.0`, etc.) are allowed by SPEC.md, but they hide configuration choices.
3. **Judgment call, not a clear defect:** a job that raises `CancelledError` on its own is recorded as `failed`. The gated build records it as `cancelled`.

## 5. Recommendations

1. **Skill wording: allow a sanctioned catch at the user-code boundary.**
   - **Problem:** the gated builder avoided every `except`, including the one SPEC.md implicitly needs. The queue must separate "the job raised" (record it on the job) from "the queue's own code raised" (report it).
   - **Fix:** add guidance along these lines. "Catching an exception at the boundary where you call user-supplied code is not swallowing it, as long as the exception is stored and re-raised or returned to the caller. Put every call into user code (including building the coroutine) inside that boundary."
   - **Rule hint:** a review-level finding for `create_task(<param>(...))` or `await <param>(...)` outside any `try`, where `<param>` is a parameter of type `Callable`, would have pointed at this line.
2. **Variadic detector: narrow one case, widen another.**
   - Don't flag `*args` that is forwarded unchanged to a callable taken in the same signature (`submit(name, coro_fn, *args)` → `coro_fn(*args)`). SPEC.md mandates this form.
   - Do flag `**kwargs: object` / `**changes: object` passed into `dataclasses.replace`, `setattr` or `__dict__.update`, as in `_update(self, job_id, **changes: object)`. Static typing of field names is lost there.
3. **SLEEP001: exempt computed backoff.** The only production finding, `await asyncio.sleep(self._settings.delay_before_retry(attempt))`, is the backoff SPEC.md asks for. Exempt sleeps whose argument is a call or attribute derived from configuration inside a retry loop, or keep the rule at `review` severity, as it is now.
4. **Consider a rule against `assert`-style validation that lets a feature degrade silently:** a lower bound of `>= 1` on a parameter whose docstring or name says it should grow (`multiplier`, `backoff`). This is low priority. It is a spec defect both builds share, and a static rule would be noisy.
5. **No rule here blocked anything legitimate.** The hook gave no feedback, so I have no blocking false positives to report.
