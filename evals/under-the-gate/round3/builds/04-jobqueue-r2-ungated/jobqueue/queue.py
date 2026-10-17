from __future__ import annotations

import asyncio
import enum
import itertools
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


class RetryableError(Exception):
    """Raise from a job to have the queue retry it after a delay."""


class QueueClosed(RuntimeError):
    """Raised by submit() once the queue has been shut down."""


class JobNotFinished(RuntimeError):
    """Raised by result() for a job that has not finished yet."""


class JobTimedOut(TimeoutError):
    """Raised by result() for a job that exceeded its timeout."""


class JobCancelled(RuntimeError):
    """Raised by result() for a job cancelled before it ran."""


class QueueInternalError(RuntimeError):
    """An unexpected error inside the queue's own code (not a job's error)."""

    def __init__(self, errors: list[BaseException], summary: Summary | None = None):
        self.errors = list(errors)
        self.summary = summary
        detail = "; ".join(f"{type(e).__name__}: {e}" for e in self.errors)
        super().__init__(f"{len(self.errors)} internal queue error(s): {detail}")
        if self.errors:
            self.__cause__ = self.errors[0]


class Status(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"

    @property
    def finished(self) -> bool:
        return self not in (Status.PENDING, Status.RUNNING)


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
    status: Status = Status.PENDING
    attempts: int = 0
    result: Any = None
    error: BaseException | None = None
    done: bool = field(default=False, repr=False)


class JobQueue:
    """Runs submitted async jobs with a fixed number of workers.

    Settings:
      workers       number of jobs run concurrently
      timeout       seconds allowed per attempt (None for no limit)
      max_attempts  total attempts for a job raising RetryableError
      retry_delay   delay before the first retry
      backoff       multiplier applied to the delay after each retry
      max_delay     upper bound on the delay (None for no bound)
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
        if retry_delay < 0 or backoff < 1:
            raise ValueError("retry_delay must be >= 0 and backoff >= 1")
        if max_delay is not None and max_delay < 0:
            raise ValueError("max_delay must be >= 0 or None")
        self.workers = workers
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.retry_delay = retry_delay
        self.backoff = backoff
        self.max_delay = max_delay

        self._ids = itertools.count(1)
        self._jobs: dict[int, _Job] = {}
        self._pending: asyncio.Queue[_Job | None] | None = None
        self._tasks: list[asyncio.Task] = []
        self._unfinished = 0
        self._changed: asyncio.Event | None = None
        self._errors: list[BaseException] = []
        self._closed = False
        self._summary: Summary | None = None

    # -- public API --------------------------------------------------------

    def submit(self, name: str, coro_fn: Callable[..., Awaitable[Any]], *args: Any) -> int:
        """Queue coro_fn(*args) to run and return its job id."""
        if self._closed:
            raise QueueClosed("queue has been shut down")
        self._start()
        job = _Job(next(self._ids), name, coro_fn, args)
        self._jobs[job.id] = job
        self._unfinished += 1
        self._pending.put_nowait(job)
        return job.id

    async def join(self) -> None:
        """Wait until every submitted job has finished.

        Raises QueueInternalError if the queue's own code failed.
        """
        while True:
            if self._errors:
                raise QueueInternalError(self._errors)
            if self._unfinished == 0:
                return
            self._changed.clear()
            await self._changed.wait()

    def result(self, job_id: int) -> Any:
        """Return the job's result, or raise its error."""
        job = self._jobs[job_id]
        if job.status is Status.SUCCEEDED:
            return job.result
        if job.status is Status.TIMED_OUT:
            raise JobTimedOut(f"job {job.id} ({job.name}) timed out")
        if job.status is Status.CANCELLED:
            raise JobCancelled(f"job {job.id} ({job.name}) was cancelled")
        if job.status is Status.FAILED:
            raise job.error
        raise JobNotFinished(f"job {job.id} ({job.name}) is {job.status.value}")

    def status(self, job_id: int) -> Status:
        return self._jobs[job_id].status

    def attempts(self, job_id: int) -> int:
        return self._jobs[job_id].attempts

    async def shutdown(self) -> Summary:
        """Stop accepting jobs, cancel waiting jobs, let running jobs finish.

        Returns a Summary, or raises QueueInternalError (carrying the summary)
        if the queue's own code failed at any point.
        """
        if self._summary is None:
            self._closed = True
            if self._pending is not None:
                while not self._pending.empty():
                    job = self._pending.get_nowait()
                    if job is not None and not job.done:
                        job.status = Status.CANCELLED
                        self._finish(job)
                # Wait for running jobs, unless no worker is left to run them.
                while self._unfinished and any(not t.done() for t in self._tasks):
                    self._changed.clear()
                    await self._changed.wait()
                for _ in self._tasks:
                    self._pending.put_nowait(None)
                await asyncio.gather(*self._tasks, return_exceptions=True)
                # Anything still unfinished was lost by a dead worker.
                for job in self._jobs.values():
                    if not job.done:
                        self._fail_internally(job)
                        self._finish(job)
            counts = {s: 0 for s in Status}
            for job in self._jobs.values():
                counts[job.status] += 1
            self._summary = Summary(
                succeeded=counts[Status.SUCCEEDED],
                failed=counts[Status.FAILED],
                timed_out=counts[Status.TIMED_OUT],
                cancelled=counts[Status.CANCELLED],
            )
        if self._errors:
            raise QueueInternalError(self._errors, self._summary)
        return self._summary

    # -- internals ---------------------------------------------------------

    def _start(self) -> None:
        if self._pending is not None:
            return
        asyncio.get_running_loop()  # submit() must be called from a running loop
        self._pending = asyncio.Queue()
        self._changed = asyncio.Event()
        for i in range(self.workers):
            task = asyncio.create_task(self._worker(), name=f"jobqueue-worker-{i}")
            task.add_done_callback(self._worker_exited)
            self._tasks.append(task)

    def _delay(self, attempt: int) -> float:
        delay = self.retry_delay * self.backoff ** (attempt - 1)
        if self.max_delay is not None:
            delay = min(delay, self.max_delay)
        return delay

    async def _worker(self) -> None:
        while True:
            job = await self._pending.get()
            if job is None:
                return
            if job.done:
                continue
            try:
                await self._run(job)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._report(exc)
            finally:
                if not job.status.finished:
                    self._fail_internally(job)
                if not job.done:
                    self._finish(job)

    async def _run(self, job: _Job) -> None:
        job.status = Status.RUNNING
        while True:
            job.attempts += 1
            deadline = asyncio.timeout(self.timeout)
            try:
                async with deadline:
                    value = await job.coro_fn(*job.args)
            except TimeoutError as exc:
                if deadline.expired():
                    job.status = Status.TIMED_OUT
                    job.error = exc
                    return
                job.status, job.error = Status.FAILED, exc
                return
            except RetryableError as exc:
                if job.attempts >= self.max_attempts:
                    job.status, job.error = Status.FAILED, exc
                    return
                await asyncio.sleep(self._delay(job.attempts))
                continue
            except asyncio.CancelledError:
                task = asyncio.current_task()
                if task is not None and task.cancelling():
                    raise
                # The job cancelled itself; record it rather than kill the worker.
                job.status = Status.CANCELLED
                return
            except Exception as exc:
                job.status, job.error = Status.FAILED, exc
                return
            job.status, job.result = Status.SUCCEEDED, value
            return

    def _finish(self, job: _Job) -> None:
        job.done = True
        self._unfinished -= 1
        self._changed.set()

    def _fail_internally(self, job: _Job) -> None:
        job.status = Status.FAILED
        job.error = QueueInternalError(self._errors)

    def _report(self, exc: BaseException) -> None:
        self._errors.append(exc)
        if self._changed is not None:
            self._changed.set()

    def _worker_exited(self, task: asyncio.Task) -> None:
        if task.cancelled():
            if not self._closed:
                self._report(RuntimeError(f"{task.get_name()} was cancelled"))
            return
        exc = task.exception()
        if exc is not None:
            self._report(exc)
        elif not self._closed:
            self._report(RuntimeError(f"{task.get_name()} exited unexpectedly"))
        else:
            self._changed.set()
