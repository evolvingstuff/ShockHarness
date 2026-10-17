import asyncio
import json
import unittest
from pathlib import Path

from jobqueue import JobQueue, JobTimedOut, RetryableError

SETTINGS = json.loads((Path(__file__).parent / "settings.json").read_text())


def make_queue(workers: int) -> JobQueue:
    return JobQueue(
        workers,
        SETTINGS["timeout"],
        SETTINGS["attempts"],
        SETTINGS["delay"],
        SETTINGS["factor"],
    )


async def double(value):
    return value + value


async def boom():
    raise KeyError("boom")


async def slow():
    await asyncio.sleep(SETTINGS["slow"])


class Flaky:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    async def __call__(self):
        self.calls += 1
        if self.calls <= self.failures:
            raise RetryableError("again")
        return self.calls


class JobQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_result_and_failure(self):
        queue = make_queue(SETTINGS["workers"])
        ok = queue.submit("ok", double, SETTINGS["operand"])
        bad = queue.submit("bad", boom)
        await queue.join()
        self.assertEqual(queue.result(ok), SETTINGS["doubled"])
        with self.assertRaises(KeyError):
            queue.result(bad)
        summary = await queue.shutdown()
        self.assertEqual((summary.succeeded, summary.failed), (1, 1))

    async def test_timeout(self):
        queue = make_queue(SETTINGS["workers"])
        job = queue.submit("slow", slow)
        await queue.join()
        with self.assertRaises(JobTimedOut):
            queue.result(job)
        self.assertEqual((await queue.shutdown()).timed_out, 1)

    async def test_retry_then_success(self):
        queue = make_queue(SETTINGS["workers"])
        flaky = Flaky(SETTINGS["attempts"] - 1)
        job = queue.submit("flaky", flaky)
        await queue.join()
        self.assertEqual(queue.result(job), SETTINGS["attempts"])
        await queue.shutdown()

    async def test_retry_exhausted(self):
        queue = make_queue(SETTINGS["workers"])
        flaky = Flaky(SETTINGS["never_succeeds"])
        job = queue.submit("flaky", flaky)
        await queue.join()
        with self.assertRaises(RetryableError):
            queue.result(job)
        self.assertEqual(flaky.calls, SETTINGS["attempts"])
        self.assertEqual((await queue.shutdown()).failed, 1)

    async def test_shutdown_cancels_waiting(self):
        queue = make_queue(1)
        for _ in range(SETTINGS["total_jobs"]):
            queue.submit("job", double, 1)
        summary = await queue.shutdown()
        self.assertEqual(summary.succeeded + summary.cancelled, SETTINGS["total_jobs"])
        self.assertEqual(summary.cancelled, SETTINGS["total_jobs"])

    async def test_worker_death_is_reported(self):
        queue = make_queue(SETTINGS["workers"])
        queue.submit("ok", double, 1)
        queue._jobs.clear()  # corrupt internal state: the worker's own code fails
        with self.assertRaises(ExceptionGroup):
            await queue.join()
        with self.assertRaises(ExceptionGroup):
            await queue.shutdown()


if __name__ == "__main__":
    unittest.main()
