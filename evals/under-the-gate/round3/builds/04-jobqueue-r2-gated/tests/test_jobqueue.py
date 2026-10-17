import asyncio
import unittest
from unittest import mock

from jobqueue import (
    JobCancelledError,
    JobNotFinishedError,
    JobQueue,
    JobStatus,
    JobTimedOutError,
    QueueClosedError,
    RetryableError,
    ShutdownSummary,
    UnknownJobError,
    WorkerCrashedError,
)


def make_queue(workers=2, timeout_seconds=1.0, max_attempts=3,
               initial_delay_seconds=0.01, delay_multiplier=2.0):
    return JobQueue(
        workers=workers,
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
        initial_delay_seconds=initial_delay_seconds,
        delay_multiplier=delay_multiplier,
    )


async def echo(value):
    await asyncio.sleep(0)
    return value


async def boom(message):
    raise ValueError(message)


class BasicTests(unittest.IsolatedAsyncioTestCase):
    async def test_result_of_successful_job(self):
        queue = make_queue()
        job_id = queue.submit("echo", echo, 42)
        await queue.join()
        self.assertEqual(queue.result(job_id), 42)
        self.assertIs(queue.status(job_id), JobStatus.SUCCEEDED)
        await queue.shutdown()

    async def test_result_raises_job_error(self):
        queue = make_queue()
        job_id = queue.submit("boom", boom, "bad")
        await queue.join()
        with self.assertRaisesRegex(ValueError, "bad"):
            queue.result(job_id)
        self.assertEqual(queue.attempts(job_id), 1)
        await queue.shutdown()

    async def test_unknown_and_unfinished_jobs(self):
        queue = make_queue()
        with self.assertRaises(UnknownJobError):
            queue.result(999)
        gate = asyncio.Event()
        job_id = queue.submit("wait", gate.wait)
        with self.assertRaises(JobNotFinishedError):
            queue.result(job_id)
        gate.set()
        await queue.join()
        await queue.shutdown()

    async def test_join_with_no_jobs(self):
        queue = make_queue()
        await queue.join()
        self.assertEqual(await queue.shutdown(), ShutdownSummary(0, 0, 0, 0))

    async def test_worker_count_limits_concurrency(self):
        queue = make_queue(workers=2)
        running = 0
        peak = 0

        async def job():
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.02)
            running -= 1

        for index in range(6):
            queue.submit(f"job-{index}", job)
        await queue.join()
        self.assertEqual(peak, 2)
        await queue.shutdown()

    async def test_invalid_settings(self):
        for bad in (dict(workers=0), dict(timeout_seconds=0), dict(max_attempts=0),
                    dict(initial_delay_seconds=-1), dict(delay_multiplier=0.5)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                make_queue(**bad)


class TimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_job_exceeding_timeout_is_cancelled(self):
        queue = make_queue(timeout_seconds=0.05)
        cancelled = asyncio.Event()

        async def slow():
            try:
                await asyncio.sleep(10)
            finally:
                # Reached early only when the sleep is cancelled.
                cancelled.set()

        job_id = queue.submit("slow", slow)
        await queue.join()
        self.assertIs(queue.status(job_id), JobStatus.TIMED_OUT)
        self.assertTrue(cancelled.is_set())
        with self.assertRaises(JobTimedOutError):
            queue.result(job_id)
        summary = await queue.shutdown()
        self.assertEqual(summary.timed_out, 1)


class RetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_retryable_error_is_retried_until_success(self):
        queue = make_queue(max_attempts=3)
        calls = 0

        async def flaky():
            nonlocal calls
            calls += 1
            if calls < 3:
                raise RetryableError("try again")
            return "ok"

        job_id = queue.submit("flaky", flaky)
        await queue.join()
        self.assertEqual(queue.result(job_id), "ok")
        self.assertEqual(queue.attempts(job_id), 3)
        await queue.shutdown()

    async def test_retries_stop_at_max_attempts(self):
        queue = make_queue(max_attempts=2)
        calls = 0

        async def always():
            nonlocal calls
            calls += 1
            raise RetryableError(f"attempt {calls}")

        job_id = queue.submit("always", always)
        await queue.join()
        self.assertEqual(calls, 2)
        with self.assertRaisesRegex(RetryableError, "attempt 2"):
            queue.result(job_id)

    async def test_non_retryable_error_fails_at_once(self):
        queue = make_queue(max_attempts=5)
        job_id = queue.submit("boom", boom, "no")
        await queue.join()
        self.assertEqual(queue.attempts(job_id), 1)
        self.assertIs(queue.status(job_id), JobStatus.FAILED)

    async def test_delay_grows_between_attempts(self):
        queue = make_queue(max_attempts=4, initial_delay_seconds=0.02, delay_multiplier=2.0)
        loop = asyncio.get_running_loop()
        times = []

        async def always():
            times.append(loop.time())
            raise RetryableError("again")

        queue.submit("always", always)
        await queue.join()
        gaps = [later - earlier for earlier, later in zip(times, times[1:])]
        self.assertEqual(len(gaps), 3)
        for gap, expected in zip(gaps, (0.02, 0.04, 0.08)):
            self.assertGreaterEqual(gap, expected * 0.9)
        self.assertLess(gaps[0], gaps[1])
        self.assertLess(gaps[1], gaps[2])

    def test_delay_schedule(self):
        settings = make_queue(initial_delay_seconds=0.5, delay_multiplier=3.0).settings
        self.assertEqual([settings.delay_after(n) for n in (1, 2, 3)], [0.5, 1.5, 4.5])


class ShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_cancels_waiting_and_finishes_running(self):
        queue = make_queue(workers=1, timeout_seconds=0.2, max_attempts=1)
        started = asyncio.Event()
        release = asyncio.Event()

        async def running():
            started.set()
            await release.wait()
            return "done"

        async def hang():
            await asyncio.sleep(10)

        first = queue.submit("running", running)
        failing = queue.submit("boom", boom, "x")
        waiting = queue.submit("waiting", echo, 1)
        await started.wait()
        shutdown = asyncio.ensure_future(queue.shutdown())
        await asyncio.sleep(0.01)
        self.assertFalse(shutdown.done())
        with self.assertRaises(QueueClosedError):
            queue.submit("late", echo, 2)
        release.set()
        summary = await shutdown
        self.assertEqual(summary, ShutdownSummary(succeeded=1, failed=0, timed_out=0, cancelled=2))
        self.assertEqual(queue.result(first), "done")
        for job_id in (failing, waiting):
            with self.assertRaises(JobCancelledError):
                queue.result(job_id)

    async def test_summary_counts_every_outcome(self):
        queue = make_queue(workers=3, timeout_seconds=0.05, max_attempts=1)

        async def slow():
            await asyncio.sleep(10)

        queue.submit("ok", echo, 1)
        queue.submit("ok2", echo, 2)
        queue.submit("bad", boom, "x")
        queue.submit("slow", slow)
        await queue.join()
        summary = await queue.shutdown()
        self.assertEqual(summary, ShutdownSummary(succeeded=2, failed=1, timed_out=1, cancelled=0))


class InternalErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_internal_error_is_reported_by_join_and_shutdown(self):
        queue = make_queue(workers=1)
        with mock.patch.object(queue, "_finish", side_effect=RuntimeError("queue bug")):
            queue.submit("echo", echo, 1)
            with self.assertRaises(WorkerCrashedError) as raised:
                await asyncio.wait_for(queue.join(), 2)
        self.assertIsInstance(raised.exception.__cause__, RuntimeError)
        with self.assertRaises(WorkerCrashedError):
            await asyncio.wait_for(queue.shutdown(), 2)

    async def test_crash_does_not_hide_other_workers(self):
        queue = make_queue(workers=2)
        original = queue._run_job
        calls = 0

        async def sometimes_broken(job):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("queue bug")
            await original(job)

        with mock.patch.object(queue, "_run_job", side_effect=sometimes_broken):
            queue.submit("a", echo, 1)
            ok = queue.submit("b", echo, 2)
            with self.assertRaises(WorkerCrashedError):
                await asyncio.wait_for(queue.join(), 2)
            with self.assertRaises(WorkerCrashedError):
                await asyncio.wait_for(queue.shutdown(), 2)
        self.assertEqual(queue.result(ok), 2)


if __name__ == "__main__":
    unittest.main()
