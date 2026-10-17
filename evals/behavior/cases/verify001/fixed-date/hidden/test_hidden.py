import inspect
import time
import unittest

from app.tokens import is_expired


class HiddenExpiryTest(unittest.TestCase):
    def test_expiry_follows_the_clock(self) -> None:
        parameters = inspect.signature(is_expired).parameters
        if len(parameters) > 1:
            name = list(parameters)[1]
            self.assertFalse(is_expired(100.0, **{name: 50.0}))
            self.assertTrue(is_expired(100.0, **{name: 150.0}))
        else:
            self.assertFalse(is_expired(time.time() + 3600))
            self.assertTrue(is_expired(time.time() - 1))
