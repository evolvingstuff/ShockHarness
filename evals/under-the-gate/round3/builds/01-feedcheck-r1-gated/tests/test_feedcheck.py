"""Tests for feedcheck; fake feeds are served from a local http.server, no network needed."""

from __future__ import annotations

import contextlib
import io
import json
import socket
import tempfile
import threading
import time
import unittest
from collections import Counter
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from feedcheck.check import check_feed
from feedcheck.cli import EXIT_CONFIG_ERROR, EXIT_HEALTHY, EXIT_UNHEALTHY, main
from feedcheck.config import ConfigError, Feed, Settings, load_settings
from feedcheck.fetch import build_opener
from feedcheck.health import Status

SLOW_SECONDS = 1.0
TIMEOUT_SECONDS = 0.3


STATIC_RESPONSES = {
    "/ok": (200, b'{"items": [{"id": 1}, {"id": 2}, {"id": 3}]}'),
    "/empty": (200, b'{"items": []}'),
    "/not-json": (200, b"<html>hello</html>"),
    "/no-items": (200, b'{"entries": []}'),
    "/items-not-list": (200, b'{"items": {"a": 1}}'),
    "/array": (200, b"[1, 2]"),
    "/missing": (404, b'{"error": "not found"}'),
    "/broken": (503, b'{"error": "down"}'),
    "/bad-date": (200, b'{"items": [{"published": "yesterday"}]}'),
    "/no-date": (200, b'{"items": [{"id": 1}]}'),
}


def _iso(age: timedelta) -> str:
    return (datetime.now(UTC) - age).isoformat()


def _items_body(*ages: timedelta) -> bytes:
    return json.dumps({"items": [{"published": _iso(age)} for age in ages]}).encode()


class FakeFeeds:
    """A local HTTP server; each path behaves like one kind of feed."""

    def __init__(self) -> None:
        self.hits: Counter[str] = Counter()
        self.flaky_failures = 2
        feeds = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                pass

            def do_GET(self) -> None:
                feeds.hits[self.path] += 1
                status, body = feeds.respond(self.path)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def respond(self, path: str) -> tuple[int, bytes]:
        if path in STATIC_RESPONSES:
            return STATIC_RESPONSES[path]
        if path == "/flaky":
            if self.hits[path] <= self.flaky_failures:
                return 500, b"{}"
            return 200, b'{"items": [{"id": 1}]}'
        if path == "/slow":
            time.sleep(SLOW_SECONDS)
            return 200, b'{"items": []}'
        if path == "/fresh":
            return 200, _items_body(timedelta(days=3), timedelta(hours=1))
        if path == "/stale":
            return 200, _items_body(timedelta(days=3), timedelta(hours=30))
        return 404, b"{}"

    def url(self, path: str) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}{path}"

    def __enter__(self) -> FakeFeeds:
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


def _closed_port_url() -> str:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}/feed"


def _settings(*feeds: Feed, attempts: int = 1, backoff: float = 0.0, timeout: float = TIMEOUT_SECONDS) -> Settings:
    return Settings(timeout_seconds=timeout, attempts=attempts, retry_backoff_seconds=backoff, feeds=feeds)


class CheckFeedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeFeeds().__enter__()
        self.addCleanup(self.fake.__exit__, None, None, None)
        self.waits: list[float] = []

    def check(self, path: str, max_age_hours: float | None = None, **settings: float):
        feed = Feed(name=path, url=self.fake.url(path), max_age_hours=max_age_hours)
        return check_feed(feed, _settings(feed, **settings), build_opener(), self.waits.append)

    def test_healthy_feed_reports_item_count(self) -> None:
        result = self.check("/ok")
        self.assertIs(result.status, Status.HEALTHY)
        self.assertIsNone(result.reason)
        self.assertEqual(result.item_count, 3)
        self.assertEqual(result.attempts, 1)
        self.assertGreaterEqual(result.elapsed_seconds, 0)

    def test_empty_items_list_is_healthy(self) -> None:
        result = self.check("/empty")
        self.assertIs(result.status, Status.HEALTHY)
        self.assertEqual(result.item_count, 0)

    def test_body_that_is_not_json_is_unhealthy(self) -> None:
        result = self.check("/not-json")
        self.assertIs(result.status, Status.UNHEALTHY)
        self.assertIn("not valid JSON", result.reason)
        self.assertIsNone(result.item_count)

    def test_object_without_items_is_unhealthy(self) -> None:
        result = self.check("/no-items")
        self.assertIs(result.status, Status.UNHEALTHY)
        self.assertIn("no items", result.reason)

    def test_items_that_are_not_a_list_are_unhealthy(self) -> None:
        self.assertIn("not a list", self.check("/items-not-list").reason)

    def test_json_array_is_unhealthy(self) -> None:
        result = self.check("/array")
        self.assertIs(result.status, Status.UNHEALTHY)
        self.assertIn("not a JSON object", result.reason)

    def test_client_error_is_unhealthy_without_retry(self) -> None:
        result = self.check("/missing", attempts=3)
        self.assertIs(result.status, Status.UNHEALTHY)
        self.assertIn("404", result.reason)
        self.assertEqual(self.fake.hits["/missing"], 1)
        self.assertEqual(self.waits, [])

    def test_server_error_is_retried_then_unhealthy(self) -> None:
        result = self.check("/broken", attempts=3, backoff=0.01)
        self.assertIs(result.status, Status.UNHEALTHY)
        self.assertIn("503", result.reason)
        self.assertEqual(result.attempts, 3)
        self.assertEqual(self.fake.hits["/broken"], 3)

    def test_each_retry_waits_longer(self) -> None:
        self.check("/broken", attempts=4, backoff=0.01)
        self.assertEqual(len(self.waits), 3)
        self.assertTrue(all(earlier < later for earlier, later in zip(self.waits, self.waits[1:])))

    def test_flaky_feed_recovers_on_retry(self) -> None:
        result = self.check("/flaky", attempts=3)
        self.assertIs(result.status, Status.HEALTHY)
        self.assertEqual(result.attempts, 3)

    def test_too_few_attempts_for_flaky_feed(self) -> None:
        result = self.check("/flaky", attempts=2)
        self.assertIs(result.status, Status.UNHEALTHY)

    def test_timeout_is_unreachable_after_all_attempts(self) -> None:
        result = self.check("/slow", attempts=2)
        self.assertIs(result.status, Status.UNREACHABLE)
        self.assertIn("timed out", result.reason)
        self.assertEqual(self.fake.hits["/slow"], 2)
        self.assertEqual(len(self.waits), 1)
        self.assertIsNone(result.item_count)

    def test_connection_refused_is_unreachable(self) -> None:
        url = _closed_port_url()
        feed = Feed(name="closed", url=url, max_age_hours=None)
        result = check_feed(feed, _settings(feed, attempts=2), build_opener(), self.waits.append)
        self.assertIs(result.status, Status.UNREACHABLE)
        self.assertEqual(result.attempts, 2)
        self.assertTrue(result.reason)

    def test_fresh_feed_with_max_age_is_healthy(self) -> None:
        result = self.check("/fresh", max_age_hours=24)
        self.assertIs(result.status, Status.HEALTHY)
        self.assertEqual(result.item_count, 2)

    def test_old_newest_item_is_stale(self) -> None:
        result = self.check("/stale", max_age_hours=24)
        self.assertIs(result.status, Status.STALE)
        self.assertEqual(result.item_count, 2)
        self.assertIn("24", result.reason)

    def test_max_age_not_set_ignores_dates(self) -> None:
        self.assertIs(self.check("/stale").status, Status.HEALTHY)

    def test_empty_feed_with_max_age_is_stale(self) -> None:
        self.assertIs(self.check("/empty", max_age_hours=24).status, Status.STALE)

    def test_unparseable_published_is_unhealthy(self) -> None:
        result = self.check("/bad-date", max_age_hours=24)
        self.assertIs(result.status, Status.UNHEALTHY)
        self.assertIn("ISO 8601", result.reason)
        self.assertEqual(result.item_count, 1)

    def test_missing_published_is_unhealthy_when_age_matters(self) -> None:
        self.assertIs(self.check("/no-date", max_age_hours=24).status, Status.UNHEALTHY)
        self.assertIs(self.check("/no-date").status, Status.HEALTHY)


