import os
import unittest
from unittest import mock

from app.logging_setup import log_level


class LogLevelTest(unittest.TestCase):
    def test_the_configured_level_is_used(self) -> None:
        with mock.patch.dict(os.environ, {"LOG_LEVEL": "WARNING"}):
            self.assertEqual(log_level(), "WARNING")


if __name__ == "__main__":
    unittest.main()
