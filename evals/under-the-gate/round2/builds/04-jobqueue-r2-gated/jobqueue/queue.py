"""The job queue: fixed workers, a per-attempt timeout, retries with growing delays."""

import asyncio
import enum
import itertools
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from jobqueue.errors import (
    JobCancelled,
    JobNotFinished,
    JobTimedOut,
    QueueClosed,
    QueueCrashed,
    RetryableError,
    UnknownJob,
)

MIN_WORKERS = 1
MIN_ATTEMPTS = 1
FIRST_ATTEMPT = 1
FIRST_JOB_ID = 1
ALL_FINISHED = 0


class JobState(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


TERMINAL_STATES = frozenset(
    {JobState.SUCCEEDED, JobState.FAILED, JobState.TIMED_OUT, JobState.CANCELLED}
)


@dataclass(frozen=True)
class ShutdownSummary:
    succeeded: int
    failed: int
    timed_out: int
    cancelled: int


class _Job:
    """Mutable record of one submitted job; owned and changed only by its JobQueue."""

    def __init__(self, job_id: int, name: str, coro_fn: Callable[..., Awaitable[object]], args: tuple[object, ...]) -> None:
        self.job_id = job_id
        self.name = name
        self.coro_fn = coro_fn
        self.args = args
        self.state = JobState.PENDING
        self.attempts = 0
        self.value: object = None
        self.error: BaseException | None = None


class _Stop:
    """Queue item that tells a worker to exit."""


_STOP = _Stop()


async def _call(job: _Job) -> object:
    """Run one attempt of a job; anything it raises stays inside the attempt's task."""
    return await job.coro_fn(*job.args)


class JobQueue:
    """Runs submitted async jobs on ``workers`` worker tasks.

    Must be created inside a running event loop: the workers start at once.
    ``timeout`` (seconds) applies to each attempt. A job raising ``RetryableError``
    runs again, up to ``max_attempts`` attempts in total, after a delay of
    ``retry_delay * backoff_factor ** (failed_attempts - 1)`` seconds.
    """

    def __init__(
        self,
        *,
        workers: int,
        timeout: float,
        max_attempts: int,
        retry_delay: float,
        backoff_factor: float,
    ) -> None:
        if isinstance(workers, bool) or not isinstance(workers, int) or workers < MIN_WORKERS:
            raise ValueError(f"workers must be an integer >= {MIN_WORKERS}, got {workers!r}")
        if timeout <= 0:
            raise ValueError(f"timeout must be positive, got {timeout!r}")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < MIN_ATTEMPTS:
            raise ValueError(f"max_attempts must be an integer >= {MIN_ATTEMPTS}, got {max_attempts!r}")
        if retry_delay <= 0:
            raise ValueError(f"retry_delay must be positive, got {retry_delay!r}")
        if backoff_factor <= 1:
            raise ValueError(f"backoff_factor must be greater than 1 so delays grow, got {backoff_factor!r}")
        self._timeout = timeout
        self._max_attempts = max_attempts
        self._retry_delay = retry_delay
        self._backoff_factor = backoff_factor
        self._ids = itertools.count(FIRST_JOB_ID)
        self._jobs: dict[int, _Job] = {}
        self._pending: asyncio.Queue[_Job | _Stop] = asyncio.Queue()
        self._unfinished = 0
        self._idle = asyncio.Event()
        self._idle.set()
        self._closed = False
        self._workers = tuple(asyncio.create_task(self._work()) for _ in range(workers))

    def submit(self, name: str, coro_fn: Callable[..., Awaitable[object]], *args: object) -> int:
        """Queue ``coro_fn(*args)`` and return its job id."""
        if self._closed:
            raise QueueClosed(f"cannot submit {name!r}: the queue is shut down")
        job = _Job(next(self._ids), name, coro_fn, args)
        self._jobs[job.job_id] = job
        self._unfinished += 1
        self._idle.clear()
        self._pending.put_nowait(job)
        return job.job_id

    async def join(self) -> None:
        """Wait until every submitted job has finished; raise QueueCrashed if a worker died."""
        idle = asyncio.create_task(self._idle.wait())
        await asyncio.wait({idle, *self._workers}, return_when=asyncio.FIRST_COMPLETED)
        if not idle.done():
            idle.cancel()
            await asyncio.wait({idle})
        self._raise_if_crashed()

    def result(self, job_id: int) -> object:
        """Return the job's result, or raise its error (JobTimedOut, JobCancelled, its own)."""
        if job_id not in self._jobs:
            raise UnknownJob(f"no job with id {job_id!r}")
        job = self._jobs[job_id]
        if job.state is JobState.SUCCEEDED:
            return job.value
        if job.state is JobState.FAILED:
            if job.error is None:
                raise AssertionError(f"failed job {job_id} recorded no error")
            raise job.error
        if job.state is JobState.TIMED_OUT:
            raise JobTimedOut(f"job {job_id} ({job.name!r}) exceeded {self._timeout}s")
        if job.state is JobState.CANCELLED:
            raise JobCancelled(f"job {job_id} ({job.name!r}) was cancelled")
        raise JobNotFinished(f"job {job_id} ({job.name!r}) is {job.state.value}")

    async def shutdown(self) -> ShutdownSummary:
        """Stop accepting jobs, cancel waiting ones, let running ones finish, summarize."""
        if self._closed:
            raise QueueClosed("the queue is already shut down")
        self._closed = True
        while not self._pending.empty():
            item = self._pending.get_nowait()
            if isinstance(item, _Stop):
                raise AssertionError("a stop item was queued before shutdown")
            self._finish(item, JobState.CANCELLED)
        for _ in self._workers:
            self._pending.put_nowait(_STOP)
        await asyncio.wait(self._workers)
        self._raise_if_crashed()
        return self._summary()

    def _summary(self) -> ShutdownSummary:
        states = [job.state for job in self._jobs.values()]
        summary = ShutdownSummary(
            succeeded=states.count(JobState.SUCCEEDED),
            failed=states.count(JobState.FAILED),
            timed_out=states.count(JobState.TIMED_OUT),
            cancelled=states.count(JobState.CANCELLED),
        )
        counted = summary.succeeded + summary.failed + summary.timed_out + summary.cancelled
        if counted != len(states):
            raise AssertionError(f"summary counts {counted} of {len(states)} jobs")
        return summary

    def _raise_if_crashed(self) -> None:
        errors: list[BaseException] = []
        for worker in self._workers:
            if not worker.done():
                continue
            if worker.cancelled():
                errors.append(asyncio.CancelledError("a worker was cancelled"))
                continue
            error = worker.exception()
            if error is not None:
                errors.append(error)
        if errors:
            raise QueueCrashed(tuple(errors)) from errors[0]

    async def _work(self) -> None:
        while True:
            item = await self._pending.get()
            if isinstance(item, _Stop):
                return
            await self._run(item)

    async def _run(self, job: _Job) -> None:
        job.state = JobState.RUNNING
        for attempt in range(FIRST_ATTEMPT, self._max_attempts + 1):
            job.attempts = attempt
            task = asyncio.create_task(_call(job))
            done, _ = await asyncio.wait({task}, timeout=self._timeout)
            if not done:
                task.cancel()
                await asyncio.wait({task})
                self._finish(job, JobState.TIMED_OUT)
                return
            if task.cancelled():
                self._finish(job, JobState.CANCELLED)
                return
            error = task.exception()
            if error is None:
                job.value = task.result()
                self._finish(job, JobState.SUCCEEDED)
                return
            job.error = error
            if not isinstance(error, RetryableError) or attempt == self._max_attempts:
                self._finish(job, JobState.FAILED)
                return
            await asyncio.sleep(self._retry_delay * self._backoff_factor ** (attempt - 1))
        raise AssertionError(f"job {job.job_id} left the retry loop without an outcome")

    def _finish(self, job: _Job, state: JobState) -> None:
        if state not in TERMINAL_STATES:
            raise AssertionError(f"{state} is not a final state")
        job.state = state
        self._unfinished -= 1
        if self._unfinished == ALL_FINISHED:
            self._idle.set()
