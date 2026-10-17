import json
import socket
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from feedcheck.check import HEALTHY, STALE, UNHEALTHY, UNREACHABLE, check_all
from feedcheck.config import Config, Feed, load_config
from feedcheck.errors import ConfigError
from tests.fixtures.fake_feeds import FakeFeeds

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)


def config_for(*feeds, attempts=3, timeout=2.0, backoff=0.01):
    return Config(timeout_seconds=timeout, attempts=attempts, retry_backoff_seconds=backoff, feeds=tuple(feeds))


def closed_port_url():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}/feed.json"


class Sleeps:
    def __init__(self):
        self.calls = []

    def __call__(self, seconds):
        self.calls.append(seconds)


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeFeeds().__enter__()
        self.addCleanup(self.fake.__exit__, None, None, None)
        self.sleeps = Sleeps()

    def check_one(self, path, max_age_hours=None, **settings):
        feed = Feed(name="f", url=self.fake.url(path), max_age_hours=max_age_hours)
        (result,) = check_all(config_for(feed, **settings), NOW, self.sleeps)
        return result

    def test_healthy_feed(self):
        self.fake.serve_json("/ok", {"items": [{"id": 1}, {"id": 2}]})
        result = self.check_one("/ok")
        self.assertEqual(result.status, HEALTHY)
        self.assertEqual(result.items, 2)
        self.assertIsNone(result.reason)
        self.assertEqual(result.attempts, 1)
        self.assertGreaterEqual(result.duration_seconds, 0)

    def test_items_not_a_list_is_unhealthy(self):
        self.fake.serve_json("/bad", {"items": {"a": 1}})
        result = self.check_one("/bad")
        self.assertEqual(result.status, UNHEALTHY)
        self.assertIn("items", result.reason)

    def test_missing_items_is_unhealthy(self):
        self.fake.serve_json("/bad", {"entries": []})
        self.assertEqual(self.check_one("/bad").status, UNHEALTHY)

    def test_json_array_is_unhealthy(self):
        self.fake.serve_json("/arr", [1, 2])
        result = self.check_one("/arr")
        self.assertEqual(result.status, UNHEALTHY)
        self.assertIn("object", result.reason)

    def test_invalid_json_is_unhealthy(self):
        self.fake.serve("/junk", (200, b"<html>", 0))
        result = self.check_one("/junk")
        self.assertEqual(result.status, UNHEALTHY)
        self.assertIn("JSON", result.reason)

    def test_404_is_unhealthy_without_retry(self):
        result = self.check_one("/missing")
        self.assertEqual(result.status, UNHEALTHY)
        self.assertIn("404", result.reason)
        self.assertEqual(self.fake.hits["/missing"], 1)
        self.assertEqual(self.sleeps.calls, [])

    def test_5xx_is_retried_with_growing_waits_then_recovers(self):
        ok = json.dumps({"items": []}).encode()
        self.fake.serve("/flaky", (503, b"{}", 0), (500, b"{}", 0), (200, ok, 0))
        result = self.check_one("/flaky", attempts=3, backoff=0.01)
        self.assertEqual(result.status, HEALTHY)
        self.assertEqual(result.attempts, 3)
        self.assertEqual(self.fake.hits["/flaky"], 3)
        self.assertEqual(len(self.sleeps.calls), 2)
        self.assertLess(self.sleeps.calls[0], self.sleeps.calls[1])

    def test_5xx_after_all_attempts_is_unhealthy(self):
        self.fake.serve("/down", (502, b"{}", 0))
        result = self.check_one("/down", attempts=2)
        self.assertEqual(result.status, UNHEALTHY)
        self.assertIn("502", result.reason)
        self.assertEqual(self.fake.hits["/down"], 2)

    def test_timeout_is_unreachable_after_retries(self):
        self.fake.serve("/slow", (200, b'{"items": []}', 0.5))
        result = self.check_one("/slow", attempts=2, timeout=0.1)
        self.assertEqual(result.status, UNREACHABLE)
        self.assertEqual(self.fake.hits["/slow"], 2)
        self.assertEqual(result.attempts, 2)
        self.assertIsNone(result.items)

    def test_connection_refused_is_unreachable(self):
        feed = Feed(name="gone", url=closed_port_url(), max_age_hours=None)
        (result,) = check_all(config_for(feed, attempts=3), NOW, self.sleeps)
        self.assertEqual(result.status, UNREACHABLE)
        self.assertTrue(result.reason)
        self.assertEqual(result.attempts, 3)
        self.assertEqual(len(self.sleeps.calls), 2)

    def test_fresh_feed_is_healthy(self):
        recent = (NOW - timedelta(hours=1)).isoformat()
        old = (NOW - timedelta(hours=50)).isoformat()
        self.fake.serve_json("/news", {"items": [{"published": old}, {"published": recent}]})
        self.assertEqual(self.check_one("/news", max_age_hours=24).status, HEALTHY)

    def test_old_feed_is_stale(self):
        self.fake.serve_json("/news", {"items": [{"published": "2026-10-15T12:00:00Z"}]})
        result = self.check_one("/news", max_age_hours=24)
        self.assertEqual(result.status, STALE)
        self.assertEqual(result.items, 1)

    def test_age_is_ignored_without_max_age(self):
        self.fake.serve_json("/news", {"items": [{"published": "2000-01-01T00:00:00Z"}]})
        self.assertEqual(self.check_one("/news").status, HEALTHY)

    def test_naive_timestamp_is_utc(self):
        self.fake.serve_json("/news", {"items": [{"published": "2026-10-17T11:00:00"}]})
        self.assertEqual(self.check_one("/news", max_age_hours=2).status, HEALTHY)

    def test_bad_published_is_unhealthy(self):
        self.fake.serve_json("/news", {"items": [{"published": "yesterday"}]})
        result = self.check_one("/news", max_age_hours=24)
        self.assertEqual(result.status, UNHEALTHY)
        self.assertIn("ISO 8601", result.reason)


