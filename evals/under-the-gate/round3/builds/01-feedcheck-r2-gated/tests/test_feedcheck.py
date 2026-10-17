import io
from collections import Counter
import json
import socket
import tempfile
import threading
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from feedcheck.check import Status, check_feed, is_retryable, retry_delay
from feedcheck.cli import EXIT_HEALTHY, EXIT_NOT_HEALTHY, main
from feedcheck.config import Config, Feed, load_config
from feedcheck.errors import ConfigError
from feedcheck.fetch import Answer, NoAnswer


def iso(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) - delta).isoformat()


class FakeFeeds:
    """A local HTTP server; routes map a path to a list of (status, body) answers.

    Each request to a path takes the next answer; the last one repeats.
    A route whose answer is the string "hang" waits until the server stops.
    """

    def __init__(self, routes):
        self.routes = routes
        self.hits = Counter()
        self.release = threading.Event()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                count = fake.hits[self.path]
                fake.hits[self.path] += 1
                if self.path not in fake.routes:
                    status, body = 404, b"not found"
                else:
                    answers = fake.routes[self.path]
                    answer = answers[min(count, len(answers) - 1)]
                    if answer == "hang":
                        fake.release.wait(10)
                        return
                    status, body = answer
                if not isinstance(body, bytes):
                    body = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def url(self, path):
        host, port = self.server.server_address
        return f"http://{host}:{port}{path}"

    @property
    def total_hits(self):
        return sum(self.hits.values())


def closed_port_url():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}/feed.json"


def config_for(feeds, attempts=1, timeout=2.0):
    return Config(timeout_seconds=timeout, attempts=attempts, retry_backoff_seconds=0.0, feeds=tuple(feeds))


def check(feed, attempts=1, timeout=2.0):
    return check_feed(feed, config_for([feed], attempts, timeout), datetime.now(timezone.utc))


class CheckFeedTests(unittest.TestCase):
    def test_healthy_feed(self):
        with FakeFeeds({"/a": [(200, {"items": [1, 2, 3]})]}) as fake:
            result = check(Feed("a", fake.url("/a"), None))
        self.assertEqual(result.status, Status.HEALTHY)
        self.assertEqual(result.item_count, 3)
        self.assertIsNone(result.reason)
        self.assertGreaterEqual(result.elapsed_seconds, 0)

    def test_unhealthy_answers(self):
        cases = {
            "/notfound": [(404, b"nope")],
            "/notjson": [(200, b"<html>")],
            "/array": [(200, [1, 2])],
            "/noitems": [(200, {"entries": []})],
            "/itemsdict": [(200, {"items": {}})],
        }
        with FakeFeeds(cases) as fake:
            for path in cases:
                with self.subTest(path=path):
                    result = check(Feed(path, fake.url(path), None))
                    self.assertEqual(result.status, Status.UNHEALTHY)
                    self.assertTrue(result.reason)

    def test_client_error_is_not_retried(self):
        with FakeFeeds({"/gone": [(410, b"gone")]}) as fake:
            result = check(Feed("gone", fake.url("/gone"), None), attempts=3)
            self.assertEqual(fake.hits["/gone"], 1)
        self.assertEqual(result.status, Status.UNHEALTHY)
        self.assertIn("410", result.reason)

    def test_server_error_is_retried_until_healthy(self):
        answers = [(503, b"busy"), (500, b"oops"), (200, {"items": []})]
        with FakeFeeds({"/flaky": answers}) as fake:
            result = check(Feed("flaky", fake.url("/flaky"), None), attempts=3)
            self.assertEqual(fake.hits["/flaky"], 3)
        self.assertEqual(result.status, Status.HEALTHY)
        self.assertEqual(result.attempts, 3)

    def test_server_error_after_all_attempts_is_unhealthy(self):
        with FakeFeeds({"/down": [(502, b"bad gateway")]}) as fake:
            result = check(Feed("down", fake.url("/down"), None), attempts=2)
            self.assertEqual(fake.hits["/down"], 2)
        self.assertEqual(result.status, Status.UNHEALTHY)
        self.assertIn("502", result.reason)

    def test_refused_connection_is_unreachable_after_retries(self):
        result = check(Feed("closed", closed_port_url(), None), attempts=2)
        self.assertEqual(result.status, Status.UNREACHABLE)
        self.assertEqual(result.attempts, 2)
        self.assertIsNone(result.item_count)

    def test_timeout_is_unreachable(self):
        with FakeFeeds({"/slow": ["hang"]}) as fake:
            result = check(Feed("slow", fake.url("/slow"), None), attempts=2, timeout=0.2)
            self.assertEqual(fake.hits["/slow"], 2)
        self.assertEqual(result.status, Status.UNREACHABLE)
        self.assertIn("timed out", result.reason)

    def test_staleness(self):
        fresh = {"items": [{"published": iso(timedelta(hours=30))}, {"published": iso(timedelta(hours=1))}]}
        old = {"items": [{"published": iso(timedelta(hours=30))}, {"published": iso(timedelta(hours=50))}]}
        zulu = {"items": [{"published": "2000-01-01T00:00:00Z"}]}
        routes = {"/fresh": [(200, fresh)], "/old": [(200, old)], "/zulu": [(200, zulu)], "/empty": [(200, {"items": []})]}
        with FakeFeeds(routes) as fake:
            self.assertEqual(check(Feed("f", fake.url("/fresh"), 24)).status, Status.HEALTHY)
            stale = check(Feed("o", fake.url("/old"), 24))
            self.assertEqual(stale.status, Status.STALE)
            self.assertEqual(stale.item_count, 2)
            self.assertEqual(check(Feed("z", fake.url("/zulu"), 24)).status, Status.STALE)
            self.assertEqual(check(Feed("e", fake.url("/empty"), 24)).status, Status.STALE)
            # Without max_age_hours the age is not checked.
            self.assertEqual(check(Feed("o2", fake.url("/old"), None)).status, Status.HEALTHY)

    def test_bad_published_is_unhealthy(self):
        routes = {
            "/missing": [(200, {"items": [{"title": "x"}]})],
            "/garbage": [(200, {"items": [{"published": "yesterday"}]})],
            "/naive": [(200, {"items": [{"published": "2026-01-01T00:00:00"}]})],
            "/number": [(200, {"items": [{"published": 12}]})],
        }
        with FakeFeeds(routes) as fake:
            for path in routes:
                with self.subTest(path=path):
                    result = check(Feed(path, fake.url(path), 24))
                    self.assertEqual(result.status, Status.UNHEALTHY)


