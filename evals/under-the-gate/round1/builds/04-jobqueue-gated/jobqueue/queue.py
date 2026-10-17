"""An in-process job queue that runs async jobs with a fixed number of workers."""

import asyncio
import itertools
from dataclasses import dataclass


class RetryableError(Exception):
    """Raised by a job to ask for another attempt."""


class QueueClosed(Exception):
    """submit() was called after shutdown()."""


class JobTimedOut(Exception):
    """The job exceeded its timeout."""


class JobCancelled(Exception):
    """The job was cancelled before it ran."""


class JobNotFinished(Exception):
    """result() was asked for a job that has not finished."""


@dataclass(frozen=True)
class Summary:
    succeeded: int
    failed: int
    timed_out: int
    cancelled: int


SUCCEEDED = "succeeded"
FAILED = "failed"
TIMED_OUT = "timed_out"
CANCELLED = "cancelled"


@dataclass
class _Job:
    name: str
    coro_fn: object
    args: tuple
    status: str | None
    value: object
    error: BaseException | None


class JobQueue:
    def __init__(
        self,
        workers: int,
        timeout: float,
        max_attempts: int,
        base_delay: float,
        backoff_factor: float,
    ) -> None:
        if workers < 1 or max_attempts < 1:
            raise ValueError("workers and max_attempts must be at least 1")
        self._workers_count = workers
        self._timeout = timeout
        self._max_attempts = max_attempts
        self._base_delay = base_delay
        self._backoff_factor = backoff_factor
        self._ids = itertools.count()
        self._jobs: dict[int, _Job] = {}
        self._pending: asyncio.Queue[int] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._closed = False

    def submit(self, name: str, coro_fn, *args) -> int:
        if self._closed:
            raise QueueClosed(name)
        if not self._workers:
            self._workers = [
                asyncio.create_task(self._worker()) for _ in range(self._workers_count)
            ]
        job_id = next(self._ids)
        self._jobs[job_id] = _Job(name, coro_fn, args, None, None, None)
        self._pending.put_nowait(job_id)
        return job_id

    async def join(self) -> None:
        """Wait for all submitted jobs; raise if a worker died."""
        self._raise_worker_failures()
        joiner = asyncio.create_task(self._pending.join())
        await asyncio.wait([joiner, *self._workers], return_when=asyncio.FIRST_COMPLETED)
        if not joiner.done():
            joiner.cancel()
            await asyncio.wait([joiner])
        self._raise_worker_failures()

    def result(self, job_id: int):
        job = self._jobs[job_id]
        if job.status is None:
            raise JobNotFinished(job.name)
        if job.status == SUCCEEDED:
            return job.value
        raise job.error

    async def shutdown(self) -> Summary:
        self._closed = True
        while not self._pending.empty():
            job_id = self._pending.get_nowait()
            job = self._jobs[job_id]
            job.status = CANCELLED
            job.error = JobCancelled(job.name)
            self._pending.task_done()
        await self.join()
        for worker in self._workers:
            worker.cancel()
        if self._workers:
            await asyncio.wait(self._workers)
        self._raise_worker_failures()
        return self._summary()

    def _summary(self) -> Summary:
        statuses = [job.status for job in self._jobs.values()]
        return Summary(
            succeeded=statuses.count(SUCCEEDED),
            failed=statuses.count(FAILED),
            timed_out=statuses.count(TIMED_OUT),
            cancelled=statuses.count(CANCELLED),
        )

    def _raise_worker_failures(self) -> None:
        failures = [
            worker.exception()
            for worker in self._workers
            if worker.done() and not worker.cancelled() and worker.exception()
        ]
        if failures:
            raise ExceptionGroup("job queue worker died", failures)

    async def _worker(self) -> None:
        while True:
            job_id = await self._pending.get()
            await self._run(self._jobs[job_id])
            self._pending.task_done()

    async def _run(self, job: _Job) -> None:
        for attempt in range(1, self._max_attempts + 1):
            task = asyncio.create_task(job.coro_fn(*job.args))
            _, still_running = await asyncio.wait([task], timeout=self._timeout)
            if still_running:
                task.cancel()
                await asyncio.wait([task])
                job.status = TIMED_OUT
                job.error = JobTimedOut(job.name)
                return
            if task.cancelled():
                job.status = CANCELLED
                job.error = JobCancelled(job.name)
                return
            error = task.exception()
            if error is None:
                job.status = SUCCEEDED
                job.value = task.result()
                return
            job.status = FAILED
            job.error = error
            if not isinstance(error, RetryableError):
                return
            if attempt < self._max_attempts:
                await asyncio.sleep(self._base_delay * self._backoff_factor ** (attempt - 1))