VALID_CONFIG = """
timeout_seconds = 2
attempts = 2
retry_backoff_seconds = 0.01

[[feeds]]
name = "a"
url = "http://127.0.0.1:1/a.json"
max_age_hours = 6
"""


class ConfigTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def write(self, text):
        path = self.dir / "feeds.toml"
        path.write_text(text)
        return path

    def test_valid_config(self):
        config = load_config(self.write(VALID_CONFIG))
        self.assertEqual(config.attempts, 2)
        self.assertEqual(config.timeout_seconds, 2.0)
        self.assertEqual(config.feeds, (Feed(name="a", url="http://127.0.0.1:1/a.json", max_age_hours=6.0),))

    def test_missing_file(self):
        with self.assertRaisesRegex(ConfigError, "cannot read"):
            load_config(self.dir / "nope.toml")

    def test_directory_is_unreadable(self):
        with self.assertRaisesRegex(ConfigError, "cannot read"):
            load_config(self.dir)

    def test_invalid_toml(self):
        with self.assertRaisesRegex(ConfigError, "not valid TOML"):
            load_config(self.write("timeout_seconds = = 2"))

    def test_invalid_values(self):
        cases = {
            "missing required keys": VALID_CONFIG.replace("attempts = 2\n", ""),
            "unknown keys": VALID_CONFIG + "\nretries = 3\n",
            "attempts must be": VALID_CONFIG.replace("attempts = 2", "attempts = 0"),
            "timeout_seconds must be positive": VALID_CONFIG.replace("timeout_seconds = 2", "timeout_seconds = 0"),
            "timeout_seconds must be a number": VALID_CONFIG.replace("timeout_seconds = 2", 'timeout_seconds = "2"'),
            "url must be": VALID_CONFIG.replace("http://127.0.0.1:1/a.json", "ftp://x/a"),
            "max_age_hours must be positive": VALID_CONFIG.replace("max_age_hours = 6", "max_age_hours = -1"),
            "feeds must be": "timeout_seconds = 2\nattempts = 1\nretry_backoff_seconds = 0\nfeeds = []\n",
            "unique": VALID_CONFIG + '\n[[feeds]]\nname = "a"\nurl = "http://h/b"\n',
        }
        for message, text in cases.items():
            with self.subTest(message), self.assertRaisesRegex(ConfigError, message):
                load_config(self.write(text))


class CliTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.fake = FakeFeeds().__enter__()
        self.addCleanup(self.fake.__exit__, None, None, None)

    def run_cli(self, config_path):
        output = self.dir / "report.json"
        proc = subprocess.run(
            [sys.executable, "-m", "feedcheck", "--config", str(config_path), "--output", str(output)],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        return proc, output

    def write_config(self, feeds):
        lines = ["timeout_seconds = 2", "attempts = 1", "retry_backoff_seconds = 0"]
        for name, url in feeds:
            lines += ["[[feeds]]", f'name = "{name}"', f'url = "{url}"']
        path = self.dir / "feeds.toml"
        path.write_text("\n".join(lines) + "\n")
        return path

    def test_all_healthy_exits_0_and_writes_report(self):
        self.fake.serve_json("/a", {"items": [1, 2, 3]})
        proc, output = self.run_cli(self.write_config([("a", self.fake.url("/a"))]))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = json.loads(output.read_text())
        self.assertTrue(report["healthy"])
        (feed,) = report["feeds"]
        self.assertEqual(feed["name"], "a")
        self.assertEqual(feed["status"], "healthy")
        self.assertEqual(feed["items"], 3)
        self.assertIsInstance(feed["duration_seconds"], float)

    def test_any_unhealthy_exits_1(self):
        self.fake.serve_json("/a", {"items": []})
        self.fake.serve("/b", (500, b"oops", 0))
        proc, output = self.run_cli(self.write_config([("a", self.fake.url("/a")), ("b", self.fake.url("/b"))]))
        self.assertEqual(proc.returncode, 1, proc.stderr)
        report = json.loads(output.read_text())
        self.assertFalse(report["healthy"])
        self.assertEqual([f["status"] for f in report["feeds"]], ["healthy", "unhealthy"])
        self.assertIn("500", report["feeds"][1]["reason"])

    def test_invalid_config_stops_before_fetching(self):
        self.fake.serve_json("/a", {"items": []})
        path = self.write_config([("a", self.fake.url("/a"))])
        path.write_text(path.read_text().replace("attempts = 1", "attempts = 0"))
        proc, output = self.run_cli(path)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("attempts must be", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertEqual(self.fake.hits, {})
        self.assertFalse(output.exists())

    def test_missing_config_gives_clear_message(self):
        proc, _ = self.run_cli(self.dir / "absent.toml")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("cannot read config file", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)


if __name__ == "__main__":
    unittest.main()
