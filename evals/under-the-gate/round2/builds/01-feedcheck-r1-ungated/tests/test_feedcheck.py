import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from feedcheck.check import check_feed, evaluate
from feedcheck.cli import main
from feedcheck.config import Config, ConfigError, Feed, load_config, parse_config

from tests.fakeserver import FakeFeedServer, closed_port_url

REPO_ROOT = Path(__file__).resolve().parent.parent


class ServerTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = FakeFeedServer().start()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def setUp(self):
        self.server.hits.clear()
        self.sleeps = []

    def check(self, path, *, attempts=3, timeout=1.0, backoff=0.5, max_age_hours=None, url=None):
        feed = Feed(name=path, url=url or self.server.url(path), max_age_hours=max_age_hours)
        config = Config(feeds=(feed,), timeout_seconds=timeout, attempts=attempts, backoff_seconds=backoff)
        return check_feed(feed, config, sleep=self.sleeps.append)


class HealthTests(ServerTestCase):
    def test_healthy_feed(self):
        result = self.check("/ok")
        self.assertEqual(result.status, "healthy")
        self.assertIsNone(result.reason)
        self.assertEqual(result.items, 2)
        self.assertEqual(result.http_status, 200)
        self.assertEqual(result.attempts, 1)
        self.assertGreaterEqual(result.duration_seconds, 0)

    def test_empty_items_is_healthy_without_max_age(self):
        result = self.check("/empty")
        self.assertEqual((result.status, result.items), ("healthy", 0))

    def test_not_json(self):
        result = self.check("/not-json")
        self.assertEqual(result.status, "unhealthy")
        self.assertIn("not valid JSON", result.reason)

    def test_json_array(self):
        result = self.check("/array")
        self.assertEqual(result.status, "unhealthy")
        self.assertIn("not an object", result.reason)

    def test_missing_items(self):
        result = self.check("/no-items")
        self.assertEqual(result.status, "unhealthy")
        self.assertIn("no 'items'", result.reason)

    def test_items_not_list(self):
        result = self.check("/items-not-list")
        self.assertEqual(result.status, "unhealthy")
        self.assertIn("not a list", result.reason)
        self.assertIsNone(result.items)

    def test_404_is_unhealthy_and_not_retried(self):
        result = self.check("/404")
        self.assertEqual(result.status, "unhealthy")
        self.assertEqual(result.reason, "HTTP 404")
        self.assertEqual(result.http_status, 404)
        self.assertEqual(self.server.hits["/404"], 1)
        self.assertEqual(self.sleeps, [])


class RetryTests(ServerTestCase):
    def test_5xx_is_retried_until_success(self):
        result = self.check("/flaky-2", attempts=3)
        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.attempts, 3)
        self.assertEqual(self.server.hits["/flaky-2"], 3)

    def test_backoff_grows_between_attempts(self):
        self.check("/always-500", attempts=4, backoff=0.5)
        self.assertEqual(self.sleeps, [0.5, 1.0, 2.0])

    def test_persistent_5xx_is_unhealthy_after_all_attempts(self):
        result = self.check("/always-500", attempts=3)
        self.assertEqual(result.status, "unhealthy")
        self.assertIn("HTTP 500", result.reason)
        self.assertIn("3 attempts", result.reason)
        self.assertEqual(self.server.hits["/always-500"], 3)

    def test_single_attempt_does_not_retry(self):
        result = self.check("/flaky-1", attempts=1)
        self.assertEqual(result.status, "unhealthy")
        self.assertEqual(self.server.hits["/flaky-1"], 1)
        self.assertEqual(self.sleeps, [])

    def test_connection_refused_is_unreachable(self):
        result = self.check("refused", url=closed_port_url(), attempts=2)
        self.assertEqual(result.status, "unreachable")
        self.assertEqual(result.attempts, 2)
        self.assertIsNone(result.items)
        self.assertIn("2 attempts", result.reason)
        self.assertEqual(self.sleeps, [0.5])

    def test_timeout_is_unreachable_and_retried(self):
        result = self.check("/slow", timeout=0.2, attempts=2)
        self.assertEqual(result.status, "unreachable")
        self.assertIn("timed out", result.reason)
        self.assertEqual(self.server.hits["/slow"], 2)
        self.assertLess(result.duration_seconds, FakeFeedServer.SLOW_SECONDS)

    def test_hangup_is_unreachable(self):
        result = self.check("/hangup", attempts=2)
        self.assertEqual(result.status, "unreachable")
        self.assertEqual(self.server.hits["/hangup"], 2)


