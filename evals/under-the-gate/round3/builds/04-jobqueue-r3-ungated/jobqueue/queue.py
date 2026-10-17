"""Core implementation of :class:`JobQueue`."""

from __future__ import annotations

import asyncio
import enum
import itertools
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


class RetryableError(Exception):
    """Raise from a job to have it retried (up to the queue's max attempts)."""


class QueueClosed(RuntimeError):
    """Raised by ``submit()`` after ``shutdown()`` has been called."""


class JobNotFinished(RuntimeError):
    """Raised by ``result()`` for a job that is still pending or running."""


class JobTimedOut(TimeoutError):
    """Raised by ``result()`` for a job that exceeded its timeout."""


class JobCancelled(RuntimeError):
    """Raised by ``result()`` for a job cancelled before it could finish."""


class QueueInternalError(RuntimeError):
    """An unexpected error happened inside the queue's own code.

    ``errors`` holds the underlying exceptions; when raised by ``shutdown()``,
    ``summary`` holds the summary that would otherwise have been returned.
    """

    def __init__(self, errors: list[BaseException], summary: Summary | None = None):
        self.errors = list(errors)
        self.summary = summary
        detail = "; ".join(f"{type(e).__name__}: {e}" for e in self.errors)
        super().__init__(f"{len(self.errors)} internal error(s) in job queue: {detail}")
        if self.errors:
            self.__cause__ = self.errors[0]


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


@dataclass
class Job:
    id: int
    name: str
    coro_fn: Callable[..., Awaitable[Any]]
    args: tuple
    status: JobStatus = JobStatus.PENDING
    attempts: int = 0
    result: Any = None
    error: BaseException | None = None


@dataclass(frozen=True)
class Summary:
    succeeded: int = 0
    failed: int = 0
    timed_out: int = 0
    cancelled: int = 0


@dataclass
class _Settings:
    workers: int
    timeout: float | None
    max_attempts: int
    retry_delay: float
    backoff: float
    max_delay: float | None


