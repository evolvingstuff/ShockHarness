import unittest

from app.settings import load_settings

ENV = {"API_URL": "https://api.example", "RETRIES": "2"}


class SettingsTest(unittest.TestCase):
    def test_the_api_url_is_read(self) -> None:
        self.assertEqual(load_settings(ENV).api_url, "https://api.example")


if __name__ == "__main__":
    unittest.main()
