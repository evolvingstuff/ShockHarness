import asyncio
import time
import unittest
from unittest import mock

from jobqueue import (
    JobCancelledError,
    JobNotFinishedError,
    JobQueue,
    JobState,
    JobTimedOutError,
    QueueClosedError,
    QueueInternalError,
    QueueSettings,
    RetryableError,
    Summary,
)


def make_queue(workers=2, timeout_seconds=1.0, max_attempts=3, base_delay_seconds=0.01, delay_multiplier=2.0):
    return JobQueue(
        workers=workers,
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
        base_delay_seconds=base_delay_seconds,
        delay_multiplier=delay_multiplier,
    )


async def add(a, b):
    return a + b


async def fail_with(error):
    raise error


async def wait_for(event):
    await event.wait()
    return "released"


class SettingsTest(unittest.TestCase):
    def test_rejects_invalid_settings(self):
        invalid = [
            {"workers": 0},
            {"timeout_seconds": 0},
            {"max_attempts": 0},
            {"base_delay_seconds": -1},
            {"delay_multiplier": 0.5},
        ]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                make_queue(**changes)

    def test_delays_grow(self):
        settings = QueueSettings(
            workers=1, timeout_seconds=1, max_attempts=4, base_delay_seconds=0.1, delay_multiplier=3
        )
        delays = [settings.delay_before_retry(attempt) for attempt in (1, 2, 3)]
        self.assertAlmostEqual(delays[0], 0.1)
        self.assertAlmostEqual(delays[1], 0.3)
        self.assertAlmostEqual(delays[2], 0.9)


