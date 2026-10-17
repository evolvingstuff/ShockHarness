"""Core implementation of :class:`JobQueue`."""

from __future__ import annotations

import asyncio
import enum
import itertools
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


class RetryableError(Exception):
    """Raise (or subclass) this from a job to have the attempt retried."""


class JobTimeoutError(TimeoutError):
    """Raised by :meth:`JobQueue.result` for a job that exceeded its timeout."""


class JobCancelledError(Exception):
    """Raised by :meth:`JobQueue.result` for a job cancelled before it ran."""


class JobNotFinishedError(Exception):
    """Raised by :meth:`JobQueue.result` for a job that has not finished yet."""


class QueueClosedError(RuntimeError):
    """Raised by :meth:`JobQueue.submit` after :meth:`JobQueue.shutdown`."""


class InternalQueueError(RuntimeError):
    """An unexpected error happened inside the queue's own code.

    ``errors`` holds the original exceptions. When raised by
    :meth:`JobQueue.shutdown`, ``summary`` holds the summary that would
    otherwise have been returned (``None`` when raised by ``join``).
    """

    def __init__(self, errors: list[BaseException], summary: Summary | None = None):
        self.errors = list(errors)
        self.summary = summary
        detail = "; ".join(f"{type(e).__name__}: {e}" for e in self.errors)
        super().__init__(f"{len(self.errors)} internal queue error(s): {detail}")
        if self.errors:
            self.__cause__ = self.errors[0]


