import os
import tempfile
import textwrap
import unittest

from feedcheck.config import ConfigError, load_config


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, text: str) -> str:
        path = os.path.join(self.tmp.name, "feeds.toml")
        with open(path, "w") as f:
            f.write(textwrap.dedent(text))
        return path

    def assertInvalid(self, text: str, fragment: str):
        with self.assertRaises(ConfigError) as cm:
            load_config(self.write(text))
        self.assertIn(fragment, str(cm.exception))

    def test_valid_config(self):
        cfg = load_config(self.write("""
            timeout_seconds = 2.5
            attempts = 4
            backoff_seconds = 0.1

            [[feeds]]
            name = "a"
            url = "http://example.com/a.json"

            [[feeds]]
            name = "b"
            url = "https://example.com/b.json"
            max_age_hours = 12
        """))
        self.assertEqual(cfg.timeout_seconds, 2.5)
        self.assertEqual(cfg.attempts, 4)
        self.assertEqual(cfg.backoff_seconds, 0.1)
        self.assertEqual([f.name for f in cfg.feeds], ["a", "b"])
        self.assertIsNone(cfg.feeds[0].max_age_hours)
        self.assertEqual(cfg.feeds[1].max_age_hours, 12.0)

    def test_defaults(self):
        cfg = load_config(self.write("""
            [[feeds]]
            name = "a"
            url = "http://example.com/a.json"
        """))
        self.assertGreater(cfg.timeout_seconds, 0)
        self.assertGreaterEqual(cfg.attempts, 1)

    def test_missing_file(self):
        with self.assertRaises(ConfigError) as cm:
            load_config(os.path.join(self.tmp.name, "nope.toml"))
        self.assertIn("not found", str(cm.exception))

    def test_directory(self):
        with self.assertRaises(ConfigError):
            load_config(self.tmp.name)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads anything")
    def test_unreadable_file(self):
        path = self.write('[[feeds]]\nname = "a"\nurl = "http://x/"\n')
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o644)
        with self.assertRaises(ConfigError) as cm:
            load_config(path)
        self.assertIn("cannot read", str(cm.exception))

    def test_bad_toml(self):
        self.assertInvalid("this is = = not toml", "not valid TOML")

    def test_no_feeds(self):
        self.assertInvalid("timeout_seconds = 3\n", "no feeds")

    def test_empty_feeds(self):
        self.assertInvalid("feeds = []\n", "non-empty")

    def test_missing_name(self):
        self.assertInvalid('[[feeds]]\nurl = "http://x/"\n', "'name'")

    def test_missing_url(self):
        self.assertInvalid('[[feeds]]\nname = "a"\n', "'url'")

    def test_bad_url(self):
        self.assertInvalid('[[feeds]]\nname = "a"\nurl = "ftp://x/"\n', "http(s) URL")

    def test_duplicate_name(self):
        self.assertInvalid(
            '[[feeds]]\nname = "a"\nurl = "http://x/"\n'
            '[[feeds]]\nname = "a"\nurl = "http://y/"\n',
            "duplicate",
        )

    def test_bad_timeout(self):
        self.assertInvalid(
            'timeout_seconds = 0\n[[feeds]]\nname = "a"\nurl = "http://x/"\n',
            "timeout_seconds",
        )
        self.assertInvalid(
            'timeout_seconds = "5"\n[[feeds]]\nname = "a"\nurl = "http://x/"\n',
            "timeout_seconds",
        )

    def test_bad_attempts(self):
        for value in ("0", "1.5", "true", '"3"'):
            self.assertInvalid(
                f'attempts = {value}\n[[feeds]]\nname = "a"\nurl = "http://x/"\n',
                "attempts",
            )

    def test_bad_max_age(self):
        self.assertInvalid(
            '[[feeds]]\nname = "a"\nurl = "http://x/"\nmax_age_hours = -1\n',
            "max_age_hours",
        )

    def test_unknown_keys(self):
        self.assertInvalid(
            'timeout = 3\n[[feeds]]\nname = "a"\nurl = "http://x/"\n', "unknown"
        )
        self.assertInvalid(
            '[[feeds]]\nname = "a"\nurl = "http://x/"\nmax_age = 3\n', "unknown"
        )


if __name__ == "__main__":
    unittest.main()
