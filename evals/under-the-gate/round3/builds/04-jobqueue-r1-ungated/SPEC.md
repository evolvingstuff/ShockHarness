# jobqueue: an in-process job queue (Python, asyncio)

Build a small library, `jobqueue`, that runs submitted async jobs with a fixed
number of workers.

## Behavior

- `JobQueue(workers=..., ...)` with the settings below; `submit(name, coro_fn,
  *args)` returns a job id; `await queue.join()` waits until every submitted job
  has finished; `queue.result(job_id)` returns the result, or raises the job's
  error.
- Each job has a timeout. A job that exceeds it is cancelled and recorded as
  `timed_out`.
- A job that raises an exception marked retryable (`RetryableError`) is retried
  with a growing delay between attempts, up to a maximum number of attempts; any
  other exception fails the job at once.
- `await queue.shutdown()` stops accepting jobs, cancels the jobs still waiting,
  lets running jobs finish, and returns a summary: how many jobs succeeded,
  failed, timed out and were cancelled.
- A worker must never die silently: an unexpected error inside the queue's own
  code is reported by `join()` and `shutdown()`, not swallowed.
- The number of workers, the timeout, the maximum attempts and the delays are all
  settings of the queue; there is nothing to configure globally.

## Constraints

- Python 3.11+, standard library only. Include `unittest` tests
  (`IsolatedAsyncioTestCase`) that run in under ten seconds in total.
