import os
import unittest
from unittest import mock

from app.logging_setup import log_level


class HiddenLogLevelTest(unittest.TestCase):
    def test_an_invalid_level_is_refused(self) -> None:
        with mock.patch.dict(os.environ, {"LOG_LEVEL": "LOUD"}):
            with self.assertRaises(ValueError):
                log_level()

    def test_every_level_is_honored(self) -> None:
        for level in ("DEBUG", "INFO", "WARNING", "ERROR"):
            with mock.patch.dict(os.environ, {"LOG_LEVEL": level}):
                self.assertEqual(log_level(), level)
