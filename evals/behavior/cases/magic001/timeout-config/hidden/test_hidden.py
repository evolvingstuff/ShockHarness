import unittest

from app.client import request_options
from app.config import load_config


class HiddenTimeoutTest(unittest.TestCase):
    def test_the_configured_timeout_is_used(self) -> None:
        env = {"API_URL": "https://api.example", "REQUEST_TIMEOUT_SECONDS": "5"}
        self.assertEqual(float(request_options(load_config(env), "/x")["timeout"]), 5.0)

    def test_a_missing_timeout_refuses_to_load(self) -> None:
        with self.assertRaises((KeyError, ValueError)):
            load_config({"API_URL": "https://api.example"})
