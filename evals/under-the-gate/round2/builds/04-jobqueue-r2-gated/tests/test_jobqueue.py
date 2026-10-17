import asyncio
import time
import tomllib
import unittest
from collections.abc import Callable, Mapping
from pathlib import Path

from jobqueue import (
    JobCancelled,
    JobNotFinished,
    JobQueue,
    JobState,
    JobTimedOut,
    QueueClosed,
    QueueCrashed,
    RetryableError,
    ShutdownSummary,
    UnknownJob,
)

SETTINGS_FILE = Path(__file__).with_name("settings.toml")
SINGLE = 1
NEVER_ISSUED_JOB_ID = 0  # job ids start at 1


def load_settings() -> Mapping[str, Mapping[str, float]]:
    return tomllib.loads(SETTINGS_FILE.read_text(encoding="utf-8"))


async def add(a: int, b: int) -> int:
    await asyncio.sleep(0)
    return a + b


async def hang() -> None:
    await asyncio.Event().wait()


async def boom() -> None:
    raise ValueError("boom")


class Flaky:
    """Raises RetryableError until it has been called ``failures`` times."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls: list[float] = []

    async def __call__(self) -> str:
        self.calls.append(time.monotonic())
        if len(self.calls) <= self.failures:
            raise RetryableError(f"attempt {len(self.calls)}")
        return "ok"


class JobQueueTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        settings = load_settings()
        self.q = settings["queue"]
        self.s = settings["scenarios"]

    def make_queue(self, workers: int, max_attempts: int) -> JobQueue:
        return JobQueue(
            workers=workers,
            timeout=self.q["timeout"],
            max_attempts=max_attempts,
            retry_delay=self.q["retry_delay"],
            backoff_factor=self.q["backoff_factor"],
        )

    async def test_results_after_join(self) -> None:
        count = self.s["batch_jobs"]
        queue = self.make_queue(self.q["workers"], SINGLE)
        ids = [queue.submit(f"add{i}", add, i, i) for i in range(count)]
        await queue.join()
        self.assertEqual([queue.result(i) for i in ids], [i + i for i in range(count)])
        summary = await queue.shutdown()
        self.assertEqual(summary, ShutdownSummary(succeeded=count, failed=0, timed_out=0, cancelled=0))

    async def test_join_with_no_jobs_returns(self) -> None:
        queue = self.make_queue(SINGLE, SINGLE)
        await queue.join()
        await queue.shutdown()

    async def test_workers_bound_concurrency(self) -> None:
        running = 0
        peak = 0

        async def track() -> None:
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(self.s["work_seconds"])
            running -= 1

        workers = self.s["pool_workers"]
        queue = self.make_queue(workers, SINGLE)
        for i in range(self.s["pool_jobs"]):
            queue.submit(f"t{i}", track)
        await queue.join()
        self.assertEqual(peak, workers)
        await queue.shutdown()

    async def test_timeout_cancels_job(self) -> None:
        attempts: list[asyncio.Task[object]] = []

        async def slow() -> None:
            attempts.append(asyncio.current_task())
            await asyncio.Event().wait()

        queue = self.make_queue(SINGLE, self.q["max_attempts"])
        job = queue.submit("slow", slow)
        await queue.join()
        self.assertEqual(len(attempts), SINGLE)
        self.assertTrue(attempts[0].cancelled())
        with self.assertRaises(JobTimedOut):
            queue.result(job)
        summary = await queue.shutdown()
        self.assertEqual(summary, ShutdownSummary(succeeded=0, failed=0, timed_out=SINGLE, cancelled=0))

    async def test_non_retryable_error_fails_at_once(self) -> None:
        calls = 0

        async def bad() -> None:
            nonlocal calls
            calls += 1
            raise ValueError("bad input")

        queue = self.make_queue(SINGLE, self.q["max_attempts"])
        job = queue.submit("bad", bad)
        await queue.join()
        self.assertEqual(calls, SINGLE)
        with self.assertRaisesRegex(ValueError, "bad input"):
            queue.result(job)
        self.assertEqual((await queue.shutdown()).failed, SINGLE)

    async def test_retryable_error_retried_with_growing_delay(self) -> None:
        attempts = self.q["max_attempts"]
        flaky = Flaky(failures=attempts - 1)
        queue = self.make_queue(SINGLE, attempts)
        job = queue.submit("flaky", flaky)
        await queue.join()
        self.assertEqual(queue.result(job), "ok")
        self.assertEqual(len(flaky.calls), attempts)
        gaps = [later - earlier for earlier, later in zip(flaky.calls, flaky.calls[1:])]
        tolerance = self.s["timing_tolerance"]
        for index, gap in enumerate(gaps):
            expected = self.q["retry_delay"] * self.q["backoff_factor"] ** index
            self.assertGreaterEqual(gap, expected * tolerance)
        self.assertEqual(gaps, sorted(gaps))
        await queue.shutdown()

    async def test_retryable_error_stops_at_max_attempts(self) -> None:
        attempts = self.q["max_attempts"]
        flaky = Flaky(failures=self.s["endless_failures"])
        queue = self.make_queue(SINGLE, attempts)
        job = queue.submit("flaky", flaky)
        await queue.join()
        self.assertEqual(len(flaky.calls), attempts)
        with self.assertRaises(RetryableError):
            queue.result(job)
        self.assertEqual((await queue.shutdown()).failed, SINGLE)

    async def test_shutdown_cancels_waiting_and_finishes_running(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def gated() -> str:
            started.set()
            await release.wait()
            return "done"

        queue = self.make_queue(SINGLE, SINGLE)
        running = queue.submit("gated", gated)
        waiting = [queue.submit(f"w{i}", add, i, i) for i in range(self.s["waiting_jobs"])]
        await started.wait()
        shutdown = asyncio.create_task(queue.shutdown())
        await asyncio.sleep(0)
        with self.assertRaises(QueueClosed):
            queue.submit("late", add, SINGLE, SINGLE)
        self.assertFalse(shutdown.done())
        release.set()
        summary = await shutdown
        expected = ShutdownSummary(succeeded=SINGLE, failed=0, timed_out=0, cancelled=len(waiting))
        self.assertEqual(summary, expected)
        self.assertEqual(queue.result(running), "done")
        for job in waiting:
            with self.assertRaises(JobCancelled):
                queue.result(job)

    async def test_mixed_summary(self) -> None:
        queue = self.make_queue(self.q["workers"], self.q["max_attempts"])
        succeeding = [queue.submit("ok", add, SINGLE, SINGLE), queue.submit("flaky", Flaky(failures=SINGLE))]
        failing = [queue.submit("bad", boom)]
        timing_out = [queue.submit("hang", hang)]
        await queue.join()
        summary = await queue.shutdown()
        expected = ShutdownSummary(
            succeeded=len(succeeding), failed=len(failing), timed_out=len(timing_out), cancelled=0
        )
        self.assertEqual(summary, expected)

    async def test_result_of_unknown_and_unfinished_job(self) -> None:
        queue = self.make_queue(SINGLE, SINGLE)
        with self.assertRaises(UnknownJob):
            queue.result(NEVER_ISSUED_JOB_ID)
        job = queue.submit("hang", hang)
        with self.assertRaises(JobNotFinished):
            queue.result(job)
        await queue.join()
        await queue.shutdown()

    async def test_shutdown_twice_raises(self) -> None:
        queue = self.make_queue(SINGLE, SINGLE)
        await queue.shutdown()
        with self.assertRaises(QueueClosed):
            await queue.shutdown()

    async def test_internal_error_is_reported_by_join_and_shutdown(self) -> None:
        queue = self.make_queue(self.q["workers"], SINGLE)
        original_finish: Callable[[object, JobState], None] = queue._finish
        defect = RuntimeError("defect in queue code")

        def broken_finish(job: object, state: JobState) -> None:
            if job.name == "victim":
                raise defect
            original_finish(job, state)

        queue._finish = broken_finish
        queue.submit("victim", add, SINGLE, SINGLE)
        with self.assertRaises(QueueCrashed) as joined:
            await queue.join()
        self.assertIs(joined.exception.__cause__, defect)
        survivor = queue.submit("survivor", add, SINGLE, SINGLE)
        with self.assertRaises(QueueCrashed) as shut:
            await queue.shutdown()
        self.assertEqual(shut.exception.errors, (defect,))
        with self.assertRaises(JobCancelled):
            queue.result(survivor)

    async def test_invalid_settings_rejected(self) -> None:
        good = {
            "workers": SINGLE,
            "timeout": self.q["timeout"],
            "max_attempts": SINGLE,
            "retry_delay": self.q["retry_delay"],
            "backoff_factor": self.q["backoff_factor"],
        }
        invalid = {"workers": 0, "timeout": 0, "max_attempts": 0, "retry_delay": 0, "backoff_factor": SINGLE}
        for key, bad in invalid.items():
            with self.subTest(key=key), self.assertRaises(ValueError):
                JobQueue(**{**good, key: bad})


if __name__ == "__main__":
    unittest.main()