class StalenessTests(ServerTestCase):
    def test_fresh_feed_is_healthy(self):
        result = self.check("/fresh", max_age_hours=24)
        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.items, 2)

    def test_old_feed_is_stale(self):
        result = self.check("/stale", max_age_hours=24)
        self.assertEqual(result.status, "stale")
        self.assertIn("48.0h old", result.reason)
        self.assertEqual(result.items, 2)

    def test_old_feed_is_healthy_without_max_age(self):
        self.assertEqual(self.check("/stale").status, "healthy")

    def test_feed_without_dates_is_stale_when_max_age_set(self):
        self.assertEqual(self.check("/undated", max_age_hours=24).status, "stale")
        self.assertEqual(self.check("/empty", max_age_hours=24).status, "stale")

    def test_bad_date_is_unhealthy(self):
        result = self.check("/baddate", max_age_hours=24)
        self.assertEqual(result.status, "unhealthy")
        self.assertIn("ISO 8601", result.reason)


class EvaluateTests(unittest.TestCase):
    NOW = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)

    def run_eval(self, items, max_age_hours=24):
        body = json.dumps({"items": items}).encode()
        return evaluate(Feed("f", "http://x/", max_age_hours), 200, body, self.NOW)

    def test_z_suffix_and_offsets(self):
        self.assertEqual(self.run_eval([{"published": "2026-01-02T00:00:00Z"}])[0], "healthy")
        # 2026-01-01T13:00:00-02:00 is 15:00 UTC, 21h before NOW.
        self.assertEqual(self.run_eval([{"published": "2026-01-01T13:00:00-02:00"}])[0], "healthy")
        self.assertEqual(self.run_eval([{"published": "2026-01-01T09:00:00-02:00"}])[0], "stale")

    def test_naive_timestamp_is_utc(self):
        self.assertEqual(self.run_eval([{"published": "2026-01-01T11:00:00"}])[0], "stale")
        self.assertEqual(self.run_eval([{"published": "2026-01-01T13:00:00"}])[0], "healthy")

    def test_newest_item_wins_regardless_of_order(self):
        items = [{"published": "2025-01-01T00:00:00Z"}, {"published": "2026-01-02T11:00:00Z"}]
        self.assertEqual(self.run_eval(items)[0], "healthy")

    def test_non_string_published_is_unhealthy(self):
        self.assertEqual(self.run_eval([{"published": 12345}])[0], "unhealthy")


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, text):
        path = Path(self.tmp.name) / "feeds.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_valid_config(self):
        config = load_config(self.write(
            'timeout_seconds = 2.5\nattempts = 4\nbackoff_seconds = 0\n'
            '[[feeds]]\nname = "a"\nurl = "https://example.com/a.json"\nmax_age_hours = 12\n'
            '[[feeds]]\nname = "b"\nurl = "http://example.com/b.json"\n'
        ))
        self.assertEqual(config.timeout_seconds, 2.5)
        self.assertEqual(config.attempts, 4)
        self.assertEqual(config.backoff_seconds, 0)
        self.assertEqual([f.name for f in config.feeds], ["a", "b"])
        self.assertEqual(config.feeds[0].max_age_hours, 12)
        self.assertIsNone(config.feeds[1].max_age_hours)

    def test_defaults(self):
        config = parse_config({"feeds": [{"name": "a", "url": "http://x/"}]})
        self.assertGreater(config.timeout_seconds, 0)
        self.assertGreaterEqual(config.attempts, 1)

    def test_missing_file(self):
        with self.assertRaisesRegex(ConfigError, "not found"):
            load_config(Path(self.tmp.name) / "nope.toml")

    def test_directory(self):
        with self.assertRaisesRegex(ConfigError, "directory"):
            load_config(self.tmp.name)

    @unittest.skipIf(os.name != "posix" or os.geteuid() == 0, "needs POSIX permissions as non-root")
    def test_unreadable_file(self):
        path = self.write('[[feeds]]\nname = "a"\nurl = "http://x/"\n')
        path.chmod(0)
        self.addCleanup(path.chmod, 0o644)
        with self.assertRaisesRegex(ConfigError, "cannot read"):
            load_config(path)

    def test_invalid_toml(self):
        with self.assertRaisesRegex(ConfigError, "not valid TOML"):
            load_config(self.write("[[feeds]\nname = "))

    def test_invalid_values(self):
        cases = {
            "no feeds": {},
            "no feeds defined": {"feeds": []},
            "array of tables": {"feeds": "x"},
            "'name' is required": {"feeds": [{"url": "http://x/"}]},
            "'url' is required": {"feeds": [{"name": "a"}]},
            "absolute http": {"feeds": [{"name": "a", "url": "ftp://x/"}]},
            "duplicate": {"feeds": [{"name": "a", "url": "http://x/"}, {"name": "a", "url": "http://y/"}]},
            "max_age_hours": {"feeds": [{"name": "a", "url": "http://x/", "max_age_hours": -1}]},
            "timeout_seconds": {"timeout_seconds": 0, "feeds": [{"name": "a", "url": "http://x/"}]},
            "attempts": {"attempts": 0, "feeds": [{"name": "a", "url": "http://x/"}]},
            "backoff_seconds": {"backoff_seconds": -1, "feeds": [{"name": "a", "url": "http://x/"}]},
            "unknown key": {"timeout": 5, "feeds": [{"name": "a", "url": "http://x/"}]},
        }
        for message, data in cases.items():
            with self.subTest(message), self.assertRaisesRegex(ConfigError, message):
                parse_config(data)

    def test_bool_is_not_a_number(self):
        with self.assertRaises(ConfigError):
            parse_config({"attempts": True, "feeds": [{"name": "a", "url": "http://x/"}]})


