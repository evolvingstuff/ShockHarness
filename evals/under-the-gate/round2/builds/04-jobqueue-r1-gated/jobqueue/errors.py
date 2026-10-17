"""Errors raised by the job queue and errors jobs raise to request a retry."""


class RetryableError(Exception):
    """Raised by a job to say the attempt failed but may succeed if retried."""


class JobTimeoutError(Exception):
    """The job exceeded the queue's timeout and was cancelled."""

    def __init__(self, job_id: int, timeout: float) -> None:
        super().__init__(f"job {job_id} exceeded its timeout of {timeout} seconds")
        self.job_id = job_id
        self.timeout = timeout


class JobCancelledError(Exception):
    """The job was cancelled before it produced a result."""

    def __init__(self, job_id: int, reason: str) -> None:
        super().__init__(f"job {job_id} was cancelled: {reason}")
        self.job_id = job_id
        self.reason = reason


class JobNotFinishedError(Exception):
    """A result was requested for a job that has not finished yet."""

    def __init__(self, job_id: int) -> None:
        super().__init__(f"job {job_id} has not finished")
        self.job_id = job_id


class QueueClosedError(Exception):
    """A job was submitted after shutdown() began."""


class QueueInternalError(Exception):
    """One or more workers stopped because of an error in the queue's own code."""

    def __init__(self, errors: tuple[BaseException, ...]) -> None:
        super().__init__(f"{len(errors)} worker(s) failed: {errors!r}")
        self.errors = errors
