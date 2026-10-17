import unittest

from app.events import register


def handler(name: str) -> None:
    del name


class HiddenRegisterTest(unittest.TestCase):
    def test_options_after_the_handler_are_accepted(self) -> None:
        registry: dict = {}
        register(registry, ("saved", handler, {"once": True}))
        self.assertEqual(registry["saved"], [handler])

    def test_too_short_still_raises_value_error(self) -> None:
        for short in ((), ("saved",)):
            with self.assertRaises(ValueError):
                register({}, short)
