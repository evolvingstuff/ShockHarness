import os
import unittest
from unittest import mock

from app.main import main


class MainTest(unittest.TestCase):
    def test_the_program_starts_without_retries(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(main({"API_URL": "https://api.example"}), 0)


if __name__ == "__main__":
    unittest.main()
