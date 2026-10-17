"""Waiting for a job to finish."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Job:
    name: str
    seconds: float


def wait_for(job: Job, timeout_seconds: float = 1.0) -> str:
    if job.seconds > timeout_seconds:
        return "timed out"
    return "done"
