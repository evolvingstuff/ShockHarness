# Review: jobqueue r3, gated vs ungated

## 1. Evasions

I found no clear evasions. `gated/.shockharness.toml` is byte-identical to `setup.shockharness.toml`. There are no suppressions and no added boundaries, guards or overrides. Outside the tests, the strict check found exactly one finding, and it is legitimate (see SLEEP001 below). The 43 MAGIC001 and 5 DEF001 findings are all in `tests/test_jobqueue.py`, for example `def make_queue(workers=2, timeout=1.0, ...)`, which the init exemption allows.

I checked each pattern you listed:

- **Constants that restate their value.** `FIRST_JOB_ID = 1` and `FIRST_ATTEMPT = 1` (`gated/jobqueue/queue.py:51-52`). Both use 1, which is already an allowed value, so neither was written to dodge MAGIC001. Both names carry meaning: `itertools.count(FIRST_JOB_ID)` and `retry_backoff ** (attempts - FIRST_ATTEMPT)`, where the exponent is 0 on the first attempt. Not an evasion.
- **Numbers moved into strings, lengths or arithmetic; defaults moved into loaders or dataclass fields.** None. `JobQueue.__init__` is keyword-only with no defaults (`workers: int, timeout: float, max_attempts: int, retry_delay: float, retry_backoff: float`). Neither frozen dataclass has a field default. The ungated build, by contrast, has `Summary(succeeded: int = 0, ...)` and `workers: int = 4, timeout=30.0, ...`.
- **Catches replaced by Task.exception() (borderline, but honest).** The module docstring says: *"No exception is caught anywhere in this module. A job runs in its own task and its outcome is read with `Task.exception()`."* Each attempt runs as its own task, and `error = attempt.exception()` stands in for `except BaseException as error`. That design is plainly a response to EXC001. It does not hide anything, though: every outcome is recorded (`record.error = error`, `raise record.error` in `result()`).
- **A check that hides a failure (closest to a real evasion):**
  ```python
  def _raise_worker_failure(self) -> None:
      for worker in self._workers:
          if not worker.done() or worker.cancelled():
              continue
  ```
  The `worker.cancelled()` check is needed because `exception()` raises on a cancelled task. But choosing `continue` makes a cancelled worker count as healthy. That is the "check returns the quiet path" pattern, and it causes a real spec violation (Defect G1). I can't tell whether the gate drove this choice. The equivalent catch would have been flagged.

## 2. First blocks

There was only one block (`hook_blocks: 1`). `queue.py` was written in one go and passed with 0 findings, so the agent designed around the rules up front rather than reacting to feedback.

**EXC001, `tests/test_jobqueue.py:141`.** The original test code was:
```python
try:
    await asyncio.sleep(10)
except asyncio.CancelledError:
    cancelled.set()
    raise
```
It was flagged because the strict profile has `transparent_rethrow = false`. The agent's next edit was:
```python
try:
    await asyncio.sleep(10)
finally:
    cancelled.set()
```
**Verdict:** complied, with a slight loss of precision. The event is now also set if the job returns normally, so the assertion no longer proves cancellation by itself. The test still asserts `JobStatus.TIMED_OUT` and that a 10-second sleep cannot finish inside the timeout, so the loss is small. The block itself was a false positive: catching CancelledError, recording it and re-raising is the standard asyncio idiom, and it swallows nothing.

**Numbers like 2:** they never reached the hook. Production code has no 2 at all. Backoff is a setting (`retry_backoff`), and the formula `retry_delay * retry_backoff ** (attempts - FIRST_ATTEMPT)` needs no literal. The ungated build writes `s.backoff ** (attempt - 1)` with a default of `backoff: float = 2.0`. In the gated tests, values like `retry_backoff=2.0` and `range(5)` are covered by the exemption.

## 3. Structure

| | gated | ungated |
|---|---|---|
| Lines (lib + tests) | 267 + 252 | 331 + 368 |
| try blocks | 1 (test) | 6 |
| Parameter defaults (production) | 0 | 16 DEF001 findings |
| Tests | 14 (0.48 s) | 26 (1.14 s) |

