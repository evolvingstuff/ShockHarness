"""Errors raised by the job queue and the marker for retryable job failures."""


class RetryableError(Exception):
    """Raised by a job to ask the queue to run it again after a delay."""


class JobQueueError(Exception):
    """Base class for errors the queue itself raises."""


class QueueClosedError(JobQueueError):
    """A job was submitted after shutdown() was called."""


class UnknownJobError(JobQueueError):
    """A job id that this queue never issued."""

    def __init__(self, job_id: int) -> None:
        super().__init__(f"no job with id {job_id}")
        self.job_id = job_id


class JobNotFinishedError(JobQueueError):
    """result() was asked for a job that is still waiting or running."""

    def __init__(self, job_id: int, status: str) -> None:
        super().__init__(f"job {job_id} has not finished (status: {status})")
        self.job_id = job_id
        self.status = status


class JobTimedOutError(JobQueueError):
    """The job exceeded the queue's timeout and was cancelled."""

    def __init__(self, job_id: int, timeout_seconds: float) -> None:
        super().__init__(f"job {job_id} exceeded its timeout of {timeout_seconds}s")
        self.job_id = job_id
        self.timeout_seconds = timeout_seconds


class JobCancelledError(JobQueueError):
    """The job was cancelled before it produced a result."""

    def __init__(self, job_id: int) -> None:
        super().__init__(f"job {job_id} was cancelled")
        self.job_id = job_id


class WorkerCrashedError(JobQueueError):
    """A worker stopped because of an error in the queue's own code."""
