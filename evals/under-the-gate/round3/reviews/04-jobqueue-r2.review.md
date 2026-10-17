# Review: 04-jobqueue-r2, gated vs ungated

## 1. Evasions

None found.

- **Configuration.** `gated/.shockharness.toml` is byte-identical to `setup.shockharness.toml`. There are no inline suppressions (`inline_suppressions: 0`, `suppressed: 0`).
- **Remaining findings.** All 53 MAGIC001 and 5 DEF001 findings are in `tests/test_jobqueue.py`, which the init config exempts by design (`make_queue(workers=2, timeout_seconds=1.0, ...)` and literal expected values). The only finding outside tests is SLEEP001 at `queue.py:262`, `await asyncio.sleep(self._settings.delay_after(attempt))`. That is the retry backoff SPEC.md requires, so it is not an evasion.
- **Candidates I checked and cleared:**
  - `FIRST_JOB_ID = 1` and `FIRST_ATTEMPT = 1`. The names describe what the values mean (where ids start, and that attempts are counted from 1), and both are used for that meaning: `itertools.count(FIRST_JOB_ID)`, and `self.delay_multiplier ** (attempt - FIRST_ATTEMPT)`. These are not `ONE = 1`.
  - `_STOP = None  # put on the pending queue once per worker to end it`. This is a real sentinel, not a fallback.
  - `attempts=0, result=None, error=None` in `submit`. This is explicit initial state at construction. The dataclass fields carry no defaults, unlike ungated's `status: Status = Status.PENDING`.
  - The only try/except in production code was removed by design: "Job outcomes are read from finished tasks (`task.cancelled()`, `task.exception()`) rather than caught". The code records the error (`job.error = error`) and does not hide it, so this is not a catch replaced by a check that returns a fallback. It does have a real cost, covered in §4.
- **Rule-shaped artifact, not an evasion.** In `JobQueue.__init__`:
  ```python
  if sys.flags.optimize:
      raise RuntimeError("jobqueue checks its invariants with asserts; do not run with python -O")
  ```
  This satisfies ASSERT002 ("asserts relied on, -O not refused") literally. The result is a library that refuses to be constructed under `-O`, which is a strange cost for three internal invariant asserts.

## 2. First blocks

The hook ran 11 times and blocked once. `queue.py` and `__init__.py` passed on their first Write with 0 findings.

**EXC001, `tests/test_jobqueue.py:107`.** The blocked code was:
```python
async def slow():
    try:
        await asyncio.sleep(10)
    except asyncio.CancelledError:
        cancelled.set()
        raise
```
The agent's next edit was:
```python
    try:
        await asyncio.sleep(10)
    finally:
        # Reached early only when the sleep is cancelled.
        cancelled.set()
```
- **Verdict: complied.** The test still proves the job was cancelled, because the 10 s sleep far exceeds the 0.05 s timeout. But the assertion is now weaker: `finally` would also set the flag on normal completion, and the comment exists to cover that gap.
- **The block was a false positive.** The original catch re-raised `CancelledError` after a side effect. That is the canonical correct asyncio pattern, not a swallow.

**Numbers like 2.** No rule ever blocked on them. The backoff base is a setting, `delay_multiplier` (validated `>= 1`), not a hard-coded `* 2`. The only remaining literal is `range(FIRST_ATTEMPT, self._settings.max_attempts + 1)`, where `+ 1` is the inclusive bound and is fine. The 2s in tests (`workers=2`, `delay_multiplier=2.0`, `(0.02, 0.04, 0.08)`) sit under the test exemption.

There were no MAGIC001 or DEF001 blocks in production code: the first draft was already written to the rules.

## 3. Structure

| | gated | ungated |
|---|---|---|
| Settings | frozen `QueueSettings` dataclass with `__post_init__` validation and `delay_after()`; all five settings required, keyword-only | constructor parameters with defaults (`workers=4`, `timeout=30.0`, `max_attempts=3`, `retry_delay=0.1`, `backoff=2.0`, `max_delay=None`) |
| Timeout | required and positive | optional (`None` = no limit), via `asyncio.timeout` |
| Job outcome | `asyncio.wait({task}, timeout=...)`, then inspects `task.cancelled()` / `task.exception()`; no try in production | `try/except` ladder distinguishing `TimeoutError` (using `deadline.expired()`), `RetryableError`, self-cancel (using `task.cancelling()`) and `Exception` |
| Internal errors | worker dies; `join`/`shutdown` race `_idle` against the worker tasks and raise `WorkerCrashedError from worker.exception()` | worker catches, `_report`s, marks the job FAILED with `QueueInternalError` and keeps running; a done-callback reports dead or cancelled workers |
| Errors | `QueueError` hierarchy including `UnknownJobError` | `RuntimeError` subclasses; an unknown id raises a bare `KeyError` |
| Size / tests | 308 + 264 lines, 16 tests | 306 + 310 lines, 21 tests |

