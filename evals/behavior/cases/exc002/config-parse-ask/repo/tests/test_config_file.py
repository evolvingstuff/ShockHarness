import tempfile
import unittest
from pathlib import Path

from app.config_file import load_config


class ConfigFileTest(unittest.TestCase):
    def test_a_malformed_file_gives_an_empty_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(load_config(path), {})


if __name__ == "__main__":
    unittest.main()
