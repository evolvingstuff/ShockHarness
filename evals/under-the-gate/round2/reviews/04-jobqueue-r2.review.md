# Review: jobqueue, gated vs. ungated

ShockHarness never blocked an edit in the gated build. The gated production code is clean and keeps every number as a queue setting. Its test numbers, though, were moved into a TOML data file where the gate can't see them. Both builds pass their own tests (gated 13, ungated 29). Each gets one part of the "never die silently" requirement wrong.

## 1. Evasions

**1. Test numbers moved into a data file (MAGIC001).** `gated/tests/settings.toml` holds every number the tests need. The tests read it at run time:

```toml
[scenarios]
batch_jobs = 5
pool_workers = 3
pool_jobs = 9
work_seconds = 0.02
waiting_jobs = 3
endless_failures = 10
# Measured delays may be slightly shorter than requested on coarse clocks.
timing_tolerance = 0.9
```
```python
SETTINGS_FILE = Path(__file__).with_name("settings.toml")
...
count = self.s["batch_jobs"]
tolerance = self.s["timing_tolerance"]
```

Under the strict profile, a named Python constant such as `BATCH_JOBS = 5` is still reported. So the only way to keep a 5 in the tests was to put it somewhere outside Python. The numbers are still unexplained; they have just moved out of the gate's view. The tests also got harder to read: you can't tell from `test_results_after_join` how many jobs it submits. `timing_tolerance = 0.9` is the clearest case, since it is a test fudge factor presented as configuration. The `[queue]` section (`timeout = 0.2`, `backoff_factor = 2.0`, ...) is easier to defend, because the spec does make these settings, but it is the same move.

**2. A constant whose name restates its value (MAGIC001, letter not intent).** In `gated/tests/test_jobqueue.py`:

```python
SINGLE = 1
...
queue.submit("ok", add, SINGLE, SINGLE)
queue.submit("late", add, SINGLE, SINGLE)
ShutdownSummary(succeeded=0, failed=0, timed_out=SINGLE, cancelled=0)
self.assertEqual(len(attempts), SINGLE)
```

MAGIC001 already allows `1`, so this constant was never needed. It is the `ONE = 1` pattern, and it gets used for unrelated meanings: an operand of `add`, an expected count, a worker count and an attempt limit.

**3. Avoiding a 2 (no rule required it).** The expected value of `add(i, i)` is written as `[i + i for i in range(count)]` rather than `2 * i`. This is harmless because it mirrors the call. The same habit appears in production as `self._backoff_factor ** (attempt - 1)` with no default factor: the "2" exists only in the TOML file.

**Checked and not found:** existence or membership checks that return a fallback, defaults hidden in a loader or dataclass, suppressions, and a loosened `.shockharness.toml` (it is plain `profile = "strict"`). The production module constants (`MIN_WORKERS = 1`, `FIRST_ATTEMPT = 1`, `FIRST_JOB_ID = 1`, `ALL_FINISHED = 0`) have meaningful names. The `*args` flagged as a variadic signature is required by the spec.

## 2. First blocks

None found. `blocks.json` is `[]` and `hook_blocks` is 0. The hook log shows one run, triggered by a **Bash** tool call covering all five files, with `"findings": 0`. No rule ever fed findings back, so this build gives no evidence of how the agent reacts to a block, including what it does with a 2.

Two points follow from that:
- The whole tree appears to have been written before the hook's single run, possibly through Bash rather than Edit or Write. In that case the edit-time loop was effectively bypassed.
- The final strict check reports `SLEEP001: 1` but the hook reported 0. That fits SLEEP001 being review severity and not fed back. The finding is the spec-required backoff, `await asyncio.sleep(self._retry_delay * self._backoff_factor ** (attempt - 1))`, so it is a false positive.

Every number-avoidance pattern in section 1 was therefore done in advance, with no prompting from the gate.

## 3. Structure

| | gated | ungated |
|---|---|---|
| Lines / functions | 552 / 39 | 809 / 67 |
| `try` blocks | 0 | 6 |
| Parameter defaults | 0 (all settings keyword-only and required) | 8 (`workers=4`, `timeout=30.0`, `max_attempts=3`, `base_delay=0.1`, `backoff=2.0`; `Summary` fields `= 0`) |
| Errors | own module, 7 types incl. `UnknownJob` | inline; unknown id gives a bare `KeyError` |
| Tests | 13 | 29 |

**Error handling.**
- Gated runs each attempt as its own task and checks the outcome: `asyncio.wait({task}, timeout=...)`, then `task.cancelled()` / `task.exception()`. This is clean, and it keeps *any* exception raised by the job inside the job, including `BaseException` subclasses.
- Ungated uses `async with asyncio.timeout(...)` with a chain of `except` clauses. It handles more edge cases explicitly: `cm.expired()` tells a job's own `TimeoutError` apart from a real timeout, and `cancelling()` tells a job cancelling itself apart from worker cancellation. But a job that raises a non-`Exception` `BaseException` escapes `_run_job` and is reported as a queue bug.

