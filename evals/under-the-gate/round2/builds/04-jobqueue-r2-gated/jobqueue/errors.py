"""Errors raised by the job queue and the marker for retryable job failures."""


class RetryableError(Exception):
    """Raised by a job to ask the queue to run it again after a delay."""


class QueueClosed(RuntimeError):
    """The queue has been shut down and accepts no more jobs."""


class UnknownJob(LookupError):
    """No job with this id was ever submitted to this queue."""


class JobNotFinished(RuntimeError):
    """The job is still waiting or running; it has no result yet."""


class JobTimedOut(TimeoutError):
    """The job exceeded the queue's timeout and was cancelled."""


class JobCancelled(RuntimeError):
    """The job was cancelled before it finished, e.g. by shutdown()."""


class QueueCrashed(RuntimeError):
    """A worker stopped because of an error in the queue's own code.

    The first error is the ``__cause__``; ``errors`` holds every one.
    """

    def __init__(self, errors: tuple[BaseException, ...]) -> None:
        super().__init__(f"{len(errors)} worker(s) crashed: {errors!r}")
        self.errors = errors
