import asyncio
import logging
import time
import unittest

from jobqueue import (
    InternalQueueError,
    JobCancelledError,
    JobNotFinishedError,
    JobQueue,
    JobState,
    JobTimeoutError,
    QueueClosedError,
    RetryableError,
    Summary,
)


async def echo(value, delay=0.0):
    await asyncio.sleep(delay)
    return value


class WorkerKilled(BaseException):
    pass


async def boom(exc):
    raise exc


class BasicTests(unittest.IsolatedAsyncioTestCase):
    async def test_submit_join_result(self):
        q = JobQueue(workers=2)
        ids = [q.submit(f"j{i}", echo, i) for i in range(5)]
        await q.join()
        self.assertEqual([q.result(i) for i in ids], list(range(5)))
        self.assertTrue(all(q.status(i) is JobState.SUCCEEDED for i in ids))
        self.assertEqual(await q.shutdown(), Summary(succeeded=5))

    async def test_join_without_jobs(self):
        q = JobQueue()
        await q.join()
        self.assertEqual(await q.shutdown(), Summary())

    async def test_job_ids_unique(self):
        q = JobQueue(workers=1)
        ids = {q.submit("j", echo, None) for _ in range(10)}
        self.assertEqual(len(ids), 10)
        await q.shutdown()

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
        await q.shutdown()

    async def test_result_unknown_and_unfinished(self):
        q = JobQueue(workers=1)
        with self.assertRaises(KeyError):
            q.result(999)
        jid = q.submit("slow", echo, 1, 0.05)
        with self.assertRaises(JobNotFinishedError):
            q.result(jid)
        await q.join()
        self.assertEqual(q.result(jid), 1)
        await q.shutdown()

    async def test_join_can_be_called_repeatedly(self):
        q = JobQueue(workers=2)
        a = q.submit("a", echo, "a")
        await q.join()
        b = q.submit("b", echo, "b")
        await q.join()
        self.assertEqual((q.result(a), q.result(b)), ("a", "b"))
        await q.shutdown()

    async def test_failing_job_raises_its_error(self):
        q = JobQueue(workers=1)
        jid = q.submit("bad", boom, ValueError("nope"))
        await q.join()
        with self.assertRaisesRegex(ValueError, "nope"):
            q.result(jid)
        self.assertEqual(q.attempts(jid), 1)
        self.assertEqual(await q.shutdown(), Summary(failed=1))

    async def test_failure_does_not_stop_other_jobs(self):
        q = JobQueue(workers=1)
        bad = q.submit("bad", boom, KeyError("x"))
        good = q.submit("good", echo, 42)
        await q.join()
        self.assertEqual(q.status(bad), JobState.FAILED)
        self.assertEqual(q.result(good), 42)
        await q.shutdown()

    async def test_submit_requires_callable(self):
        q = JobQueue()
        with self.assertRaises(TypeError):
            q.submit("x", 123)


class TimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout(self):
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
        self.assertEqual(q.status(jid), "timed_out")
        with self.assertRaises(JobTimeoutError):
            q.result(jid)
        self.assertEqual(q.result(ok), "fine")
        self.assertEqual(await q.shutdown(), Summary(succeeded=1, timed_out=1))

    async def test_timeout_is_not_retried(self):
        calls = 0

        async def hang():
            nonlocal calls
            calls += 1
            await asyncio.sleep(10)

        q = JobQueue(workers=1, timeout=0.02, max_attempts=3, base_delay=0)
        jid = q.submit("hang", hang)
        await q.join()
        self.assertEqual(calls, 1)
        self.assertEqual(q.status(jid), JobState.TIMED_OUT)
        await q.shutdown()

    async def test_job_raising_timeout_error_itself_is_failed(self):
        q = JobQueue(workers=1, timeout=5)
        jid = q.submit("own", boom, TimeoutError("mine"))
        await q.join()
        self.assertEqual(q.status(jid), JobState.FAILED)
        with self.assertRaisesRegex(TimeoutError, "mine"):
            q.result(jid)
        await q.shutdown()

    async def test_no_timeout(self):
        q = JobQueue(workers=1, timeout=None)
        jid = q.submit("j", echo, 1, 0.01)
        await q.join()
        self.assertEqual(q.result(jid), 1)
        await q.shutdown()


class RetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_then_succeed_with_growing_delay(self):
        stamps = []

        async def flaky():
            stamps.append(time.monotonic())
            if len(stamps) < 4:
                raise RetryableError("again")
            return "done"

        q = JobQueue(workers=1, max_attempts=5, base_delay=0.02, backoff=2)
        jid = q.submit("flaky", flaky)
        await q.join()
        self.assertEqual(q.result(jid), "done")
        self.assertEqual(q.attempts(jid), 4)
        gaps = [b - a for a, b in zip(stamps, stamps[1:])]
        for gap, expected in zip(gaps, [0.02, 0.04, 0.08]):
            self.assertGreaterEqual(gap, expected * 0.9)
        self.assertLess(gaps[0], gaps[1])
        self.assertLess(gaps[1], gaps[2])
        await q.shutdown()

    async def test_retry_exhausted(self):
        calls = 0

        async def always():
            nonlocal calls
            calls += 1
            raise RetryableError(f"attempt {calls}")

        q = JobQueue(workers=1, max_attempts=3, base_delay=0.001)
        jid = q.submit("always", always)
        await q.join()
        self.assertEqual(calls, 3)
        with self.assertRaisesRegex(RetryableError, "attempt 3"):
            q.result(jid)
        self.assertEqual(await q.shutdown(), Summary(failed=1))

    async def test_retryable_subclass(self):
        class Flaky(RetryableError):
            pass

        calls = 0

        async def job():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise Flaky()
            return calls

        q = JobQueue(workers=1, base_delay=0)
        jid = q.submit("j", job)
        await q.join()
        self.assertEqual(q.result(jid), 2)
        await q.shutdown()

    async def test_non_retryable_not_retried(self):
        calls = 0

        async def job():
            nonlocal calls
            calls += 1
            raise RuntimeError("fatal")

        q = JobQueue(workers=1, max_attempts=5, base_delay=0)
        q.submit("j", job)
        await q.join()
        self.assertEqual(calls, 1)
        await q.shutdown()

    def test_delay_schedule(self):
        q = JobQueue(base_delay=0.1, backoff=3, max_delay=0.5)
        self.assertEqual(
            [round(q._retry_delay(n), 6) for n in (1, 2, 3, 4)],
            [0.1, 0.3, 0.5, 0.5],
        )

    async def test_max_attempts_one_disables_retry(self):
        calls = 0

        async def job():
            nonlocal calls
            calls += 1
            raise RetryableError()

        q = JobQueue(workers=1, max_attempts=1)
        q.submit("j", job)
        await q.join()
        self.assertEqual(calls, 1)
        await q.shutdown()


class ShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_cancels_waiting_and_finishes_running(self):
        started = asyncio.Event()

        async def slow():
            started.set()
            await asyncio.sleep(0.05)
            return "slow"

        q = JobQueue(workers=1)
        running = q.submit("slow", slow)
        waiting = [q.submit(f"w{i}", echo, i) for i in range(3)]
        await started.wait()
        summary = await q.shutdown()
        self.assertEqual(summary, Summary(succeeded=1, cancelled=3))
        self.assertEqual(q.result(running), "slow")
        for jid in waiting:
            self.assertEqual(q.status(jid), JobState.CANCELLED)
            with self.assertRaises(JobCancelledError):
                q.result(jid)

    async def test_submit_after_shutdown(self):
        q = JobQueue()
        await q.shutdown()
        with self.assertRaises(QueueClosedError):
            q.submit("late", echo, 1)

    async def test_shutdown_idempotent(self):
        q = JobQueue(workers=1)
        q.submit("a", echo, 1)
        await q.join()
        first = await q.shutdown()
        self.assertEqual(first, await q.shutdown())

    async def test_shutdown_summary_mixed(self):
        async def hang():
            await asyncio.sleep(10)

        q = JobQueue(workers=4, timeout=0.05, max_attempts=2, base_delay=0)
        q.submit("ok", echo, 1)
        q.submit("bad", boom, ValueError())
        q.submit("retry", boom, RetryableError())
        q.submit("hang", hang)
        await q.join()
        self.assertEqual(
            await q.shutdown(), Summary(succeeded=1, failed=2, timed_out=1)
        )

    async def test_shutdown_waits_for_job_in_retry(self):
        calls = 0

        async def flaky():
            nonlocal calls
            calls += 1
            if calls < 3:
                raise RetryableError()
            return "ok"

        q = JobQueue(workers=1, max_attempts=3, base_delay=0.02)
        jid = q.submit("flaky", flaky)
        await asyncio.sleep(0.005)
        await q.shutdown()
        self.assertEqual(q.result(jid), "ok")

    async def test_workers_stopped_after_shutdown(self):
        q = JobQueue(workers=3)
        q.submit("a", echo, 1)
        await q.shutdown()
        self.assertEqual(q._worker_tasks, set())


class InternalErrorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        logging.getLogger("jobqueue.queue").disabled = True

    def tearDown(self):
        logging.getLogger("jobqueue.queue").disabled = False

    async def test_internal_error_reported_by_join_and_shutdown(self):
        q = JobQueue(workers=1)
        original = q._run_job
        calls = 0

        async def broken(job):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ZeroDivisionError("queue bug")
            await original(job)

        q._run_job = broken
        bad = q.submit("a", echo, 1)
        good = q.submit("b", echo, 2)
        with self.assertRaises(InternalQueueError) as cm:
            await asyncio.wait_for(q.join(), 2)
        self.assertIsInstance(cm.exception.errors[0], ZeroDivisionError)
        self.assertEqual(q.status(bad), JobState.FAILED)

        with self.assertRaises(InternalQueueError) as cm:
            await asyncio.wait_for(q.shutdown(), 2)
        self.assertEqual(cm.exception.summary, Summary(succeeded=1, failed=1))
        self.assertEqual(q.result(good), 2)

    async def test_dead_worker_is_reported_and_replaced(self):
        q = JobQueue(workers=1)
        original = q._run_job
        calls = 0

        async def fatal(job):
            nonlocal calls
            calls += 1
            if calls == 1:
                # Not an Exception subclass: escapes the worker's handler
                # and kills the worker task.
                raise WorkerKilled("worker killed")
            await original(job)

        q._run_job = fatal
        killed = q.submit("a", echo, 1)
        after = q.submit("b", echo, 2)
        with self.assertRaises(InternalQueueError) as cm:
            await asyncio.wait_for(q.join(), 2)
        self.assertIsInstance(cm.exception.errors[0], WorkerKilled)

        # The replacement worker keeps processing jobs.
        with self.assertRaises(InternalQueueError):
            await asyncio.wait_for(q.shutdown(), 2)
        self.assertEqual(q.status(killed), JobState.FAILED)
        self.assertEqual(q.result(after), 2)


class SettingsTests(unittest.IsolatedAsyncioTestCase):
    def test_invalid_settings(self):
        for kwargs in (
            {"workers": 0},
            {"timeout": 0},
            {"max_attempts": 0},
            {"base_delay": -1},
            {"backoff": 0.5},
            {"max_delay": -1},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                JobQueue(**kwargs)

    async def test_queues_are_independent(self):
        async def hang():
            await asyncio.sleep(10)

        fast = JobQueue(workers=1, timeout=0.02)
        patient = JobQueue(workers=1, timeout=1)
        a = fast.submit("a", echo, 1, 0.05)
        b = patient.submit("b", echo, 1, 0.05)
        await asyncio.gather(fast.join(), patient.join())
        self.assertEqual(fast.status(a), JobState.TIMED_OUT)
        self.assertEqual(patient.status(b), JobState.SUCCEEDED)
        await fast.shutdown()
        await patient.shutdown()


if __name__ == "__main__":
    unittest.main()