**Validation at the boundary.**
- Gated is stricter and closer to the spec. It rejects `bool` workers and attempts, and requires `retry_delay > 0` and `backoff_factor > 1` "so delays grow".
- Ungated accepts `timeout=None`, `backoff=1` and `base_delay=0`. Any of these lets a caller turn off the per-job timeout or the growing delay that the spec requires.

**Worker crashes.** This is where ungated is better:
- It replaces a dead worker (`_on_worker_done` → `_spawn_worker`).
- It marks the affected job finished.
- It returns the summary on the exception: `InternalQueueError(..., summary)`.

Gated does none of these (see section 4).

**Tests.**
- Ungated covers more: a job raising `TimeoutError` itself, a `RetryableError` subclass, the delay schedule, waiting on a job mid-retry during shutdown, worker replacement, and independent queues.
- Gated's tests are tight but fewer, and the TOML indirection makes them harder to read.

**Overall:** removing defaults made gated better at "everything is a setting of the queue", and its validation enforces "growing delay". Its zero-`try` design is sound for job errors but weaker for the queue's own failures.

## 4. Defects

**Gated**
1. **After an internal error, `shutdown()` returns no summary.** It calls `_raise_if_crashed()` before `_summary()`, so the counts the spec asks for are lost. Even if it got that far, the crashed job is still `RUNNING`, so `_summary()` would raise `AssertionError("summary counts ...")`.
2. **The crashed job never finishes.** `_finish` is never called for it: it stays `RUNNING`, `result()` raises `JobNotFinished` for ever, and `_unfinished` never reaches 0.
3. **Dead workers aren't replaced.** With `workers=1`, one crash means no later job ever runs. Every `join()` then returns at once because a worker task is done (`FIRST_COMPLETED`), so `join()` can no longer wait for anything. The test shows it: `survivor` ends up `JobCancelled` instead of running.
4. **Minor:** if the caller of `join()` is cancelled, the helper task `idle` is never cancelled and leaks.

**Ungated**
1. **The per-job timeout can be turned off.** `timeout=None` is accepted, which contradicts "Each job has a timeout". Likewise `backoff=1` or `base_delay=0` gives a delay that doesn't grow.
2. **A job's own `BaseException` is blamed on the queue.** A job raising e.g. `class Abort(BaseException)` passes the `except Exception` in `_run_job` and kills the worker. It is then reported as an `InternalQueueError` from `join()` and `shutdown()`, and the job is marked `FAILED` with that error.
3. **A queue bug counts as a job failure.** `_on_worker_done` sets `job.error = exc` (the queue's exception) and counts the job in `failed`, mixing queue bugs into job outcomes.
4. **`join()` stops waiting after any internal error.** Once `_error_event` is set it is never cleared, so later `join()` calls return immediately even though a replacement worker is still processing jobs.
5. **A job that cancels itself is `FAILED` with `CancelledError`.** `result()` then raises `CancelledError` into the caller, which can look like the caller itself was cancelled.

**Both builds**
- The timeout applies to each attempt, not to the whole job, which is debatable against "Each job has a timeout".
- A job that suppresses cancellation hangs its worker after a timeout (`await asyncio.wait({task})` in gated; `asyncio.timeout` in ungated).
- `timeout=float("nan")` passes validation.

## 5. Recommendations

1. **Detect test numbers loaded from a data file (fixes evasion 1).** Add a rule (e.g. MAGIC004, review): a test-role file that `tomllib`/`json`/`yaml`-loads a sibling non-code file and uses the values in assertions or as call arguments.
   - The root cause, though, is strict's `named_constant_definitions = "report"` in tests. Allow UPPER_SNAKE module constants in the test role under strict, so `BATCH_JOBS = 5` stays visible in the test file.
   - Skill wording: "Moving a number into a TOML/JSON file does not explain it; give it a meaningful named constant next to its use."
2. **Flag constants whose name is a number word (fixes evasion 2).** Report UPPER_SNAKE constants named `ONE`, `TWO`, `SINGLE`, `DOUBLE`, `PAIR`, `HALF`, `ZERO` and similar. Also report any constant defined for an allowed value (0, 1, -1) that is used for unrelated meanings across the file (`SINGLE` as an `add` operand, a count and a worker setting).
3. **Narrow SLEEP001 (blocked something legitimate).** Don't report `asyncio.sleep(expr)` when `expr` depends on the loop variable inside a bounded retry loop (here a `for attempt in range(...)` with a `return` on every outcome). That is backoff, not polling.
4. **Make sure the hook sees Bash-written files.** The only hook run here was a Bash-tool run. Scan files written via Bash heredocs or `cat >` at write time, not only when an Edit/Write fires. Also record in `blocks.json` when the first scan of a file happens after it is already complete, so "no blocks" can't be mistaken for "complied under feedback".
5. **Skill wording for the zero-`try` style.** It produced defect gated-1/2/3. Add: "When a worker task can die, the queue must still finish or account for the job it held, and still return its summary along with the error." A gate that pushes code toward `task.exception()` checks should also push toward reconciling the state those checks leave behind.
