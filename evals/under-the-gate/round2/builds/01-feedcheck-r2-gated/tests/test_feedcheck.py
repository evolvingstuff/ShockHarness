"""feedcheck end to end, against feeds served from a local http.server."""

import json
import socket
import tempfile
import tomllib
import unittest
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from pathlib import Path

from feedcheck.checker import check_feed
from feedcheck.cli import EXIT_ALL_HEALTHY, EXIT_NOT_ALL_HEALTHY, main
from feedcheck.config import ConfigError, load_config
from tests.helpers import FakeFeedServer, Reply, json_reply

ITEMS = [{"title": "a"}, {"title": "b"}, {"title": "c"}]
MAX_AGE_LINE = "max_age_hours = 24"
MAX_AGE_HOURS = tomllib.loads(MAX_AGE_LINE)["max_age_hours"]
FAST_RETRY = "timeout_seconds = 2\nattempts = 3\nretry_delay_seconds = 0\n"


def iso_hours_ago(hours: float) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours)).isoformat()


def feed_table(name: str, url: str, extra: str) -> str:
    return f'[[feeds]]\nname = "{name}"\nurl = "{url}"\n{extra}\n'


def closed_port_url() -> str:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        host, port = probe.getsockname()
    return f"http://{host}:{port}/feed.json"


