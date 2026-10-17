import asyncio
import time
import unittest

from jobqueue import (
    JobCancelled,
    JobNotFinished,
    JobQueue,
    JobState,
    JobTimedOut,
    QueueClosed,
    QueueInternalError,
    RetryableError,
    Summary,
)


async def add(a, b):
    await asyncio.sleep(0)
    return a + b


async def sleep_for(seconds, value=None):
    await asyncio.sleep(seconds)
    return value


async def boom():
    raise ValueError("boom")


def fast_queue(**kw):
    opts = dict(workers=2, timeout=1.0, max_attempts=3, base_delay=0.01, max_delay=0.1)
    opts.update(kw)
    return JobQueue(**opts)


class BasicTests(unittest.IsolatedAsyncioTestCase):
    async def test_submit_join_result(self):
        q = fast_queue()
        ids = [q.submit(f"add{i}", add, i, i) for i in range(10)]
        await q.join()
        self.assertEqual([q.result(i) for i in ids], [2 * i for i in range(10)])
        self.assertEqual(len(set(ids)), 10)
        self.assertEqual(await q.shutdown(), Summary(succeeded=10))

    async def test_join_with_no_jobs(self):
        q = fast_queue()
        await q.join()
        self.assertEqual(await q.shutdown(), Summary())

    async def test_result_before_finish(self):
        q = fast_queue()
        jid = q.submit("slow", sleep_for, 0.05)
        with self.assertRaises(JobNotFinished):
            q.result(jid)
        await q.join()
        self.assertIsNone(q.result(jid))

    async def test_unknown_job_id(self):
        q = fast_queue()
        with self.assertRaises(KeyError):
            q.result(42)

    async def test_worker_count_limits_concurrency(self):
        running = 0
        peak = 0

        async def track():
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.02)
            running -= 1

        q = fast_queue(workers=3)
        for i in range(12):
            q.submit(f"t{i}", track)
        await q.join()
        self.assertEqual(peak, 3)

    async def test_workers_run_in_parallel(self):
        q = fast_queue(workers=5)
        start = time.monotonic()
        for i in range(5):
            q.submit(f"s{i}", sleep_for, 0.1)
        await q.join()
        self.assertLess(time.monotonic() - start, 0.3)

    async def test_invalid_settings(self):
        for kw in [dict(workers=0), dict(timeout=0), dict(max_attempts=0),
                   dict(base_delay=-1), dict(backoff=0.5)]:
            with self.subTest(**kw), self.assertRaises(ValueError):
                fast_queue(**kw)

    async def test_queues_are_independent(self):
        a = fast_queue(timeout=0.05)
        b = fast_queue(timeout=1.0)
        ja = a.submit("x", sleep_for, 0.1, "a")
        jb = b.submit("x", sleep_for, 0.1, "b")
        await asyncio.gather(a.join(), b.join())
        with self.assertRaises(JobTimedOut):
            a.result(ja)
        self.assertEqual(b.result(jb), "b")


class FailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_retryable_fails_at_once(self):
        calls = 0

        async def bad():
            nonlocal calls
            calls += 1
            raise ValueError("nope")

        q = fast_queue()
        jid = q.submit("bad", bad)
        await q.join()
        with self.assertRaisesRegex(ValueError, "nope"):
            q.result(jid)
        self.assertEqual(calls, 1)
        self.assertEqual(q.state(jid), JobState.FAILED)

    async def test_timeout(self):
        q = fast_queue(timeout=0.05)
        cancelled = asyncio.Event()

        async def hang():
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        jid = q.submit("hang", hang)
        ok = q.submit("ok", add, 1, 2)
        await q.join()
        self.assertTrue(cancelled.is_set())
        self.assertEqual(q.state(jid), JobState.TIMED_OUT)
        with self.assertRaises(JobTimedOut):
            q.result(jid)
        self.assertEqual(q.result(ok), 3)
        self.assertEqual(await q.shutdown(), Summary(succeeded=1, timed_out=1))

    async def test_job_raising_timeout_error_is_failure_not_timeout(self):
        async def raises_timeout():
            raise TimeoutError("mine")

        q = fast_queue()
        jid = q.submit("t", raises_timeout)
        await q.join()
        self.assertEqual(q.state(jid), JobState.FAILED)
        with self.assertRaisesRegex(TimeoutError, "mine"):
            q.result(jid)

    async def test_job_cancelling_itself_does_not_kill_worker(self):
        async def self_cancel():
            raise asyncio.CancelledError()

        q = fast_queue(workers=1)
        bad = q.submit("c", self_cancel)
        good = q.submit("g", add, 2, 2)
        await q.join()
        self.assertEqual(q.state(bad), JobState.FAILED)
        self.assertEqual(q.result(good), 4)
        self.assertEqual(await q.shutdown(), Summary(succeeded=1, failed=1))

    async def test_retry_then_succeed_with_growing_delay(self):
        times = []

        async def flaky():
            times.append(time.monotonic())
            if len(times) < 4:
                raise RetryableError("again")
            return "done"

        q = fast_queue(max_attempts=5, base_delay=0.02, backoff=2.0, max_delay=1.0)
        jid = q.submit("flaky", flaky)
        await q.join()
        self.assertEqual(q.result(jid), "done")
        self.assertEqual(q.attempts(jid), 4)
        gaps = [b - a for a, b in zip(times, times[1:])]
        # expected delays 0.02, 0.04, 0.08
        for gap, expected in zip(gaps, [0.02, 0.04, 0.08]):
            self.assertGreaterEqual(gap, expected * 0.9)
        self.assertLess(gaps[0], gaps[1])
        self.assertLess(gaps[1], gaps[2])

    async def test_retry_exhausted(self):
        calls = 0

        class Flaky(RetryableError):
            pass

        async def always():
            nonlocal calls
            calls += 1
            raise Flaky(f"attempt {calls}")

        q = fast_queue(max_attempts=3)
        jid = q.submit("always", always)
        await q.join()
        self.assertEqual(calls, 3)
        with self.assertRaisesRegex(Flaky, "attempt 3"):
            q.result(jid)

    async def test_max_delay_caps_backoff(self):
        q = fast_queue(base_delay=0.01, backoff=10, max_delay=0.05)
        self.assertEqual([q._delay(n) for n in (1, 2, 3, 4)], [0.01, 0.05, 0.05, 0.05])

    async def test_timeout_applies_per_attempt_and_is_not_retried(self):
        calls = 0

        async def slow():
            nonlocal calls
            calls += 1
            await asyncio.sleep(1)

        q = fast_queue(timeout=0.03, max_attempts=3)
        jid = q.submit("slow", slow)
        await q.join()
        self.assertEqual(calls, 1)
        self.assertEqual(q.state(jid), JobState.TIMED_OUT)


class ShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_cancels_waiting_and_finishes_running(self):
        q = fast_queue(workers=2)
        running = [q.submit(f"r{i}", sleep_for, 0.05, i) for i in range(2)]
        await asyncio.sleep(0.01)  # let the workers pick up the first two
        waiting = [q.submit(f"w{i}", sleep_for, 0.05, i) for i in range(3)]
        summary = await q.shutdown()
        self.assertEqual(summary, Summary(succeeded=2, cancelled=3))
        self.assertEqual([q.result(j) for j in running], [0, 1])
        for j in waiting:
            with self.assertRaises(JobCancelled):
                q.result(j)

    async def test_shutdown_summary_counts_everything(self):
        q = fast_queue(workers=4, timeout=0.05, max_attempts=2)

        async def retry_forever():
            raise RetryableError()

        q.submit("ok", add, 1, 1)
        q.submit("bad", boom)
        q.submit("retry", retry_forever)
        q.submit("slow", sleep_for, 1)
        await q.join()
        self.assertEqual(await q.shutdown(),
                         Summary(succeeded=1, failed=2, timed_out=1, cancelled=0))

    async def test_submit_after_shutdown(self):
        q = fast_queue()
        await q.shutdown()
        with self.assertRaises(QueueClosed):
            q.submit("late", add, 1, 2)

    async def test_join_after_shutdown_returns(self):
        q = fast_queue(workers=1)
        q.submit("a", sleep_for, 0.02)
        q.submit("b", sleep_for, 0.02)
        await asyncio.sleep(0)
        await q.shutdown()
        await asyncio.wait_for(q.join(), 1)


class InternalErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_internal_error_reported_by_join_and_shutdown(self):
        q = fast_queue(workers=1)
        original = q._finish
        calls = 0

        def broken_finish(job, state, **kw):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("bug in queue")
            return original(job, state, **kw)

        q._finish = broken_finish
        first = q.submit("first", add, 1, 1)
        second = q.submit("second", add, 2, 2)
        with self.assertRaises(QueueInternalError) as ctx:
            await asyncio.wait_for(q.join(), 1)
        self.assertIn("bug in queue", str(ctx.exception))
        # the worker survived and processed the next job
        self.assertEqual(q.result(second), 4)
        with self.assertRaises(QueueInternalError):
            q.result(first)
        with self.assertRaises(QueueInternalError) as ctx:
            await q.shutdown()
        self.assertEqual(ctx.exception.summary, Summary(succeeded=1, failed=1))

    async def test_dead_worker_does_not_hang_join(self):
        q = fast_queue(workers=1)

        class WorkerKilled(BaseException):
            pass

        async def broken_run_job(job):
            raise WorkerKilled("worker killed")  # escapes the worker loop

        q._run_job = broken_run_job
        q.submit("a", add, 1, 1)
        q.submit("b", add, 1, 1)
        with self.assertRaises(QueueInternalError) as ctx:
            await asyncio.wait_for(q.join(), 1)
        self.assertIn("worker killed", str(ctx.exception))
        with self.assertRaises(QueueInternalError):
            await asyncio.wait_for(q.shutdown(), 1)

    async def test_externally_cancelled_worker_is_reported(self):
        q = fast_queue(workers=1)
        q.submit("a", sleep_for, 0.5)
        await asyncio.sleep(0)
        q._worker_tasks[0].cancel()
        with self.assertRaises(QueueInternalError):
            await asyncio.wait_for(q.join(), 1)


if __name__ == "__main__":
    unittest.main()
