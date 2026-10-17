"""The job queue: workers, timeouts, retries with backoff, and shutdown.

No exception is caught anywhere in this module. A job runs in its own task and
its outcome is read with ``Task.exception()``; a failure in the queue's own code
ends the worker task, and ``join()`` and ``shutdown()`` raise it.
"""

import asyncio
import enum
import itertools
from collections.abc import Awaitable, Callable
from dataclasses import dataclass


class RetryableError(Exception):
    """Raised by a job to ask the queue to run it again after a delay."""


class QueueClosedError(RuntimeError):
    """The queue has been shut down and accepts no more jobs."""


class QueueInternalError(RuntimeError):
    """A worker stopped because of an error in the queue's own code."""


class JobNotFinishedError(RuntimeError):
    """The job has not finished yet, so it has no result."""


class JobTimedOutError(TimeoutError):
    """The job exceeded the queue's timeout and was cancelled."""


class JobCancelledError(RuntimeError):
    """The job was still waiting when the queue shut down."""


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
FIRST_JOB_ID = 1
FIRST_ATTEMPT = 1


@dataclass(frozen=True)
class ShutdownSummary:
    succeeded: int
    failed: int
    timed_out: int
    cancelled: int


@dataclass(frozen=True)
class JobSpec:
    job_id: int
    name: str
    coro_fn: Callable[..., Awaitable[object]]
    args: tuple[object, ...]


class JobRecord:
    """The mutable state of one job, written only by the queue."""

    def __init__(self, spec: JobSpec) -> None:
        self.spec = spec
        self.status = JobStatus.PENDING
        self.attempts = 0
        self.result: object = None
        self.error: BaseException | None = None