class Workspace(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.config_path = self.root / "feeds.toml"
        self.report_path = self.root / "report.json"

    def write_config(self, text: str) -> Path:
        self.config_path.write_text(text, encoding="utf-8")
        return self.config_path

    def run_cli(self, config_text: str) -> tuple[int, dict]:
        self.write_config(config_text)
        code = main(["--config", str(self.config_path), "--output", str(self.report_path)])
        return code, json.loads(self.report_path.read_text(encoding="utf-8"))

    def run_one(self, server: FakeFeedServer, path: str, extra: str) -> dict:
        _, report = self.run_cli(FAST_RETRY + feed_table("feed", server.url(path), extra))
        (entry,) = report["feeds"]
        return entry


class HealthTests(Workspace, unittest.TestCase):
    def test_healthy_feed_reports_item_count_and_duration(self) -> None:
        routes = {"/ok": [json_reply(HTTPStatus.OK, {"items": ITEMS})]}
        with FakeFeedServer(routes, frozenset()) as server:
            code, report = self.run_cli(FAST_RETRY + feed_table("ok", server.url("/ok"), ""))
        self.assertEqual(code, EXIT_ALL_HEALTHY)
        self.assertTrue(report["all_healthy"])
        (entry,) = report["feeds"]
        self.assertEqual(entry["name"], "ok")
        self.assertEqual(entry["status"], "healthy")
        self.assertIsNone(entry["reason"])
        self.assertEqual(entry["items"], len(ITEMS))
        self.assertIsInstance(entry["duration_seconds"], float)
        self.assertGreaterEqual(entry["duration_seconds"], 0)

    def test_client_error_is_unhealthy_and_not_retried(self) -> None:
        routes = {"/gone": [json_reply(HTTPStatus.NOT_FOUND, {"items": []})]}
        with FakeFeedServer(routes, frozenset()) as server:
            entry = self.run_one(server, "/gone", "")
            self.assertEqual(server.requests["/gone"], 1)
        self.assertEqual(entry["status"], "unhealthy")
        self.assertEqual(entry["reason"], f"HTTP {HTTPStatus.NOT_FOUND.value}")
        self.assertIsNone(entry["items"])

    def test_server_error_is_retried_until_attempts_run_out(self) -> None:
        routes = {"/down": [json_reply(HTTPStatus.SERVICE_UNAVAILABLE, {})]}
        with FakeFeedServer(routes, frozenset()) as server:
            entry = self.run_one(server, "/down", "")
            attempts = load_config(self.config_path).retry.attempts
            self.assertEqual(server.requests["/down"], attempts)
        self.assertEqual(entry["status"], "unhealthy")
        self.assertIn(f"HTTP {HTTPStatus.SERVICE_UNAVAILABLE.value}", entry["reason"])

    def test_server_error_then_success_is_healthy(self) -> None:
        replies = [json_reply(HTTPStatus.BAD_GATEWAY, {}), json_reply(HTTPStatus.OK, {"items": ITEMS})]
        with FakeFeedServer({"/flaky": replies}, frozenset()) as server:
            entry = self.run_one(server, "/flaky", "")
            self.assertEqual(server.requests["/flaky"], len(replies))
        self.assertEqual(entry["status"], "healthy")
        self.assertEqual(entry["items"], len(ITEMS))

    def test_bodies_that_are_not_a_feed_are_unhealthy(self) -> None:
        routes = {
            "/text": [Reply(HTTPStatus.OK, b"<html>not json</html>")],
            "/list": [json_reply(HTTPStatus.OK, ITEMS)],
            "/no-items": [json_reply(HTTPStatus.OK, {"entries": ITEMS})],
            "/items-object": [json_reply(HTTPStatus.OK, {"items": {"a": ITEMS}})],
            "/binary": [Reply(HTTPStatus.OK, b"\xff\xfe\xfa")],
        }
        with FakeFeedServer(routes, frozenset()) as server:
            for path in routes:
                with self.subTest(path=path):
                    entry = self.run_one(server, path, "")
                    self.assertEqual(entry["status"], "unhealthy")
                    self.assertTrue(entry["reason"])

    def test_closed_port_is_unreachable(self) -> None:
        url = closed_port_url()
        code, report = self.run_cli(FAST_RETRY + feed_table("closed", url, ""))
        self.assertEqual(code, EXIT_NOT_ALL_HEALTHY)
        (entry,) = report["feeds"]
        self.assertEqual(entry["status"], "unreachable")
        self.assertIn("no answer", entry["reason"])
        self.assertIsNone(entry["items"])

    def test_feed_that_never_answers_times_out_and_is_retried(self) -> None:
        config = "timeout_seconds = 0.2\nattempts = 2\nretry_delay_seconds = 0\n"
        with FakeFeedServer({}, frozenset({"/hang"})) as server:
            _, report = self.run_cli(config + feed_table("hang", server.url("/hang"), ""))
            attempts = load_config(self.config_path).retry.attempts
            self.assertEqual(server.requests["/hang"], attempts)
        (entry,) = report["feeds"]
        self.assertEqual(entry["status"], "unreachable")
        self.assertIn("timed out", entry["reason"])

    def test_one_bad_feed_makes_exit_code_one_and_every_feed_is_listed(self) -> None:
        routes = {
            "/ok": [json_reply(HTTPStatus.OK, {"items": ITEMS})],
            "/bad": [json_reply(HTTPStatus.OK, {"items": None})],
        }
        with FakeFeedServer(routes, frozenset()) as server:
            tables = "".join(feed_table(path.strip("/"), server.url(path), "") for path in routes)
            code, report = self.run_cli(FAST_RETRY + tables)
        self.assertEqual(code, EXIT_NOT_ALL_HEALTHY)
        self.assertFalse(report["all_healthy"])
        statuses = {entry["name"]: entry["status"] for entry in report["feeds"]}
        self.assertEqual(statuses, {"ok": "healthy", "bad": "unhealthy"})


class FreshnessTests(Workspace, unittest.TestCase):
    def judge(self, items: list) -> dict:
        routes = {"/feed": [json_reply(HTTPStatus.OK, {"items": items})]}
        with FakeFeedServer(routes, frozenset()) as server:
            return self.run_one(server, "/feed", MAX_AGE_LINE)

    def test_recent_newest_item_is_healthy(self) -> None:
        items = [{"published": iso_hours_ago(MAX_AGE_HOURS + 1)}, {"published": iso_hours_ago(1)}]
        entry = self.judge(items)
        self.assertEqual(entry["status"], "healthy")
        self.assertEqual(entry["items"], len(items))

    def test_old_newest_item_is_stale(self) -> None:
        items = [{"published": iso_hours_ago(MAX_AGE_HOURS + 1)}]
        entry = self.judge(items)
        self.assertEqual(entry["status"], "stale")
        self.assertEqual(entry["items"], len(items))
        self.assertIn("older than", entry["reason"])

    def test_zulu_suffix_is_accepted(self) -> None:
        published = (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(self.judge([{"published": published}])["status"], "healthy")

    def test_empty_feed_with_max_age_is_stale(self) -> None:
        entry = self.judge([])
        self.assertEqual(entry["status"], "stale")
        self.assertEqual(entry["items"], 0)

    def test_bad_published_values_are_unhealthy(self) -> None:
        cases = {
            "missing": [{"title": "x"}],
            "not a string": [{"published": 1}],
            "not iso": [{"published": "yesterday"}],
            "no timezone": [{"published": "2026-01-01T00:00:00"}],
        }
        for label, items in cases.items():
            with self.subTest(case=label):
                entry = self.judge(items)
                self.assertEqual(entry["status"], "unhealthy")
                self.assertIn("published", entry["reason"])

    def test_max_age_is_ignored_when_not_set(self) -> None:
        routes = {"/feed": [json_reply(HTTPStatus.OK, {"items": [{"published": "long ago"}]})]}
        with FakeFeedServer(routes, frozenset()) as server:
            self.assertEqual(self.run_one(server, "/feed", "")["status"], "healthy")


class RetryDelayTests(Workspace, unittest.TestCase):
    def test_each_retry_waits_longer_than_the_one_before(self) -> None:
        config = "timeout_seconds = 2\nattempts = 4\nretry_delay_seconds = 0.5\n"
        routes = {"/down": [json_reply(HTTPStatus.INTERNAL_SERVER_ERROR, {})]}
        waits: list[float] = []
        with FakeFeedServer(routes, frozenset()) as server:
            loaded = load_config(self.write_config(config + feed_table("down", server.url("/down"), "")))
            result = check_feed(loaded.feeds[0], loaded, waits.append)
        self.assertEqual(result.verdict.status, "unhealthy")
        self.assertEqual(len(waits), loaded.retry.attempts - 1)
        self.assertGreater(waits[0], 0)
        self.assertEqual(waits, sorted(set(waits)))


class ConfigErrorTests(Workspace, unittest.TestCase):
    def assert_stops_before_fetching(self, config_text: str | None, expected: str) -> None:
        routes = {"/feed": [json_reply(HTTPStatus.OK, {"items": ITEMS})]}
        with FakeFeedServer(routes, frozenset()) as server:
            if config_text is not None:
                self.write_config(config_text.replace("FEED_URL", server.url("/feed")))
            with self.assertRaises(SystemExit) as raised:
                main(["--config", str(self.config_path), "--output", str(self.report_path)])
            self.assertEqual(server.requests["/feed"], 0)
        self.assertIsInstance(raised.exception, ConfigError)
        self.assertEqual(raised.exception.code, f"feedcheck: {raised.exception.message}")
        self.assertIn(expected, raised.exception.message)
        self.assertFalse(self.report_path.exists())

    def test_missing_file(self) -> None:
        self.assert_stops_before_fetching(None, "does not exist")

    def test_unreadable_file(self) -> None:
        self.config_path.mkdir()
        self.assert_stops_before_fetching(None, "cannot read")

    def test_invalid_encoding(self) -> None:
        self.config_path.write_bytes(b"\xff\xfe")
        self.assert_stops_before_fetching(None, "UTF-8")

    def test_invalid_configs(self) -> None:
        good_feed = feed_table("a", "FEED_URL", "")
        cases = {
            "not toml": ("timeout_seconds = = 1", "not valid TOML"),
            "missing timeout": ("attempts = 1\nretry_delay_seconds = 0\n" + good_feed, "timeout_seconds"),
            "zero attempts": (FAST_RETRY.replace("attempts = 3", "attempts = 0") + good_feed, "attempts"),
            "string timeout": (FAST_RETRY.replace("= 2", '= "2"') + good_feed, "timeout_seconds"),
            "negative delay": (FAST_RETRY.replace("delay_seconds = 0", "delay_seconds = -1") + good_feed, "retry"),
            "no feeds": (FAST_RETRY, "feeds"),
            "feed without url": (FAST_RETRY + '[[feeds]]\nname = "a"\n', "url"),
            "relative url": (FAST_RETRY + feed_table("a", "/feed.json", ""), "absolute"),
            "duplicate names": (FAST_RETRY + good_feed + good_feed, "unique"),
            "unknown key": (FAST_RETRY + feed_table("a", "FEED_URL", "colour = 1"), "unknown"),
            "bad max age": (FAST_RETRY + feed_table("a", "FEED_URL", "max_age_hours = 0"), "max_age_hours"),
            "one bad of two": (FAST_RETRY + good_feed + feed_table("b", "ftp://x/y", ""), "feeds[1]"),
        }
        for label, (text, expected) in cases.items():
            with self.subTest(case=label):
                self.assert_stops_before_fetching(text, expected)


if __name__ == "__main__":
    unittest.main()
