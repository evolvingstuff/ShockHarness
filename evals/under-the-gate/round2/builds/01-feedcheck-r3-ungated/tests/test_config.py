import os
import tempfile
import unittest
from pathlib import Path

from feedcheck.config import ConfigError, load_config


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write(self, text, name="feeds.toml"):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def assertConfigError(self, text, fragment):
        with self.assertRaises(ConfigError) as ctx:
            load_config(self.write(text))
        self.assertIn(fragment, str(ctx.exception))

    def test_valid_config(self):
        cfg = load_config(self.write(
            'timeout_seconds = 2.5\nattempts = 4\nbackoff_seconds = 0\n'
            '[[feeds]]\nname = "a"\nurl = "http://example.com/a"\n'
            '[[feeds]]\nname = "b"\nurl = "https://example.com/b"\nmax_age_hours = 6\n'
        ))
        self.assertEqual(cfg.timeout_seconds, 2.5)
        self.assertEqual(cfg.attempts, 4)
        self.assertEqual(cfg.backoff_seconds, 0)
        self.assertEqual([f.name for f in cfg.feeds], ["a", "b"])
        self.assertIsNone(cfg.feeds[0].max_age_hours)
        self.assertEqual(cfg.feeds[1].max_age_hours, 6.0)

    def test_defaults(self):
        cfg = load_config(self.write('[[feeds]]\nname = "a"\nurl = "http://x/a"\n'))
        self.assertGreater(cfg.timeout_seconds, 0)
        self.assertGreaterEqual(cfg.attempts, 1)

    def test_missing_file(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config(self.dir / "nope.toml")
        self.assertIn("not found", str(ctx.exception))

    def test_directory(self):
        with self.assertRaises(ConfigError):
            load_config(self.dir)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root can read anything")
    def test_unreadable_file(self):
        path = self.write('[[feeds]]\nname = "a"\nurl = "http://x/a"\n')
        path.chmod(0)
        self.addCleanup(path.chmod, 0o600)
        with self.assertRaises(ConfigError) as ctx:
            load_config(path)
        self.assertIn("cannot read", str(ctx.exception))

    def test_bad_toml(self):
        self.assertConfigError("this is = = not toml", "not valid TOML")

    def test_not_utf8(self):
        path = self.dir / "bin.toml"
        path.write_bytes(b"\xff\xfe\x00")
        with self.assertRaises(ConfigError):
            load_config(path)

    def test_no_feeds(self):
        self.assertConfigError("timeout_seconds = 3\n", "no feeds")

    def test_feeds_not_tables(self):
        self.assertConfigError('feeds = ["a"]\n', "must be a table")

    def test_missing_name(self):
        self.assertConfigError('[[feeds]]\nurl = "http://x/a"\n', "'name'")

    def test_missing_url(self):
        self.assertConfigError('[[feeds]]\nname = "a"\n', "'url'")

    def test_bad_url_scheme(self):
        self.assertConfigError('[[feeds]]\nname = "a"\nurl = "file:///etc/passwd"\n', "http(s)")

    def test_duplicate_names(self):
        self.assertConfigError(
            '[[feeds]]\nname = "a"\nurl = "http://x/a"\n'
            '[[feeds]]\nname = "a"\nurl = "http://x/b"\n',
            "duplicate",
        )

    def test_bad_timeout(self):
        for value in ("0", "-1", '"5"', "true", "nan", "inf"):
            with self.subTest(value=value):
                self.assertConfigError(
                    f'timeout_seconds = {value}\n[[feeds]]\nname = "a"\nurl = "http://x/a"\n',
                    "timeout_seconds",
                )

    def test_bad_attempts(self):
        for value in ("0", "1.5", "true", '"3"'):
            with self.subTest(value=value):
                self.assertConfigError(
                    f'attempts = {value}\n[[feeds]]\nname = "a"\nurl = "http://x/a"\n',
                    "attempts",
                )

    def test_bad_max_age(self):
        self.assertConfigError(
            '[[feeds]]\nname = "a"\nurl = "http://x/a"\nmax_age_hours = -2\n',
            "max_age_hours",
        )

    def test_unknown_keys_rejected(self):
        self.assertConfigError(
            'timeout = 5\n[[feeds]]\nname = "a"\nurl = "http://x/a"\n', "unknown"
        )
        self.assertConfigError(
            '[[feeds]]\nname = "a"\nurl = "http://x/a"\nmax_age = 3\n', "unknown"
        )


if __name__ == "__main__":
    unittest.main()
