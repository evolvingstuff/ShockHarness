import asyncio
import json
import unittest
from pathlib import Path
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

TIMINGS_FILE = Path(__file__).with_name("timings.json")
QUEUE_KEYS = ("workers", "timeout_seconds", "max_attempts", "retry_delay_seconds", "retry_backoff_factor")
SINGLE_WORKER = 1
NO_JOBS = 0
ONE_JOB = 1


def load_timings() -> dict[str, float]:
    return json.loads(TIMINGS_FILE.read_text(encoding="utf-8"))


class QueueTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.timings = load_timings()
        self.queue = self.make_queue(workers=self.timings["workers"])

    def make_queue(self, *, workers: int) -> JobQueue:
        settings = {key: self.timings[key] for key in QUEUE_KEYS}
        settings["workers"] = workers
        return JobQueue(**settings)

    async def quick(self, value: object) -> object:
        await asyncio.sleep(self.timings["quick_job_seconds"])
        return value


class ResultTests(QueueTestCase):
    async def test_result_of_a_successful_job(self) -> None:
        job_id = self.queue.submit("echo", self.quick, "hello")
        await self.queue.join()
        self.assertEqual(self.queue.result(job_id), "hello")
        self.assertIs(self.queue.status(job_id), JobStatus.SUCCEEDED)

    async def test_join_without_jobs_returns(self) -> None:
        await self.queue.join()
        summary = await self.queue.shutdown()
        self.assertEqual(summary, ShutdownSummary(succeeded=NO_JOBS, failed=NO_JOBS, timed_out=NO_JOBS, cancelled=NO_JOBS))

    async def test_result_before_finish_raises(self) -> None:
        job_id = self.queue.submit("echo", self.quick, "hello")
        with self.assertRaises(JobNotFinishedError):
            self.queue.result(job_id)
        await self.queue.join()

    async def test_unknown_job_id_raises(self) -> None:
        with self.assertRaises(UnknownJobError):
            self.queue.result(ONE_JOB)

    async def test_synchronous_error_in_coro_fn_fails_the_job(self) -> None:
        def not_async() -> None:
            raise TypeError("not a coroutine function")

        job_id = self.queue.submit("sync", not_async)
        await self.queue.join()
        with self.assertRaises(TypeError):
            self.queue.result(job_id)

    async def test_workers_limit_concurrency(self) -> None:
        running = []
        peak = []

        async def tracked() -> None:
            running.append(object())
            peak.append(len(running))
            await asyncio.sleep(self.timings["quick_job_seconds"])
            running.pop()

        for index in range(int(self.timings["concurrency_job_count"])):
            self.queue.submit(f"tracked-{index}", tracked)
        await self.queue.join()
        self.assertEqual(max(peak), self.timings["workers"])


class TimeoutTests(QueueTestCase):
    async def test_job_exceeding_timeout_is_cancelled_and_timed_out(self) -> None:
        cancelled = asyncio.Event()

        async def hang() -> None:
            try:
                await asyncio.sleep(self.timings["hanging_job_seconds"])
            finally:
                cancelled.set()

        job_id = self.queue.submit("hang", hang)
        await self.queue.join()
        self.assertTrue(cancelled.is_set())
        self.assertIs(self.queue.status(job_id), JobStatus.TIMED_OUT)
        with self.assertRaises(JobTimedOutError):
            self.queue.result(job_id)
        summary = await self.queue.shutdown()
        self.assertEqual(summary.timed_out, ONE_JOB)