class JobQueue:
    def __init__(
        self,
        *,
        workers: int,
        timeout: float,
        max_attempts: int,
        retry_delay: float,
        retry_backoff: float,
    ) -> None:
        """Create a queue.

        ``timeout`` is in seconds per attempt. A retryable failure of attempt
        ``n`` waits ``retry_delay * retry_backoff ** (n - 1)`` seconds before
        attempt ``n + 1``; ``max_attempts`` counts the first attempt.
        """
        if workers < 1:
            raise ValueError(f"workers must be at least 1, got {workers}")
        if timeout <= 0:
            raise ValueError(f"timeout must be positive, got {timeout}")
        if max_attempts < 1:
            raise ValueError(f"max_attempts must be at least 1, got {max_attempts}")
        if retry_delay < 0:
            raise ValueError(f"retry_delay must not be negative, got {retry_delay}")
        if retry_backoff < 1:
            raise ValueError(f"retry_backoff must be at least 1, got {retry_backoff}")
        self._worker_count = workers
        self._timeout = timeout
        self._max_attempts = max_attempts
        self._retry_delay = retry_delay
        self._retry_backoff = retry_backoff
        self._ids = itertools.count(FIRST_JOB_ID)
        self._jobs: dict[int, JobRecord] = {}
        self._waiting: asyncio.Queue[JobRecord | None] | None = None
        self._workers: list[asyncio.Task[None]] = []
        self._wake: asyncio.Event | None = None
        self._unfinished = 0
        self._closed = False

    def submit(self, name: str, coro_fn: Callable[..., Awaitable[object]], *args: object) -> int:
        """Queue ``coro_fn(*args)`` and return its job id. Must be called inside a running loop."""
        if self._closed:
            raise QueueClosedError(f"queue is shut down; job {name!r} was not accepted")
        self._start_workers()
        assert self._waiting is not None, "workers are started with their queue"
        record = JobRecord(JobSpec(job_id=next(self._ids), name=name, coro_fn=coro_fn, args=args))
        self._jobs[record.spec.job_id] = record
        self._unfinished += 1
        self._waiting.put_nowait(record)
        return record.spec.job_id

    def status(self, job_id: int) -> JobStatus:
        return self._jobs[job_id].status

    def result(self, job_id: int) -> object:
        """Return the job's result, or raise its error; an unknown id raises KeyError."""
        record = self._jobs[job_id]
        if record.status is JobStatus.SUCCEEDED:
            return record.result
        if record.status is JobStatus.FAILED:
            assert record.error is not None, "a failed job keeps its error"
            raise record.error
        if record.status is JobStatus.TIMED_OUT:
            raise JobTimedOutError(f"job {job_id} ({record.spec.name}) timed out after {self._timeout}s")
        if record.status is JobStatus.CANCELLED:
            raise JobCancelledError(f"job {job_id} ({record.spec.name}) was cancelled")
        raise JobNotFinishedError(f"job {job_id} ({record.spec.name}) is {record.status.value}")

    async def join(self) -> None:
        """Wait until every submitted job has finished; raise QueueInternalError if a worker died."""
        while True:
            self._raise_worker_failure()
            if self._unfinished == 0:
                return
            assert self._wake is not None, "unfinished jobs imply started workers"
            self._wake.clear()
            self._raise_worker_failure()
            if self._unfinished == 0:
                return
            await self._wake.wait()

    async def shutdown(self) -> ShutdownSummary:
        """Stop accepting jobs, cancel waiting ones, let running ones finish, and summarize."""
        self._closed = True
        if self._waiting is not None:
            self._cancel_waiting(self._waiting)
            for _ in self._workers:
                self._waiting.put_nowait(None)
        if self._workers:
            await asyncio.wait(self._workers)
        self._raise_worker_failure()
        return self._summary()

    def _start_workers(self) -> None:
        if self._waiting is not None:
            return
        self._waiting = asyncio.Queue()
        self._wake = asyncio.Event()
        for index in range(self._worker_count):
            worker = asyncio.get_running_loop().create_task(
                self._work(self._waiting), name=f"jobqueue-worker-{index}"
            )
            worker.add_done_callback(self._on_worker_done)
            self._workers.append(worker)

    def _on_worker_done(self, worker: asyncio.Task[None]) -> None:
        assert self._wake is not None, "workers are started with their wake event"
        self._wake.set()

    def _raise_worker_failure(self) -> None:
        for worker in self._workers:
            if not worker.done() or worker.cancelled():
                continue
            error = worker.exception()
            if error is not None:
                raise QueueInternalError(f"{worker.get_name()} stopped: {error!r}") from error

    def _cancel_waiting(self, waiting: "asyncio.Queue[JobRecord | None]") -> None:
        while not waiting.empty():
            record = waiting.get_nowait()
            if record is not None:
                record.status = JobStatus.CANCELLED
                self._finish()

    async def _work(self, waiting: "asyncio.Queue[JobRecord | None]") -> None:
        while True:
            record = await waiting.get()
            if record is None:
                return
            await self._run(record)
            self._finish()

    def _finish(self) -> None:
        self._unfinished -= 1
        if self._unfinished < 0:
            raise AssertionError("more jobs finished than were submitted")
        assert self._wake is not None, "jobs finish only after workers started"
        self._wake.set()

    async def _run(self, record: JobRecord) -> None:
        record.status = JobStatus.RUNNING
        while True:
            record.attempts += 1
            attempt = asyncio.get_running_loop().create_task(
                self._call(record.spec), name=f"job-{record.spec.job_id}-attempt-{record.attempts}"
            )
            done, _ = await asyncio.wait({attempt}, timeout=self._timeout)
            if not done:
                attempt.cancel()
                await asyncio.wait({attempt})
                record.status = JobStatus.TIMED_OUT
                return
            if attempt.cancelled():
                record.status = JobStatus.CANCELLED
                return
            error = attempt.exception()
            if error is None:
                record.result = attempt.result()
                record.status = JobStatus.SUCCEEDED
                return
            if not isinstance(error, RetryableError) or record.attempts >= self._max_attempts:
                record.error = error
                record.status = JobStatus.FAILED
                return
            await asyncio.sleep(self._backoff(record.attempts))

    def _backoff(self, attempts: int) -> float:
        return self._retry_delay * self._retry_backoff ** (attempts - FIRST_ATTEMPT)

    @staticmethod
    async def _call(spec: JobSpec) -> object:
        return await spec.coro_fn(*spec.args)

    def _summary(self) -> ShutdownSummary:
        counts = {status: 0 for status in JobStatus}
        for record in self._jobs.values():
            counts[record.status] += 1
        unfinished = [s for s in JobStatus if s not in FINISHED_STATUSES and counts[s]]
        if unfinished:
            raise AssertionError(f"shutdown left jobs in {unfinished}")
        return ShutdownSummary(
            succeeded=counts[JobStatus.SUCCEEDED],
            failed=counts[JobStatus.FAILED],
            timed_out=counts[JobStatus.TIMED_OUT],
            cancelled=counts[JobStatus.CANCELLED],
        )