class CliTests(ServerTestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.output = self.dir / "report.json"

    def write_config(self, feeds, header="timeout_seconds = 1\nattempts = 2\nbackoff_seconds = 0\n"):
        lines = [header]
        for name, path, *rest in feeds:
            url = path if path.startswith("http") else self.server.url(path)
            lines.append(f'[[feeds]]\nname = "{name}"\nurl = "{url}"\n')
            if rest:
                lines.append(f"max_age_hours = {rest[0]}\n")
        config = self.dir / "feeds.toml"
        config.write_text("".join(lines), encoding="utf-8")
        return config

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_all_healthy_exits_zero(self):
        config = self.write_config([("a", "/ok"), ("b", "/fresh", 24)])
        code, out, _ = self.run_main("--config", str(config), "--output", str(self.output))
        self.assertEqual(code, 0)
        report = json.loads(self.output.read_text())
        self.assertTrue(report["all_healthy"])
        self.assertEqual(report["summary"]["total"], 2)
        self.assertEqual(report["summary"]["healthy"], 2)
        self.assertIn("healthy", out)

    def test_mixed_results_exit_one_and_report_every_feed(self):
        config = self.write_config([
            ("ok", "/ok"),
            ("broken", "/404"),
            ("old", "/stale", 24),
            ("gone", closed_port_url()),
            ("flaky", "/flaky-1"),
        ])
        code, _, _ = self.run_main("--config", str(config), "--output", str(self.output))
        self.assertEqual(code, 1)
        report = json.loads(self.output.read_text())
        feeds = {f["name"]: f for f in report["feeds"]}
        self.assertEqual([f["name"] for f in report["feeds"]], ["ok", "broken", "old", "gone", "flaky"])
        self.assertEqual(feeds["ok"]["status"], "healthy")
        self.assertEqual(feeds["broken"]["status"], "unhealthy")
        self.assertEqual(feeds["broken"]["reason"], "HTTP 404")
        self.assertEqual(feeds["old"]["status"], "stale")
        self.assertEqual(feeds["gone"]["status"], "unreachable")
        self.assertEqual(feeds["flaky"]["status"], "healthy")
        for feed in report["feeds"]:
            self.assertIn("items", feed)
            self.assertIn("duration_seconds", feed)
            self.assertIsInstance(feed["duration_seconds"], float)
        self.assertEqual(feeds["ok"]["items"], 2)
        self.assertIsNone(feeds["gone"]["items"])
        self.assertEqual(report["summary"],
                         {"total": 5, "healthy": 2, "unhealthy": 1, "stale": 1, "unreachable": 1})

    def test_bad_config_stops_before_fetching(self):
        config = self.write_config(
            [("ok", "/ok"), ("bad", "http:no-host")],
        )
        code, _, err = self.run_main("--config", str(config), "--output", str(self.output))
        self.assertEqual(code, 2)
        self.assertIn("absolute http(s) URL", err)
        self.assertEqual(self.server.total_hits, 0)
        self.assertFalse(self.output.exists())

    def test_missing_config(self):
        code, _, err = self.run_main("--config", str(self.dir / "nope.toml"), "--output", str(self.output))
        self.assertEqual(code, 2)
        self.assertIn("config file not found", err)
        self.assertFalse(self.output.exists())

    def test_unwritable_output(self):
        config = self.write_config([("ok", "/ok")])
        code, _, err = self.run_main("--config", str(config), "--output", str(self.dir / "no" / "r.json"))
        self.assertEqual(code, 2)
        self.assertIn("cannot write report", err)

    def test_runs_as_module(self):
        config = self.write_config([("ok", "/ok")])
        proc = subprocess.run(
            [sys.executable, "-m", "feedcheck", "--config", str(config), "--output", str(self.output)],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(self.output.read_text())["feeds"][0]["status"], "healthy")


if __name__ == "__main__":
    unittest.main()