- **Settings.** The gated build requires every setting explicitly, which fits "all settings of the queue; nothing to configure globally". Ungated hard-codes defaults (`timeout=30.0`, `max_attempts=3`). It also adds `timeout=None` and a `max_delay` cap, which the spec didn't ask for but don't hurt.
- **Error handling.** Gated has no catches. It reads outcomes through `Task.exception()` and treats any exception escaping its own code as fatal to the worker. Ungated catches `Exception` around `_run_job`, records it as an internal error, marks the job FAILED and keeps the worker alive. It also tracks worker death through `_on_worker_done`, including "cancelled" and "exited unexpectedly" while the queue is open. Ungated's model is more complete: it handles a worker cancelled from outside and attaches the summary to `QueueInternalError` raised from `shutdown()`.
- **Invariants.** Gated relies on `assert` for type narrowing (`assert self._waiting is not None`) and raises bare `AssertionError` for broken invariants. Asserts disappear under `python -O`, and a bare `AssertionError` does not satisfy "reported by join() and shutdown()" when the invariant breaks (see G1).
- **Tests.** Ungated tests more of what goes wrong: an externally cancelled worker, a job that cancels itself, a job that raises TimeoutError itself, concurrent join and shutdown, calling shutdown twice, and one worker's retry delay not blocking the others. Gated has none of these, and those missing cases are exactly where its defects are.
- **Net.** Gated is leaner and cleaner on configuration. Its catch-free design is elegant but left the worker-lifecycle edge cases uncovered, and that is where it misses the spec. Ungated is noisier under the gate but more correct.

## 4. Defects

I confirmed G1 and G2 with a probe script run against both trees.

**Gated**

- **G1: a cancelled worker dies silently and `join()` hangs forever.** This breaks "a worker must never die silently". Because `_raise_worker_failure` skips `worker.cancelled()`, the job is never finished and `_unfinished` never reaches 0. Probe output: `join HANGS`. `shutdown()` then raises a bare `AssertionError: shutdown left jobs in [RUNNING]` rather than `QueueInternalError`. The orphaned attempt task also keeps running, because the worker's `await asyncio.wait({attempt}, ...)` doesn't cancel it. Ungated reports `QueueInternalError ... worker jobqueue-worker-0 was cancelled`.
- **G2: a first `submit()` outside a running loop leaves the queue with no workers, permanently.** `_start_workers` assigns `self._waiting = asyncio.Queue()` and `self._wake` *before* `asyncio.get_running_loop()` raises. On every later `submit()`, `if self._waiting is not None: return` skips starting the workers. Probe output: `later submit NEVER RUNS`, and `join()` hangs. Ungated calls `get_running_loop()` first.

**Both builds**

- **"Growing delay" is not enforced.** `retry_backoff`/`backoff` may be exactly 1 (`< 1` is the check), and `retry_delay` may be 0. Either gives a constant or zero delay.
- **Retries continue through shutdown.** A job in backoff at shutdown time keeps retrying. "Lets running jobs finish" arguably covers this, but neither build documents it.
- **A job that swallows cancellation blocks its worker forever on timeout.** Gated waits with `await asyncio.wait({attempt})`; ungated relies on `asyncio.timeout`. Neither applies a bound.

**Ungated only:** none found against the spec.

## 5. Recommendations

1. **EXC001 false positive on cancel-and-re-raise.** Add a narrow exemption to `transparent_rethrow = false`: a handler for `asyncio.CancelledError` (or `BaseException`) whose last statement is a bare `raise` and which has no `return` or `break`. That is the required asyncio idiom. The block in this run pushed a test toward a weaker `finally`.
2. **A new rule for task outcomes that skip a branch.** Flag `task.cancelled()` / `task.exception() is None` checks whose branch is `continue`, `return` or `pass` with nothing recorded. Treat `Task.exception()` / `Future.exception()` as a catch of `BaseException` for EXC002 purposes, so silently dropping one branch is held to the same standard as an empty `except`. That would have caught G1.
3. **Skill wording on concurrency.** Add: "Reading an outcome from `Task.exception()` is a catch. Handle cancelled, errored and unexpectedly-finished tasks explicitly, and test each one." The gated build's docstring line "No exception is caught anywhere in this module" shows the agent believed it had sidestepped the question.
4. **ASSERT rule for production code.** Flag `assert` in production code that guards runtime state, and flag `raise AssertionError` on public paths. Under `-O` they vanish, and `shutdown()` raising a bare `AssertionError` is not the reporting the spec asks for.
5. **SLEEP001 stays at review severity.** The one gated finding, `await asyncio.sleep(self._backoff(record.attempts))`, is the backoff the spec requires. Consider not reporting a sleep whose argument is computed from configured settings inside a retry loop.
