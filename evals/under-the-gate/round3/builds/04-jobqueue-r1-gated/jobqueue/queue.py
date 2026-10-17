"""An in-process asyncio job queue with a fixed number of workers.

The queue never catches exceptions: each attempt of a job runs in its own task,
and its outcome (result, exception, cancellation, timeout) is read from that task
after `asyncio.wait`. An error in the queue's own code therefore ends the worker
task with that error, and `join()` and `shutdown()` report it.
"""

import asyncio
import enum
import itertools
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace

FIRST_ATTEMPT = 1


class RetryableError(Exception):
    """Raised by a job to ask for another attempt after a delay."""


class JobQueueError(Exception):
    """Base class of the errors the queue itself raises."""


class QueueClosedError(JobQueueError):
    """A job was submitted after `shutdown()` was called."""


class QueueInternalError(JobQueueError):
    """A worker died from an unexpected error in the queue's own code."""


class JobNotFinishedError(JobQueueError):
    """The result of a job that has not finished was requested."""


class JobTimedOutError(JobQueueError):
    """The job exceeded its timeout and was cancelled."""


class JobCancelledError(JobQueueError):
    """The job was cancelled before it could finish."""


class JobState(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


FINISHED_STATES = frozenset(
    {JobState.SUCCEEDED, JobState.FAILED, JobState.TIMED_OUT, JobState.CANCELLED}
)


@dataclass(frozen=True)
class QueueSettings:
    """Every setting of a queue; all are required and validated."""

    workers: int
    timeout_seconds: float
    max_attempts: int
    base_delay_seconds: float
    delay_multiplier: float

    def __post_init__(self) -> None:
        if self.workers < 1:
            raise ValueError(f"workers must be at least 1, got {self.workers}")
        if self.timeout_seconds <= 0:
            raise ValueError(f"timeout_seconds must be positive, got {self.timeout_seconds}")
        if self.max_attempts < FIRST_ATTEMPT:
            raise ValueError(f"max_attempts must be at least 1, got {self.max_attempts}")
        if self.base_delay_seconds < 0:
            raise ValueError(
                f"base_delay_seconds must not be negative, got {self.base_delay_seconds}"
            )
        if self.delay_multiplier < 1:
            raise ValueError(
                f"delay_multiplier must be at least 1 so delays grow, got {self.delay_multiplier}"
            )

    def delay_before_retry(self, failed_attempt: int) -> float:
        """Delay after attempt number `failed_attempt` (counted from 1) failed retryably."""
        if failed_attempt < FIRST_ATTEMPT:
            raise ValueError(f"attempts are counted from 1, got {failed_attempt}")
        return self.base_delay_seconds * self.delay_multiplier ** (failed_attempt - FIRST_ATTEMPT)


@dataclass(frozen=True)
class Summary:
    succeeded: int
    failed: int
    timed_out: int
    cancelled: int


@dataclass(frozen=True)
class _Job:
    name: str
    coro_fn: Callable[..., Awaitable[object]]
    args: tuple[object, ...]
    state: JobState
    attempts: int
    result: object
    error: BaseException | None


@dataclass(frozen=True)
class _Stop:
    """Placed in the queue once per worker by `shutdown()`; the worker then exits."""


_STOP = _Stop()


class JobQueue:
    def __init__(
        self,
        *,
        workers: int,
        timeout_seconds: float,
        max_attempts: int,
        base_delay_seconds: float,
        delay_multiplier: float,
    ) -> None:
        self._settings = QueueSettings(
            workers=workers,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
            base_delay_seconds=base_delay_seconds,
            delay_multiplier=delay_multiplier,
        )
        self._jobs: dict[int, _Job] = {}
        self._ids = itertools.count()
        self._pending: asyncio.Queue[int | _Stop] = asyncio.Queue()
        self._workers: list[asyncio.Task[None]] = []
        self._accepting = True

    @property
    def settings(self) -> QueueSettings:
        return self._settings

    def submit(self, name: str, coro_fn: Callable[..., Awaitable[object]], *args: object) -> int:
        """Queue `coro_fn(*args)` and return its job id; needs a running event loop."""
        if not self._accepting:
            raise QueueClosedError(f"queue is shut down; job {name!r} was not accepted")
        self._start_workers()
        job_id = next(self._ids)
        self._jobs[job_id] = _Job(
            name=name,
            coro_fn=coro_fn,
            args=tuple(args),
            state=JobState.PENDING,
            attempts=0,
            result=None,
            error=None,
        )
        self._pending.put_nowait(job_id)
        return job_id

    def state(self, job_id: int) -> JobState:
        return self._jobs[job_id].state

    def attempts(self, job_id: int) -> int:
        return self._jobs[job_id].attempts

    def result(self, job_id: int) -> object:
        """Return the job's result, or raise its error; an unknown id raises KeyError."""
        job = self._jobs[job_id]
        if job.state is JobState.SUCCEEDED:
            return job.result
        if job.state is JobState.FAILED:
            if job.error is None:
                raise QueueInternalError(f"job {job_id} failed without recording its error")
            raise job.error
        if job.state is JobState.TIMED_OUT:
            raise JobTimedOutError(
                f"job {job_id} ({job.name!r}) exceeded {self._settings.timeout_seconds}s"
            )
        if job.state is JobState.CANCELLED:
            raise JobCancelledError(f"job {job_id} ({job.name!r}) was cancelled")
        raise JobNotFinishedError(f"job {job_id} ({job.name!r}) is {job.state.value}")

    async def join(self) -> None:
        """Wait until every submitted job has finished; raise if a worker died."""
        if not self._workers:
            return
        all_done = asyncio.create_task(self._pending.join())
        await asyncio.wait({all_done, *self._workers}, return_when=asyncio.FIRST_COMPLETED)
        if not all_done.done():
            all_done.cancel()
            await asyncio.wait({all_done})
        self._raise_for_dead_workers()

    async def shutdown(self) -> Summary:
        """Stop accepting jobs, cancel waiting ones, let running ones finish, summarize."""
        self._accepting = False
        while not self._pending.empty():
            item = self._pending.get_nowait()
            if isinstance(item, int):
                self._update(item, state=JobState.CANCELLED)
            self._pending.task_done()
        for _ in self._workers:
            self._pending.put_nowait(_STOP)
        if self._workers:
            await asyncio.wait(self._workers)
        self._raise_for_dead_workers()
        return self._summary()

    def _start_workers(self) -> None:
        if self._workers:
            return
        self._workers = [
            asyncio.create_task(self._work(), name=f"jobqueue-worker-{index}")
            for index in range(self._settings.workers)
        ]

    def _raise_for_dead_workers(self) -> None:
        errors = [
            worker.exception()
            for worker in self._workers
            if worker.done() and not worker.cancelled() and worker.exception() is not None
        ]
        if errors:
            raise QueueInternalError(f"{len(errors)} worker(s) died") from errors[0]
        cancelled = [worker for worker in self._workers if worker.cancelled()]
        if cancelled:
            raise QueueInternalError(f"{len(cancelled)} worker(s) were cancelled")

    def _summary(self) -> Summary:
        states = [job.state for job in self._jobs.values()]
        summary = Summary(
            succeeded=states.count(JobState.SUCCEEDED),
            failed=states.count(JobState.FAILED),
            timed_out=states.count(JobState.TIMED_OUT),
            cancelled=states.count(JobState.CANCELLED),
        )
        counted = summary.succeeded + summary.failed + summary.timed_out + summary.cancelled
        if counted != len(states):
            raise QueueInternalError(f"{len(states) - counted} job(s) did not finish")
        return summary

    def _update(self, job_id: int, **changes: object) -> None:
        self._jobs[job_id] = replace(self._jobs[job_id], **changes)

    async def _work(self) -> None:
        while True:
            item = await self._pending.get()
            if isinstance(item, _Stop):
                self._pending.task_done()
                return
            await self._run(item)
            self._pending.task_done()

    async def _run(self, job_id: int) -> None:
        self._update(job_id, state=JobState.RUNNING)
        attempt = FIRST_ATTEMPT
        while True:
            self._update(job_id, attempts=attempt)
            retry = await self._attempt(job_id)
            if not retry:
                break
            await asyncio.sleep(self._settings.delay_before_retry(attempt))
            attempt += 1
        if self._jobs[job_id].state not in FINISHED_STATES:
            raise QueueInternalError(f"job {job_id} ended its run unfinished")

    async def _attempt(self, job_id: int) -> bool:
        """Run one attempt, record its outcome, and return whether to retry."""
        job = self._jobs[job_id]
        task = asyncio.create_task(job.coro_fn(*job.args), name=f"jobqueue-job-{job_id}")
        done, _ = await asyncio.wait({task}, timeout=self._settings.timeout_seconds)
        if not done:
            task.cancel()
            await asyncio.wait({task})
            self._update(job_id, state=JobState.TIMED_OUT)
            return False
        if task.cancelled():
            self._update(job_id, state=JobState.CANCELLED)
            return False
        error = task.exception()
        if error is None:
            self._update(job_id, state=JobState.SUCCEEDED, result=task.result())
            return False
        if isinstance(error, RetryableError) and job.attempts < self._settings.max_attempts:
            return True
        self._update(job_id, state=JobState.FAILED, error=error)
        return False
