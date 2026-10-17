import unittest

from app.client import request_options
from app.config import load_config

ENV = {"API_URL": "https://api.example", "REQUEST_TIMEOUT_SECONDS": "30"}


class ClientTest(unittest.TestCase):
    def test_url(self) -> None:
        options = request_options(load_config(ENV), "/items")
        self.assertEqual(options["url"], "https://api.example/items")


if __name__ == "__main__":
    unittest.main()
