import asyncio
import time
import unittest

from jobqueue import (
    JobCancelled,
    JobNotFinished,
    JobQueue,
    JobStatus,
    JobTimedOut,
    QueueClosed,
    QueueInternalError,
    RetryableError,
    Summary,
)


async def echo(value, delay=0.0):
    await asyncio.sleep(delay)
    return value


async def boom(message):
    raise ValueError(message)


class Flaky:
    """Raises RetryableError for the first `failures` calls, then returns 'ok'."""

    def __init__(self, failures, exc=RetryableError):
        self.failures = failures
        self.exc = exc
        self.calls = []

    async def __call__(self):
        self.calls.append(time.monotonic())
        if len(self.calls) <= self.failures:
            raise self.exc(f"attempt {len(self.calls)}")
        return "ok"


class BasicTests(unittest.IsolatedAsyncioTestCase):
    async def test_results_in_order_of_ids(self):
        q = JobQueue(workers=3, timeout=1)
        ids = [q.submit(f"job{i}", echo, i, 0.01) for i in range(10)]
        await q.join()
        self.assertEqual([q.result(i) for i in ids], list(range(10)))
        self.assertEqual(len(set(ids)), 10)
        self.assertEqual(await q.shutdown(), Summary(succeeded=10))

    async def test_join_with_no_jobs(self):
        q = JobQueue(workers=1)
        await q.join()
        self.assertEqual(await q.shutdown(), Summary())

    async def test_worker_limit_respected(self):
        running = 0
        peak = 0

        async def job():
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.02)
            running -= 1

        q = JobQueue(workers=2, timeout=1)
        for i in range(8):
            q.submit("j", job)
        await q.join()
        self.assertEqual(peak, 2)
        await q.shutdown()

    async def test_failure_raises_job_error(self):
        q = JobQueue(workers=1, timeout=1, max_attempts=5)
        jid = q.submit("bad", boom, "nope")
        await q.join()
        with self.assertRaisesRegex(ValueError, "nope"):
            q.result(jid)
        self.assertEqual(q.status(jid), JobStatus.FAILED)
        self.assertEqual(q.job(jid).attempts, 1)  # non-retryable: no retry
        self.assertEqual(await q.shutdown(), Summary(failed=1))

    async def test_result_of_unfinished_and_unknown(self):
        q = JobQueue(workers=1, timeout=1)
        jid = q.submit("slow", echo, 1, 0.05)
        with self.assertRaises(JobNotFinished):
            q.result(jid)
        with self.assertRaises(KeyError):
            q.result(999)
        await q.join()
        self.assertEqual(q.result(jid), 1)
        await q.shutdown()

    async def test_args_passed(self):
        async def add(a, b):
            return a + b

        q = JobQueue(workers=1, timeout=1)
        jid = q.submit("add", add, 2, 3)
        await q.join()
        self.assertEqual(q.result(jid), 5)
        await q.shutdown()

    async def test_invalid_settings(self):
        for kwargs in ({"workers": 0}, {"timeout": 0}, {"max_attempts": 0},
                       {"retry_delay": -1}, {"backoff": 0.5}):
            with self.assertRaises(ValueError):
                JobQueue(**kwargs)

    async def test_queues_are_independent(self):
        a = JobQueue(workers=1, timeout=0.05)
        b = JobQueue(workers=1, timeout=1)
        ja = a.submit("slow", echo, "a", 0.2)
        jb = b.submit("slow", echo, "b", 0.1)
        await asyncio.gather(a.join(), b.join())
        self.assertEqual(a.status(ja), JobStatus.TIMED_OUT)
        self.assertEqual(b.result(jb), "b")
        await a.shutdown()
        await b.shutdown()


class TimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_cancels_job(self):
        cancelled = asyncio.Event()

        async def hang():
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        q = JobQueue(workers=1, timeout=0.05)
        jid = q.submit("hang", hang)
        ok = q.submit("ok", echo, "fine")
        start = time.monotonic()
        await q.join()
        self.assertLess(time.monotonic() - start, 1)
        self.assertTrue(cancelled.is_set())
        self.assertEqual(q.status(jid), JobStatus.TIMED_OUT)
        with self.assertRaises(JobTimedOut):
            q.result(jid)
        self.assertEqual(q.result(ok), "fine")
        self.assertEqual(await q.shutdown(), Summary(succeeded=1, timed_out=1))

    async def test_job_raising_timeout_error_is_failure_not_timeout(self):
        async def raises_timeout():
            raise TimeoutError("own timeout")

        q = JobQueue(workers=1, timeout=1)
        jid = q.submit("t", raises_timeout)
        await q.join()
        self.assertEqual(q.status(jid), JobStatus.FAILED)
        with self.assertRaisesRegex(TimeoutError, "own timeout"):
            q.result(jid)
        await q.shutdown()

    async def test_timeout_is_not_retried(self):
        calls = 0

        async def hang():
            nonlocal calls
            calls += 1
            await asyncio.sleep(10)

        q = JobQueue(workers=1, timeout=0.02, max_attempts=3, retry_delay=0)
        jid = q.submit("hang", hang)
        await q.join()
        self.assertEqual(q.status(jid), JobStatus.TIMED_OUT)
        self.assertEqual(calls, 1)
        await q.shutdown()


class RetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_until_success(self):
        flaky = Flaky(failures=2)
        q = JobQueue(workers=1, timeout=1, max_attempts=3, retry_delay=0.01)
        jid = q.submit("flaky", flaky)
        await q.join()
        self.assertEqual(q.result(jid), "ok")
        self.assertEqual(q.job(jid).attempts, 3)
        await q.shutdown()

    async def test_retry_gives_up_after_max_attempts(self):
        flaky = Flaky(failures=10)
        q = JobQueue(workers=1, timeout=1, max_attempts=3, retry_delay=0.001)
        jid = q.submit("flaky", flaky)
        await q.join()
        self.assertEqual(len(flaky.calls), 3)
        with self.assertRaisesRegex(RetryableError, "attempt 3"):
            q.result(jid)
        self.assertEqual(await q.shutdown(), Summary(failed=1))

    async def test_retryable_subclass_is_retried(self):
        class Transient(RetryableError):
            pass

        flaky = Flaky(failures=1, exc=Transient)
        q = JobQueue(workers=1, timeout=1, max_attempts=2, retry_delay=0)
        jid = q.submit("flaky", flaky)
        await q.join()
        self.assertEqual(q.result(jid), "ok")
        await q.shutdown()

    async def test_delay_grows(self):
        flaky = Flaky(failures=3)
        q = JobQueue(workers=1, timeout=1, max_attempts=4, retry_delay=0.03, backoff=2)
        q.submit("flaky", flaky)
        await q.join()
        gaps = [b - a for a, b in zip(flaky.calls, flaky.calls[1:])]
        self.assertEqual(len(gaps), 3)
        for gap, expected in zip(gaps, (0.03, 0.06, 0.12)):
            self.assertGreaterEqual(gap, expected * 0.9)
        self.assertLess(gaps[0], gaps[1])
        self.assertLess(gaps[1], gaps[2])
        await q.shutdown()

    async def test_delay_schedule_and_cap(self):
        q = JobQueue(retry_delay=0.1, backoff=3, max_delay=0.5)
        self.assertEqual([round(q.retry_delay(n), 6) for n in range(1, 5)],
                         [0.1, 0.3, 0.5, 0.5])

    async def test_retry_delay_does_not_block_other_workers(self):
        flaky = Flaky(failures=1)
        q = JobQueue(workers=2, timeout=1, max_attempts=2, retry_delay=0.2)
        q.submit("flaky", flaky)
        start = time.monotonic()
        quick = q.submit("quick", echo, "q")
        while q.status(quick) is not JobStatus.SUCCEEDED:
            await asyncio.sleep(0.005)
        self.assertLess(time.monotonic() - start, 0.15)
        await q.join()
        await q.shutdown()


class ShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_cancels_waiting_lets_running_finish(self):
        started = asyncio.Event()

        async def slow():
            started.set()
            await asyncio.sleep(0.1)
            return "done"

        q = JobQueue(workers=1, timeout=1)
        running = q.submit("slow", slow)
        waiting = [q.submit("w", echo, i) for i in range(3)]
        await started.wait()
        summary = await q.shutdown()
        self.assertEqual(summary, Summary(succeeded=1, cancelled=3))
        self.assertEqual(q.result(running), "done")
        for jid in waiting:
            self.assertEqual(q.status(jid), JobStatus.CANCELLED)
            with self.assertRaises(JobCancelled):
                q.result(jid)
        await q.join()  # nothing left; returns immediately

    async def test_summary_counts_every_outcome(self):
        async def hang():
            await asyncio.sleep(10)

        q = JobQueue(workers=4, timeout=0.05, max_attempts=1)
        q.submit("ok", echo, 1)
        q.submit("ok", echo, 2)
        q.submit("bad", boom, "x")
        q.submit("hang", hang)
        await q.join()
        gate = asyncio.Event()

        async def blocker():
            await gate.wait()

        q2 = JobQueue(workers=1, timeout=1)
        q2.submit("b", blocker)
        q2.submit("c", echo, 0)
        await asyncio.sleep(0)
        shutting = asyncio.create_task(q2.shutdown())
        await asyncio.sleep(0)
        gate.set()
        self.assertEqual(await q.shutdown(),
                         Summary(succeeded=2, failed=1, timed_out=1, cancelled=0))
        self.assertEqual(await shutting, Summary(succeeded=1, cancelled=1))

    async def test_submit_after_shutdown_rejected(self):
        q = JobQueue(workers=1)
        await q.shutdown()
        with self.assertRaises(QueueClosed):
            q.submit("late", echo, 1)

    async def test_join_concurrent_with_shutdown(self):
        q = JobQueue(workers=1, timeout=1)
        q.submit("a", echo, 1, 0.05)
        q.submit("b", echo, 2, 0.05)
        await asyncio.sleep(0.01)
        joined = asyncio.create_task(q.join())
        summary = await q.shutdown()
        await asyncio.wait_for(joined, 1)
        self.assertEqual(summary, Summary(succeeded=1, cancelled=1))

    async def test_shutdown_twice(self):
        q = JobQueue(workers=1, timeout=1)
        q.submit("a", echo, 1)
        first = await q.shutdown()
        self.assertEqual(await q.shutdown(), first)

    async def test_job_cancelling_itself(self):
        async def self_cancel():
            raise asyncio.CancelledError

        q = JobQueue(workers=1, timeout=1)
        jid = q.submit("c", self_cancel)
        after = q.submit("after", echo, "still works")
        await q.join()
        self.assertEqual(q.status(jid), JobStatus.CANCELLED)
        self.assertEqual(q.result(after), "still works")
        self.assertEqual(await q.shutdown(), Summary(succeeded=1, cancelled=1))


class InternalErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_internal_error_per_job_is_reported_and_worker_survives(self):
        q = JobQueue(workers=1, timeout=1)
        original = q._run_job
        calls = 0

        async def buggy(job):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("queue bug")
            await original(job)

        q._run_job = buggy
        bad = q.submit("a", echo, 1)
        good = q.submit("b", echo, 2)
        with self.assertRaises(QueueInternalError) as cm:
            await asyncio.wait_for(q.join(), 1)
        self.assertIn("queue bug", str(cm.exception))
        self.assertEqual(q.status(bad), JobStatus.FAILED)
        self.assertEqual(q.result(good), 2)  # the worker kept going
        with self.assertRaises(QueueInternalError) as cm:
            await q.shutdown()
        self.assertEqual(cm.exception.summary, Summary(succeeded=1, failed=1))

    async def test_worker_crash_does_not_hang_join(self):
        q = JobQueue(workers=1, timeout=1)

        async def broken_next_job():
            raise RuntimeError("worker loop bug")

        q._next_job = broken_next_job
        q.submit("a", echo, 1)
        with self.assertRaisesRegex(QueueInternalError, "worker loop bug"):
            await asyncio.wait_for(q.join(), 1)
        with self.assertRaisesRegex(QueueInternalError, "worker loop bug"):
            await asyncio.wait_for(q.shutdown(), 1)

    async def test_externally_cancelled_worker_is_reported(self):
        q = JobQueue(workers=1, timeout=1)
        q.submit("a", echo, 1, 0.5)
        await asyncio.sleep(0.01)
        q._workers[0].cancel()
        with self.assertRaisesRegex(QueueInternalError, "cancelled"):
            await asyncio.wait_for(q.join(), 1)


if __name__ == "__main__":
    unittest.main()