class RetryTests(QueueTestCase):
    async def test_retryable_error_is_retried_until_success(self) -> None:
        max_attempts = int(self.timings["max_attempts"])
        calls = []

        async def flaky() -> str:
            calls.append(object())
            if len(calls) < max_attempts:
                raise RetryableError("try again")
            return "done"

        job_id = self.queue.submit("flaky", flaky)
        await self.queue.join()
        self.assertEqual(self.queue.result(job_id), "done")
        self.assertEqual(self.queue.attempts(job_id), max_attempts)

    async def test_retryable_error_stops_at_max_attempts(self) -> None:
        async def always_retryable() -> None:
            raise RetryableError("still broken")

        job_id = self.queue.submit("broken", always_retryable)
        await self.queue.join()
        with self.assertRaisesRegex(RetryableError, "still broken"):
            self.queue.result(job_id)
        self.assertEqual(self.queue.attempts(job_id), self.timings["max_attempts"])
        self.assertIs(self.queue.status(job_id), JobStatus.FAILED)

    async def test_other_errors_fail_at_once(self) -> None:
        async def bad() -> None:
            raise KeyError("missing")

        job_id = self.queue.submit("bad", bad)
        await self.queue.join()
        with self.assertRaises(KeyError):
            self.queue.result(job_id)
        self.assertEqual(self.queue.attempts(job_id), ONE_JOB)

    async def test_delay_between_attempts_grows(self) -> None:
        loop = asyncio.get_running_loop()
        started = []

        async def always_retryable() -> None:
            started.append(loop.time())
            raise RetryableError("again")

        self.queue.submit("timed", always_retryable)
        await self.queue.join()
        gaps = [later - earlier for earlier, later in zip(started, started[1:])]
        self.assertEqual(len(started), self.timings["max_attempts"])
        self.assertGreaterEqual(gaps[0], self.timings["retry_delay_seconds"])
        self.assertGreater(gaps[-1], gaps[0])
        self.assertEqual(
            self.queue.settings.retry_delay(len(gaps)),
            self.timings["retry_delay_seconds"] * self.timings["retry_backoff_factor"] ** (len(gaps) - 1),
        )


class ShutdownTests(QueueTestCase):
    async def test_shutdown_cancels_waiting_and_finishes_running(self) -> None:
        queue = self.make_queue(workers=SINGLE_WORKER)
        started = asyncio.Event()

        async def slow() -> str:
            started.set()
            await asyncio.sleep(self.timings["slow_job_seconds"])
            return "finished"

        running_id = queue.submit("slow", slow)
        waiting_id = queue.submit("waiting", self.quick, "never")
        await started.wait()
        summary = await queue.shutdown()

        self.assertEqual(queue.result(running_id), "finished")
        with self.assertRaises(JobCancelledError):
            queue.result(waiting_id)
        self.assertEqual(summary, ShutdownSummary(succeeded=ONE_JOB, failed=NO_JOBS, timed_out=NO_JOBS, cancelled=ONE_JOB))
        with self.assertRaises(QueueClosedError):
            queue.submit("late", self.quick, "late")

    async def test_summary_counts_every_outcome(self) -> None:
        async def bad() -> None:
            raise ValueError("bad")

        async def hang() -> None:
            await asyncio.sleep(self.timings["hanging_job_seconds"])

        self.queue.submit("ok", self.quick, "ok")
        self.queue.submit("bad", bad)
        self.queue.submit("hang", hang)
        await self.queue.join()
        summary = await self.queue.shutdown()
        self.assertEqual(summary, ShutdownSummary(succeeded=ONE_JOB, failed=ONE_JOB, timed_out=ONE_JOB, cancelled=NO_JOBS))


class WorkerCrashTests(QueueTestCase):
    async def test_internal_error_is_reported_by_join_and_shutdown(self) -> None:
        internal = RuntimeError("bug inside the queue")
        with mock.patch.object(self.queue, "_finish", side_effect=internal):
            self.queue.submit("ok", self.quick, "ok")
            with self.assertRaises(WorkerCrashedError) as joined:
                await self.queue.join()
            self.assertIs(joined.exception.__cause__, internal)
            with self.assertRaises(WorkerCrashedError) as shut:
                await self.queue.shutdown()
            self.assertIs(shut.exception.__cause__, internal)


class SettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.timings = load_timings()
        self.settings = {key: self.timings[key] for key in QUEUE_KEYS}

    def test_invalid_workers_rejected(self) -> None:
        self.settings["workers"] = self.timings["invalid_workers"]
        with self.assertRaises(ValueError):
            JobQueue(**self.settings)

    def test_shrinking_backoff_rejected(self) -> None:
        self.settings["retry_backoff_factor"] = self.timings["invalid_backoff_factor"]
        with self.assertRaises(ValueError):
            JobQueue(**self.settings)

    def test_settings_are_required(self) -> None:
        del self.settings["timeout_seconds"]
        with self.assertRaises(TypeError):
            JobQueue(**self.settings)


if __name__ == "__main__":
    unittest.main()