**Where the gated build is better:**
- No hidden defaults.
- Settings are validated in one frozen object.
- The id lookup raises a typed error.
- The waiting logic is cleaner: one `Event` plus `asyncio.wait` on the workers, instead of ungated's clear/wait loops on `_changed`.

**Where the gated build is worse at what SPEC.md asks:**
- **Brittle worker-death design.** Avoiding try/except entirely means anything raised outside the task-inspection path kills a worker permanently, and the gated build never replaces it.
- **Shutdown loses the summary.** `shutdown()` raises without a summary when a worker crashed. Ungated attaches it: `QueueInternalError(self._errors, self._summary)`.
- **Thinner tests.** The gated suite has no test for:
  - a job raising its own `TimeoutError`
  - a timed-out job not being retried
  - idempotent shutdown
  - shutdown of an unused queue
  - a worker surviving an internal error

  The ungated suite covers all five.

## 4. Defects

I confirmed these with a probe script against both trees.

**gated**

1. **A synchronous error from `coro_fn` kills a worker and strands jobs.** `task = asyncio.ensure_future(job.coro_fn(*job.args))` (`queue.py:267`) is outside any outcome handling. If `coro_fn` raises before returning a coroutine, or returns a non-awaitable, the exception escapes `_run_job`. Probe with `workers=1`, `submit("bad", sync_raise)` then `submit("ok", ok, 5)`:
   ```
   join raised WorkerCrashedError ValueError('sync')
   1 JobStatus.RUNNING   result raised JobNotFinishedError
   2 JobStatus.PENDING   result raised JobNotFinishedError
   ```
   - The job's own error is misreported as a queue-internal crash.
   - The job stays `RUNNING` forever and is missing from the summary.
   - With one worker, no further job ever runs.

   Ungated records the same job as `FAILED` with `ValueError` and runs job 2.
2. **Dead workers are never replaced.** Capacity drops silently below `workers`. It is reported only as an exception, never recovered.
3. **`shutdown()` after a crash raises with no summary.** SPEC.md says shutdown "returns a summary" and reports the error. Gated cannot do both.
4. **A second `shutdown()` after a crash fails its own invariant.** It raises `AssertionError: stop markers are only queued after pending jobs are drained`, because the crashed worker's `_STOP` marker is still in the queue and `_cancel_pending` asserts against it.
5. **Refuses to be constructed under `python -O`** (§1). This is not a SPEC.md requirement, but it is a hostile restriction for a library.

**ungated**

1. **Unknown ids leak an internal exception.** `result(999)` raises a bare `KeyError` from `self._jobs[job_id]`. SPEC.md is silent on this, so it is minor.
2. **Timeouts can be turned off.** `timeout=None` disables them, against "Each job has a timeout". This is minor because it is opt-in, but the defaults (`timeout=30.0`, etc.) are values the library chose for the user.

**Both:** the timeout applies per attempt, not per job. SPEC.md is ambiguous here, so I'm noting it rather than counting it as a defect.

## 5. Recommendations

1. **Narrow EXC001.** Do not flag `except X:` blocks that end in a bare `raise` (a side effect followed by a re-raise). That would have removed the only block in this run, which was a false positive that slightly weakened a test.
2. **Allow a capture-and-record catch in EXC001.** Permit a broad `except Exception as e:` whose body stores `e` into state that is later re-raised or exposed: `job.error = e`, `self._errors.append(e)`, or a re-raise from `result()`. Say so in the skill. Gated avoided all production try blocks, and the uncovered `coro_fn(*args)` call is exactly where the right code was a catch that records the job's error. The rule's pressure produced defect 1.
3. **Add a rule: worker or task loops that can die.** Flag a long-lived `while True` coroutine started with `create_task` that has neither a per-iteration error boundary nor a supervisor or restart. Flag it as `review` severity, not as an error.
4. **Reword ASSERT002 in the skill.** Recommend replacing invariant asserts with explicit `raise` statements. Refusing `-O` should not be a suggested way to comply. Better still, flag `if sys.flags.optimize: raise` as a smell.
5. **SLEEP001:** keep it at `review`, and exempt `asyncio.sleep` whose argument comes from a backoff or delay computation inside a retry loop. Here the sleep was a spec-mandated delay.
6. **No new anti-evasion rule is needed for this run.** No constant-restating names, number laundering, fallback helpers or config changes appeared.
