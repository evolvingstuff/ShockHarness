from __future__ import annotations

import asyncio
import enum
import itertools
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


class RetryableError(Exception):
    """Raise from a job to have it retried (up to the queue's max attempts)."""


class QueueClosedError(RuntimeError):
    """Raised by submit() after shutdown() has been called."""


class JobTimeoutError(TimeoutError):
    """Raised by result() for a job that exceeded its timeout."""


class JobCancelledError(Exception):
    """Raised by result() for a job cancelled before it ran."""


class JobNotFinishedError(Exception):
    """Raised by result() for a job that has not finished yet."""


class QueueInternalError(RuntimeError):
    """Raised by join()/shutdown() when the queue's own code failed."""

    def __init__(self, errors: list[BaseException], summary: "Summary | None" = None):
        self.errors = list(errors)
        self.summary = summary
        super().__init__(
            f"{len(self.errors)} internal queue error(s): "
            + "; ".join(repr(e) for e in self.errors)
        )


class JobState(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


_TERMINAL = {JobState.SUCCEEDED, JobState.FAILED, JobState.TIMED_OUT, JobState.CANCELLED}


@dataclass
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
    state: JobState = JobState.PENDING
    attempts: int = 0
    result: Any = None
    error: BaseException | None = field(default=None, repr=False)


class JobQueue:
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
        if workers < 1:
            raise ValueError("workers must be >= 1")
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if timeout is not None and timeout <= 0:
            raise ValueError("timeout must be positive or None")
        if base_delay < 0 or backoff < 1:
            raise ValueError("base_delay must be >= 0 and backoff >= 1")
        self.workers = workers
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.backoff = backoff
        self.max_delay = max_delay

        self._jobs: dict[int, _Job] = {}
        self._ids = itertools.count(1)
        self._pending: asyncio.Queue[_Job] | None = None
        self._worker_tasks: list[asyncio.Task] = []
        self._live_workers = 0
        self._unfinished = 0
        self._errors: list[BaseException] = []
        self._changed: asyncio.Event | None = None
        self._closed = False
        self._stopping = False

    # -- public API -------------------------------------------------------

    def submit(self, name: str, coro_fn: Callable[..., Awaitable[Any]], *args: Any) -> int:
        if self._closed:
            raise QueueClosedError("queue is shut down")
        self._ensure_started()
        job = _Job(next(self._ids), name, coro_fn, args)
        self._jobs[job.id] = job
        self._unfinished += 1
        self._pending.put_nowait(job)
        return job.id

    async def join(self) -> None:
        """Wait until every submitted job has finished.

        Raises QueueInternalError if the queue's own code failed.
        """
        await self._wait_idle()
        if self._errors:
            raise QueueInternalError(self._errors)

    def result(self, job_id: int) -> Any:
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.state is JobState.SUCCEEDED:
            return job.result
        if job.state is JobState.FAILED:
            raise job.error
        if job.state is JobState.TIMED_OUT:
            raise JobTimeoutError(f"job {job_id} ({job.name}) timed out") from job.error
        if job.state is JobState.CANCELLED:
            raise JobCancelledError(f"job {job_id} ({job.name}) was cancelled")
        raise JobNotFinishedError(f"job {job_id} ({job.name}) is {job.state.value}")

    def state(self, job_id: int) -> JobState:
        return self._jobs[job_id].state

    def attempts(self, job_id: int) -> int:
        return self._jobs[job_id].attempts

    async def shutdown(self) -> Summary:
        """Stop accepting jobs, cancel waiting jobs, let running jobs finish.

        Returns a Summary; raises QueueInternalError (carrying the summary)
        if the queue's own code failed.
        """
        self._closed = True
        if self._pending is not None:
            while True:
                try:
                    job = self._pending.get_nowait()
                except asyncio.QueueEmpty:
                    break
                self._finish(job, JobState.CANCELLED)
            await self._wait_idle()
            self._stopping = True
            for task in self._worker_tasks:
                task.cancel()
            await asyncio.gather(*self._worker_tasks, return_exceptions=True)
            self._worker_tasks.clear()
        summary = self.summary()
        if self._errors:
            raise QueueInternalError(self._errors, summary)
        return summary

    def summary(self) -> Summary:
        s = Summary()
        for job in self._jobs.values():
            if job.state is JobState.SUCCEEDED:
                s.succeeded += 1
            elif job.state is JobState.FAILED:
                s.failed += 1
            elif job.state is JobState.TIMED_OUT:
                s.timed_out += 1
            elif job.state is JobState.CANCELLED:
                s.cancelled += 1
        return s

    # -- internals --------------------------------------------------------

    def _ensure_started(self) -> None:
        if self._pending is not None:
            return
        asyncio.get_running_loop()  # submit() must be called inside a loop
        self._pending = asyncio.Queue()
        self._changed = asyncio.Event()
        for i in range(self.workers):
            self._worker_tasks.append(
                asyncio.create_task(self._worker(), name=f"jobqueue-worker-{i}")
            )
        self._live_workers = self.workers

    async def _wait_idle(self) -> None:
        if self._changed is None:
            return
        # Jobs left over once every worker has died can never run; stop
        # waiting then (the deaths are in self._errors).
        while self._unfinished and self._live_workers:
            self._changed.clear()
            await self._changed.wait()

    def _notify(self) -> None:
        if self._changed is not None:
            self._changed.set()

    def _report(self, exc: BaseException) -> None:
        self._errors.append(exc)
        self._notify()

    def _finish(self, job: _Job, state: JobState) -> None:
        if job.state in _TERMINAL:
            return
        job.state = state
        self._unfinished -= 1
        self._notify()

    async def _worker(self) -> None:
        try:
            while True:
                job = await self._pending.get()
                try:
                    await self._process(job)
                except asyncio.CancelledError:
                    self._finish(job, JobState.CANCELLED)
                    raise
                except BaseException as exc:  # the queue's own code failed
                    if job.error is None:
                        job.error = exc
                    self._finish(job, JobState.FAILED)
                    self._report(exc)
        except asyncio.CancelledError:
            if not self._stopping:
                self._report(RuntimeError("worker was cancelled unexpectedly"))
            raise
        except BaseException as exc:
            self._report(exc)
            raise
        finally:
            self._live_workers -= 1
            self._notify()

    def _delay(self, attempt: int) -> float:
        delay = self.base_delay * self.backoff ** (attempt - 1)
        if self.max_delay is not None:
            delay = min(delay, self.max_delay)
        return delay

    async def _process(self, job: _Job) -> None:
        job.state = JobState.RUNNING
        while True:
            job.attempts += 1
            deadline = asyncio.timeout(self.timeout)
            try:
                async with deadline:
                    value = await job.coro_fn(*job.args)
            except TimeoutError as exc:
                job.error = exc
                self._finish(job, JobState.TIMED_OUT if deadline.expired() else JobState.FAILED)
                return
            except asyncio.CancelledError as exc:
                if asyncio.current_task().cancelling():
                    raise  # the worker itself is being cancelled
                job.error = exc  # the job cancelled itself
                self._finish(job, JobState.FAILED)
                return
            except RetryableError as exc:
                job.error = exc
                if job.attempts >= self.max_attempts:
                    self._finish(job, JobState.FAILED)
                    return
                await asyncio.sleep(self._delay(job.attempts))
                continue
            except Exception as exc:
                job.error = exc
                self._finish(job, JobState.FAILED)
                return
            job.result = value
            job.error = None
            self._finish(job, JobState.SUCCEEDED)
            return