class JobQueueTest(unittest.IsolatedAsyncioTestCase):
    async def test_results_after_join(self):
        queue = make_queue()
        ids = [queue.submit(f"add-{n}", add, n, n) for n in range(5)]
        await queue.join()
        self.assertEqual([queue.result(job_id) for job_id in ids], [0, 2, 4, 6, 8])
        self.assertEqual(len(set(ids)), 5)
        self.assertEqual(await queue.shutdown(), Summary(succeeded=5, failed=0, timed_out=0, cancelled=0))

    async def test_join_without_jobs(self):
        queue = make_queue()
        await queue.join()
        self.assertEqual(await queue.shutdown(), Summary(succeeded=0, failed=0, timed_out=0, cancelled=0))

    async def test_workers_limit_concurrency(self):
        queue = make_queue(workers=2)
        running = 0
        peak = 0

        async def tracked():
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.01)
            running -= 1

        for n in range(6):
            queue.submit(f"tracked-{n}", tracked)
        await queue.join()
        self.assertEqual(peak, 2)
        await queue.shutdown()

    async def test_unknown_job_id(self):
        queue = make_queue()
        with self.assertRaises(KeyError):
            queue.result(42)

    async def test_result_before_finish(self):
        queue = make_queue()
        release = asyncio.Event()
        job_id = queue.submit("blocked", wait_for, release)
        with self.assertRaises(JobNotFinishedError):
            queue.result(job_id)
        release.set()
        await queue.join()
        self.assertEqual(queue.result(job_id), "released")
        await queue.shutdown()

    async def test_timeout_cancels_job(self):
        queue = make_queue(timeout_seconds=0.05)
        observed = []

        async def slow():
            observed.append("started")
            try:
                await asyncio.Event().wait()
            finally:
                observed.append("cleaned up")

        job_id = queue.submit("slow", slow)
        await queue.join()
        self.assertEqual(queue.state(job_id), JobState.TIMED_OUT)
        self.assertEqual(observed, ["started", "cleaned up"])
        with self.assertRaises(JobTimedOutError):
            queue.result(job_id)
        self.assertEqual(await queue.shutdown(), Summary(succeeded=0, failed=0, timed_out=1, cancelled=0))

    async def test_non_retryable_error_fails_at_once(self):
        queue = make_queue(max_attempts=5)
        error = ValueError("bad input")
        job_id = queue.submit("bad", fail_with, error)
        await queue.join()
        self.assertEqual(queue.state(job_id), JobState.FAILED)
        self.assertEqual(queue.attempts(job_id), 1)
        with self.assertRaises(ValueError) as caught:
            queue.result(job_id)
        self.assertIs(caught.exception, error)
        self.assertEqual(await queue.shutdown(), Summary(succeeded=0, failed=1, timed_out=0, cancelled=0))

    async def test_retryable_error_is_retried_until_success(self):
        queue = make_queue(max_attempts=3, base_delay_seconds=0.02, delay_multiplier=2.0)
        starts = []

        async def flaky():
            starts.append(time.monotonic())
            if len(starts) < 3:
                raise RetryableError("try again")
            return "ok"

        job_id = queue.submit("flaky", flaky)
        await queue.join()
        self.assertEqual(queue.result(job_id), "ok")
        self.assertEqual(queue.attempts(job_id), 3)
        first_gap = starts[1] - starts[0]
        second_gap = starts[2] - starts[1]
        self.assertGreaterEqual(first_gap, 0.02)
        self.assertGreaterEqual(second_gap, 0.04)
        await queue.shutdown()

    async def test_retryable_error_exhausts_attempts(self):
        queue = make_queue(max_attempts=3, base_delay_seconds=0.0, delay_multiplier=1.0)
        job_id = queue.submit("always", fail_with, RetryableError("again"))
        await queue.join()
        self.assertEqual(queue.state(job_id), JobState.FAILED)
        self.assertEqual(queue.attempts(job_id), 3)
        with self.assertRaises(RetryableError):
            queue.result(job_id)
        await queue.shutdown()

    async def test_job_cancelling_itself_is_recorded_cancelled(self):
        queue = make_queue()

        async def cancels():
            raise asyncio.CancelledError()

        job_id = queue.submit("cancels", cancels)
        await queue.join()
        with self.assertRaises(JobCancelledError):
            queue.result(job_id)
        await queue.shutdown()

    async def test_shutdown_cancels_waiting_and_finishes_running(self):
        queue = make_queue(workers=1)
        started = asyncio.Event()
        release = asyncio.Event()

        async def running():
            started.set()
            await release.wait()
            return "done"

        running_id = queue.submit("running", running)
        waiting_ids = [queue.submit(f"waiting-{n}", add, n, n) for n in range(3)]
        await started.wait()
        shutdown = asyncio.create_task(queue.shutdown())
        await asyncio.sleep(0)
        with self.assertRaises(QueueClosedError):
            queue.submit("late", add, 1, 1)
        release.set()
        summary = await shutdown
        self.assertEqual(summary, Summary(succeeded=1, failed=0, timed_out=0, cancelled=3))
        self.assertEqual(queue.result(running_id), "done")
        for job_id in waiting_ids:
            with self.assertRaises(JobCancelledError):
                queue.result(job_id)

    async def test_shutdown_summary_counts_every_outcome(self):
        queue = make_queue(workers=3, timeout_seconds=0.05, max_attempts=1)
        queue.submit("ok", add, 1, 2)
        queue.submit("bad", fail_with, KeyError("missing"))
        queue.submit("slow", wait_for, asyncio.Event())
        await queue.join()
        self.assertEqual(await queue.shutdown(), Summary(succeeded=1, failed=1, timed_out=1, cancelled=0))

    async def test_internal_error_is_reported_by_join_and_shutdown(self):
        queue = make_queue(workers=1)
        boom = RuntimeError("queue bug")
        with mock.patch.object(queue, "_update", side_effect=boom):
            queue.submit("victim", add, 1, 1)
            with self.assertRaises(QueueInternalError) as joined:
                await queue.join()
        self.assertIs(joined.exception.__cause__, boom)
        with self.assertRaises(QueueInternalError) as shut:
            await queue.shutdown()
        self.assertIs(shut.exception.__cause__, boom)


if __name__ == "__main__":
    unittest.main()
