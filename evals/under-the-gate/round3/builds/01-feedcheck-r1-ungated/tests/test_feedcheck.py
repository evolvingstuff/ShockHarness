import contextlib
import io
import json
import socket
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from feedcheck.checker import Checker
from feedcheck.cli import main
from feedcheck.config import Config, ConfigError, Feed, load_config

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)


class FakeFeedServer:
    """A local HTTP server; each path answers with a queue of responses.

    A response is (status, body) or ("sleep", seconds). The last response of a
    queue repeats forever.
    """

    def __init__(self):
        self.routes: dict[str, list] = {}
        self.hits: dict[str, int] = {}
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                server.hits[self.path] = server.hits.get(self.path, 0) + 1
                queue = server.routes.get(self.path, [(404, "not found")])
                response = queue.pop(0) if len(queue) > 1 else queue[0]
                if response[0] == "sleep":
                    time.sleep(response[1])
                    response = (200, {"items": []})
                status, body = response
                if not isinstance(body, (str, bytes)):
                    body = json.dumps(body)
                if isinstance(body, str):
                    body = body.encode()
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, args=(0.01,), daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()

    def url(self, path):
        return f"http://127.0.0.1:{self.httpd.server_address[1]}{path}"

    @property
    def total_hits(self):
        return sum(self.hits.values())


def unused_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def iso(dt):
    return dt.isoformat()


class CheckerTestCase(unittest.TestCase):
    def setUp(self):
        self.server = FakeFeedServer().__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)
        self.sleeps = []

    def check(self, path, max_age_hours=None, attempts=3, timeout=2.0, url=None):
        feed = Feed(name="f", url=url or self.server.url(path), max_age_hours=max_age_hours)
        config = Config(feeds=[feed], timeout_seconds=timeout, attempts=attempts,
                        backoff_seconds=0.5)
        checker = Checker(config, sleep=self.sleeps.append, now=lambda: NOW)
        return checker.check(feed)


class HealthTests(CheckerTestCase):
    def test_healthy_feed(self):
        self.server.routes["/ok"] = [(200, {"items": [{"id": 1}, {"id": 2}]})]
        r = self.check("/ok")
        self.assertEqual(r.status, "healthy")
        self.assertEqual(r.items, 2)
        self.assertIsNone(r.reason)
        self.assertEqual(r.attempts, 1)
        self.assertGreaterEqual(r.duration_seconds, 0)

    def test_empty_items_is_healthy_without_max_age(self):
        self.server.routes["/e"] = [(200, {"items": []})]
        self.assertEqual(self.check("/e").status, "healthy")

    def test_items_not_a_list(self):
        self.server.routes["/x"] = [(200, {"items": {"a": 1}})]
        r = self.check("/x")
        self.assertEqual(r.status, "unhealthy")
        self.assertIn("'items'", r.reason)

    def test_missing_items(self):
        self.server.routes["/x"] = [(200, {"entries": []})]
        r = self.check("/x")
        self.assertEqual(r.status, "unhealthy")
        self.assertIn("no 'items'", r.reason)

    def test_not_an_object(self):
        self.server.routes["/x"] = [(200, [1, 2])]
        r = self.check("/x")
        self.assertEqual(r.status, "unhealthy")
        self.assertIn("expected an object", r.reason)

    def test_invalid_json(self):
        self.server.routes["/x"] = [(200, "<html>oops</html>")]
        r = self.check("/x")
        self.assertEqual(r.status, "unhealthy")
        self.assertIn("not valid JSON", r.reason)

    def test_4xx_is_unhealthy_and_not_retried(self):
        self.server.routes["/x"] = [(404, "nope")]
        r = self.check("/x")
        self.assertEqual(r.status, "unhealthy")
        self.assertEqual(r.reason, "HTTP 404")
        self.assertEqual(self.server.hits["/x"], 1)
        self.assertEqual(self.sleeps, [])

    def test_other_2xx_is_unhealthy(self):
        self.server.routes["/x"] = [(204, b"")]
        r = self.check("/x")
        self.assertEqual(r.status, "unhealthy")
        self.assertEqual(r.reason, "HTTP 204")


