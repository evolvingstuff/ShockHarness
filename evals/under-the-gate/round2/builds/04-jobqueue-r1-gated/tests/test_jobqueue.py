import asyncio
import json
import time
import unittest
from pathlib import Path

from jobqueue import (
    JobCancelledError,
    JobNotFinishedError,
    JobQueue,
    JobStatus,
    JobTimeoutError,
    QueueClosedError,
    QueueInternalError,
    QueueSettings,
    RetryableError,
)

TIMING_FILE = Path(__file__).with_name("timing.json")


def load_timing() -> dict[str, float]:
    return json.loads(TIMING_FILE.read_text(encoding="utf-8"))


async def echo(value: object) -> object:
    return value


async def raise_value_error(message: str) -> None:
    raise ValueError(message)


class FlakyJob:
    """Raises RetryableError until it has been called `failures` times, then returns `value`."""

    def __init__(self, failures: int, value: object) -> None:
        self.failures = failures
        self.value = value
        self.call_times: list[float] = []

    async def __call__(self) -> object:
        self.call_times.append(time.monotonic())
        if len(self.call_times) <= self.failures:
            raise RetryableError(f"call {len(self.call_times)} fails")
        return self.value


class JobQueueTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.timing = load_timing()

    def make_queue(self, workers: int) -> JobQueue:
        return JobQueue(
            workers=workers,
            timeout=self.timing["timeout"],
            max_attempts=int(self.timing["max_attempts"]),
            retry_delay=self.timing["retry_delay"],
            backoff_factor=self.timing["backoff_factor"],
        )

    async def test_results_are_returned_by_job_id(self) -> None:
        queue = self.make_queue(int(self.timing["workers"]))
        values = ["a", "b", "c"]
        ids = [queue.submit(f"echo-{value}", echo, value) for value in values]
        await queue.join()
        self.assertEqual(len(set(ids)), len(values))
        self.assertEqual([queue.result(job_id) for job_id in ids], values)
        summary = await queue.shutdown()
        self.assertEqual(summary.succeeded, len(values))
        self.assertEqual((summary.failed, summary.timed_out, summary.cancelled), (0, 0, 0))

    async def test_no_more_jobs_run_at_once_than_workers(self) -> None:
        workers = int(self.timing["workers"])
        queue = self.make_queue(workers)
        running = 0
        peak = 0

        async def tracked() -> None:
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(self.timing["short_job"])
            running -= 1

        for index in range(workers * workers + 1):
            queue.submit(f"tracked-{index}", tracked)
        await queue.join()
        await queue.shutdown()
        self.assertEqual(peak, workers)

    async def test_job_exceeding_timeout_is_cancelled_and_timed_out(self) -> None:
        queue = self.make_queue(int(self.timing["workers"]))
        cancelled = asyncio.Event()

        async def slow() -> None:
            try:
                await asyncio.sleep(self.timing["long_job"])
            finally:
                cancelled.set()

        job_id = queue.submit("slow", slow)
        await queue.join()
        self.assertEqual(queue.status(job_id), JobStatus.TIMED_OUT)
        self.assertTrue(cancelled.is_set())
        with self.assertRaises(JobTimeoutError):
            queue.result(job_id)
        summary = await queue.shutdown()
        self.assertEqual(summary.timed_out, 1)

    async def test_retryable_error_is_retried_with_growing_delay(self) -> None:
        max_attempts = int(self.timing["max_attempts"])
        queue = self.make_queue(int(self.timing["workers"]))
        flaky = FlakyJob(failures=max_attempts - 1, value="done")
        job_id = queue.submit("flaky", flaky)
        await queue.join()
        self.assertEqual(queue.result(job_id), "done")
        self.assertEqual(queue.attempts(job_id), max_attempts)
        gaps = [later - earlier for earlier, later in zip(flaky.call_times, flaky.call_times[1:])]
        self.assertGreaterEqual(gaps[0], self.timing["retry_delay"])
        self.assertGreater(gaps[-1], gaps[0])
        await queue.shutdown()

    async def test_retryable_error_fails_after_max_attempts(self) -> None:
        max_attempts = int(self.timing["max_attempts"])
        queue = self.make_queue(int(self.timing["workers"]))
        flaky = FlakyJob(failures=max_attempts, value="never")
        job_id = queue.submit("always-flaky", flaky)
        await queue.join()
        self.assertEqual(queue.status(job_id), JobStatus.FAILED)
        self.assertEqual(len(flaky.call_times), max_attempts)
        with self.assertRaises(RetryableError):
            queue.result(job_id)
        summary = await queue.shutdown()
        self.assertEqual(summary.failed, 1)

    async def test_other_error_fails_at_once(self) -> None:
        queue = self.make_queue(int(self.timing["workers"]))
        job_id = queue.submit("broken", raise_value_error, "bad input")
        await queue.join()
        self.assertEqual(queue.attempts(job_id), 1)
        with self.assertRaisesRegex(ValueError, "bad input"):
            queue.result(job_id)

    async def test_synchronous_error_from_job_function_fails_the_job(self) -> None:
        queue = self.make_queue(int(self.timing["workers"]))

        def not_async() -> None:
            raise TypeError("not a coroutine function")

        job_id = queue.submit("sync", not_async)
        await queue.join()
        with self.assertRaises(TypeError):
            queue.result(job_id)
        await queue.shutdown()

    async def test_result_of_unfinished_job_raises(self) -> None:
        queue = self.make_queue(int(self.timing["workers"]))
        job_id = queue.submit("echo", echo, "x")
        with self.assertRaises(JobNotFinishedError):
            queue.result(job_id)
        await queue.join()
        await queue.shutdown()

    async def test_shutdown_cancels_waiting_jobs_and_lets_running_finish(self) -> None:
        queue = self.make_queue(int(self.timing["single_worker"]))
        started = asyncio.Event()
        release = asyncio.Event()

        async def blocking() -> str:
            started.set()
            await release.wait()
            return "finished"

        running_id = queue.submit("blocking", blocking)
        waiting_ids = [queue.submit(f"waiting-{value}", echo, value) for value in "xyz"]
        await started.wait()
        shutdown = asyncio.create_task(queue.shutdown())
        await asyncio.sleep(0)
        with self.assertRaises(QueueClosedError):
            queue.submit("late", echo, "late")
        release.set()
        summary = await shutdown
        self.assertEqual(queue.result(running_id), "finished")
        for job_id in waiting_ids:
            self.assertEqual(queue.status(job_id), JobStatus.CANCELLED)
            with self.assertRaises(JobCancelledError):
                queue.result(job_id)
        self.assertEqual(summary.succeeded, 1)
        self.assertEqual(summary.cancelled, len(waiting_ids))

    async def test_shutdown_summary_counts_every_outcome(self) -> None:
        queue = self.make_queue(int(self.timing["workers"]))

        async def slow() -> None:
            await asyncio.sleep(self.timing["long_job"])

        queue.submit("ok", echo, "ok")
        queue.submit("bad", raise_value_error, "bad")
        queue.submit("slow", slow)
        await queue.join()
        summary = await queue.shutdown()
        self.assertEqual((summary.succeeded, summary.failed, summary.timed_out, summary.cancelled), (1, 1, 1, 0))

    async def test_internal_error_is_reported_by_join_and_shutdown(self) -> None:
        queue = self.make_queue(int(self.timing["single_worker"]))

        def broken_finish(*_: object) -> None:
            raise RuntimeError("bookkeeping bug")

        queue._finish = broken_finish
        queue.submit("echo", echo, "x")
        with self.assertRaises(QueueInternalError) as raised:
            await asyncio.wait_for(queue.join(), self.timing["long_job"])
        self.assertIsInstance(raised.exception.__cause__, RuntimeError)
        with self.assertRaises(QueueInternalError):
            await queue.shutdown()

    async def test_settings_are_validated(self) -> None:
        with self.assertRaises(ValueError):
            self.make_queue(0)
        with self.assertRaises(ValueError):
            QueueSettings(
                workers=1,
                timeout=0,
                max_attempts=1,
                retry_delay=self.timing["retry_delay"],
                backoff_factor=self.timing["backoff_factor"],
            )

    async def test_queues_do_not_share_settings(self) -> None:
        first = self.make_queue(int(self.timing["workers"]))
        second = self.make_queue(int(self.timing["single_worker"]))
        self.assertNotEqual(first.settings.workers, second.settings.workers)


if __name__ == "__main__":
    unittest.main()
