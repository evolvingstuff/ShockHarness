import asyncio
import time
import unittest

from jobqueue import (
    JobCancelledError,
    JobNotFinishedError,
    JobQueue,
    JobStatus,
    JobTimedOutError,
    QueueClosedError,
    QueueInternalError,
    RetryableError,
    ShutdownSummary,
)


def make_queue(workers=2, timeout=1.0, max_attempts=3, retry_delay=0.01, retry_backoff=2.0):
    return JobQueue(
        workers=workers,
        timeout=timeout,
        max_attempts=max_attempts,
        retry_delay=retry_delay,
        retry_backoff=retry_backoff,
    )


async def add(a, b):
    await asyncio.sleep(0)
    return a + b


async def boom():
    raise ValueError("bad input")


class Flaky:
    def __init__(self, failures):
        self.failures = failures
        self.calls = []

    async def __call__(self):
        self.calls.append(time.monotonic())
        if len(self.calls) <= self.failures:
            raise RetryableError(f"attempt {len(self.calls)}")
        return "ok"


class SettingsTest(unittest.TestCase):
    def test_rejects_invalid_settings(self):
        for kwargs in (
            {"workers": 0},
            {"timeout": 0},
            {"max_attempts": 0},
            {"retry_delay": -1},
            {"retry_backoff": 0.5},
        ):
            with self.subTest(**kwargs), self.assertRaises(ValueError):
                make_queue(**kwargs)


