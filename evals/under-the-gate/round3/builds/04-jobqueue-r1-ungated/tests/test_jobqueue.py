import asyncio
import time
import unittest

from jobqueue import (
    JobCancelledError,
    JobNotFinishedError,
    JobQueue,
    JobStatus,
    JobTimeoutError,
    QueueClosedError,
    QueueInternalError,
    RetryableError,
    Summary,
)


async def echo(value, delay=0.0):
    await asyncio.sleep(delay)
    return value


async def boom(message):
    raise ValueError(message)


class BasicTests(unittest.IsolatedAsyncioTestCase):
    async def test_runs_jobs_and_returns_results(self):
        q = JobQueue(workers=2)
        ids = [q.submit(f"job{i}", echo, i) for i in range(5)]
        await q.join()
        self.assertEqual([q.result(i) for i in ids], list(range(5)))
        self.assertEqual(await q.shutdown(), Summary(succeeded=5))

    async def test_job_ids_are_unique(self):
        q = JobQueue(workers=1)
        ids = {q.submit("j", echo, i) for i in range(10)}
        self.assertEqual(len(ids), 10)
        await q.shutdown()

    async def test_join_with_no_jobs_returns(self):
        q = JobQueue()
        await asyncio.wait_for(q.join(), 1)

    async def test_failing_job_raises_its_error(self):
        q = JobQueue(workers=1)
        jid = q.submit("bad", boom, "nope")
        await q.join()
        with self.assertRaisesRegex(ValueError, "nope"):
            q.result(jid)
        self.assertEqual(q.status(jid), JobStatus.FAILED)
        self.assertEqual(q.attempts(jid), 1)

    async def test_result_of_unfinished_job(self):
        q = JobQueue(workers=1)
        jid = q.submit("slow", echo, 1, 0.2)
        with self.assertRaises(JobNotFinishedError):
            q.result(jid)
        await q.join()
        self.assertEqual(q.result(jid), 1)

    async def test_result_of_unknown_job(self):
        q = JobQueue()
        with self.assertRaises(KeyError):
            q.result(12345)

    async def test_worker_count_limits_concurrency(self):
        running = 0
        peak = 0

        async def track():
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.02)
            running -= 1

        q = JobQueue(workers=3)
        for _ in range(10):
            q.submit("t", track)
        await q.join()
        self.assertEqual(peak, 3)

    async def test_jobs_run_concurrently(self):
        q = JobQueue(workers=5)
        start = time.monotonic()
        for i in range(5):
            q.submit("s", echo, i, 0.1)
        await q.join()
        self.assertLess(time.monotonic() - start, 0.3)

    async def test_join_can_be_called_repeatedly(self):
        q = JobQueue(workers=2)
        a = q.submit("a", echo, "a")
        await q.join()
        b = q.submit("b", echo, "b")
        await q.join()
        self.assertEqual((q.result(a), q.result(b)), ("a", "b"))

    async def test_non_coroutine_callable_fails_job_not_worker(self):
        q = JobQueue(workers=1)
        bad = q.submit("bad", lambda: 42)
        good = q.submit("good", echo, "ok")
        await q.join()
        with self.assertRaises(TypeError):
            q.result(bad)
        self.assertEqual(q.result(good), "ok")

    def test_invalid_settings(self):
        for kwargs in (
            {"workers": 0},
            {"timeout": 0},
            {"max_attempts": 0},
            {"retry_delay": -1},
            {"backoff": 0.5},
            {"max_delay": -1},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                JobQueue(**kwargs)

    async def test_queues_are_independent(self):
        fast = JobQueue(workers=1, timeout=0.05)
        slow = JobQueue(workers=1, timeout=1)
        a = fast.submit("a", echo, "a", 0.1)
        b = slow.submit("b", echo, "b", 0.1)
        await fast.join()
        await slow.join()
        self.assertEqual(fast.status(a), JobStatus.TIMED_OUT)
        self.assertEqual(slow.result(b), "b")


class TimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_job_exceeding_timeout_is_cancelled(self):
        cancelled = asyncio.Event()

        async def hang():
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        q = JobQueue(workers=1, timeout=0.05)
        jid = q.submit("hang", hang)
        after = q.submit("after", echo, "fine")
        await asyncio.wait_for(q.join(), 2)
        self.assertTrue(cancelled.is_set())
        self.assertEqual(q.status(jid), JobStatus.TIMED_OUT)
        with self.assertRaises(JobTimeoutError):
            q.result(jid)
        with self.assertRaises(TimeoutError):
            q.result(jid)
        self.assertEqual(q.result(after), "fine")
        self.assertEqual(await q.shutdown(), Summary(succeeded=1, timed_out=1))

    async def test_job_raising_its_own_timeout_error_is_a_failure(self):
        async def own_timeout():
            raise TimeoutError("mine")

        q = JobQueue(workers=1, timeout=5)
        jid = q.submit("own", own_timeout)
        await q.join()
        self.assertEqual(q.status(jid), JobStatus.FAILED)
        with self.assertRaisesRegex(TimeoutError, "mine"):
            q.result(jid)

    async def test_timed_out_job_is_not_retried(self):
        q = JobQueue(workers=1, timeout=0.03, max_attempts=5, retry_delay=0)
        jid = q.submit("hang", echo, None, 1)
        await q.join()
        self.assertEqual(q.attempts(jid), 1)

    async def test_no_timeout(self):
        q = JobQueue(workers=1, timeout=None)
        jid = q.submit("j", echo, 7, 0.05)
        await q.join()
        self.assertEqual(q.result(jid), 7)


class RetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_retryable_error_is_retried_until_success(self):
        calls = []

        async def flaky():
            calls.append(time.monotonic())
            if len(calls) < 3:
                raise RetryableError("try again")
            return "done"

        q = JobQueue(workers=1, max_attempts=5, retry_delay=0.02, backoff=2)
        jid = q.submit("flaky", flaky)
        await q.join()
        self.assertEqual(q.result(jid), "done")
        self.assertEqual(q.attempts(jid), 3)
        gaps = [b - a for a, b in zip(calls, calls[1:])]
        self.assertGreaterEqual(gaps[0], 0.02 * 0.9)
        self.assertGreaterEqual(gaps[1], 0.04 * 0.9)
        self.assertGreater(gaps[1], gaps[0])

    async def test_retries_stop_at_max_attempts(self):
        calls = 0

        async def always():
            nonlocal calls
            calls += 1
            raise RetryableError(f"attempt {calls}")

        q = JobQueue(workers=1, max_attempts=3, retry_delay=0.001)
        jid = q.submit("always", always)
        await q.join()
        self.assertEqual(calls, 3)
        self.assertEqual(q.status(jid), JobStatus.FAILED)
        with self.assertRaisesRegex(RetryableError, "attempt 3"):
            q.result(jid)

    async def test_subclass_of_retryable_error_is_retried(self):
        class Flaky(RetryableError):
            pass

        calls = 0

        async def job():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise Flaky()
            return calls

        q = JobQueue(workers=1, retry_delay=0)
        jid = q.submit("j", job)
        await q.join()
        self.assertEqual(q.result(jid), 2)

    async def test_other_errors_are_not_retried(self):
        calls = 0

        async def job():
            nonlocal calls
            calls += 1
            raise KeyError("x")

        q = JobQueue(workers=1, max_attempts=5, retry_delay=0)
        jid = q.submit("j", job)
        await q.join()
        self.assertEqual(calls, 1)
        with self.assertRaises(KeyError):
            q.result(jid)

    def test_delay_grows_and_is_capped(self):
        q = JobQueue(retry_delay=0.1, backoff=3, max_delay=0.5)
        delays = [q._retry_delay(n) for n in range(1, 5)]
        self.assertAlmostEqual(delays[0], 0.1)
        self.assertAlmostEqual(delays[1], 0.3)
        self.assertEqual(delays[2:], [0.5, 0.5])

    async def test_timeout_applies_per_attempt(self):
        calls = 0

        async def job():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RetryableError()
            await asyncio.sleep(1)

        q = JobQueue(workers=1, timeout=0.05, retry_delay=0)
        jid = q.submit("j", job)
        await q.join()
        self.assertEqual(calls, 2)
        self.assertEqual(q.status(jid), JobStatus.TIMED_OUT)


class ShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_cancels_waiting_and_finishes_running(self):
        started = asyncio.Event()

        async def running():
            started.set()
            await asyncio.sleep(0.1)
            return "finished"

        q = JobQueue(workers=1)
        r = q.submit("running", running)
        waiting = [q.submit("waiting", echo, i) for i in range(3)]
        await started.wait()
        summary = await asyncio.wait_for(q.shutdown(), 2)
        self.assertEqual(summary, Summary(succeeded=1, cancelled=3))
        self.assertEqual(q.result(r), "finished")
        for jid in waiting:
            self.assertEqual(q.status(jid), JobStatus.CANCELLED)
            with self.assertRaises(JobCancelledError):
                q.result(jid)

    async def test_summary_counts_every_outcome(self):
        gate = asyncio.Event()

        async def blocker():
            await gate.wait()
            return 1

        q = JobQueue(workers=4, timeout=0.05, max_attempts=2, retry_delay=0)

        async def retry_fail():
            raise RetryableError()

        q.submit("ok", echo, 1)
        q.submit("fail", boom, "x")
        q.submit("retry", retry_fail)
        q.submit("timeout", echo, None, 1)
        await q.join()
        q2 = JobQueue(workers=1)
        q2.submit("block", blocker)
        q2.submit("w1", echo, 1)
        q2.submit("w2", echo, 2)
        await asyncio.sleep(0.01)
        shutdown = asyncio.ensure_future(q2.shutdown())
        await asyncio.sleep(0.01)
        gate.set()
        self.assertEqual(await shutdown, Summary(succeeded=1, cancelled=2))
        self.assertEqual(
            await q.shutdown(), Summary(succeeded=1, failed=2, timed_out=1)
        )

    async def test_submit_after_shutdown_is_rejected(self):
        q = JobQueue()
        q.submit("a", echo, 1)
        await q.shutdown()
        with self.assertRaises(QueueClosedError):
            q.submit("b", echo, 2)

    async def test_shutdown_twice_and_without_jobs(self):
        q = JobQueue()
        self.assertEqual(await q.shutdown(), Summary())
        self.assertEqual(await q.shutdown(), Summary())

    async def test_shutdown_lets_retrying_job_finish(self):
        calls = 0

        async def flaky():
            nonlocal calls
            calls += 1
            if calls < 3:
                raise RetryableError()
            return "ok"

        q = JobQueue(workers=1, retry_delay=0.02)
        jid = q.submit("flaky", flaky)
        await asyncio.sleep(0.005)
        summary = await q.shutdown()
        self.assertEqual(summary, Summary(succeeded=1))
        self.assertEqual(q.result(jid), "ok")

    async def test_join_returns_after_shutdown(self):
        q = JobQueue(workers=1)
        q.submit("a", echo, 1, 0.05)
        q.submit("b", echo, 2)
        await asyncio.sleep(0)
        await q.shutdown()
        await asyncio.wait_for(q.join(), 1)


class InternalErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_error_in_queue_code_is_reported_by_join_and_shutdown(self):
        q = JobQueue(workers=2)
        original = q._record

        def broken_record(job, status, **kw):
            if job.name == "victim":
                raise RuntimeError("bookkeeping bug")
            original(job, status, **kw)

        q._record = broken_record
        victim = q.submit("victim", echo, 1)
        others = [q.submit("other", echo, i) for i in range(4)]
        with self.assertRaises(QueueInternalError) as cm:
            await asyncio.wait_for(q.join(), 2)
        self.assertIn("bookkeeping bug", str(cm.exception))
        self.assertIsInstance(cm.exception.errors[0], RuntimeError)
        # The worker survived and the other jobs still ran.
        self.assertEqual([q.result(j) for j in others], [0, 1, 2, 3])
        self.assertEqual(q.status(victim), JobStatus.FAILED)
        with self.assertRaises(QueueInternalError) as cm:
            await q.shutdown()
        self.assertEqual(cm.exception.summary, Summary(succeeded=4, failed=1))

    async def test_dead_worker_is_reported_and_join_does_not_hang(self):
        q = JobQueue(workers=1)
        gate = asyncio.Event()

        async def blocker():
            await gate.wait()

        q.submit("block", blocker)
        q.submit("waiting", echo, 1)
        await asyncio.sleep(0.01)
        q._worker_tasks[0].cancel()
        with self.assertRaises(QueueInternalError):
            await asyncio.wait_for(q.join(), 2)
        with self.assertRaises(QueueInternalError) as cm:
            await asyncio.wait_for(q.shutdown(), 2)
        self.assertEqual(cm.exception.summary.cancelled, 2)

    async def test_worker_crash_outside_job_is_reported(self):
        q = JobQueue(workers=1)

        async def crashing_worker():
            raise RuntimeError("worker crashed")

        q._worker = crashing_worker
        q.submit("never runs", echo, 1)
        with self.assertRaisesRegex(QueueInternalError, "worker crashed"):
            await asyncio.wait_for(q.join(), 2)
        with self.assertRaises(QueueInternalError):
            await q.shutdown()


if __name__ == "__main__":
    unittest.main()