class RetryTests(CheckerTestCase):
    def test_5xx_retried_then_succeeds(self):
        self.server.routes["/r"] = [(503, "busy"), (500, "err"), (200, {"items": [1]})]
        r = self.check("/r", attempts=3)
        self.assertEqual(r.status, "healthy")
        self.assertEqual(r.attempts, 3)
        self.assertEqual(self.server.hits["/r"], 3)
        self.assertEqual(self.sleeps, [0.5, 1.0])  # waits grow

    def test_5xx_exhausts_attempts(self):
        self.server.routes["/r"] = [(502, "bad gateway")]
        r = self.check("/r", attempts=4)
        self.assertEqual(r.status, "unhealthy")
        self.assertEqual(r.reason, "HTTP 502")
        self.assertEqual(self.server.hits["/r"], 4)
        self.assertEqual(self.sleeps, [0.5, 1.0, 2.0])

    def test_single_attempt_means_no_retry(self):
        self.server.routes["/r"] = [(500, "err"), (200, {"items": []})]
        r = self.check("/r", attempts=1)
        self.assertEqual(r.status, "unhealthy")
        self.assertEqual(self.server.hits["/r"], 1)

    def test_connection_refused_is_unreachable(self):
        r = self.check(None, url=f"http://127.0.0.1:{unused_port()}/feed", attempts=2)
        self.assertEqual(r.status, "unreachable")
        self.assertIn("connection failed", r.reason)
        self.assertEqual(r.attempts, 2)
        self.assertEqual(self.sleeps, [0.5])
        self.assertIsNone(r.items)

    def test_timeout_is_unreachable_and_retried(self):
        self.server.routes["/slow"] = [("sleep", 1.0)]
        r = self.check("/slow", timeout=0.2, attempts=2)
        self.assertEqual(r.status, "unreachable")
        self.assertIn("timed out", r.reason)
        self.assertEqual(self.server.hits["/slow"], 2)

    def test_timeout_then_success(self):
        self.server.routes["/slow"] = [("sleep", 1.0), (200, {"items": [1, 2, 3]})]
        r = self.check("/slow", timeout=0.2, attempts=2)
        self.assertEqual(r.status, "healthy")
        self.assertEqual(r.items, 3)


