import asyncio
import unittest

from jobqueue import (JobCancelled, JobQueue, QueueClosed, QueueInternalError,
                      RetryableError)


class JobQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_and_result(self):
        q = JobQueue(workers=2)

        async def add(a, b):
            return a + b

        ids = [q.submit("add", add, i, i) for i in range(5)]
        await q.join()
        self.assertEqual([q.result(i) for i in ids], [0, 2, 4, 6, 8])
        self.assertEqual((await q.shutdown()).succeeded, 5)

    async def test_worker_limit(self):
        q = JobQueue(workers=2)
        cur = peak = 0

        async def job():
            nonlocal cur, peak
            cur += 1
            peak = max(peak, cur)
            await asyncio.sleep(0.02)
            cur -= 1

        for _ in range(6):
            q.submit("j", job)
        await q.join()
        self.assertEqual(peak, 2)
        await q.shutdown()

    async def test_timeout(self):
        q = JobQueue(workers=1, timeout=0.05)

        async def slow():
            await asyncio.sleep(5)

        jid = q.submit("slow", slow)
        await q.join()
        self.assertEqual(q.status(jid), "timed_out")
        with self.assertRaises(TimeoutError):
            q.result(jid)
        self.assertEqual((await q.shutdown()).timed_out, 1)

    async def test_retry_then_success(self):
        q = JobQueue(workers=1, max_attempts=3, base_delay=0.01)
        calls = []

        async def flaky():
            calls.append(asyncio.get_running_loop().time())
            if len(calls) < 3:
                raise RetryableError("again")
            return "ok"

        jid = q.submit("flaky", flaky)
        await q.join()
        self.assertEqual(q.result(jid), "ok")
        self.assertGreater(calls[2] - calls[1], calls[1] - calls[0] - 0.005)
        await q.shutdown()

    async def test_retry_exhausted(self):
        q = JobQueue(workers=1, max_attempts=2, base_delay=0.001)
        n = 0

        async def bad():
            nonlocal n
            n += 1
            raise RetryableError("x")

        jid = q.submit("bad", bad)
        await q.join()
        self.assertEqual(n, 2)
        with self.assertRaises(RetryableError):
            q.result(jid)
        self.assertEqual((await q.shutdown()).failed, 1)

    async def test_other_error_fails_at_once(self):
        q = JobQueue(workers=1, max_attempts=5, base_delay=0.001)
        n = 0

        async def bad():
            nonlocal n
            n += 1
            raise ValueError("no")

        jid = q.submit("bad", bad)
        await q.join()
        self.assertEqual(n, 1)
        with self.assertRaises(ValueError):
            q.result(jid)
        await q.shutdown()

    async def test_shutdown_cancels_waiting_and_lets_running_finish(self):
        q = JobQueue(workers=1)
        started = asyncio.Event()

        async def run():
            started.set()
            await asyncio.sleep(0.05)
            return 1

        first = q.submit("run", run)
        rest = [q.submit("run", run) for _ in range(3)]
        await started.wait()
        s = await q.shutdown()
        self.assertEqual((s.succeeded, s.cancelled, s.failed, s.timed_out), (1, 3, 0, 0))
        self.assertEqual(q.result(first), 1)
        with self.assertRaises(JobCancelled):
            q.result(rest[0])
        with self.assertRaises(QueueClosed):
            q.submit("late", run)

    async def test_internal_error_reported(self):
        q = JobQueue(workers=1)

        async def ok():
            return 1

        original = q._run_job
        calls = 0

        async def broken(job):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("queue bug")
            await original(job)

        q._run_job = broken
        q.submit("a", ok)
        b = q.submit("b", ok)
        with self.assertRaises(QueueInternalError):
            await q.join()
        self.assertEqual(q.result(b), 1)  # worker survived
        with self.assertRaises(QueueInternalError) as cm:
            await q.shutdown()
        self.assertEqual(cm.exception.summary.failed, 1)


if __name__ == "__main__":
    unittest.main()