class JobQueueTest(unittest.IsolatedAsyncioTestCase):
    async def test_runs_jobs_and_returns_results(self):
        queue = make_queue()
        ids = [queue.submit(f"add-{i}", add, i, i) for i in range(5)]
        await queue.join()
        self.assertEqual([queue.result(i) for i in ids], [0, 2, 4, 6, 8])
        self.assertEqual(len(set(ids)), 5)
        await queue.shutdown()

    async def test_join_without_jobs_returns(self):
        queue = make_queue()
        await queue.join()
        self.assertEqual(await queue.shutdown(), ShutdownSummary(0, 0, 0, 0))

    async def test_respects_worker_count(self):
        queue = make_queue(workers=2)
        running = 0
        peak = 0

        async def job():
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.01)
            running -= 1

        for i in range(6):
            queue.submit(f"job-{i}", job)
        await queue.join()
        self.assertEqual(peak, 2)
        await queue.shutdown()

    async def test_non_retryable_error_fails_at_once(self):
        queue = make_queue()
        calls = 0

        async def job():
            nonlocal calls
            calls += 1
            raise ValueError("nope")

        job_id = queue.submit("bad", job)
        await queue.join()
        self.assertEqual(calls, 1)
        self.assertIs(queue.status(job_id), JobStatus.FAILED)
        with self.assertRaisesRegex(ValueError, "nope"):
            queue.result(job_id)
        await queue.shutdown()

    async def test_retryable_error_is_retried_with_growing_delay(self):
        queue = make_queue(max_attempts=4, retry_delay=0.02, retry_backoff=2.0)
        flaky = Flaky(failures=3)
        job_id = queue.submit("flaky", flaky)
        await queue.join()
        self.assertEqual(queue.result(job_id), "ok")
        self.assertEqual(len(flaky.calls), 4)
        gaps = [later - earlier for earlier, later in zip(flaky.calls, flaky.calls[1:])]
        for gap, expected in zip(gaps, (0.02, 0.04, 0.08)):
            self.assertGreaterEqual(gap, expected * 0.9)
        self.assertGreater(gaps[2], gaps[0])
        await queue.shutdown()

    async def test_retries_stop_at_max_attempts(self):
        queue = make_queue(max_attempts=2)
        flaky = Flaky(failures=10)
        job_id = queue.submit("flaky", flaky)
        await queue.join()
        self.assertEqual(len(flaky.calls), 2)
        with self.assertRaisesRegex(RetryableError, "attempt 2"):
            queue.result(job_id)
        await queue.shutdown()

    async def test_timeout_cancels_job(self):
        queue = make_queue(timeout=0.05)
        cancelled = asyncio.Event()

        async def slow():
            try:
                await asyncio.sleep(10)
            finally:
                cancelled.set()

        job_id = queue.submit("slow", slow)
        await queue.join()
        self.assertTrue(cancelled.is_set())
        self.assertIs(queue.status(job_id), JobStatus.TIMED_OUT)
        with self.assertRaises(JobTimedOutError):
            queue.result(job_id)
        await queue.shutdown()

    async def test_timed_out_job_is_not_retried(self):
        queue = make_queue(timeout=0.02, max_attempts=3)
        calls = 0

        async def slow():
            nonlocal calls
            calls += 1
            await asyncio.sleep(10)

        queue.submit("slow", slow)
        await queue.join()
        self.assertEqual(calls, 1)
        await queue.shutdown()

    async def test_result_of_unfinished_or_unknown_job(self):
        queue = make_queue()
        gate = asyncio.Event()

        async def wait():
            await gate.wait()

        job_id = queue.submit("wait", wait)
        with self.assertRaises(JobNotFinishedError):
            queue.result(job_id)
        with self.assertRaises(KeyError):
            queue.result(job_id + 100)
        gate.set()
        await queue.join()
        self.assertIsNone(queue.result(job_id))
        await queue.shutdown()

    async def test_shutdown_cancels_waiting_and_finishes_running(self):
        queue = make_queue(workers=1, timeout=0.05)
        started = asyncio.Event()
        release = asyncio.Event()

        async def running_job():
            started.set()
            await release.wait()
            return "done"

        running = queue.submit("running", running_job)
        await started.wait()
        failed = queue.submit("fails", boom)
        waiting = queue.submit("waiting", add, 1, 2)
        asyncio.get_running_loop().call_later(0.01, release.set)
        summary = await queue.shutdown()
        self.assertEqual(queue.result(running), "done")
        for job_id in (failed, waiting):
            with self.assertRaises(JobCancelledError):
                queue.result(job_id)
        self.assertEqual(summary, ShutdownSummary(succeeded=1, failed=0, timed_out=0, cancelled=2))
        with self.assertRaises(QueueClosedError):
            queue.submit("late", add, 1, 1)

    async def test_summary_counts_every_outcome(self):
        queue = make_queue(workers=3, timeout=0.05, max_attempts=1)

        async def slow():
            await asyncio.sleep(10)

        queue.submit("ok", add, 1, 1)
        queue.submit("bad", boom)
        queue.submit("slow", slow)
        await queue.join()
        summary = await queue.shutdown()
        self.assertEqual(summary, ShutdownSummary(succeeded=1, failed=1, timed_out=1, cancelled=0))

    async def test_internal_error_is_reported_by_join_and_shutdown(self):
        queue = make_queue(workers=1)

        async def broken_run(record):
            raise RuntimeError("queue bug")

        queue._run = broken_run
        queue.submit("victim", add, 1, 1)
        with self.assertRaises(QueueInternalError) as caught:
            await asyncio.wait_for(queue.join(), timeout=1)
        self.assertIsInstance(caught.exception.__cause__, RuntimeError)
        with self.assertRaises(QueueInternalError):
            await asyncio.wait_for(queue.shutdown(), timeout=1)

    async def test_queues_are_independent(self):
        fast = make_queue(timeout=0.05)
        patient = make_queue(timeout=1.0)

        async def medium():
            await asyncio.sleep(0.1)
            return "made it"

        a = fast.submit("medium", medium)
        b = patient.submit("medium", medium)
        await asyncio.gather(fast.join(), patient.join())
        self.assertIs(fast.status(a), JobStatus.TIMED_OUT)
        self.assertEqual(patient.result(b), "made it")
        await fast.shutdown()
        await patient.shutdown()


if __name__ == "__main__":
    unittest.main()
