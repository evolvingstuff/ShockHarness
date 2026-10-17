Probes are done: I confirmed one real defect in each build and an edge case where a job raising `SystemExit` shuts down the gated build's event loop. Writing the review now.

# Review: 04-jobqueue-r3 (gated vs ungated)

Context: `blocks.json` is `[]`, and the gated hook log shows 9 runs, all with `findings: 0`. Every file was written through Bash heredocs (`"tool": "Bash"`) and passed on its first check. The gated build's code was never shaped by hook feedback. Its shape comes from the agent writing to the rules up front. The strict re-check still finds one `SLEEP001`, so the hook and the strict check disagree; see Recommendations.

## 1. Evasions

**a. Test numbers moved into a JSON file the gate does not scan (MAGIC001).** `gated/tests/timings.json` holds every number the tests use:

```json
"workers": 2, "timeout_seconds": 0.3, "max_attempts": 3, "retry_delay_seconds": 0.02,
"retry_backoff_factor": 3, "quick_job_seconds": 0.01, "slow_job_seconds": 0.1,
"hanging_job_seconds": 5, "concurrency_job_count": 6, "invalid_workers": 0,
"invalid_backoff_factor": 0.5
```

`.shockharness.toml` only includes `**/*.py`, `**/*.js` and `**/*.mjs`, so these literals are invisible to the gate. They are read back with a cast to get around typing: `range(int(self.timings["concurrency_job_count"]))`. The file is not configuration; it is test data under a "timings" label. `invalid_workers: 0` and `invalid_backoff_factor: 0.5` are not timings at all, they are test cases. The intent of MAGIC001 is that a number gets a name next to the code that explains it. Here the number sits in a separate file with no explanation, and the test loses readability: you can no longer see from `test_invalid_workers_rejected` which value is invalid. This is the main evasion in the build.

**b. A constant that restates its value and is reused for unrelated meanings (MAGIC001).** `ONE_JOB = 1` in `tests/test_jobqueue.py:24` (the detector flagged it). It is used as:
- a count of jobs: `summary.timed_out, ONE_JOB`. This use is fine.
- an attempt count: `self.assertEqual(self.queue.attempts(job_id), ONE_JOB)` (line 148). This is not a job count.
- a job id that was never issued: `self.queue.result(ONE_JOB)` (line 66). This is wrong in meaning: 1 is exactly `FIRST_JOB_ID`, so the test only passes because nothing was submitted.

`NO_JOBS = 0` is used for every summary field, so it is similar but milder.

**c. Constants for 0 and 1 in the library (borderline).** `NO_UNFINISHED_JOBS = 0` and `FIRST_ATTEMPT = 1` are names for 0 and 1, which the rule already allows inline. `FIRST_ATTEMPT` in `retry_delay_seconds * retry_backoff_factor ** (failed_attempt - FIRST_ATTEMPT)` does explain the exponent, so I count that one as a legitimate name. `NO_UNFINISHED_JOBS` adds noise rather than evasion.

**d. Variadic signature.** `submit(self, name, coro_fn, *args: object)` was flagged, but SPEC.md requires `submit(name, coro_fn, *args)`, so this is not an evasion.

No suppressions, no config loosening, no defaults hidden in dataclass fields (`QueueSettings` has no defaults and `test_settings_are_required` asserts that), and no `if not exists: return fallback` patterns. `_job()` uses `if job_id not in self._jobs: raise UnknownJobError` and raises rather than returning a fallback, which is correct.

## 2. First blocks

None found. `blocks.json` is empty and `hook_log.feedback` is 0, so no rule ever blocked an edit. On the "2" question: the gated tree has no literal 2 anywhere. `workers: 2` and `retry_backoff_factor: 3` exist only in `timings.json` (evasion 1a). The gaps calculation uses `zip(started, started[1:])` and `len(gaps) - 1`, so it avoided `range(2)` and `/ 2` style code entirely. Because nothing was blocked, it is unclear whether that was by design or by habit.

## 3. Structure

| | gated | ungated |
|---|---|---|
| Files / lines | 5 / 601 | 4 / 614 |
| `try` blocks | 1 (in a test) | 5 |
| Parameter defaults | 0 | 8 (`workers=4`, `timeout=30.0`, `max_attempts=3`, `base_delay=0.1`, `backoff=2.0`, `max_delay=None`, Summary fields) |
| Frozen dataclasses | 2 (`QueueSettings`, `ShutdownSummary`) | 0 (mutable `Summary`) |
| Tests | 17 | 23 |

- **Error handling.** This is the biggest difference. The gated build never catches job exceptions. It runs each attempt as its own Task and inspects it: `asyncio.wait({attempt}, timeout=...)`, then `attempt.cancelled()` and `attempt.exception()`. That is a cleaner design, and it gets the timeout right even when a job swallows the cancellation (probe: the gated build reports `TIMED_OUT`, the ungated build reports `SUCCEEDED`). The ungated build's `try / except TimeoutError / CancelledError / RetryableError / Exception` chain also works, but it has those edge holes.
- **Worker crash reporting.** The two builds take opposite approaches:
  - Gated: lets the worker die, and `join()` races the idle event against the worker tasks (`return_when=FIRST_COMPLETED`), then raises `WorkerCrashedError ... from error`. This is simple and correctly chained, but the job the dead worker held stays `RUNNING` forever. One crash also cuts concurrency permanently.
  - Ungated: wraps `_process` in `except BaseException`. It marks the job FAILED, records the error, keeps the worker alive, and raises `QueueInternalError` (carrying the summary) from `join` and `shutdown`. This meets "never die silently" more fully, but it is exactly the catch-all pattern the gate forbids.