class JobState(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"

    @property
    def finished(self) -> bool:
        return self not in (JobState.PENDING, JobState.RUNNING)


@dataclass(frozen=True)
class Summary:
    succeeded: int = 0
    failed: int = 0
    timed_out: int = 0
    cancelled: int = 0


@dataclass(eq=False)
class _Job:
    id: int
    name: str
    fn: Callable[..., Awaitable[Any]]
    args: tuple
    state: JobState = JobState.PENDING
    attempts: int = 0
    value: Any = None
    error: BaseException | None = field(default=None, repr=False)


class JobQueue:
    """Run submitted async jobs on a fixed number of workers.

    Settings:
      workers       number of concurrent workers (>= 1)
      timeout       seconds allowed per attempt; ``None`` disables it
      max_attempts  total attempts for a job raising ``RetryableError`` (>= 1)
      base_delay    delay before the first retry, in seconds
      backoff       multiplier applied to the delay after each retry (>= 1)
      max_delay     upper bound for the retry delay; ``None`` means no bound

    The delay before retry *n* (1-based) is
    ``min(base_delay * backoff ** (n - 1), max_delay)``.

    ``submit`` must be called while an event loop is running; the workers
    are started on the first submission.
    """

    def __init__(
        self,
        workers: int = 4,
        *,
        timeout: float | None = 30.0,
        max_attempts: int = 3,
        base_delay: float = 0.1,
        backoff: float = 2.0,
        max_delay: float | None = None,
    ) -> None:
        if not isinstance(workers, int) or workers < 1:
            raise ValueError("workers must be an integer >= 1")
        if timeout is not None and timeout <= 0:
            raise ValueError("timeout must be > 0 or None")
        if not isinstance(max_attempts, int) or max_attempts < 1:
            raise ValueError("max_attempts must be an integer >= 1")
        if base_delay < 0:
            raise ValueError("base_delay must be >= 0")
        if backoff < 1:
            raise ValueError("backoff must be >= 1")
        if max_delay is not None and max_delay < 0:
            raise ValueError("max_delay must be >= 0 or None")

        self.workers = workers
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.backoff = backoff
        self.max_delay = max_delay

        self._ids = itertools.count(1)
        self._jobs: dict[int, _Job] = {}
        self._pending: asyncio.Queue[_Job] | None = None
        self._worker_tasks: set[asyncio.Task] = set()
        self._current: dict[asyncio.Task, _Job] = {}
        self._unfinished = 0
        self._idle: asyncio.Event | None = None
        self._error_event: asyncio.Event | None = None
        self._internal_errors: list[BaseException] = []
        self._closed = False
        self._stopping = False
        self._summary: Summary | None = None

    # ------------------------------------------------------------------ API

    def submit(self, name: str, coro_fn: Callable[..., Awaitable[Any]], *args: Any) -> int:
        """Queue ``coro_fn(*args)`` to run under ``name``; return the job id."""
        if self._closed:
            raise QueueClosedError("queue is shut down")
        if not callable(coro_fn):
            raise TypeError("coro_fn must be callable")
        self._ensure_started()
        job = _Job(id=next(self._ids), name=name, fn=coro_fn, args=args)
        self._jobs[job.id] = job
        self._unfinished += 1
        self._idle.clear()
        self._pending.put_nowait(job)
        return job.id

    async def join(self) -> None:
        """Wait until every submitted job has finished.

        Raises :class:`InternalQueueError` if the queue's own code failed.
        """
        if self._pending is not None:
            await self._wait_idle_or_error()
        self._raise_internal_errors()

    def result(self, job_id: int) -> Any:
        """Return the job's result, or raise its error.

        Raises ``KeyError`` for an unknown id, :class:`JobNotFinishedError`
        if the job has not finished, :class:`JobTimeoutError` if it timed
        out, :class:`JobCancelledError` if it was cancelled, and the job's
        own exception if it failed.
        """
        job = self._jobs[job_id]
        if job.state is JobState.SUCCEEDED:
            return job.value
        if job.state is JobState.TIMED_OUT:
            raise JobTimeoutError(f"job {job.id} ({job.name!r}) timed out")
        if job.state is JobState.CANCELLED:
            raise JobCancelledError(f"job {job.id} ({job.name!r}) was cancelled")
        if job.state is JobState.FAILED:
            raise job.error
        raise JobNotFinishedError(f"job {job.id} ({job.name!r}) is {job.state.value}")

    def status(self, job_id: int) -> JobState:
        return self._jobs[job_id].state

    def attempts(self, job_id: int) -> int:
        return self._jobs[job_id].attempts

    async def shutdown(self) -> Summary:
        """Stop accepting jobs, cancel waiting ones, let running ones finish.

        Returns a :class:`Summary`, or raises :class:`InternalQueueError`
        (carrying the summary) if the queue's own code failed.
        """
        if self._summary is None:
            self._closed = True
            if self._pending is not None:
                while True:
                    try:
                        job = self._pending.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    job.state = JobState.CANCELLED
                    self._finish(job)
                await self._idle.wait()
                self._stopping = True
                for task in list(self._worker_tasks):
                    task.cancel()
                await asyncio.gather(*self._worker_tasks, return_exceptions=True)
            self._summary = self._make_summary()
        if self._internal_errors:
            raise InternalQueueError(self._internal_errors, self._summary)
        return self._summary

    # ------------------------------------------------------------ internals

    def _ensure_started(self) -> None:
        if self._pending is not None:
            return
        asyncio.get_running_loop()  # raises RuntimeError outside a loop
        self._pending = asyncio.Queue()
        self._idle = asyncio.Event()
        self._idle.set()
        self._error_event = asyncio.Event()
        for _ in range(self.workers):
            self._spawn_worker()

    def _spawn_worker(self) -> None:
        task = asyncio.get_running_loop().create_task(self._worker())
        self._worker_tasks.add(task)
        task.add_done_callback(self._on_worker_done)

    def _on_worker_done(self, task: asyncio.Task) -> None:
        self._worker_tasks.discard(task)
        job = self._current.pop(task, None)
        if task.cancelled():
            exc: BaseException | None = None
        else:
            exc = task.exception()
            if exc is None:
                exc = RuntimeError("worker exited unexpectedly")
        if exc is not None:
            self._report_internal_error(exc)
        if job is not None and not job.state.finished:
            if exc is None:
                job.state = JobState.CANCELLED
            else:
                job.state = JobState.FAILED
                job.error = exc
            try:
                self._finish(job)
            except BaseException as finish_exc:  # pragma: no cover - last resort
                self._report_internal_error(finish_exc)
        if exc is not None and not self._stopping:
            # Keep the configured number of workers alive.
            self._spawn_worker()

    async def _worker(self) -> None:
        me = asyncio.current_task()
        while True:
            job = await self._pending.get()
            self._current[me] = job
            try:
                await self._run_job(job)
            except asyncio.CancelledError:
                if not job.state.finished:
                    job.state = JobState.CANCELLED
                raise
            except Exception as exc:
                self._report_internal_error(exc)
                if not job.state.finished:
                    job.state = JobState.FAILED
                    job.error = exc
            finally:
                if job.state.finished:
                    del self._current[me]
                    self._finish(job)

    async def _run_job(self, job: _Job) -> None:
        job.state = JobState.RUNNING
        while True:
            job.attempts += 1
            try:
                async with asyncio.timeout(self.timeout) as cm:
                    value = await job.fn(*job.args)
            except TimeoutError as exc:
                if cm.expired():
                    job.state = JobState.TIMED_OUT
                    job.error = JobTimeoutError(f"job {job.id} ({job.name!r}) timed out")
                else:
                    job.state = JobState.FAILED
                    job.error = exc
                return
            except RetryableError as exc:
                if job.attempts >= self.max_attempts:
                    job.state = JobState.FAILED
                    job.error = exc
                    return
                await asyncio.sleep(self._retry_delay(job.attempts))
            except asyncio.CancelledError as exc:
                if asyncio.current_task().cancelling():
                    raise  # the worker itself is being cancelled
                job.state = JobState.FAILED  # the job cancelled itself
                job.error = exc
                return
            except Exception as exc:
                job.state = JobState.FAILED
                job.error = exc
                return
            else:
                job.value = value
                job.state = JobState.SUCCEEDED
                return

    def _retry_delay(self, attempt: int) -> float:
        delay = self.base_delay * self.backoff ** (attempt - 1)
        if self.max_delay is not None:
            delay = min(delay, self.max_delay)
        return delay

    def _finish(self, job: _Job) -> None:
        self._unfinished -= 1
        if self._unfinished == 0:
            self._idle.set()

    def _report_internal_error(self, exc: BaseException) -> None:
        logger.error("internal jobqueue error", exc_info=exc)
        self._internal_errors.append(exc)
        if self._error_event is not None:
            self._error_event.set()

    def _raise_internal_errors(self) -> None:
        if self._internal_errors:
            raise InternalQueueError(self._internal_errors)

    async def _wait_idle_or_error(self) -> None:
        if self._idle.is_set() or self._error_event.is_set():
            return
        idle = asyncio.ensure_future(self._idle.wait())
        err = asyncio.ensure_future(self._error_event.wait())
        try:
            await asyncio.wait({idle, err}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            idle.cancel()
            err.cancel()

    def _make_summary(self) -> Summary:
        counts = {s: 0 for s in JobState}
        for job in self._jobs.values():
            counts[job.state] += 1
        return Summary(
            succeeded=counts[JobState.SUCCEEDED],
            failed=counts[JobState.FAILED],
            timed_out=counts[JobState.TIMED_OUT],
            cancelled=counts[JobState.CANCELLED],
        )
