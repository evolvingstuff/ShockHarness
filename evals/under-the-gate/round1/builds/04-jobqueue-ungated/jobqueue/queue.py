"""In-process async job queue with a fixed number of workers."""

import asyncio
import itertools
from dataclasses import dataclass, field


class RetryableError(Exception):
    """Raise from a job to have it retried (up to the queue's max_attempts)."""


class QueueClosed(Exception):
    """submit() was called after shutdown()."""


class JobCancelled(Exception):
    """The job was cancelled by shutdown() before it started."""


class JobNotFinished(Exception):
    """result() was called for a job that has not finished yet."""


class QueueInternalError(Exception):
    """The queue's own code failed; `errors` holds the underlying exceptions."""

    def __init__(self, errors, summary=None):
        super().__init__(f"{len(errors)} internal error(s): {errors!r}")
        self.errors = list(errors)
        self.summary = summary


@dataclass(frozen=True)
class Summary:
    succeeded: int = 0
    failed: int = 0
    timed_out: int = 0
    cancelled: int = 0


PENDING, RUNNING = "pending", "running"
SUCCEEDED, FAILED, TIMED_OUT, CANCELLED = "succeeded", "failed", "timed_out", "cancelled"


@dataclass
class _Job:
    id: int
    name: str
    fn: object
    args: tuple
    status: str = PENDING
    attempts: int = 0
    value: object = None
    error: BaseException | None = None


class JobQueue:
    def __init__(
        self,
        workers=4,
        timeout=30.0,
        max_attempts=3,
        base_delay=0.1,
        backoff=2.0,
        max_delay=10.0,
    ):
        if workers < 1 or max_attempts < 1:
            raise ValueError("workers and max_attempts must be >= 1")
        self.workers = workers
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.backoff = backoff
        self.max_delay = max_delay
        self._queue = asyncio.Queue()
        self._jobs = {}
        self._ids = itertools.count(1)
        self._tasks = []
        self._closed = False
        self._internal_errors = []

    # -- public API ---------------------------------------------------

    def submit(self, name, coro_fn, *args):
        if self._closed:
            raise QueueClosed("queue is shut down")
        if not self._tasks:
            loop = asyncio.get_running_loop()
            self._tasks = [
                loop.create_task(self._worker(), name=f"jobqueue-worker-{i}")
                for i in range(self.workers)
            ]
        job = _Job(next(self._ids), name, coro_fn, args)
        self._jobs[job.id] = job
        self._queue.put_nowait(job)
        return job.id

    async def join(self):
        await self._queue.join()
        self._raise_internal()

    def result(self, job_id):
        job = self._jobs[job_id]
        if job.status == SUCCEEDED:
            return job.value
        if job.status in (PENDING, RUNNING):
            raise JobNotFinished(f"job {job_id} is {job.status}")
        raise job.error

    def status(self, job_id):
        return self._jobs[job_id].status

    async def shutdown(self):
        self._closed = True
        while True:
            try:
                job = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            job.status = CANCELLED
            job.error = JobCancelled(f"job {job.id} ({job.name}) cancelled by shutdown")
            self._queue.task_done()
        await self._queue.join()  # running jobs finish
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        counts = {s: 0 for s in (SUCCEEDED, FAILED, TIMED_OUT, CANCELLED)}
        for job in self._jobs.values():
            if job.status in counts:
                counts[job.status] += 1
        summary = Summary(**counts)
        if self._internal_errors:
            raise QueueInternalError(self._internal_errors, summary)
        return summary

    # -- internals ----------------------------------------------------

    def _raise_internal(self):
        if self._internal_errors:
            raise QueueInternalError(self._internal_errors)

    async def _worker(self):
        while True:
            job = await self._queue.get()
            try:
                await self._run_job(job)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # bug in the queue itself: record, keep going
                self._internal_errors.append(exc)
                if job.status in (PENDING, RUNNING):
                    job.status, job.error = FAILED, exc
            finally:
                self._queue.task_done()

    def _delay(self, attempt):
        return min(self.base_delay * self.backoff ** (attempt - 1), self.max_delay)

    async def _run_job(self, job):
        job.status = RUNNING
        while True:
            job.attempts += 1
            try:
                async with asyncio.timeout(self.timeout) as scope:
                    job.value = await job.fn(*job.args)
                job.status = SUCCEEDED
                return
            except TimeoutError as exc:
                if scope.expired():
                    job.status, job.error = TIMED_OUT, exc
                    return
                job.status, job.error = FAILED, exc
                return
            except RetryableError as exc:
                if job.attempts >= self.max_attempts:
                    job.status, job.error = FAILED, exc
                    return
                await asyncio.sleep(self._delay(job.attempts))
            except Exception as exc:
                job.status, job.error = FAILED, exc
                return
