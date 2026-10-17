import unittest

from app.config import Config
from app.sync import resync


class SyncTest(unittest.TestCase):
    def test_resync_uses_the_configured_retries(self) -> None:
        self.assertEqual(resync(Config(retries=3), ["u"]), ["u#retries=3"])


if __name__ == "__main__":
    unittest.main()
