"""The job queue: submit async jobs, run them with a fixed set of workers, collect results.

Job failures are observed without try/except: every attempt runs as its own task and
the worker inspects the finished task (cancelled, exception or result). An error in
the queue's own code ends the worker task with that error, and join() and shutdown()
raise it as QueueInternalError.
"""

import asyncio
import enum
import itertools
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from jobqueue.errors import (
    JobCancelledError,
    JobNotFinishedError,
    JobTimeoutError,
    QueueClosedError,
    QueueInternalError,
    RetryableError,
)
from jobqueue.settings import MIN_ATTEMPTS, QueueSettings

JobFunction = Callable[..., Awaitable[object]]

# Put on the pending queue once per worker by shutdown(): the worker exits when it takes one.
_STOP_SIGNAL = None


class JobStatus(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


FINISHED_STATUSES = frozenset(
    {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.TIMED_OUT, JobStatus.CANCELLED}
)


@dataclass(frozen=True)
class ShutdownSummary:
    succeeded: int
    failed: int
    timed_out: int
    cancelled: int


class _Job:
    """Mutable record of one submitted job; owned and updated only by its queue."""

    def __init__(self, job_id: int, name: str, function: JobFunction, args: tuple[object, ...]) -> None:
        self.job_id = job_id
        self.name = name
        self.function = function
        self.args = args
        self.status = JobStatus.PENDING
        self.attempts = 0
        self.result: object = None
        self.error: BaseException | None = None


async def _invoke(job: _Job) -> object:
    """Run one attempt; calling the job function inside the task makes a synchronous raise a task error."""
    return await job.function(*job.args)


class JobQueue:
    """Runs submitted async jobs with a fixed number of workers.

    Must be used from inside a running event loop: workers start on the first submit().
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
        self._settings = QueueSettings(
            workers=workers,
            timeout=timeout,
            max_attempts=max_attempts,
            retry_delay=retry_delay,
            backoff_factor=backoff_factor,
        )
        self._jobs: dict[int, _Job] = {}
        self._ids = itertools.count()
        self._pending: asyncio.Queue[_Job | None] = asyncio.Queue()
        self._workers: list[asyncio.Task[None]] = []
        self._unfinished = 0
        self._idle = asyncio.Event()
        self._idle.set()
        self._accepting = True
        self._stopping = False

    @property
    def settings(self) -> QueueSettings:
        return self._settings

    def submit(self, name: str, coro_fn: JobFunction, *args: object) -> int:
        """Queue a job and return its id."""
        if not self._accepting:
            raise QueueClosedError(f"queue is shut down; job {name!r} was not accepted")
        self._start_workers()
        job = _Job(next(self._ids), name, coro_fn, args)
        self._jobs[job.job_id] = job
        self._unfinished += 1
        self._idle.clear()
        self._pending.put_nowait(job)
        return job.job_id

    def status(self, job_id: int) -> JobStatus:
        return self._jobs[job_id].status

    def attempts(self, job_id: int) -> int:
        return self._jobs[job_id].attempts

    def result(self, job_id: int) -> object:
        """Return the job's result, or raise its error; raises KeyError for an unknown id."""
        job = self._jobs[job_id]
        if job.status not in FINISHED_STATUSES:
            raise JobNotFinishedError(job_id)
        if job.error is not None:
            raise job.error
        return job.result

    async def join(self) -> None:
        """Wait until every submitted job has finished; raise QueueInternalError if a worker failed."""
        idle = asyncio.create_task(self._idle.wait())
        await asyncio.wait({idle, *self._workers}, return_when=asyncio.FIRST_COMPLETED)
        if not idle.done():
            idle.cancel()
            await asyncio.wait({idle})
        self._raise_worker_failures()

    async def shutdown(self) -> ShutdownSummary:
        """Stop accepting jobs, cancel waiting ones, let running ones finish, and summarize."""
        self._accepting = False
        self._stopping = True
        while not self._pending.empty():
            job = self._pending.get_nowait()
            if job is not _STOP_SIGNAL:
                self._finish(job, JobStatus.CANCELLED, JobCancelledError(job.job_id, "queue shut down"))
        for _ in self._workers:
            self._pending.put_nowait(_STOP_SIGNAL)
        if self._workers:
            await asyncio.wait(self._workers)
        self._raise_worker_failures()
        return self._summary()

    def _start_workers(self) -> None:
        if self._workers:
            return
        self._workers = [asyncio.create_task(self._work()) for _ in range(self._settings.workers)]

    async def _work(self) -> None:
        while True:
            job = await self._pending.get()
            if job is _STOP_SIGNAL:
                return
            await self._run(job)

    async def _run(self, job: _Job) -> None:
        job.status = JobStatus.RUNNING
        for attempt in range(MIN_ATTEMPTS, self._settings.max_attempts + 1):
            job.attempts = attempt
            task = asyncio.create_task(_invoke(job))
            done, _ = await asyncio.wait({task}, timeout=self._settings.timeout)
            if task not in done:
                task.cancel()
                await asyncio.wait({task})
                self._finish(job, JobStatus.TIMED_OUT, JobTimeoutError(job.job_id, self._settings.timeout))
                return
            if task.cancelled():
                self._finish(job, JobStatus.CANCELLED, JobCancelledError(job.job_id, "the job cancelled itself"))
                return
            error = task.exception()
            if error is None:
                job.result = task.result()
                self._finish(job, JobStatus.SUCCEEDED, None)
                return
            if not isinstance(error, RetryableError) or attempt == self._settings.max_attempts:
                self._finish(job, JobStatus.FAILED, error)
                return
            await asyncio.sleep(self._settings.delay_after(attempt))
        raise AssertionError(f"job {job.job_id} left the attempt loop without an outcome")

    def _finish(self, job: _Job, status: JobStatus, error: BaseException | None) -> None:
        if status not in FINISHED_STATUSES:
            raise ValueError(f"{status} is not a finished status")
        job.status = status
        job.error = error
        self._unfinished -= 1
        if self._unfinished < 0:
            raise AssertionError("more jobs finished than were submitted")
        if self._unfinished == 0:
            self._idle.set()

    def _raise_worker_failures(self) -> None:
        errors: list[BaseException] = []
        for worker in self._workers:
            if not worker.done():
                continue
            if worker.cancelled():
                errors.append(asyncio.CancelledError("worker task was cancelled"))
                continue
            error = worker.exception()
            if error is not None:
                errors.append(error)
            elif not self._stopping:
                errors.append(RuntimeError("worker exited before shutdown"))
        if errors:
            raise QueueInternalError(tuple(errors)) from errors[0]

    def _summary(self) -> ShutdownSummary:
        counts = {status: 0 for status in JobStatus}
        for job in self._jobs.values():
            counts[job.status] += 1
        return ShutdownSummary(
            succeeded=counts[JobStatus.SUCCEEDED],
            failed=counts[JobStatus.FAILED],
            timed_out=counts[JobStatus.TIMED_OUT],
            cancelled=counts[JobStatus.CANCELLED],
        )