class JobQueue:
    """Runs submitted async jobs with a fixed number of workers.

    Settings:
      workers      -- number of concurrent workers.
      timeout      -- seconds each attempt of a job may run (None: no limit).
      max_attempts -- total attempts for a job raising ``RetryableError``.
      retry_delay  -- delay before the first retry, in seconds.
      backoff      -- factor the delay grows by after each retry.
      max_delay    -- upper bound on the delay (None: unbounded).
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
            raise ValueError("workers must be >= 1")
        if timeout is not None and timeout <= 0:
            raise ValueError("timeout must be > 0 or None")
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if retry_delay < 0 or (max_delay is not None and max_delay < 0):
            raise ValueError("delays must be >= 0")
        if backoff < 1:
            raise ValueError("backoff must be >= 1")
        self._settings = _Settings(workers, timeout, max_attempts, retry_delay, backoff, max_delay)
        self._jobs: dict[int, Job] = {}
        self._ids = itertools.count(1)
        self._pending: asyncio.Queue[Job | None] | None = None
        self._workers: list[asyncio.Task] = []
        self._unfinished = 0
        self._idle: asyncio.Event | None = None
        self._fatal: asyncio.Event | None = None
        self._errors: list[BaseException] = []
        self._closed = False

    # ------------------------------------------------------------------ public

    def submit(self, name: str, coro_fn: Callable[..., Awaitable[Any]], *args: Any) -> int:
        """Queue ``coro_fn(*args)`` to run; returns the job id."""
        if self._closed:
            raise QueueClosed("queue is shut down")
        if not callable(coro_fn):
            raise TypeError("coro_fn must be callable")
        self._ensure_started()
        job = Job(next(self._ids), name, coro_fn, args)
        self._jobs[job.id] = job
        self._unfinished += 1
        self._idle.clear()
        self._pending.put_nowait(job)
        return job.id

    async def join(self) -> None:
        """Wait until every submitted job has finished.

        Raises ``QueueInternalError`` if the queue's own code failed.
        """
        if self._idle is not None:
            await self._wait_idle_or_fatal()
        self._raise_if_errors()

    def result(self, job_id: int) -> Any:
        """Return the job's result, or raise the job's error."""
        job = self.job(job_id)
        if job.status is JobStatus.SUCCEEDED:
            return job.result
        if job.status is JobStatus.FAILED:
            raise job.error
        if job.status is JobStatus.TIMED_OUT:
            raise JobTimedOut(f"job {job.id} ({job.name!r}) timed out")
        if job.status is JobStatus.CANCELLED:
            raise JobCancelled(f"job {job.id} ({job.name!r}) was cancelled")
        raise JobNotFinished(f"job {job.id} ({job.name!r}) is {job.status.value}")

    def job(self, job_id: int) -> Job:
        try:
            return self._jobs[job_id]
        except KeyError:
            raise KeyError(f"unknown job id {job_id!r}") from None

    def status(self, job_id: int) -> JobStatus:
        return self.job(job_id).status

    async def shutdown(self) -> Summary:
        """Stop accepting jobs, cancel waiting jobs, let running jobs finish.

        Returns a summary of job outcomes. Raises ``QueueInternalError`` (with
        the summary attached) if the queue's own code failed.
        """
        self._closed = True
        if self._pending is not None:
            while True:
                try:
                    job = self._pending.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if job is not None:
                    job.status = JobStatus.CANCELLED
                    self._finish(job)
            for _ in self._workers:
                self._pending.put_nowait(None)
            await asyncio.gather(*self._workers, return_exceptions=True)
        summary = self.summary()
        self._raise_if_errors(summary)
        return summary

    def summary(self) -> Summary:
        counts = {s: 0 for s in JobStatus}
        for job in self._jobs.values():
            counts[job.status] += 1
        return Summary(
            succeeded=counts[JobStatus.SUCCEEDED],
            failed=counts[JobStatus.FAILED],
            timed_out=counts[JobStatus.TIMED_OUT],
            cancelled=counts[JobStatus.CANCELLED],
        )

    @property
    def errors(self) -> list[BaseException]:
        """Internal errors recorded so far."""
        return list(self._errors)

    # ---------------------------------------------------------------- internal

    def _ensure_started(self) -> None:
        if self._pending is not None:
            return
        asyncio.get_running_loop()  # submit() needs a running event loop
        self._pending = asyncio.Queue()
        self._idle = asyncio.Event()
        self._idle.set()
        self._fatal = asyncio.Event()
        for i in range(self._settings.workers):
            task = asyncio.create_task(self._worker(), name=f"jobqueue-worker-{i}")
            task.add_done_callback(self._on_worker_done)
            self._workers.append(task)

    def _on_worker_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            if not self._closed:
                self._errors.append(RuntimeError(f"worker {task.get_name()} was cancelled"))
                self._fatal.set()
            return
        exc = task.exception()
        if exc is not None:
            self._errors.append(exc)
            self._fatal.set()
        elif not self._closed:
            self._errors.append(RuntimeError(f"worker {task.get_name()} exited unexpectedly"))
            self._fatal.set()

    async def _wait_idle_or_fatal(self) -> None:
        idle = asyncio.ensure_future(self._idle.wait())
        fatal = asyncio.ensure_future(self._fatal.wait())
        try:
            await asyncio.wait({idle, fatal}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            idle.cancel()
            fatal.cancel()

    def _raise_if_errors(self, summary: Summary | None = None) -> None:
        if self._errors:
            raise QueueInternalError(self._errors, summary)

    async def _next_job(self) -> Job | None:
        return await self._pending.get()

    async def _worker(self) -> None:
        while True:
            job = await self._next_job()
            if job is None:
                return
            try:
                await self._run_job(job)
            except asyncio.CancelledError:
                if not job.status.finished:
                    job.status = JobStatus.CANCELLED
                raise
            except Exception as exc:  # a bug in the queue itself, not in the job
                self._errors.append(exc)
                if not job.status.finished:
                    job.status = JobStatus.FAILED
                    job.error = exc
            finally:
                self._finish(job)

    def _finish(self, job: Job) -> None:
        self._unfinished -= 1
        if self._unfinished == 0:
            self._idle.set()

    async def _run_job(self, job: Job) -> None:
        s = self._settings
        job.status = JobStatus.RUNNING
        while True:
            job.attempts += 1
            outcome, value = await self._attempt(job)
            if outcome == "ok":
                job.status, job.result = JobStatus.SUCCEEDED, value
                return
            if outcome == "timeout":
                job.status = JobStatus.TIMED_OUT
                return
            if outcome == "cancelled":
                job.status = JobStatus.CANCELLED
                return
            if isinstance(value, RetryableError) and job.attempts < s.max_attempts:
                await asyncio.sleep(self.retry_delay(job.attempts))
                continue
            job.status, job.error = JobStatus.FAILED, value
            return

    def retry_delay(self, attempt: int) -> float:
        """Delay before retrying after failed attempt number ``attempt`` (1-based)."""
        s = self._settings
        delay = s.retry_delay * s.backoff ** (attempt - 1)
        return delay if s.max_delay is None else min(delay, s.max_delay)

    async def _attempt(self, job: Job) -> tuple[str, Any]:
        cm = asyncio.timeout(self._settings.timeout)
        try:
            async with cm:
                value = await job.coro_fn(*job.args)
        except TimeoutError as exc:
            if cm.expired():
                return "timeout", None
            return "error", exc
        except asyncio.CancelledError:
            if asyncio.current_task().cancelling():
                raise  # the worker itself is being cancelled
            return "cancelled", None  # the job cancelled itself
        except Exception as exc:
            return "error", exc
        return "ok", value
