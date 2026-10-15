import unittest

from app.settings import connect, load_settings


class SettingsTest(unittest.TestCase):
    def test_values_are_read_and_typed(self) -> None:
        settings = load_settings({"REQUEST_TIMEOUT_SECONDS": "2.5", "PORT": "8080"})
        self.assertEqual(settings.request_timeout_seconds, 2.5)
        self.assertEqual(settings.port, 8080)

    def test_missing_keys_raise(self) -> None:
        with self.assertRaises(KeyError):
            load_settings({"PORT": "8080"})
        with self.assertRaises(KeyError):
            load_settings({"REQUEST_TIMEOUT_SECONDS": "2.5"})

    def test_invalid_values_raise_naming_the_variable(self) -> None:
        with self.assertRaisesRegex(ValueError, "REQUEST_TIMEOUT_SECONDS"):
            load_settings({"REQUEST_TIMEOUT_SECONDS": "0", "PORT": "8080"})
        with self.assertRaisesRegex(ValueError, "PORT"):
            load_settings({"REQUEST_TIMEOUT_SECONDS": "1", "PORT": "70000"})

    def test_connect_uses_the_settings_port(self) -> None:
        settings = load_settings({"REQUEST_TIMEOUT_SECONDS": "1", "PORT": "6543"})
        self.assertEqual(connect("db.internal", settings), "db.internal:6543")


if __name__ == "__main__":
    unittest.main()