class RetryPolicyTests(unittest.TestCase):
    def test_delay_grows_with_each_attempt(self):
        delays = [retry_delay(0.5, index) for index in range(4)]
        self.assertEqual(delays[0], 0)
        self.assertEqual(delays, sorted(delays))
        self.assertEqual(len(set(delays)), 4)

    def test_retryable(self):
        self.assertTrue(is_retryable(NoAnswer("refused")))
        self.assertTrue(is_retryable(Answer(500, b"")))
        self.assertTrue(is_retryable(Answer(599, b"")))
        self.assertFalse(is_retryable(Answer(404, b"")))
        self.assertFalse(is_retryable(Answer(200, b"")))


VALID_CONFIG = """
timeout_seconds = 2.5
attempts = 3
retry_backoff_seconds = 0.1

[[feeds]]
name = "news"
url = "https://example.com/news.json"
max_age_hours = 12

[[feeds]]
name = "blog"
url = "http://example.com/blog.json"
"""


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, text, name="feeds.toml"):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_valid_config(self):
        config = load_config(self.write(VALID_CONFIG))
        self.assertEqual(config.timeout_seconds, 2.5)
        self.assertEqual(config.attempts, 3)
        self.assertEqual(config.feeds[0], Feed("news", "https://example.com/news.json", 12.0))
        self.assertIsNone(config.feeds[1].max_age_hours)

    def test_missing_and_unreadable(self):
        with self.assertRaisesRegex(ConfigError, "cannot read"):
            load_config(self.dir / "nope.toml")
        with self.assertRaisesRegex(ConfigError, "cannot read"):
            load_config(self.dir)
        bad = self.dir / "bin.toml"
        bad.write_bytes(b"\xff\xfe\x00")
        with self.assertRaisesRegex(ConfigError, "UTF-8"):
            load_config(bad)

    def test_invalid_configs(self):
        base = VALID_CONFIG
        cases = {
            "not toml": "this is = = not toml",
            "missing timeout": base.replace("timeout_seconds = 2.5\n", ""),
            "zero timeout": base.replace("timeout_seconds = 2.5", "timeout_seconds = 0"),
            "string timeout": base.replace("timeout_seconds = 2.5", 'timeout_seconds = "5"'),
            "nan timeout": base.replace("timeout_seconds = 2.5", "timeout_seconds = nan"),
            "zero attempts": base.replace("attempts = 3", "attempts = 0"),
            "float attempts": base.replace("attempts = 3", "attempts = 2.5"),
            "bool attempts": base.replace("attempts = 3", "attempts = true"),
            "negative backoff": base.replace("retry_backoff_seconds = 0.1", "retry_backoff_seconds = -1"),
            "unknown key": base + "\nextra = 1\n",
            "no feeds": base.split("[[feeds]]")[0],
            "feed without url": base.replace('url = "http://example.com/blog.json"\n', ""),
            "bad scheme": base.replace("http://example.com/blog.json", "ftp://example.com/blog.json"),
            "duplicate name": base.replace('name = "blog"', 'name = "news"'),
            "bad max age": base.replace("max_age_hours = 12", "max_age_hours = -3"),
            "unknown feed key": base.replace("max_age_hours = 12", "max_age = 12"),
        }
        for label, text in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(ConfigError):
                    load_config(self.write(text))


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.output = self.dir / "report.json"

    def tearDown(self):
        self.tmp.cleanup()

    def write_config(self, feeds):
        lines = ["timeout_seconds = 2", "attempts = 2", "retry_backoff_seconds = 0", ""]
        for name, url, max_age in feeds:
            lines += ["[[feeds]]", f'name = "{name}"', f'url = "{url}"']
            if max_age is not None:
                lines.append(f"max_age_hours = {max_age}")
        path = self.dir / "feeds.toml"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def run_main(self, config_path):
        return main(["--config", str(config_path), "--output", str(self.output)])

    def test_all_healthy_exits_zero(self):
        with FakeFeeds({"/a": [(200, {"items": [{"published": iso(timedelta(minutes=5))}]})]}) as fake:
            config = self.write_config([("a", fake.url("/a"), 1)])
            self.assertEqual(self.run_main(config), EXIT_HEALTHY)
        report = json.loads(self.output.read_text())
        self.assertTrue(report["healthy"])
        [feed] = report["feeds"]
        self.assertEqual(feed["name"], "a")
        self.assertEqual(feed["status"], "healthy")
        self.assertEqual(feed["items"], 1)
        self.assertIsInstance(feed["elapsed_seconds"], float)

    def test_mixed_results_exit_one_and_list_every_feed(self):
        routes = {
            "/ok": [(200, {"items": []})],
            "/bad": [(200, b"nope")],
            "/old": [(200, {"items": [{"published": "2001-01-01T00:00:00+00:00"}]})],
        }
        with FakeFeeds(routes) as fake:
            config = self.write_config(
                [
                    ("ok", fake.url("/ok"), None),
                    ("bad", fake.url("/bad"), None),
                    ("old", fake.url("/old"), 24),
                    ("gone", closed_port_url(), None),
                ]
            )
            self.assertEqual(self.run_main(config), EXIT_NOT_HEALTHY)
        report = json.loads(self.output.read_text())
        self.assertFalse(report["healthy"])
        statuses = {feed["name"]: feed["status"] for feed in report["feeds"]}
        self.assertEqual(statuses, {"ok": "healthy", "bad": "unhealthy", "old": "stale", "gone": "unreachable"})
        for feed in report["feeds"]:
            self.assertIn("elapsed_seconds", feed)
            self.assertIn("items", feed)

    def test_invalid_config_stops_before_any_fetch(self):
        with FakeFeeds({"/a": [(200, {"items": []})]}) as fake:
            path = self.dir / "feeds.toml"
            path.write_text(
                f'timeout_seconds = 2\nattempts = 0\nretry_backoff_seconds = 0\n[[feeds]]\nname = "a"\nurl = "{fake.url("/a")}"\n',
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit) as caught:
                self.run_main(path)
            self.assertEqual(fake.total_hits, 0)
        self.assertIn("attempts", str(caught.exception.code))
        self.assertTrue(str(caught.exception.code).startswith("feedcheck:"))
        self.assertFalse(self.output.exists())

    def test_missing_config_gives_clear_message(self):
        with self.assertRaises(SystemExit) as caught:
            self.run_main(self.dir / "missing.toml")
        self.assertIn("cannot read config file", str(caught.exception.code))

    def test_missing_arguments_is_usage_error(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            main([])
        self.assertNotEqual(caught.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