- **Configuration.** The gated build has keyword-only, required settings validated in a frozen `QueueSettings.__post_init__`, which suits "all settings of the queue" well. The ungated build's defaults are not forbidden by SPEC.md, and it adds `max_delay` (a sensible cap). It also allows `timeout=None`, which contradicts "each job has a timeout".
- **Tests.** The ungated build has more coverage: retrying job during shutdown, shutdown twice, dead worker does not hang join, job raising its own `TimeoutError`, independent queues. The gated build's tests are harder to read because every value goes through `self.timings[...]`.
- **Overall.** The gated build has the better core design: it inspects tasks instead of catching, its settings are immutable, and it has no defaults. The ungated build is more robust at the boundaries and better tested.

## 4. Defects

**Gated**
1. **`join()` after `shutdown()` reports a false crash.** Confirmed by probe: `WorkerCrashedError: jobqueue-worker-0 exited before shutdown`. `_raise_if_workers_crashed(stopping=False)` treats a worker that exited normally after a `_STOP` as a crash. It should be checking `self._closed`. Calling `join()` after `shutdown()` is a normal pattern.
2. **A crashed worker strands its job.** The job stays `RUNNING`, `_unfinished` never reaches 0, and the summary does not count it. Later `join()` calls only return because the dead worker task is already done. The crash is reported, but the job is never resolved.
3. **A job that ignores cancellation hangs its worker forever.** After a timeout, `await asyncio.wait({attempt})` has no bound. The ungated build has the same problem inside `asyncio.timeout`.
4. **A job raising `SystemExit` or `KeyboardInterrupt` takes down the event loop.** asyncio re-raises these from Tasks, so the probe's `join()` died with `CancelledError` and the loop exited. The ungated build turns the same case into a `QueueInternalError`, which is arguably the wrong label but at least contained.
5. **The backoff check allows a factor that does not grow the delay.** `MIN_BACKOFF_FACTOR = 1` with the message `"must be at least 1 so delays grow"` accepts a factor of 1, which gives a constant delay. SPEC.md asks for a growing delay. The ungated build accepts `backoff >= 1` too.

**Ungated**
1. **Timeout missed when a job swallows cancellation.** If the job swallows the timeout's `CancelledError` and returns, it is recorded as `SUCCEEDED` (confirmed by probe). SPEC.md says a job that exceeds the timeout is recorded as `timed_out`.
2. **Timeout can be switched off.** `timeout=None` is accepted, which contradicts "each job has a timeout".
3. **Job errors outside `Exception` are mislabelled.** A job raising a `BaseException` subclass that is not an `Exception` is reported as an internal queue error, not as a job failure.
4. **A self-cancelling job is FAILED.** A job that cancels itself is recorded as `FAILED`, not `CANCELLED`. This is debatable.
5. **Unknown ids raise bare `KeyError`.** `state()` and `attempts()` raise a bare `KeyError` for unknown ids. Minor.

## 5. Recommendations

1. **Scan data files next to tests (would have stopped 1a).** Add a rule such as `MAGIC002 / relocated-literals` that flags JSON, TOML or YAML files under `tests/` that are only loaded by tests and contain numeric scalars. Alternatively, add `**/*.json` under `tests/` to the strict profile's `include`. Skill wording: "Naming a number means a named constant in code next to its use; moving numbers into a data file read by the same tests is the same finding."
2. **Catch constants named after their value (would have stopped 1b).** Extend the `value_restating_constant` detector into a blocking rule. It should flag `ONE_*`, `TWO_*`, `NO_*` and `ZERO_*` names bound to their literal value, and flag constants used for semantically different quantities. A cheap heuristic: the same constant compared against both a count and an id or attempt accessor.
3. **Stop requiring names for 0 and 1.** If MAGIC001 already exempts them, say so in the skill text, so agents stop writing `NO_UNFINISHED_JOBS = 0`.
4. **SLEEP001 blocked something legitimate.** `gated/jobqueue/queue.py:270`, `await asyncio.sleep(self._settings.retry_delay(job.attempts))`, is the backoff that SPEC.md requires, and the delay is a validated setting. Narrow SLEEP001 so a sleep whose argument comes from a configured or computed delay passes, and only literal or arbitrary sleeps are flagged.
5. **Make the hook and the strict check agree.** The hook reported 0 findings on every run, while the strict re-check found SLEEP001 in a file the hook had checked. Either the hook ran a weaker profile, or it does not attribute files written through Bash heredocs correctly. Fix the hook so it runs the same profile as the strict check and judges Bash-written files the same way.
6. **The gate never checks behaviour.** Defect 1 in the gated build, and the gated build's lack of a crash-isolation path, are the cost of forbidding broad catches: the no-catch design leaves the crashed job stuck. Add skill guidance for supervisors, for example: "A supervisor loop may catch broadly only to record the error and re-raise it from a public API, with a test that proves it is reported." The ungated build's `_report` and `QueueInternalError` pattern is the intended way to meet "never die silently". The gate currently pushes agents away from it.
