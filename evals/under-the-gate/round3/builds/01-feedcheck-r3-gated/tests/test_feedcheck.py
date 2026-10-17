import collections
import contextlib
import io
import json
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from feedcheck.check import Clocks, check_feeds
from feedcheck.cli import main
from feedcheck.config import ConfigError, load_config

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


@dataclass(frozen=True)
class Reply:
    status: int
    body: bytes
    delay: float = 0.0


def json_reply(document, status=200):
    return Reply(status, json.dumps(document).encode())


class FeedServer:
    """Serves scripted replies per path; the last reply for a path repeats."""

    def __init__(self):
        self.routes = {}
        self.hits = collections.Counter()
        self.lock = threading.Lock()
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                with server.lock:
                    count = server.hits[self.path]
                    server.hits[self.path] += 1
                if self.path in server.routes:
                    replies = server.routes[self.path]
                    reply = replies[min(count, len(replies) - 1)]
                else:
                    reply = Reply(404, b"no route for this path")
                if reply.delay:
                    time.sleep(reply.delay)
                self.send_response(reply.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(reply.body)))
                self.end_headers()
                self.wfile.write(reply.body)

            def log_message(self, format, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.httpd.block_on_close = False
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def url(self, path):
        return f"http://127.0.0.1:{self.httpd.server_address[1]}{path}"

    def route(self, path, *replies):
        self.routes[path] = list(replies)
        return self.url(path)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


def unused_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def config_text(feeds, timeout=2.0, attempts=3, delay=0.01):
    lines = [f"timeout_seconds = {timeout}", f"attempts = {attempts}", f"retry_delay_seconds = {delay}", ""]
    for feed in feeds:
        lines.append("[[feeds]]")
        for key, value in feed.items():
            lines.append(f"{key} = {json.dumps(value)}")
        lines.append("")
    return "\n".join(lines)


class TempDirMixin:
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write_config(self, text):
        path = self.tmp / "feeds.toml"
        path.write_text(text, encoding="utf-8")
        return path


class CheckTest(TempDirMixin, unittest.TestCase):
    """Runs checks against the fake server with recorded sleeps and a fixed 'now'."""

    def run_check(self, feeds, **settings):
        config = load_config(self.write_config(config_text(feeds, **settings)))
        self.sleeps = []
        clocks = Clocks(sleep=self.sleeps.append, monotonic=time.monotonic, now=lambda: NOW)
        return {result.feed.name: result for result in check_feeds(config, clocks)}

    def test_healthy_feed(self):
        with FeedServer() as server:
            url = server.route("/ok", json_reply({"items": [{"id": 1}, {"id": 2}]}))
            result = self.run_check([{"name": "ok", "url": url}])["ok"]
        self.assertEqual(result.verdict.status, "healthy")
        self.assertIsNone(result.verdict.reason)
        self.assertEqual(result.verdict.item_count, 2)
        self.assertGreaterEqual(result.duration_seconds, 0)

    def test_unhealthy_reasons(self):
        cases = {
            "notfound": (Reply(404, b"{}"), "404"),
            "nocontent": (Reply(204, b""), "204"),
            "badjson": (Reply(200, b"{not json"), "not valid JSON"),
            "array": (json_reply([1, 2]), "expected an object"),
            "noitems": (json_reply({"entries": []}), "no 'items'"),
            "itemsdict": (json_reply({"items": {}}), "expected a list"),
        }
        with FeedServer() as server:
            feeds = [{"name": name, "url": server.route(f"/{name}", reply)} for name, (reply, _) in cases.items()]
            results = self.run_check(feeds)
            self.assertEqual(server.hits["/notfound"], 1, "4xx is not retried")
        for name, (_, reason) in cases.items():
            with self.subTest(name):
                self.assertEqual(results[name].verdict.status, "unhealthy")
                self.assertIn(reason, results[name].verdict.reason)

    def test_5xx_is_retried_with_growing_delay(self):
        with FeedServer() as server:
            url = server.route("/flaky", Reply(503, b""), Reply(500, b""), json_reply({"items": []}))
            result = self.run_check([{"name": "flaky", "url": url}], attempts=3, delay=0.5)["flaky"]
            self.assertEqual(server.hits["/flaky"], 3)
        self.assertEqual(result.verdict.status, "healthy")
        self.assertEqual(self.sleeps, [0.5, 1.0])

    def test_persistent_5xx_is_unhealthy_after_all_attempts(self):
        with FeedServer() as server:
            url = server.route("/down", Reply(502, b""))
            result = self.run_check([{"name": "down", "url": url}], attempts=4)["down"]
            self.assertEqual(server.hits["/down"], 4)
        self.assertEqual(result.verdict.status, "unhealthy")
        self.assertIn("502", result.verdict.reason)
        self.assertEqual(len(self.sleeps), 3)

    def test_single_attempt_does_not_retry(self):
        with FeedServer() as server:
            url = server.route("/down", Reply(503, b""))
            self.run_check([{"name": "down", "url": url}], attempts=1)
            self.assertEqual(server.hits["/down"], 1)
        self.assertEqual(self.sleeps, [])

    def test_timeout_is_unreachable_and_retried(self):
        with FeedServer() as server:
            url = server.route("/slow", Reply(200, b'{"items": []}', delay=1.0))
            result = self.run_check([{"name": "slow", "url": url}], timeout=0.2, attempts=2)["slow"]
            self.assertEqual(server.hits["/slow"], 2)
        self.assertEqual(result.verdict.status, "unreachable")
        self.assertIn("timed out", result.verdict.reason)

    def test_timeout_then_recovery(self):
        with FeedServer() as server:
            url = server.route("/slow", Reply(200, b"", delay=1.0), json_reply({"items": [{}]}))
            result = self.run_check([{"name": "slow", "url": url}], timeout=0.2, attempts=2)["slow"]
        self.assertEqual(result.verdict.status, "healthy")
        self.assertEqual(result.verdict.item_count, 1)

    def test_connection_refused_is_unreachable(self):
        url = f"http://127.0.0.1:{unused_port()}/feed"
        result = self.run_check([{"name": "gone", "url": url}], attempts=2)["gone"]
        self.assertEqual(result.verdict.status, "unreachable")
        self.assertTrue(result.verdict.reason)
        self.assertEqual(len(self.sleeps), 1)

    def test_staleness(self):
        fresh = (NOW - timedelta(hours=2)).isoformat()
        old = (NOW - timedelta(hours=30)).isoformat()
        with FeedServer() as server:
            feeds = [
                {"name": "fresh", "url": server.route("/fresh", json_reply({"items": [{"published": old}, {"published": fresh}]})), "max_age_hours": 24},
                {"name": "stale", "url": server.route("/stale", json_reply({"items": [{"published": old}]})), "max_age_hours": 24},
                {"name": "zulu", "url": server.route("/zulu", json_reply({"items": [{"published": "2026-10-17T11:00:00Z"}]})), "max_age_hours": 1.5},
                {"name": "unchecked", "url": server.route("/unchecked", json_reply({"items": [{"published": old}]}))},
                {"name": "empty", "url": server.route("/empty", json_reply({"items": []})), "max_age_hours": 24},
                {"name": "nodate", "url": server.route("/nodate", json_reply({"items": [{"id": 1}]})), "max_age_hours": 24},
                {"name": "baddate", "url": server.route("/baddate", json_reply({"items": [{"published": "yesterday"}]})), "max_age_hours": 24},
                {"name": "naive", "url": server.route("/naive", json_reply({"items": [{"published": "2026-10-17T11:00:00"}]})), "max_age_hours": 24},
            ]
            results = self.run_check(feeds)
        expected = {
            "fresh": "healthy",
            "stale": "stale",
            "zulu": "healthy",
            "unchecked": "healthy",
            "empty": "stale",
            "nodate": "unhealthy",
            "baddate": "unhealthy",
            "naive": "unhealthy",
        }
        for name, status in expected.items():
            with self.subTest(name):
                self.assertEqual(results[name].verdict.status, status)
        self.assertIn("30.0 hours old", results["stale"].verdict.reason)
        self.assertEqual(results["stale"].verdict.item_count, 1)


class ConfigTest(TempDirMixin, unittest.TestCase):
    def assert_invalid(self, text, message):
        with self.assertRaises(ConfigError) as caught:
            load_config(self.write_config(text))
        self.assertIn(message, str(caught.exception))

    def test_valid_config(self):
        config = load_config(self.write_config(config_text([{"name": "a", "url": "https://example.com/f", "max_age_hours": 6}], timeout=5, attempts=2, delay=0)))
        self.assertEqual(config.timeout_seconds, 5.0)
        self.assertEqual(config.attempts, 2)
        self.assertEqual(config.retry_delay_seconds, 0.0)
        self.assertEqual(config.feeds[0].max_age_hours, 6.0)

    def test_missing_file(self):
        with self.assertRaises(ConfigError) as caught:
            load_config(self.tmp / "absent.toml")
        self.assertIn("cannot read config file", str(caught.exception))

    def test_directory_is_unreadable(self):
        with self.assertRaises(ConfigError):
            load_config(self.tmp)

    def test_invalid_contents(self):
        feed = [{"name": "a", "url": "http://example.com/"}]
        cases = {
            "not toml [": "not valid TOML",
            "attempts = 1\nretry_delay_seconds = 0\n[[feeds]]\nname='a'\nurl='http://x/'": "missing required key(s): timeout_seconds",
            config_text(feed, attempts=0): "attempts must be",
            config_text(feed, timeout=0): "timeout_seconds must be a positive number",
            config_text(feed, delay=-1): "retry_delay_seconds",
            config_text(feed) + "extra = 1\n": "unknown key(s): extra",
            config_text([]) + "feeds = []\n": "feeds must be a non-empty list",
            config_text([{"name": "a", "url": "ftp://example.com/"}]): "http or https",
            config_text([{"name": "a"}]): "missing required key(s): url",
            config_text([{"name": "", "url": "http://x/"}]): "name must be a non-empty string",
            config_text([{"name": "a", "url": "http://x/", "max_age_hours": -2}]): "max_age_hours must be a positive number",
            config_text([{"name": "a", "url": "http://x/"}, {"name": "a", "url": "http://y/"}]): "repeated: a",
        }
        for text, message in cases.items():
            with self.subTest(message):
                self.assert_invalid(text, message)

    def test_attempts_must_be_integer(self):
        self.assert_invalid(config_text([{"name": "a", "url": "http://x/"}], attempts=1.5), "attempts must be")

    def test_non_utf8(self):
        path = self.tmp / "feeds.toml"
        path.write_bytes(b"\xff\xfe")
        with self.assertRaises(ConfigError):
            load_config(path)


class CliTest(TempDirMixin, unittest.TestCase):
    def run_main(self, config_path, output):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = main(["--config", str(config_path), "--output", str(output)])
        return code, stderr.getvalue()

    def test_report_and_exit_code_when_all_healthy(self):
        output = self.tmp / "report.json"
        with FeedServer() as server:
            url = server.route("/ok", json_reply({"items": [1, 2, 3]}))
            code, _ = self.run_main(self.write_config(config_text([{"name": "ok", "url": url}])), output)
        self.assertEqual(code, 0)
        report = json.loads(output.read_text())
        self.assertTrue(report["healthy"])
        (feed,) = report["feeds"]
        self.assertEqual(feed["name"], "ok")
        self.assertEqual(feed["url"], url)
        self.assertEqual(feed["status"], "healthy")
        self.assertIsNone(feed["reason"])
        self.assertEqual(feed["items"], 3)
        self.assertIsInstance(feed["duration_seconds"], float)

    def test_exit_code_one_when_any_feed_is_not_healthy(self):
        output = self.tmp / "report.json"
        with FeedServer() as server:
            feeds = [
                {"name": "ok", "url": server.route("/ok", json_reply({"items": []}))},
                {"name": "bad", "url": server.route("/bad", Reply(500, b""))},
            ]
            code, _ = self.run_main(self.write_config(config_text(feeds, attempts=1)), output)
        self.assertEqual(code, 1)
        report = json.loads(output.read_text())
        self.assertFalse(report["healthy"])
        self.assertEqual([feed["status"] for feed in report["feeds"]], ["healthy", "unhealthy"])

    def test_invalid_config_stops_before_any_fetch(self):
        output = self.tmp / "report.json"
        with FeedServer() as server:
            url = server.route("/ok", json_reply({"items": []}))
            config = self.write_config(config_text([{"name": "ok", "url": url}], attempts=0))
            with self.assertRaises(SystemExit) as caught:
                self.run_main(config, output)
            self.assertEqual(server.hits, {})
        self.assertIn("attempts must be", str(caught.exception.code))
        self.assertFalse(output.exists())

    def test_subprocess_missing_config(self):
        output = self.tmp / "report.json"
        proc = subprocess.run(
            [sys.executable, "-m", "feedcheck", "--config", str(self.tmp / "nope.toml"), "--output", str(output)],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("feedcheck: cannot read config file", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertFalse(output.exists())

    def test_subprocess_end_to_end(self):
        output = self.tmp / "report.json"
        with FeedServer() as server:
            url = server.route("/ok", json_reply({"items": [{"published": datetime.now(UTC).isoformat()}]}))
            config = self.write_config(config_text([{"name": "ok", "url": url, "max_age_hours": 1}]))
            proc = subprocess.run(
                [sys.executable, "-m", "feedcheck", "--config", str(config), "--output", str(output)],
                cwd=ROOT, capture_output=True, text=True, timeout=30,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(output.read_text())["feeds"][0]["status"], "healthy")


if __name__ == "__main__":
    unittest.main()
