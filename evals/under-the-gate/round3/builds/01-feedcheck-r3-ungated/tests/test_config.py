import os
import tempfile
import unittest
from pathlib import Path

from feedcheck.config import ConfigError, load_config

VALID = """
timeout_seconds = 5
attempts = 2
backoff_seconds = 0.25

[[feeds]]
name = "news"
url = "https://example.com/news.json"
max_age_hours = 12

[[feeds]]
name = "blog"
url = "http://example.com/blog.json"
"""


class LoadConfigTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def write(self, text: str) -> Path:
        path = Path(self.dir.name) / "feeds.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def assertInvalid(self, text: str, fragment: str):
        with self.assertRaises(ConfigError) as ctx:
            load_config(self.write(text))
        self.assertIn(fragment, str(ctx.exception))

    def test_valid_config(self):
        config = load_config(self.write(VALID))
        self.assertEqual(config.timeout_seconds, 5.0)
        self.assertEqual(config.attempts, 2)
        self.assertEqual(config.backoff_seconds, 0.25)
        self.assertEqual([f.name for f in config.feeds], ["news", "blog"])
        self.assertEqual(config.feeds[0].max_age_hours, 12.0)
        self.assertIsNone(config.feeds[1].max_age_hours)

    def test_defaults(self):
        config = load_config(self.write('[[feeds]]\nname = "a"\nurl = "http://x/"\n'))
        self.assertGreater(config.timeout_seconds, 0)
        self.assertGreaterEqual(config.attempts, 1)

    def test_missing_file(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config(Path(self.dir.name) / "nope.toml")
        self.assertIn("not found", str(ctx.exception))

    def test_directory(self):
        with self.assertRaises(ConfigError):
            load_config(self.dir.name)

    @unittest.skipIf(os.name != "posix" or os.geteuid() == 0, "needs non-root POSIX")
    def test_unreadable_file(self):
        path = self.write(VALID)
        path.chmod(0)
        self.addCleanup(path.chmod, 0o644)
        with self.assertRaises(ConfigError) as ctx:
            load_config(path)
        self.assertIn("cannot read", str(ctx.exception))

    def test_not_toml(self):
        self.assertInvalid("this is = = not toml", "not valid TOML")

    def test_not_utf8(self):
        path = Path(self.dir.name) / "feeds.toml"
        path.write_bytes(b"\xff\xfe\x00")
        with self.assertRaises(ConfigError):
            load_config(path)

    def test_invalid_values(self):
        feed = '\n[[feeds]]\nname = "a"\nurl = "http://x/"\n'
        cases = [
            ("", "no feeds"),
            ("feeds = []", "non-empty list"),
            ('feeds = "x"', "non-empty list"),
            ("feeds = [1]", "must be a table"),
            ("timeout_seconds = 0" + feed, "timeout_seconds"),
            ("timeout_seconds = -1" + feed, "timeout_seconds"),
            ('timeout_seconds = "5"' + feed, "timeout_seconds"),
            ("timeout_seconds = true" + feed, "timeout_seconds"),
            ("timeout_seconds = inf" + feed, "timeout_seconds"),
            ("attempts = 0" + feed, "attempts"),
            ("attempts = 1.5" + feed, "attempts"),
            ("backoff_seconds = -1" + feed, "backoff_seconds"),
            ("retries = 3" + feed, "unknown setting"),
            ('[[feeds]]\nurl = "http://x/"', "'name'"),
            ('[[feeds]]\nname = ""\nurl = "http://x/"', "'name'"),
            ('[[feeds]]\nname = "a"', "'url'"),
            ('[[feeds]]\nname = "a"\nurl = 5', "'url'"),
            ('[[feeds]]\nname = "a"\nurl = "ftp://x/"', "http://"),
            ('[[feeds]]\nname = "a"\nurl = "not a url"', "http://"),
            (feed + feed, "duplicate"),
            (feed + "max_age_hours = 0", "max_age_hours"),
            (feed + 'max_age_hours = "1"', "max_age_hours"),
            (feed + 'colour = "red"', "unknown key"),
        ]
        for text, fragment in cases:
            with self.subTest(text=text):
                self.assertInvalid(text, fragment)


if __name__ == "__main__":
    unittest.main()
