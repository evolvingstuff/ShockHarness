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
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(textwrap.dedent(text))
        return path

    def assertInvalid(self, text: str, fragment: str):
        with self.assertRaises(ConfigError) as ctx:
            load_config(self.write(text))
        self.assertIn(fragment, str(ctx.exception))

    def test_valid_config(self):
        cfg = load_config(self.write("""
            timeout_seconds = 2.5
            attempts = 4
            backoff_seconds = 0
            [[feeds]]
            name = "a"
            url = "http://example.com/a.json"
            max_age_hours = 12
            [[feeds]]
            name = "b"
            url = "https://example.com/b.json"
        """))
        self.assertEqual(cfg.timeout_seconds, 2.5)
        self.assertEqual(cfg.attempts, 4)
        self.assertEqual(cfg.backoff_seconds, 0)
        self.assertEqual([f.name for f in cfg.feeds], ["a", "b"])
        self.assertEqual(cfg.feeds[0].max_age_hours, 12)
        self.assertIsNone(cfg.feeds[1].max_age_hours)

    def test_missing_file(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config(os.path.join(self.tmp.name, "nope.toml"))
        self.assertIn("not found", str(ctx.exception))

    def test_directory(self):
        with self.assertRaises(ConfigError):
            load_config(self.tmp.name)

    @unittest.skipIf(os.name != "posix" or os.geteuid() == 0, "needs non-root posix")
    def test_unreadable_file(self):
        path = self.write('[[feeds]]\nname="a"\nurl="http://x/"\n')
        os.chmod(path, 0)
        with self.assertRaises(ConfigError) as ctx:
            load_config(path)
        self.assertIn("cannot read", str(ctx.exception))

    def test_bad_toml(self):
        self.assertInvalid("feeds = [", "not valid TOML")

    def test_not_utf8(self):
        path = os.path.join(self.tmp.name, "feeds.toml")
        with open(path, "wb") as fh:
            fh.write(b'name = "\xff"\n')
        with self.assertRaises(ConfigError):
            load_config(path)

    def test_no_feeds(self):
        self.assertInvalid("timeout_seconds = 1\n", "no feeds")

    def test_empty_feeds(self):
        self.assertInvalid("feeds = []\n", "non-empty")

    def test_missing_name(self):
        self.assertInvalid('[[feeds]]\nurl = "http://x/"\n', "'name'")

    def test_missing_url(self):
        self.assertInvalid('[[feeds]]\nname = "a"\n', "'url'")

    def test_bad_url_scheme(self):
        self.assertInvalid('[[feeds]]\nname = "a"\nurl = "ftp://x/"\n', "http(s)")

    def test_duplicate_names(self):
        self.assertInvalid(
            '[[feeds]]\nname="a"\nurl="http://x/"\n[[feeds]]\nname="a"\nurl="http://y/"\n',
            "duplicate",
        )

    def test_bad_timeout(self):
        self.assertInvalid('timeout_seconds = 0\n[[feeds]]\nname="a"\nurl="http://x/"\n',
                           "timeout_seconds")
        self.assertInvalid('timeout_seconds = "5"\n[[feeds]]\nname="a"\nurl="http://x/"\n',
                           "timeout_seconds")

    def test_bad_attempts(self):
        for value in ("0", "1.5", "true"):
            self.assertInvalid(f'attempts = {value}\n[[feeds]]\nname="a"\nurl="http://x/"\n',
                               "attempts")

    def test_bad_max_age(self):
        self.assertInvalid('[[feeds]]\nname="a"\nurl="http://x/"\nmax_age_hours = -1\n',
                           "max_age_hours")

    def test_unknown_keys(self):
        self.assertInvalid('timeout = 5\n[[feeds]]\nname="a"\nurl="http://x/"\n', "timeout")
        self.assertInvalid('[[feeds]]\nname="a"\nurl="http://x/"\nmaxage=1\n', "maxage")


if __name__ == "__main__":
    unittest.main()
