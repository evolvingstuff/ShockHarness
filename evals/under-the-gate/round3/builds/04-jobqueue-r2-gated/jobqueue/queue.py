"""An in-process job queue that runs async jobs on a fixed number of workers.

Job outcomes are read from finished tasks (``task.cancelled()``,
``task.exception()``) rather than caught, so a job's error is recorded exactly
as it was raised and the queue's own errors are never mistaken for a job's.
"""

import asyncio
import enum
import itertools
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

FIRST_JOB_ID = 1
FIRST_ATTEMPT = 1


class RetryableError(Exception):
    """Raised by a job to ask for another attempt after a delay."""


class QueueError(Exception):
    """Base class of the errors the queue itself raises."""


class QueueClosedError(QueueError):
    """A job was submitted after shutdown began."""


class UnknownJobError(QueueError):
    """A job id that this queue never issued."""


class JobNotFinishedError(QueueError):
    """The result of a job that is still pending or running was requested."""


class JobTimedOutError(QueueError):
    """The job exceeded its timeout and was cancelled."""


class JobCancelledError(QueueError):
    """The job was cancelled before it produced a result."""


class WorkerCrashedError(QueueError):
    """A worker stopped on an unexpected error inside the queue's own code."""


class JobStatus(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class QueueSettings:
    """Every setting of a queue; validated on construction."""

    workers: int
    timeout_seconds: float
    max_attempts: int
    initial_delay_seconds: float
    delay_multiplier: float

    def __post_init__(self) -> None:
        if self.workers < 1:
            raise ValueError(f"workers must be at least 1, got {self.workers}")
        if self.timeout_seconds <= 0:
            raise ValueError(f"timeout_seconds must be positive, got {self.timeout_seconds}")
        if self.max_attempts < 1:
            raise ValueError(f"max_attempts must be at least 1, got {self.max_attempts}")
        if self.initial_delay_seconds < 0:
            raise ValueError(
                f"initial_delay_seconds must not be negative, got {self.initial_delay_seconds}"
            )
        if self.delay_multiplier < 1:
            raise ValueError(f"delay_multiplier must be at least 1, got {self.delay_multiplier}")

    def delay_after(self, attempt: int) -> float:
        """The delay before the attempt that follows ``attempt`` (counted from 1)."""
        return self.initial_delay_seconds * self.delay_multiplier ** (attempt - FIRST_ATTEMPT)


@dataclass(frozen=True)
class ShutdownSummary:
    succeeded: int
    failed: int
    timed_out: int
    cancelled: int


@dataclass
class _Job:
    """A submitted job; its mutable state is owned by the queue."""

    job_id: int
    name: str
    coro_fn: Callable[..., Awaitable[object]]
    args: tuple[object, ...]
    status: JobStatus
    attempts: int
    result: object
    error: BaseException | None


@dataclass(frozen=True)
class _Attempt:
    task: asyncio.Future[object]
    timed_out: bool


_STOP = None  # put on the pending queue once per worker to end it


class JobQueue:
    """Runs submitted async jobs on ``workers`` worker tasks.

    Workers start on the first ``submit``, which must therefore be called while
    an event loop is running.
    """

    def __init__(
        self,
        *,
        workers: int,
        timeout_seconds: float,
        max_attempts: int,
        initial_delay_seconds: float,
        delay_multiplier: float,
    ) -> None:
        if sys.flags.optimize:
            raise RuntimeError("jobqueue checks its invariants with asserts; do not run with python -O")
        self._settings = QueueSettings(
            workers=workers,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
            initial_delay_seconds=initial_delay_seconds,
            delay_multiplier=delay_multiplier,
        )
        self._jobs: dict[int, _Job] = {}
        self._ids = itertools.count(FIRST_JOB_ID)
        self._pending: asyncio.Queue[int | None] = asyncio.Queue()
        self._workers: list[asyncio.Task[None]] = []
        self._unfinished = 0
        self._idle = asyncio.Event()
        self._idle.set()
        self._accepting = True

    @property
    def settings(self) -> QueueSettings:
        return self._settings

    def submit(self, name: str, coro_fn: Callable[..., Awaitable[object]], *args: object) -> int:
        """Queue ``coro_fn(*args)`` as a job and return its id."""
        if not self._accepting:
            raise QueueClosedError(f"cannot submit {name!r}: the queue is shutting down")
        self._start_workers()
        job_id = next(self._ids)
        self._jobs[job_id] = _Job(
            job_id=job_id,
            name=name,
            coro_fn=coro_fn,
            args=args,
            status=JobStatus.PENDING,
            attempts=0,
            result=None,
            error=None,
        )
        self._unfinished += 1
        self._idle.clear()
        self._pending.put_nowait(job_id)
        return job_id

    def status(self, job_id: int) -> JobStatus:
        return self._job(job_id).status

    def attempts(self, job_id: int) -> int:
        return self._job(job_id).attempts

    def result(self, job_id: int) -> object:
        """Return the job's result, or raise the job's error."""
        job = self._job(job_id)
        if job.status is JobStatus.SUCCEEDED:
            return job.result
        if job.status is JobStatus.FAILED:
            assert job.error is not None, "a failed job always records its error"
            raise job.error
        if job.status is JobStatus.TIMED_OUT:
            raise JobTimedOutError(
                f"job {job_id} ({job.name}) exceeded {self._settings.timeout_seconds}s"
            )
        if job.status is JobStatus.CANCELLED:
            raise JobCancelledError(f"job {job_id} ({job.name}) was cancelled")
        raise JobNotFinishedError(f"job {job_id} ({job.name}) is {job.status.value}")

    async def join(self) -> None:
        """Wait until every submitted job has finished; raise if a worker crashed."""
        self._raise_if_worker_crashed()
        await self._wait_idle_or_crash()
        self._raise_if_worker_crashed()

    async def shutdown(self) -> ShutdownSummary:
        """Stop accepting jobs, cancel waiting ones, let running ones finish.

        Raises ``WorkerCrashedError`` after cleanup when a worker crashed.
        """
        self._accepting = False
        self._cancel_pending()
        await self._wait_idle_or_crash()
        for _ in self._workers:
            self._pending.put_nowait(_STOP)
        if self._workers:
            await asyncio.wait(self._workers)
        self._raise_if_worker_crashed()
        return self._summary()

    def _job(self, job_id: int) -> _Job:
        if job_id not in self._jobs:
            raise UnknownJobError(f"no job with id {job_id}")
        return self._jobs[job_id]

    def _start_workers(self) -> None:
        if self._workers:
            return
        self._workers = [
            asyncio.create_task(self._worker(), name=f"jobqueue-worker-{index}")
            for index in range(self._settings.workers)
        ]

    async def _worker(self) -> None:
        while True:
            job_id = await self._pending.get()
            if job_id is _STOP:
                return
            await self._run_job(self._jobs[job_id])

    async def _run_job(self, job: _Job) -> None:
        job.status = JobStatus.RUNNING
        for attempt in range(FIRST_ATTEMPT, self._settings.max_attempts + 1):
            job.attempts = attempt
            outcome = await self._attempt(job)
            if outcome.timed_out:
                self._finish(job, JobStatus.TIMED_OUT)
                return
            if outcome.task.cancelled():
                self._finish(job, JobStatus.CANCELLED)
                return
            error = outcome.task.exception()
            if error is None:
                job.result = outcome.task.result()
                self._finish(job, JobStatus.SUCCEEDED)
                return
            job.error = error
            if not isinstance(error, RetryableError) or attempt == self._settings.max_attempts:
                self._finish(job, JobStatus.FAILED)
                return
            await asyncio.sleep(self._settings.delay_after(attempt))
        raise AssertionError(f"job {job.job_id} left the attempt loop without an outcome")

    async def _attempt(self, job: _Job) -> _Attempt:
        """Run one attempt of ``job`` to completion or until it exceeds the timeout."""
        task = asyncio.ensure_future(job.coro_fn(*job.args))
        done, _ = await asyncio.wait({task}, timeout=self._settings.timeout_seconds)
        if task in done:
            return _Attempt(task=task, timed_out=False)
        task.cancel()
        await asyncio.wait({task})
        return _Attempt(task=task, timed_out=True)

    def _finish(self, job: _Job, status: JobStatus) -> None:
        job.status = status
        self._unfinished -= 1
        assert self._unfinished >= 0, "more jobs finished than were submitted"
        if self._unfinished == 0:
            self._idle.set()

    def _cancel_pending(self) -> None:
        while not self._pending.empty():
            job_id = self._pending.get_nowait()
            assert job_id is not _STOP, "stop markers are only queued after pending jobs are drained"
            self._finish(self._jobs[job_id], JobStatus.CANCELLED)

    async def _wait_idle_or_crash(self) -> None:
        idle = asyncio.ensure_future(self._idle.wait())
        await asyncio.wait({idle, *self._workers}, return_when=asyncio.FIRST_COMPLETED)
        idle.cancel()
        await asyncio.wait({idle})

    def _raise_if_worker_crashed(self) -> None:
        for worker in self._workers:
            if worker.done() and not worker.cancelled() and worker.exception() is not None:
                raise WorkerCrashedError(
                    f"{worker.get_name()} stopped on an internal error"
                ) from worker.exception()

    def _summary(self) -> ShutdownSummary:
        statuses = [job.status for job in self._jobs.values()]
        return ShutdownSummary(
            succeeded=statuses.count(JobStatus.SUCCEEDED),
            failed=statuses.count(JobStatus.FAILED),
            timed_out=statuses.count(JobStatus.TIMED_OUT),
            cancelled=statuses.count(JobStatus.CANCELLED),
        )
