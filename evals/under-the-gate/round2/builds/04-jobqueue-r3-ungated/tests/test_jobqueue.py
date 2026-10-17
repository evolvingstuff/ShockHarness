import asyncio
import time
import unittest

from jobqueue import (
    JobCancelledError,
    JobNotFinishedError,
    JobQueue,
    JobState,
    JobTimeoutError,
    QueueClosedError,
    QueueInternalError,
    RetryableError,
    Summary,
)


async def echo(value, delay=0.0):
    await asyncio.sleep(delay)
    return value


async def boom():
    raise ValueError("boom")


class Flaky:
    """Raises RetryableError `failures` times, then returns 'ok'."""

    def __init__(self, failures):
        self.failures = failures
        self.calls = []

    async def __call__(self):
        self.calls.append(time.monotonic())
        if len(self.calls) <= self.failures:
            raise RetryableError(f"attempt {len(self.calls)}")
        return "ok"


class BasicTests(unittest.IsolatedAsyncioTestCase):
    async def test_results(self):
        q = JobQueue(workers=2, timeout=1)
        ids = [q.submit(f"j{i}", echo, i) for i in range(5)]
        await q.join()
        self.assertEqual([q.result(i) for i in ids], [0, 1, 2, 3, 4])
        self.assertEqual(await q.shutdown(), Summary(succeeded=5))

    async def test_ids_are_unique(self):
        q = JobQueue(workers=1)
        ids = {q.submit("j", echo, 1) for _ in range(10)}
        self.assertEqual(len(ids), 10)
        await q.shutdown()

    async def test_join_with_no_jobs(self):
        q = JobQueue(workers=1)
        await q.join()
        self.assertEqual(await q.shutdown(), Summary())

    async def test_failure_raised_from_result(self):
        q = JobQueue(workers=1, max_attempts=5)
        jid = q.submit("boom", boom)
        await q.join()
        with self.assertRaisesRegex(ValueError, "boom"):
            q.result(jid)
        self.assertEqual(q.state(jid), JobState.FAILED)
        self.assertEqual(q.attempts(jid), 1)  # not retried

    async def test_unknown_and_unfinished(self):
        q = JobQueue(workers=1)
        with self.assertRaises(KeyError):
            q.result(999)
        jid = q.submit("slow", echo, 1, 0.05)
        with self.assertRaises(JobNotFinishedError):
            q.result(jid)
        await q.join()
        self.assertEqual(q.result(jid), 1)

    async def test_worker_limit(self):
        running = 0
        peak = 0

        async def job():
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.02)
            running -= 1

        q = JobQueue(workers=3)
        for _ in range(10):
            q.submit("j", job)
        await q.join()
        self.assertEqual(peak, 3)

    async def test_invalid_settings(self):
        for kwargs in ({"workers": 0}, {"max_attempts": 0}, {"timeout": 0}, {"backoff": 0.5}):
            with self.assertRaises(ValueError):
                JobQueue(**kwargs)

    async def test_queues_are_independent(self):
        a = JobQueue(workers=1, timeout=0.05)
        b = JobQueue(workers=1, timeout=1)
        ja = a.submit("a", echo, 1, 0.2)
        jb = b.submit("b", echo, 2, 0.1)
        await asyncio.gather(a.join(), b.join())
        self.assertEqual(a.state(ja), JobState.TIMED_OUT)
        self.assertEqual(b.result(jb), 2)


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
        await q.join()
        self.assertTrue(cancelled.is_set())
        self.assertEqual(q.state(jid), JobState.TIMED_OUT)
        with self.assertRaises(JobTimeoutError):
            q.result(jid)
        self.assertEqual(q.result(ok), "fine")
        self.assertEqual(await q.shutdown(), Summary(succeeded=1, timed_out=1))

    async def test_job_raising_timeout_error_is_failure(self):
        async def job():
            raise TimeoutError("own timeout")

        q = JobQueue(workers=1, timeout=1)
        jid = q.submit("j", job)
        await q.join()
        self.assertEqual(q.state(jid), JobState.FAILED)
        with self.assertRaisesRegex(TimeoutError, "own timeout"):
            q.result(jid)

    async def test_timed_out_job_not_retried(self):
        calls = 0

        async def job():
            nonlocal calls
            calls += 1
            await asyncio.sleep(1)

        q = JobQueue(workers=1, timeout=0.02, max_attempts=3, base_delay=0)
        jid = q.submit("j", job)
        await q.join()
        self.assertEqual(calls, 1)
        self.assertEqual(q.state(jid), JobState.TIMED_OUT)


class RetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_then_succeed(self):
        flaky = Flaky(2)
        q = JobQueue(workers=1, max_attempts=3, base_delay=0.02, backoff=2)
        jid = q.submit("flaky", flaky)
        await q.join()
        self.assertEqual(q.result(jid), "ok")
        self.assertEqual(q.attempts(jid), 3)
        gaps = [b - a for a, b in zip(flaky.calls, flaky.calls[1:])]
        self.assertGreaterEqual(gaps[0], 0.018)
        self.assertGreaterEqual(gaps[1], 0.038)  # delay grows
        self.assertGreater(gaps[1], gaps[0])

    async def test_retry_exhausted(self):
        flaky = Flaky(10)
        q = JobQueue(workers=1, max_attempts=3, base_delay=0.001)
        jid = q.submit("flaky", flaky)
        await q.join()
        self.assertEqual(len(flaky.calls), 3)
        self.assertEqual(q.state(jid), JobState.FAILED)
        with self.assertRaisesRegex(RetryableError, "attempt 3"):
            q.result(jid)

    async def test_max_delay_caps_backoff(self):
        flaky = Flaky(3)
        q = JobQueue(workers=1, max_attempts=4, base_delay=0.01, backoff=100, max_delay=0.02)
        start = time.monotonic()
        jid = q.submit("flaky", flaky)
        await q.join()
        self.assertEqual(q.result(jid), "ok")
        self.assertLess(time.monotonic() - start, 0.5)

    async def test_retryable_subclass(self):
        class Transient(RetryableError):
            pass

        calls = 0

        async def job():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise Transient()
            return calls

        q = JobQueue(workers=1, max_attempts=2, base_delay=0)
        jid = q.submit("j", job)
        await q.join()
        self.assertEqual(q.result(jid), 2)


class ShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_summary(self):
        q = JobQueue(workers=2, timeout=0.1, max_attempts=1)
        q.submit("ok", echo, 1, 0.05)
        q.submit("slow", echo, 2, 1)
        q.submit("waiting1", echo, 3)
        q.submit("waiting2", boom)
        await asyncio.sleep(0)  # let the workers pick up the first two jobs
        summary = await q.shutdown()
        self.assertEqual(summary, Summary(succeeded=1, failed=0, timed_out=1, cancelled=2))

    async def test_shutdown_lets_running_jobs_finish(self):
        q = JobQueue(workers=1, timeout=1)
        running = q.submit("running", echo, "done", 0.05)
        waiting = q.submit("waiting", echo, "never")
        await asyncio.sleep(0.01)
        summary = await q.shutdown()
        self.assertEqual(q.result(running), "done")
        self.assertEqual(q.state(waiting), JobState.CANCELLED)
        with self.assertRaises(JobCancelledError):
            q.result(waiting)
        self.assertEqual(summary, Summary(succeeded=1, cancelled=1))

    async def test_shutdown_lets_retrying_job_finish(self):
        flaky = Flaky(1)
        q = JobQueue(workers=1, max_attempts=2, base_delay=0.05)
        jid = q.submit("flaky", flaky)
        await asyncio.sleep(0.01)  # first attempt failed, now in retry delay
        summary = await q.shutdown()
        self.assertEqual(q.result(jid), "ok")
        self.assertEqual(summary, Summary(succeeded=1))

    async def test_submit_after_shutdown(self):
        q = JobQueue(workers=1)
        await q.shutdown()
        with self.assertRaises(QueueClosedError):
            q.submit("late", echo, 1)

    async def test_shutdown_twice(self):
        q = JobQueue(workers=1)
        q.submit("j", echo, 1)
        first = await q.shutdown()
        self.assertEqual(await q.shutdown(), first)

    async def test_join_returns_after_shutdown_cancels(self):
        q = JobQueue(workers=1)
        q.submit("running", echo, 1, 0.05)
        q.submit("waiting", echo, 2)
        await asyncio.sleep(0.01)
        joiner = asyncio.create_task(q.join())
        await q.shutdown()
        await asyncio.wait_for(joiner, 1)


class InternalErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_internal_error_reported_by_join_and_shutdown(self):
        q = JobQueue(workers=1)
        original = q._process

        async def broken(job):
            if job.name == "bad":
                raise RuntimeError("queue bug")
            await original(job)

        q._process = broken
        bad = q.submit("bad", echo, 1)
        good = q.submit("good", echo, 2)
        with self.assertRaises(QueueInternalError) as ctx:
            await asyncio.wait_for(q.join(), 1)
        self.assertIn("queue bug", str(ctx.exception))
        with self.assertRaises(QueueInternalError) as ctx:
            await asyncio.wait_for(q.shutdown(), 1)
        self.assertEqual(q.state(bad), JobState.FAILED)
        self.assertEqual(q.result(good), 2)  # the worker survived
        self.assertEqual(ctx.exception.summary, Summary(succeeded=1, failed=1))

    async def test_dead_worker_does_not_hang_join(self):
        q = JobQueue(workers=1)
        q.submit("j", echo, 1, 0.5)
        await asyncio.sleep(0)
        q._worker_tasks[0].cancel()  # kill the only worker from outside
        with self.assertRaises(QueueInternalError):
            await asyncio.wait_for(q.join(), 1)
        with self.assertRaises(QueueInternalError):
            await asyncio.wait_for(q.shutdown(), 1)


if __name__ == "__main__":
    unittest.main()
