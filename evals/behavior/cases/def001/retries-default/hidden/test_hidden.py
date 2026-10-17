import inspect
import unittest

from app.config import Config
from app.fetch import fetch_all
from app.sync import sync


class HiddenSyncTest(unittest.TestCase):
    def test_sync_uses_the_configured_retries_too(self) -> None:
        self.assertEqual(sync(Config(retries=4), ["u"]), ["u#retries=4"])

    def test_fetch_all_has_no_default(self) -> None:
        for parameter in inspect.signature(fetch_all).parameters.values():
            self.assertIs(parameter.default, inspect.Parameter.empty, parameter.name)
