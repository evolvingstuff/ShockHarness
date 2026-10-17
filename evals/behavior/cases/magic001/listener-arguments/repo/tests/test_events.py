import unittest

from app.events import register


def handler(name: str) -> None:
    del name


class RegisterTest(unittest.TestCase):
    def test_registers_a_handler(self) -> None:
        registry: dict = {}
        register(registry, ("saved", handler))
        self.assertEqual(registry, {"saved": [handler]})

    def test_a_registration_without_a_handler_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            register({}, ("saved",))


if __name__ == "__main__":
    unittest.main()