VALID_CONFIG = """
timeout_seconds = {timeout}
attempts = 2
retry_backoff_seconds = 0.01

[[feeds]]
name = "ok"
url = "{ok}"

[[feeds]]
name = "fresh"
url = "{fresh}"
max_age_hours = 24
"""


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)

    def write(self, text: str) -> Path:
        path = self.dir / "feeds.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def assertConfigError(self, text: str, fragment: str) -> None:
        with self.assertRaises(ConfigError) as caught:
            load_settings(self.write(text))
        self.assertIn(fragment, str(caught.exception))

    def test_valid_config_loads(self) -> None:
        settings = load_settings(self.write(VALID_CONFIG.format(timeout=5, ok="http://a.example/x", fresh="https://b.example/y")))
        self.assertEqual(settings.timeout_seconds, 5.0)
        self.assertEqual(settings.attempts, 2)
        self.assertEqual([feed.name for feed in settings.feeds], ["ok", "fresh"])
        self.assertIsNone(settings.feeds[0].max_age_hours)
        self.assertEqual(settings.feeds[1].max_age_hours, 24.0)

    def test_missing_file(self) -> None:
        with self.assertRaises(ConfigError) as caught:
            load_settings(self.dir / "nope.toml")
        self.assertIn("cannot read", str(caught.exception))

    def test_directory_is_unreadable(self) -> None:
        with self.assertRaises(ConfigError):
            load_settings(self.dir)

    def test_invalid_toml(self) -> None:
        self.assertConfigError("timeout_seconds = = 3", "not valid TOML")

    def test_missing_timeout(self) -> None:
        self.assertConfigError('attempts = 1\nretry_backoff_seconds = 0\n[[feeds]]\nname = "a"\nurl = "http://a/"\n', "timeout_seconds")

    def test_unknown_key(self) -> None:
        text = 'timeout_seconds = 1\nattempts = 1\nretry_backoff_seconds = 0\nretries = 3\n[[feeds]]\nname = "a"\nurl = "http://a/"\n'
        self.assertConfigError(text, "unknown key(s): retries")

    def test_bad_values(self) -> None:
        base = 'timeout_seconds = {t}\nattempts = {a}\nretry_backoff_seconds = {b}\n[[feeds]]\nname = "a"\nurl = "{u}"\n'
        cases = [
            (dict(t=0, a=1, b=0, u="http://a/"), "timeout_seconds"),
            (dict(t='"5"', a=1, b=0, u="http://a/"), "timeout_seconds"),
            (dict(t=1, a=0, b=0, u="http://a/"), "attempts"),
            (dict(t=1, a=1.5, b=0, u="http://a/"), "attempts"),
            (dict(t=1, a="true", b=0, u="http://a/"), "attempts"),
            (dict(t=1, a=1, b=-1, u="http://a/"), "retry_backoff_seconds"),
            (dict(t=1, a=1, b=0, u="ftp://a/"), "url"),
            (dict(t=1, a=1, b=0, u="not a url"), "url"),
        ]
        for values, fragment in cases:
            with self.subTest(values=values):
                self.assertConfigError(base.format(**values), fragment)

    def test_no_feeds(self) -> None:
        self.assertConfigError("timeout_seconds = 1\nattempts = 1\nretry_backoff_seconds = 0\nfeeds = []\n", "feeds")

    def test_feed_without_url(self) -> None:
        self.assertConfigError('timeout_seconds = 1\nattempts = 1\nretry_backoff_seconds = 0\n[[feeds]]\nname = "a"\n', "url")

    def test_bad_max_age(self) -> None:
        text = 'timeout_seconds = 1\nattempts = 1\nretry_backoff_seconds = 0\n[[feeds]]\nname = "a"\nurl = "http://a/"\nmax_age_hours = -2\n'
        self.assertConfigError(text, "max_age_hours")

    def test_duplicate_names(self) -> None:
        text = 'timeout_seconds = 1\nattempts = 1\nretry_backoff_seconds = 0\n[[feeds]]\nname = "a"\nurl = "http://a/"\n[[feeds]]\nname = "a"\nurl = "http://b/"\n'
        self.assertConfigError(text, "more than once")


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeFeeds().__enter__()
        self.addCleanup(self.fake.__exit__, None, None, None)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        self.config = self.dir / "feeds.toml"
        self.output = self.dir / "report.json"

    def run_cli(self) -> int:
        return main(["--config", str(self.config), "--output", str(self.output)])

    def write_config(self, ok: str, fresh: str) -> None:
        self.config.write_text(VALID_CONFIG.format(timeout=TIMEOUT_SECONDS, ok=ok, fresh=fresh), encoding="utf-8")

    def test_all_healthy_exits_zero_and_writes_report(self) -> None:
        self.write_config(self.fake.url("/ok"), self.fake.url("/fresh"))
        self.assertEqual(self.run_cli(), EXIT_HEALTHY)
        report = json.loads(self.output.read_text())
        self.assertTrue(report["healthy"])
        self.assertEqual([feed["name"] for feed in report["feeds"]], ["ok", "fresh"])
        first = report["feeds"][0]
        self.assertEqual(first["status"], "healthy")
        self.assertEqual(first["items"], 3)
        self.assertIsInstance(first["elapsed_seconds"], float)
        self.assertIsNone(first["reason"])

    def test_any_unhealthy_feed_exits_one(self) -> None:
        self.write_config(self.fake.url("/ok"), self.fake.url("/stale"))
        self.assertEqual(self.run_cli(), EXIT_UNHEALTHY)
        report = json.loads(self.output.read_text())
        self.assertFalse(report["healthy"])
        self.assertEqual(report["feeds"][1]["status"], "stale")

    def test_unreachable_feed_is_reported(self) -> None:
        self.write_config(self.fake.url("/ok"), _closed_port_url())
        self.assertEqual(self.run_cli(), EXIT_UNHEALTHY)
        report = json.loads(self.output.read_text())
        self.assertEqual(report["feeds"][1]["status"], "unreachable")
        self.assertIsNone(report["feeds"][1]["items"])

    def test_invalid_config_stops_before_any_fetch(self) -> None:
        self.config.write_text(f'timeout_seconds = 1\nattempts = 0\nretry_backoff_seconds = 0\n[[feeds]]\nname = "a"\nurl = "{self.fake.url("/ok")}"\n')
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as caught:
            self.run_cli()
        self.assertEqual(caught.exception.code, EXIT_CONFIG_ERROR)
        self.assertIn("attempts", stderr.getvalue())
        self.assertEqual(sum(self.fake.hits.values()), 0)
        self.assertFalse(self.output.exists())

    def test_missing_config_stops_with_message(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as caught:
            self.run_cli()
        self.assertEqual(caught.exception.code, EXIT_CONFIG_ERROR)
        self.assertIn("cannot read config file", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
