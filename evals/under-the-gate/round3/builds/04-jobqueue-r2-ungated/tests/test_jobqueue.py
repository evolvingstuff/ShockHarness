import asyncio
import time
import unittest
from unittest import mock

from jobqueue import (
    JobCancelled,
    JobNotFinished,
    JobQueue,
    JobTimedOut,
    QueueClosed,
    QueueInternalError,
    RetryableError,
    Status,
    Summary,
)


async def add(a, b):
    await asyncio.sleep(0)
    return a + b


async def boom():
    raise ValueError("boom")


class BasicTests(unittest.IsolatedAsyncioTestCase):
    async def test_results(self):
        q = JobQueue(workers=2)
        ids = [q.submit(f"add{i}", add, i, 10) for i in range(5)]
        await q.join()
        self.assertEqual([q.result(i) for i in ids], [10, 11, 12, 13, 14])
        self.assertEqual(await q.shutdown(), Summary(succeeded=5))

    async def test_join_with_no_jobs(self):
        q = JobQueue(workers=1)
        await q.join()
        self.assertEqual(await q.shutdown(), Summary())

    async def test_worker_limit(self):
        running = peak = 0

        async def job():
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.02)
            running -= 1

        q = JobQueue(workers=3)
        for i in range(10):
            q.submit(f"j{i}", job)
        await q.join()
        self.assertEqual(peak, 3)
        await q.shutdown()

    async def test_non_retryable_error_fails_at_once(self):
        q = JobQueue(workers=1, max_attempts=5, retry_delay=0)
        jid = q.submit("boom", boom)
        await q.join()
        self.assertEqual(q.status(jid), Status.FAILED)
        self.assertEqual(q.attempts(jid), 1)
        with self.assertRaisesRegex(ValueError, "boom"):
            q.result(jid)
        self.assertEqual(await q.shutdown(), Summary(failed=1))

    async def test_result_of_unfinished_job(self):
        q = JobQueue(workers=1)
        jid = q.submit("slow", asyncio.sleep, 0.05)
        with self.assertRaises(JobNotFinished):
            q.result(jid)
        await q.join()
        self.assertIsNone(q.result(jid))
        await q.shutdown()

    async def test_unknown_job(self):
        q = JobQueue()
        with self.assertRaises(KeyError):
            q.result(42)

    def test_invalid_settings(self):
        for kwargs in (
            {"workers": 0},
            {"timeout": 0},
            {"max_attempts": 0},
            {"retry_delay": -1},
            {"backoff": 0.5},
            {"max_delay": -1},
        ):
            with self.subTest(**kwargs), self.assertRaises(ValueError):
                JobQueue(**kwargs)


class TimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_job_times_out_and_is_cancelled(self):
        cancelled = asyncio.Event()

        async def hang():
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        q = JobQueue(workers=1, timeout=0.05)
        jid = q.submit("hang", hang)
        ok = q.submit("ok", add, 1, 2)
        await q.join()
        self.assertTrue(cancelled.is_set())
        self.assertEqual(q.status(jid), Status.TIMED_OUT)
        with self.assertRaises(JobTimedOut):
            q.result(jid)
        self.assertEqual(q.result(ok), 3)
        self.assertEqual(await q.shutdown(), Summary(succeeded=1, timed_out=1))

    async def test_timed_out_job_is_not_retried(self):
        q = JobQueue(workers=1, timeout=0.02, max_attempts=3, retry_delay=0)
        jid = q.submit("hang", asyncio.sleep, 10)
        await q.join()
        self.assertEqual(q.attempts(jid), 1)
        await q.shutdown()

    async def test_timeout_error_raised_by_job_is_a_failure(self):
        async def raises_timeout():
            raise TimeoutError("own")

        q = JobQueue(workers=1, timeout=5)
        jid = q.submit("t", raises_timeout)
        await q.join()
        self.assertEqual(q.status(jid), Status.FAILED)
        with self.assertRaisesRegex(TimeoutError, "own"):
            q.result(jid)
        await q.shutdown()

    async def test_no_timeout(self):
        q = JobQueue(workers=1, timeout=None)
        jid = q.submit("s", add, 2, 2)
        await q.join()
        self.assertEqual(q.result(jid), 4)
        await q.shutdown()


class RetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_retries_with_growing_delay(self):
        times = []

        async def flaky():
            times.append(time.monotonic())
            if len(times) < 4:
                raise RetryableError("again")
            return "done"

        q = JobQueue(workers=1, max_attempts=5, retry_delay=0.02, backoff=2.0)
        jid = q.submit("flaky", flaky)
        await q.join()
        self.assertEqual(q.result(jid), "done")
        self.assertEqual(q.attempts(jid), 4)
        gaps = [b - a for a, b in zip(times, times[1:])]
        for gap, expected in zip(gaps, (0.02, 0.04, 0.08)):
            self.assertGreaterEqual(gap, expected * 0.9)
        self.assertLess(gaps[0], gaps[1])
        self.assertLess(gaps[1], gaps[2])
        await q.shutdown()

    async def test_gives_up_after_max_attempts(self):
        calls = 0

        async def always():
            nonlocal calls
            calls += 1
            raise RetryableError(f"attempt {calls}")

        q = JobQueue(workers=1, max_attempts=3, retry_delay=0.001)
        jid = q.submit("always", always)
        await q.join()
        self.assertEqual(calls, 3)
        self.assertEqual(q.status(jid), Status.FAILED)
        with self.assertRaisesRegex(RetryableError, "attempt 3"):
            q.result(jid)
        self.assertEqual(await q.shutdown(), Summary(failed=1))

    async def test_delay_is_capped(self):
        q = JobQueue(retry_delay=1, backoff=3, max_delay=5)
        self.assertEqual([q._delay(n) for n in (1, 2, 3, 4)], [1, 3, 5, 5])

    async def test_settings_are_per_queue(self):
        counts = {"a": 0, "b": 0}

        async def fail(key):
            counts[key] += 1
            raise RetryableError

        qa = JobQueue(workers=1, max_attempts=2, retry_delay=0)
        qb = JobQueue(workers=1, max_attempts=4, retry_delay=0)
        qa.submit("a", fail, "a")
        qb.submit("b", fail, "b")
        await asyncio.gather(qa.join(), qb.join())
        self.assertEqual(counts, {"a": 2, "b": 4})
        await qa.shutdown()
        await qb.shutdown()


class ShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_cancels_waiting_and_finishes_running(self):
        started = asyncio.Event()

        async def slow(v):
            started.set()
            await asyncio.sleep(0.05)
            return v

        q = JobQueue(workers=1)
        running = q.submit("running", slow, "r")
        waiting = [q.submit(f"w{i}", slow, i) for i in range(3)]
        await started.wait()
        summary = await q.shutdown()
        self.assertEqual(summary, Summary(succeeded=1, cancelled=3))
        self.assertEqual(q.result(running), "r")
        for jid in waiting:
            self.assertEqual(q.status(jid), Status.CANCELLED)
            with self.assertRaises(JobCancelled):
                q.result(jid)
        with self.assertRaises(QueueClosed):
            q.submit("late", add, 1, 1)
        await q.join()
        self.assertTrue(all(t.done() for t in q._tasks))

    async def test_summary_counts_every_outcome(self):
        async def retry_once():
            raise RetryableError

        q = JobQueue(workers=4, timeout=0.05, max_attempts=1)
        q.submit("ok", add, 1, 1)
        q.submit("fail", boom)
        q.submit("retry", retry_once)
        q.submit("hang", asyncio.sleep, 10)
        await q.join()
        self.assertEqual(
            await q.shutdown(), Summary(succeeded=1, failed=2, timed_out=1)
        )

    async def test_shutdown_is_idempotent_and_works_unused(self):
        q = JobQueue()
        self.assertEqual(await q.shutdown(), Summary())
        self.assertEqual(await q.shutdown(), Summary())
        with self.assertRaises(QueueClosed):
            q.submit("x", add, 1, 2)


class InternalErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_error_in_queue_code_is_reported(self):
        q = JobQueue(workers=1)
        bug = RuntimeError("bug in queue")
        with mock.patch.object(q, "_run", side_effect=bug):
            jid = q.submit("x", add, 1, 2)
            with self.assertRaises(QueueInternalError) as cm:
                await asyncio.wait_for(q.join(), 2)
        self.assertIs(cm.exception.errors[0], bug)
        self.assertEqual(q.status(jid), Status.FAILED)
        with self.assertRaises(QueueInternalError):
            q.result(jid)
        with self.assertRaises(QueueInternalError) as cm:
            await asyncio.wait_for(q.shutdown(), 2)
        self.assertEqual(cm.exception.summary, Summary(failed=1))

    async def test_worker_keeps_running_after_internal_error(self):
        q = JobQueue(workers=1)
        real_run = q._run
        calls = 0

        async def sometimes_broken(job):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("first job breaks")
            await real_run(job)

        with mock.patch.object(q, "_run", side_effect=sometimes_broken):
            q.submit("a", add, 1, 1)
            b = q.submit("b", add, 2, 2)
            with self.assertRaises(QueueInternalError):
                await asyncio.wait_for(q.join(), 2)
            with self.assertRaises(QueueInternalError) as cm:
                await asyncio.wait_for(q.shutdown(), 2)
        self.assertEqual(q.result(b), 4)
        self.assertEqual(cm.exception.summary, Summary(succeeded=1, failed=1))

    async def test_dead_worker_is_reported_not_hung(self):
        q = JobQueue(workers=1)
        started = asyncio.Event()

        async def slow():
            started.set()
            await asyncio.sleep(10)

        jid = q.submit("slow", slow)
        q.submit("waiting", add, 1, 1)
        await started.wait()
        q._tasks[0].cancel()  # simulate a worker dying from outside
        with self.assertRaises(QueueInternalError):
            await asyncio.wait_for(q.join(), 2)
        with self.assertRaises(QueueInternalError) as cm:
            await asyncio.wait_for(q.shutdown(), 2)
        self.assertEqual(q.status(jid), Status.FAILED)
        self.assertEqual(cm.exception.summary, Summary(failed=1, cancelled=1))


if __name__ == "__main__":
    unittest.main()
