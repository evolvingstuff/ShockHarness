import unittest

from app.jobs import Job, wait_for


class JobsTest(unittest.TestCase):
    def test_a_quick_job_is_done(self) -> None:
        self.assertEqual(wait_for(Job("index", 0.5)), "done")


if __name__ == "__main__":
    unittest.main()
