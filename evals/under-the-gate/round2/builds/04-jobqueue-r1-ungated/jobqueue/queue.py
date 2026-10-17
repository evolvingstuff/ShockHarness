from __future__ import annotations

import asyncio
import enum
import itertools
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


class RetryableError(Exception):
    """Raise (or subclass) this from a job to have it retried."""


class JobQueueError(Exception):
    """Base class for errors raised by the queue itself."""


class JobTimedOut(JobQueueError):
    """Raised by ``result()`` for a job that exceeded its timeout."""


class JobCancelled(JobQueueError):
    """Raised by ``result()`` for a job cancelled before it ran."""


class JobNotFinished(JobQueueError):
    """Raised by ``result()`` for a job that has not finished yet."""


class QueueClosed(JobQueueError):
    """Raised by ``submit()`` after ``shutdown()`` has been called."""


class QueueInternalError(JobQueueError):
    """An unexpected error happened inside the queue's own code."""

    def __init__(self, errors: list[BaseException], summary: Summary | None = None):
        self.errors = list(errors)
        self.summary = summary
        super().__init__(
            f"{len(self.errors)} internal error(s) in job queue: "
            + "; ".join(repr(e) for e in self.errors)
        )


class JobState(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


_FINAL = {JobState.SUCCEEDED, JobState.FAILED, JobState.TIMED_OUT, JobState.CANCELLED}


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
    fn: Callable[..., Awaitable[Any]]
    args: tuple
    state: JobState = JobState.PENDING
    attempts: int = 0
    result: Any = None
    error: BaseException | None = None
    counted: bool = field(default=False, repr=False)


class JobQueue:
    def __init__(
        self,
        workers: int = 4,
        *,
        timeout: float = 10.0,
        max_attempts: int = 3,
        base_delay: float = 0.1,
        backoff: float = 2.0,
        max_delay: float = 5.0,
    ) -> None:
        if workers < 1:
            raise ValueError("workers must be >= 1")
        if timeout <= 0:
            raise ValueError("timeout must be > 0")
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if base_delay < 0 or max_delay < 0:
            raise ValueError("delays must be >= 0")
        if backoff < 1:
            raise ValueError("backoff must be >= 1")
        self.workers = workers
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.backoff = backoff
        self.max_delay = max_delay

        self._ids = itertools.count(1)
        self._jobs: dict[int, _Job] = {}
        self._pending: asyncio.Queue[_Job | None] | None = None
        self._worker_tasks: list[asyncio.Task] = []
        self._reported_workers: set[asyncio.Task] = set()
        self._unfinished = 0
        self._wakeup: asyncio.Event | None = None
        self._internal_errors: list[BaseException] = []
        self._closed = False

    # -- public API -------------------------------------------------------

    def submit(self, name: str, coro_fn: Callable[..., Awaitable[Any]], *args: Any) -> int:
        if self._closed:
            raise QueueClosed("queue is shut down")
        self._ensure_started()
        job = _Job(next(self._ids), name, coro_fn, args)
        self._jobs[job.id] = job
        self._unfinished += 1
        self._pending.put_nowait(job)
        return job.id

    async def join(self) -> None:
        """Wait until every submitted job has finished.

        Raises ``QueueInternalError`` if the queue's own code failed.
        """
        if self._wakeup is not None:
            while self._unfinished > 0 and not self._all_workers_dead():
                self._wakeup.clear()
                await self._wakeup.wait()
        self._raise_internal_errors()

    def result(self, job_id: int) -> Any:
        job = self._jobs[job_id]
        if job.state is JobState.SUCCEEDED:
            return job.result
        if job.state is JobState.FAILED:
            raise job.error
        if job.state is JobState.TIMED_OUT:
            raise JobTimedOut(f"job {job.id} ({job.name!r}) timed out after {self.timeout}s")
        if job.state is JobState.CANCELLED:
            raise JobCancelled(f"job {job.id} ({job.name!r}) was cancelled")
        raise JobNotFinished(f"job {job.id} ({job.name!r}) is {job.state.value}")

    def state(self, job_id: int) -> JobState:
        return self._jobs[job_id].state

    def attempts(self, job_id: int) -> int:
        return self._jobs[job_id].attempts

    async def shutdown(self) -> Summary:
        """Stop accepting jobs, cancel waiting jobs, let running jobs finish.

        Returns a ``Summary``; raises ``QueueInternalError`` (carrying the
        summary) if the queue's own code failed.
        """
        self._closed = True
        if self._pending is not None:
            while True:
                try:
                    job = self._pending.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if job is not None:
                    job.state = JobState.CANCELLED
                    self._job_done(job)
            for _ in self._worker_tasks:
                self._pending.put_nowait(None)
            await asyncio.gather(*self._worker_tasks, return_exceptions=True)
        summary = self._summary()
        self._raise_internal_errors(summary)
        return summary

    # -- internals --------------------------------------------------------

    def _ensure_started(self) -> None:
        if self._pending is not None:
            return
        asyncio.get_running_loop()  # fail early outside of a running loop
        self._pending = asyncio.Queue()
        self._wakeup = asyncio.Event()
        for i in range(self.workers):
            task = asyncio.create_task(self._worker(), name=f"jobqueue-worker-{i}")
            task.add_done_callback(self._on_worker_exit)
            self._worker_tasks.append(task)

    def _all_workers_dead(self) -> bool:
        return all(t.done() for t in self._worker_tasks)

    def _on_worker_exit(self, task: asyncio.Task) -> None:
        # Workers only exit normally on the shutdown sentinel.
        if task not in self._reported_workers:
            if task.cancelled():
                self._internal_errors.append(
                    asyncio.CancelledError(f"{task.get_name()} was cancelled"))
            elif task.exception() is not None:
                self._internal_errors.append(task.exception())
            elif not self._closed:
                self._internal_errors.append(
                    RuntimeError(f"{task.get_name()} exited unexpectedly"))
        self._wakeup.set()

    def _record_internal_error(self, job: _Job, exc: BaseException) -> None:
        self._internal_errors.append(exc)
        if job.state not in _FINAL:
            job.state = JobState.FAILED
            job.error = QueueInternalError([exc])

    async def _worker(self) -> None:
        while True:
            job = await self._pending.get()
            if job is None:
                return
            try:
                await self._run_job(job)
            except Exception as exc:
                # A bug in the queue itself: record it, fail the job, keep going.
                self._record_internal_error(job, exc)
            except BaseException as exc:
                # The worker is going down (cancelled, or worse): record it
                # before the job counts as done, so join() cannot miss it.
                self._record_internal_error(job, exc)
                self._reported_workers.add(asyncio.current_task())
                raise
            finally:
                self._job_done(job)

    async def _run_job(self, job: _Job) -> None:
        job.state = JobState.RUNNING
        while True:
            job.attempts += 1
            try:
                async with asyncio.timeout(self.timeout) as cm:
                    value = await job.fn(*job.args)
            except TimeoutError as exc:
                if cm.expired():
                    self._finish(job, JobState.TIMED_OUT)
                else:  # the job raised TimeoutError itself
                    self._finish(job, JobState.FAILED, error=exc)
                return
            except asyncio.CancelledError as exc:
                if asyncio.current_task().cancelling():
                    raise  # the worker itself is being cancelled
                self._finish(job, JobState.FAILED, error=exc)
                return
            except RetryableError as exc:
                if job.attempts >= self.max_attempts:
                    self._finish(job, JobState.FAILED, error=exc)
                    return
                await asyncio.sleep(self._delay(job.attempts))
            except Exception as exc:
                self._finish(job, JobState.FAILED, error=exc)
                return
            else:
                self._finish(job, JobState.SUCCEEDED, result=value)
                return

    def _delay(self, attempt: int) -> float:
        return min(self.base_delay * self.backoff ** (attempt - 1), self.max_delay)

    def _finish(self, job: _Job, state: JobState, *, result: Any = None,
                error: BaseException | None = None) -> None:
        job.state = state
        job.result = result
        job.error = error

    def _job_done(self, job: _Job) -> None:
        if job.counted:
            return
        job.counted = True
        self._unfinished -= 1
        if self._unfinished == 0:
            self._wakeup.set()

    def _summary(self) -> Summary:
        counts = {s: 0 for s in JobState}
        for job in self._jobs.values():
            counts[job.state] += 1
        return Summary(
            succeeded=counts[JobState.SUCCEEDED],
            failed=counts[JobState.FAILED],
            timed_out=counts[JobState.TIMED_OUT],
            cancelled=counts[JobState.CANCELLED],
        )

    def _raise_internal_errors(self, summary: Summary | None = None) -> None:
        if self._internal_errors:
            raise QueueInternalError(self._internal_errors, summary)

