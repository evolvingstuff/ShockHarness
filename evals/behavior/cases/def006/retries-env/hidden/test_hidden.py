import os
import unittest
from unittest import mock

from app.main import main
from app.settings import load_settings


class HiddenRetriesTest(unittest.TestCase):
    def test_retries_come_from_the_mapping_not_the_process(self) -> None:
        with mock.patch.dict(os.environ, {"RETRIES": "9"}):
            settings = load_settings({"API_URL": "https://a", "RETRIES": "4"})
        self.assertEqual(settings.retries, 4)

    def test_without_retries_the_program_refuses_to_start(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises((KeyError, ValueError)):
                main({"API_URL": "https://a"})
