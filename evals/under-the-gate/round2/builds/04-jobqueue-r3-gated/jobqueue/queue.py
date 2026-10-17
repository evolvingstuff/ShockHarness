"""The job queue: workers, timeouts, retries and shutdown.

Job outcomes are read from the finished asyncio.Task of each attempt
(``Task.cancelled()``, ``Task.exception()``), so the queue never needs to catch
the arbitrary exceptions that jobs raise.
"""

import asyncio
import enum
import itertools
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from jobqueue.errors import (
    JobCancelledError,
    JobNotFinishedError,
    JobTimedOutError,
    QueueClosedError,
    RetryableError,
    UnknownJobError,
    WorkerCrashedError,
)

FIRST_JOB_ID = 1
FIRST_ATTEMPT = 1
MIN_WORKERS = 1
MIN_ATTEMPTS = 1
MIN_BACKOFF_FACTOR = 1
NO_UNFINISHED_JOBS = 0


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
class QueueSettings:
    """Every setting of a queue; validated on construction.

    The delay before retry attempt n+1 is
    ``retry_delay_seconds * retry_backoff_factor ** (n - 1)``.
    """

    workers: int
    timeout_seconds: float
    max_attempts: int
    retry_delay_seconds: float
    retry_backoff_factor: float

    def __post_init__(self) -> None:
        if self.workers < MIN_WORKERS:
            raise ValueError(f"workers must be at least {MIN_WORKERS}, got {self.workers}")
        if self.timeout_seconds <= 0:
            raise ValueError(f"timeout_seconds must be positive, got {self.timeout_seconds}")
        if self.max_attempts < MIN_ATTEMPTS:
            raise ValueError(f"max_attempts must be at least {MIN_ATTEMPTS}, got {self.max_attempts}")
        if self.retry_delay_seconds < 0:
            raise ValueError(f"retry_delay_seconds must not be negative, got {self.retry_delay_seconds}")
        if self.retry_backoff_factor < MIN_BACKOFF_FACTOR:
            raise ValueError(
                f"retry_backoff_factor must be at least {MIN_BACKOFF_FACTOR} so delays grow, "
                f"got {self.retry_backoff_factor}"
            )

    def retry_delay(self, failed_attempt: int) -> float:
        """Seconds to wait after the given (1-based) attempt failed with a RetryableError."""
        return self.retry_delay_seconds * self.retry_backoff_factor ** (failed_attempt - FIRST_ATTEMPT)


@dataclass(frozen=True)
class ShutdownSummary:
    succeeded: int
    failed: int
    timed_out: int
    cancelled: int


class _Job:
    """Mutable record of one submitted job; owned and updated by the queue only."""

    def __init__(
        self, job_id: int, name: str, coro_fn: Callable[..., Awaitable[object]], args: tuple[object, ...]
    ) -> None:
        self.job_id = job_id
        self.name = name
        self.coro_fn = coro_fn
        self.args = args
        self.status = JobStatus.PENDING
        self.attempts = 0
        self.value: object = None
        self.error: BaseException | None = None

    async def invoke(self) -> object:
        # Calling coro_fn inside the task means a synchronous raise is a job failure too.
        return await self.coro_fn(*self.args)


class _Stop:
    """Sentinel put on the pending queue to tell one worker to exit."""


_STOP = _Stop()


