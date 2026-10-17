"""Validated settings of one job queue; nothing is configured globally."""

from dataclasses import dataclass

MIN_WORKERS = 1
MIN_ATTEMPTS = 1
MIN_BACKOFF_FACTOR = 1


@dataclass(frozen=True)
class QueueSettings:
    """Settings of a queue.

    workers: number of jobs run at the same time.
    timeout: seconds one attempt of a job may run before it is cancelled.
    max_attempts: attempts a job raising RetryableError gets in total.
    retry_delay: seconds waited after the first failed attempt.
    backoff_factor: each later delay is the previous one multiplied by this.
    """

    workers: int
    timeout: float
    max_attempts: int
    retry_delay: float
    backoff_factor: float

    def __post_init__(self) -> None:
        if self.workers < MIN_WORKERS:
            raise ValueError(f"workers must be at least {MIN_WORKERS}, got {self.workers}")
        if self.timeout <= 0:
            raise ValueError(f"timeout must be positive, got {self.timeout}")
        if self.max_attempts < MIN_ATTEMPTS:
            raise ValueError(f"max_attempts must be at least {MIN_ATTEMPTS}, got {self.max_attempts}")
        if self.retry_delay < 0:
            raise ValueError(f"retry_delay must not be negative, got {self.retry_delay}")
        if self.backoff_factor < MIN_BACKOFF_FACTOR:
            raise ValueError(
                f"backoff_factor must be at least {MIN_BACKOFF_FACTOR} so delays grow, got {self.backoff_factor}"
            )

    def delay_after(self, failed_attempt: int) -> float:
        """Seconds to wait after the given failed attempt (counted from 1) before the next."""
        if failed_attempt < MIN_ATTEMPTS:
            raise ValueError(f"attempts are counted from {MIN_ATTEMPTS}, got {failed_attempt}")
        return self.retry_delay * self.backoff_factor ** (failed_attempt - MIN_ATTEMPTS)