class StalenessTests(CheckerTestCase):
    def feed(self, *published):
        return [(200, {"items": [{"published": p} for p in published]})]

    def test_fresh_feed(self):
        self.server.routes["/f"] = self.feed(iso(NOW - timedelta(hours=30)),
                                             iso(NOW - timedelta(hours=1)))
        r = self.check("/f", max_age_hours=2)
        self.assertEqual(r.status, "healthy")
        self.assertEqual(r.items, 2)

    def test_stale_feed_uses_newest_item(self):
        self.server.routes["/f"] = self.feed(iso(NOW - timedelta(hours=5)),
                                             iso(NOW - timedelta(hours=3)))
        r = self.check("/f", max_age_hours=2)
        self.assertEqual(r.status, "stale")
        self.assertIn("3.0 hours", r.reason)
        self.assertEqual(r.items, 2)

    def test_z_suffix_and_offsets(self):
        self.server.routes["/f"] = self.feed("2026-10-17T11:30:00Z",
                                             "2026-10-17T13:00:00+02:00")
        self.assertEqual(self.check("/f", max_age_hours=1).status, "healthy")

    def test_naive_timestamp_treated_as_utc(self):
        self.server.routes["/f"] = self.feed("2026-10-17T08:00:00")
        self.assertEqual(self.check("/f", max_age_hours=3).status, "stale")

    def test_no_max_age_ignores_old_items(self):
        self.server.routes["/f"] = self.feed("2000-01-01T00:00:00Z")
        self.assertEqual(self.check("/f").status, "healthy")

    def test_empty_feed_with_max_age_is_stale(self):
        self.server.routes["/f"] = [(200, {"items": []})]
        r = self.check("/f", max_age_hours=1)
        self.assertEqual(r.status, "stale")

    def test_invalid_published_is_unhealthy(self):
        self.server.routes["/f"] = self.feed("yesterday")
        r = self.check("/f", max_age_hours=1)
        self.assertEqual(r.status, "unhealthy")
        self.assertIn("invalid 'published'", r.reason)

    def test_missing_published_is_unhealthy(self):
        self.server.routes["/f"] = [(200, {"items": [{"id": 1}]})]
        r = self.check("/f", max_age_hours=1)
        self.assertEqual(r.status, "unhealthy")
        self.assertIn("no 'published'", r.reason)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def write(self, text):
        path = self.dir / "feeds.toml"
        path.write_text(text)
        return path

    def test_valid_config(self):
        cfg = load_config(self.write("""
timeout_seconds = 5
attempts = 2
backoff_seconds = 0.25

[[feeds]]
name = "a"
url = "http://example.com/a.json"
max_age_hours = 12

[[feeds]]
name = "b"
url = "https://example.com/b.json"
"""))
        self.assertEqual(cfg.timeout_seconds, 5.0)
        self.assertEqual(cfg.attempts, 2)
        self.assertEqual(cfg.backoff_seconds, 0.25)
        self.assertEqual([f.name for f in cfg.feeds], ["a", "b"])
        self.assertEqual(cfg.feeds[0].max_age_hours, 12.0)
        self.assertIsNone(cfg.feeds[1].max_age_hours)

    def test_defaults(self):
        cfg = load_config(self.write('[[feeds]]\nname = "a"\nurl = "http://x/a"\n'))
        self.assertGreater(cfg.timeout_seconds, 0)
        self.assertGreaterEqual(cfg.attempts, 1)

    def test_missing_file(self):
        with self.assertRaisesRegex(ConfigError, "not found"):
            load_config(self.dir / "nope.toml")

    def test_directory(self):
        with self.assertRaises(ConfigError):
            load_config(self.dir)

    def test_invalid_toml(self):
        with self.assertRaisesRegex(ConfigError, "not valid TOML"):
            load_config(self.write("this is = = not toml"))

    def assertInvalid(self, text, pattern):
        with self.assertRaisesRegex(ConfigError, pattern):
            load_config(self.write(text))

    def test_invalid_contents(self):
        feed = '[[feeds]]\nname = "a"\nurl = "http://x/a"\n'
        cases = [
            ("", "no feeds"),
            ("feeds = []", "non-empty"),
            ("timeout_seconds = 0\n" + feed, "timeout_seconds"),
            ('timeout_seconds = "5"\n' + feed, "timeout_seconds"),
            ("attempts = 0\n" + feed, "attempts"),
            ("attempts = 1.5\n" + feed, "attempts"),
            ("attempts = true\n" + feed, "attempts"),
            ("backoff_seconds = -1\n" + feed, "backoff_seconds"),
            ("retries = 3\n" + feed, "unknown key"),
            ('[[feeds]]\nurl = "http://x/a"\n', "name"),
            ('[[feeds]]\nname = "a"\n', "url"),
            ('[[feeds]]\nname = "a"\nurl = "ftp://x/a"\n', "invalid url"),
            ('[[feeds]]\nname = "a"\nurl = "not a url"\n', "invalid url"),
            (feed + "max_age_hours = -1\n", "max_age_hours"),
            (feed + 'max_age_hours = "1"\n', "max_age_hours"),
            (feed + "max_age = 1\n", "unknown key"),
            (feed + feed, "duplicate"),
        ]
        for text, pattern in cases:
            with self.subTest(text=text):
                self.assertInvalid(text, pattern)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeFeedServer().__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)
        self.dir = Path(tempfile.mkdtemp())
        self.output = self.dir / "report.json"

    def run_cli(self, config_text=None, config_path=None):
        if config_path is None:
            config_path = self.dir / "feeds.toml"
            config_path.write_text(config_text)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--config", str(config_path), "--output", str(self.output)])
        return code, out.getvalue(), err.getvalue()

    def feeds_toml(self, *feeds, attempts=2):
        text = f"timeout_seconds = 1\nattempts = {attempts}\nbackoff_seconds = 0\n"
        for name, path, *rest in feeds:
            text += f'[[feeds]]\nname = "{name}"\nurl = "{self.server.url(path)}"\n'
            if rest:
                text += f"max_age_hours = {rest[0]}\n"
        return text

    def test_all_healthy_exits_zero(self):
        recent = iso(datetime.now(timezone.utc) - timedelta(minutes=5))
        self.server.routes["/a"] = [(200, {"items": [1, 2, 3]})]
        self.server.routes["/b"] = [(200, {"items": [{"published": recent}]})]
        code, out, err = self.run_cli(self.feeds_toml(("a", "/a"), ("b", "/b", 1)))
        self.assertEqual(code, 0, err)
        report = json.loads(self.output.read_text())
        self.assertTrue(report["healthy"])
        self.assertEqual([f["name"] for f in report["feeds"]], ["a", "b"])
        a = report["feeds"][0]
        self.assertEqual(a["status"], "healthy")
        self.assertEqual(a["items"], 3)
        self.assertIsInstance(a["duration_seconds"], float)
        self.assertEqual(report["summary"], {"total": 2, "healthy": 2})

    def test_mixed_results_exit_one_and_report_every_feed(self):
        self.server.routes["/ok"] = [(200, {"items": []})]
        self.server.routes["/bad"] = [(200, {"items": "nope"})]
        self.server.routes["/down"] = [(503, "busy")]
        self.server.routes["/old"] = [(200, {"items": [{"published": "2001-01-01T00:00:00Z"}]})]
        code, out, err = self.run_cli(self.feeds_toml(
            ("ok", "/ok"), ("bad", "/bad"), ("down", "/down"), ("old", "/old", 24)))
        self.assertEqual(code, 1)
        report = json.loads(self.output.read_text())
        self.assertFalse(report["healthy"])
        statuses = {f["name"]: f["status"] for f in report["feeds"]}
        self.assertEqual(statuses, {"ok": "healthy", "bad": "unhealthy",
                                    "down": "unhealthy", "old": "stale"})
        by_name = {f["name"]: f for f in report["feeds"]}
        self.assertIn("reason", by_name["bad"])
        self.assertEqual(by_name["down"]["reason"], "HTTP 503")
        self.assertEqual(by_name["down"]["attempts"], 2)
        self.assertNotIn("reason", by_name["ok"])

    def test_unreachable_feed_in_report(self):
        text = ("timeout_seconds = 1\nattempts = 1\n[[feeds]]\nname = \"gone\"\n"
                f'url = "http://127.0.0.1:{unused_port()}/feed"\n')
        code, out, err = self.run_cli(text)
        self.assertEqual(code, 1)
        feed = json.loads(self.output.read_text())["feeds"][0]
        self.assertEqual(feed["status"], "unreachable")
        self.assertIsNone(feed["items"])
        self.assertIn("duration_seconds", feed)

    def test_invalid_config_stops_before_fetching(self):
        self.server.routes["/a"] = [(200, {"items": []})]
        text = self.feeds_toml(("a", "/a")) + '[[feeds]]\nname = "b"\nurl = "ftp://nope"\n'
        code, out, err = self.run_cli(text)
        self.assertEqual(code, 2)
        self.assertIn("invalid url", err)
        self.assertEqual(self.server.total_hits, 0)
        self.assertFalse(self.output.exists())

    def test_missing_config(self):
        code, out, err = self.run_cli(config_path=self.dir / "missing.toml")
        self.assertEqual(code, 2)
        self.assertIn("not found", err)
        self.assertFalse(self.output.exists())

    def test_malformed_config(self):
        code, out, err = self.run_cli("[[feeds]\nname=")
        self.assertEqual(code, 2)
        self.assertIn("not valid TOML", err)
        self.assertEqual(self.server.total_hits, 0)


if __name__ == "__main__":
    unittest.main()