class JobQueue:
    """Runs submitted async jobs on a fixed number of workers.

    Workers start on the first submit(), which must be called from a running
    event loop.
    """

    def __init__(
        self,
        *,
        workers: int,
        timeout_seconds: float,
        max_attempts: int,
        retry_delay_seconds: float,
        retry_backoff_factor: float,
    ) -> None:
        self._settings = QueueSettings(
            workers=workers,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
            retry_delay_seconds=retry_delay_seconds,
            retry_backoff_factor=retry_backoff_factor,
        )
        self._jobs: dict[int, _Job] = {}
        self._ids = itertools.count(FIRST_JOB_ID)
        self._pending: asyncio.Queue[_Job | _Stop] = asyncio.Queue()
        self._workers: tuple[asyncio.Task[None], ...] = ()
        self._unfinished = NO_UNFINISHED_JOBS
        self._idle = asyncio.Event()
        self._idle.set()
        self._closed = False

    @property
    def settings(self) -> QueueSettings:
        return self._settings

    def submit(self, name: str, coro_fn: Callable[..., Awaitable[object]], *args: object) -> int:
        """Queue coro_fn(*args) as a job and return its id. `name` labels the job's tasks."""
        if self._closed:
            raise QueueClosedError(f"cannot submit {name!r}: the queue is shut down")
        if not self._workers:
            self._workers = tuple(
                asyncio.create_task(self._work(), name=f"jobqueue-worker-{index}")
                for index in range(self._settings.workers)
            )
        job = _Job(next(self._ids), name, coro_fn, args)
        self._jobs[job.job_id] = job
        self._unfinished += 1
        self._idle.clear()
        self._pending.put_nowait(job)
        return job.job_id

    def status(self, job_id: int) -> JobStatus:
        return self._job(job_id).status

    def attempts(self, job_id: int) -> int:
        return self._job(job_id).attempts

    def result(self, job_id: int) -> object:
        """Return the job's result, or raise the job's error (or why it has none)."""
        job = self._job(job_id)
        if job.status is JobStatus.SUCCEEDED:
            return job.value
        if job.status is JobStatus.FAILED:
            if job.error is None:
                raise AssertionError(f"failed job {job_id} has no recorded error")
            raise job.error
        if job.status is JobStatus.TIMED_OUT:
            raise JobTimedOutError(job_id, self._settings.timeout_seconds)
        if job.status is JobStatus.CANCELLED:
            raise JobCancelledError(job_id)
        raise JobNotFinishedError(job_id, job.status.value)

    async def join(self) -> None:
        """Wait until every submitted job has finished; raise WorkerCrashedError if a worker died."""
        if not self._workers:
            return
        idle_waiter = asyncio.create_task(self._idle.wait())
        await asyncio.wait({idle_waiter, *self._workers}, return_when=asyncio.FIRST_COMPLETED)
        idle_waiter.cancel()
        await asyncio.wait({idle_waiter})
        self._raise_if_workers_crashed(stopping=False)

    async def shutdown(self) -> ShutdownSummary:
        """Stop accepting jobs, cancel waiting ones, let running ones finish, and summarize."""
        self._closed = True
        while not self._pending.empty():
            item = self._pending.get_nowait()
            if isinstance(item, _Job):
                self._finish(item, JobStatus.CANCELLED)
        for _ in self._workers:
            self._pending.put_nowait(_STOP)
        if self._workers:
            await asyncio.wait(self._workers)
        self._raise_if_workers_crashed(stopping=True)
        return self._summary()

    def _job(self, job_id: int) -> _Job:
        if job_id not in self._jobs:
            raise UnknownJobError(job_id)
        return self._jobs[job_id]

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

    def _raise_if_workers_crashed(self, *, stopping: bool) -> None:
        for worker in self._workers:
            if not worker.done():
                continue
            if worker.cancelled():
                raise WorkerCrashedError(f"{worker.get_name()} was cancelled")
            error = worker.exception()
            if error is not None:
                raise WorkerCrashedError(f"{worker.get_name()} crashed: {error!r}") from error
            if not stopping:
                raise WorkerCrashedError(f"{worker.get_name()} exited before shutdown")

    async def _work(self) -> None:
        while True:
            item = await self._pending.get()
            if isinstance(item, _Stop):
                return
            await self._run(item)

    async def _run(self, job: _Job) -> None:
        job.status = JobStatus.RUNNING
        while True:
            job.attempts += 1
            attempt = asyncio.create_task(job.invoke(), name=f"job-{job.job_id}-{job.name}")
            done, _ = await asyncio.wait({attempt}, timeout=self._settings.timeout_seconds)
            if not done:
                attempt.cancel()
                await asyncio.wait({attempt})
                self._finish(job, JobStatus.TIMED_OUT)
                return
            if attempt.cancelled():
                self._finish(job, JobStatus.CANCELLED)
                return
            error = attempt.exception()
            if error is None:
                job.value = attempt.result()
                self._finish(job, JobStatus.SUCCEEDED)
                return
            job.error = error
            if not isinstance(error, RetryableError) or job.attempts >= self._settings.max_attempts:
                self._finish(job, JobStatus.FAILED)
                return
            await asyncio.sleep(self._settings.retry_delay(job.attempts))

    def _finish(self, job: _Job, status: JobStatus) -> None:
        if status not in FINISHED_STATUSES:
            raise ValueError(f"{status} is not a finished status")
        if job.status in FINISHED_STATUSES:
            raise RuntimeError(f"job {job.job_id} finished twice ({job.status} then {status})")
        job.status = status
        self._unfinished -= 1
        if self._unfinished == NO_UNFINISHED_JOBS:
            self._idle.set()
