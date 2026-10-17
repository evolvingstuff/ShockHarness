"""Implementation of :class:`JobQueue`."""

from __future__ import annotations

import asyncio
import enum
import itertools
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


class RetryableError(Exception):
    """Raise (or subclass) this from a job to have it retried with backoff."""


class JobTimeoutError(TimeoutError):
    """Raised by :meth:`JobQueue.result` for a job that timed out."""


class JobCancelledError(Exception):
    """Raised by :meth:`JobQueue.result` for a job cancelled by shutdown."""


class JobNotFinishedError(RuntimeError):
    """Raised by :meth:`JobQueue.result` for a job that has not finished yet."""


class QueueClosedError(RuntimeError):
    """Raised by :meth:`JobQueue.submit` after shutdown has begun."""


class QueueInternalError(RuntimeError):
    """An unexpected error happened inside the queue's own code.

    ``errors`` holds the original exceptions. When raised by
    :meth:`JobQueue.shutdown`, ``summary`` holds the shutdown summary.
    """

    def __init__(self, errors: list[BaseException], summary: Summary | None = None):
        super().__init__(
            f"{len(errors)} internal error(s) in job queue: "
            + "; ".join(repr(e) for e in errors)
        )
        self.errors = list(errors)
        self.summary = summary


class JobStatus(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"

    @property
    def finished(self) -> bool:
        return self not in (JobStatus.PENDING, JobStatus.RUNNING)


@dataclass(frozen=True)
class Summary:
    succeeded: int = 0
    failed: int = 0
    timed_out: int = 0
    cancelled: int = 0


@dataclass
class _Job:
    id: int
    name: str
    coro_fn: Callable[..., Awaitable[Any]]
    args: tuple
    status: JobStatus = JobStatus.PENDING
    attempts: int = 0
    result: Any = None
    error: BaseException | None = field(default=None, repr=False)


class JobQueue:
    """Runs submitted async jobs on a fixed number of worker tasks.

    Settings:
      workers       number of concurrent worker tasks.
      timeout       seconds allowed per attempt of a job (None: no limit).
      max_attempts  total attempts for a job raising :class:`RetryableError`.
      retry_delay   delay before the first retry, in seconds.
      backoff       multiplier applied to the delay after each retry.
      max_delay     upper bound on the retry delay (None: unbounded).
    """

    def __init__(
        self,
        workers: int = 4,
        *,
        timeout: float | None = 30.0,
        max_attempts: int = 3,
        retry_delay: float = 0.1,
        backoff: float = 2.0,
        max_delay: float | None = None,
    ):
        if workers < 1:
            raise ValueError("workers must be at least 1")
        if timeout is not None and timeout <= 0:
            raise ValueError("timeout must be positive or None")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if retry_delay < 0:
            raise ValueError("retry_delay must be non-negative")
        if backoff < 1:
            raise ValueError("backoff must be at least 1")
        if max_delay is not None and max_delay < 0:
            raise ValueError("max_delay must be non-negative or None")

        self.workers = workers
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.retry_delay = retry_delay
        self.backoff = backoff
        self.max_delay = max_delay

        self._jobs: dict[int, _Job] = {}
        self._ids = itertools.count(1)
        self._pending: asyncio.Queue[_Job | None] = asyncio.Queue()
        self._worker_tasks: list[asyncio.Task] = []
        self._unfinished = 0
        self._idle = asyncio.Event()
        self._idle.set()
        self._crashed = asyncio.Event()
        self._internal_errors: list[BaseException] = []
        self._closed = False

    # ------------------------------------------------------------------ API

    def submit(self, name: str, coro_fn: Callable[..., Awaitable[Any]], *args: Any) -> int:
        """Queue ``coro_fn(*args)`` to run; returns the job id."""
        if self._closed:
            raise QueueClosedError("queue is shut down")
        self._start_workers()
        job = _Job(id=next(self._ids), name=name, coro_fn=coro_fn, args=args)
        self._jobs[job.id] = job
        self._unfinished += 1
        self._idle.clear()
        self._pending.put_nowait(job)
        return job.id

    async def join(self) -> None:
        """Wait until every submitted job has finished.

        Raises :class:`QueueInternalError` if the queue's own code failed.
        """
        if self._unfinished and not self._crashed.is_set():
            waiters = [
                asyncio.ensure_future(self._idle.wait()),
                asyncio.ensure_future(self._crashed.wait()),
            ]
            try:
                await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for w in waiters:
                    w.cancel()
        self._raise_internal_errors()

    def result(self, job_id: int) -> Any:
        """Return the job's result, or raise the job's error."""
        job = self._jobs[job_id]
        if job.status is JobStatus.SUCCEEDED:
            return job.result
        if job.status is JobStatus.FAILED:
            raise job.error
        if job.status is JobStatus.TIMED_OUT:
            raise JobTimeoutError(f"job {job.id} ({job.name!r}) timed out")
        if job.status is JobStatus.CANCELLED:
            raise JobCancelledError(f"job {job.id} ({job.name!r}) was cancelled")
        raise JobNotFinishedError(f"job {job.id} ({job.name!r}) is {job.status.value}")

    def status(self, job_id: int) -> JobStatus:
        return self._jobs[job_id].status

    def attempts(self, job_id: int) -> int:
        return self._jobs[job_id].attempts

    async def shutdown(self) -> Summary:
        """Stop accepting jobs, cancel waiting jobs, let running jobs finish.

        Returns a :class:`Summary`. Raises :class:`QueueInternalError` (carrying
        the summary) if the queue's own code failed at any point.
        """
        if not self._closed:
            self._closed = True
            while not self._pending.empty():
                job = self._pending.get_nowait()
                if job is not None:
                    job.status = JobStatus.CANCELLED
                    self._job_done()
            for _ in self._worker_tasks:
                self._pending.put_nowait(None)
        await asyncio.gather(*self._worker_tasks, return_exceptions=True)
        summary = self._summary()
        if self._internal_errors:
            raise QueueInternalError(self._internal_errors, summary)
        return summary

    # ------------------------------------------------------------ internals

    def _start_workers(self) -> None:
        if self._worker_tasks:
            return
        loop = asyncio.get_running_loop()
        for i in range(self.workers):
            task = loop.create_task(self._worker(), name=f"jobqueue-worker-{i}")
            task.add_done_callback(self._on_worker_exit)
            self._worker_tasks.append(task)

    async def _worker(self) -> None:
        while True:
            job = await self._pending.get()
            if job is None:
                return
            try:
                await self._run_job(job)
            except asyncio.CancelledError:
                if not job.status.finished:
                    job.status = JobStatus.CANCELLED
                raise
            except Exception as exc:
                # A bug in the queue itself: report it, fail the job so that
                # nobody waits on it forever, and keep the worker alive.
                self._report_internal_error(exc)
                if not job.status.finished:
                    job.status = JobStatus.FAILED
                    job.error = exc
            finally:
                self._job_done()

    async def _run_job(self, job: _Job) -> None:
        job.status = JobStatus.RUNNING
        while True:
            job.attempts += 1
            try:
                async with asyncio.timeout(self.timeout) as deadline:
                    result = await job.coro_fn(*job.args)
            except RetryableError as exc:
                if job.attempts >= self.max_attempts:
                    self._record(job, JobStatus.FAILED, error=exc)
                    return
                await asyncio.sleep(self._retry_delay(job.attempts))
            except TimeoutError as exc:
                if deadline.expired():
                    self._record(job, JobStatus.TIMED_OUT, error=exc)
                else:
                    self._record(job, JobStatus.FAILED, error=exc)
                return
            except asyncio.CancelledError as exc:
                if asyncio.current_task().cancelling():
                    raise  # the worker itself is being cancelled
                # The job raised CancelledError on its own: that is its failure.
                self._record(job, JobStatus.FAILED, error=exc)
                return
            except Exception as exc:
                self._record(job, JobStatus.FAILED, error=exc)
                return
            else:
                self._record(job, JobStatus.SUCCEEDED, result=result)
                return

    def _retry_delay(self, attempt: int) -> float:
        delay = self.retry_delay * self.backoff ** (attempt - 1)
        if self.max_delay is not None:
            delay = min(delay, self.max_delay)
        return delay

    def _record(
        self, job: _Job, status: JobStatus, *, result: Any = None,
        error: BaseException | None = None,
    ) -> None:
        job.result = result
        job.error = error
        job.status = status

    def _job_done(self) -> None:
        self._unfinished -= 1
        if self._unfinished == 0:
            self._idle.set()

    def _on_worker_exit(self, task: asyncio.Task) -> None:
        if task.cancelled():
            error: BaseException = RuntimeError(f"{task.get_name()} was cancelled")
        elif task.exception() is not None:
            error = task.exception()
        elif not self._closed:
            error = RuntimeError(f"{task.get_name()} exited unexpectedly")
        else:
            return
        self._report_internal_error(error)
        self._crashed.set()

    def _report_internal_error(self, exc: BaseException) -> None:
        self._internal_errors.append(exc)

    def _raise_internal_errors(self) -> None:
        if self._internal_errors:
            raise QueueInternalError(self._internal_errors)

    def _summary(self) -> Summary:
        counts = {s: 0 for s in JobStatus}
        for job in self._jobs.values():
            counts[job.status] += 1
        return Summary(
            succeeded=counts[JobStatus.SUCCEEDED],
            failed=counts[JobStatus.FAILED],
            timed_out=counts[JobStatus.TIMED_OUT],
            cancelled=counts[JobStatus.CANCELLED],
        )
