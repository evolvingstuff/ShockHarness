import io
import json
import tempfile
import tomllib
import unittest
from contextlib import redirect_stderr
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from pathlib import Path

from feedcheck.cli import EXIT_CONFIG_ERROR, EXIT_HEALTHY, EXIT_UNHEALTHY, main
from feedcheck.config import load_config
from feedcheck.fetch import Answer, NoAnswer, RetryPolicy, fetch
from tests.fake_server import FakeFeedServer, Reply, json_reply, recording_sleep, unused_port_url

VALUES_PATH = Path(__file__).parent / "fixtures" / "values.toml"


def values() -> dict[str, float]:
    return tomllib.loads(VALUES_PATH.read_text(encoding="utf-8"))


def iso_hours_ago(hours: float) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours)).isoformat()


def config_text(feeds: list[dict[str, object]], timeout: float, attempts: int, backoff: float) -> str:
    lines = [f"timeout_seconds = {timeout}", f"attempts = {attempts}", f"retry_backoff_seconds = {backoff}"]
    for feed in feeds:
        lines.append("[[feeds]]")
        for key, value in feed.items():
            lines.append(f"{key} = {json.dumps(value)}")
    return "\n".join(lines) + "\n"


def standard_config(feeds: list[dict[str, object]]) -> str:
    """Config text with the fixture timeout and attempts, and no wait between attempts."""
    fixture = values()
    return config_text(feeds, fixture["timeout_seconds"], fixture["attempts"], backoff=0)


class CliTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.config_path = self.dir / "feeds.toml"
        self.report_path = self.dir / "report.json"
        self.values = values()

    def run_cli(self, text: str) -> tuple[int, dict]:
        self.config_path.write_text(text, encoding="utf-8")
        code = main(["--config", str(self.config_path), "--output", str(self.report_path)])
        return code, json.loads(self.report_path.read_text(encoding="utf-8"))

    def feed(self, report: dict, name: str) -> dict:
        return next(entry for entry in report["feeds"] if entry["name"] == name)


class HealthTests(CliTestCase):
    def test_all_healthy_exits_zero_and_reports_every_feed(self) -> None:
        items = [{"id": "first"}, {"id": "second"}]
        with FakeFeedServer() as server:
            server.routes["/a"] = [json_reply(HTTPStatus.OK, {"items": items})]
            server.routes["/b"] = [json_reply(HTTPStatus.OK, {"items": []})]
            code, report = self.run_cli(
                standard_config([{"name": "a", "url": server.url("/a")}, {"name": "b", "url": server.url("/b")}])
            )
        self.assertEqual(code, EXIT_HEALTHY)
        self.assertTrue(report["healthy"])
        self.assertEqual([entry["name"] for entry in report["feeds"]], ["a", "b"])
        a = self.feed(report, "a")
        self.assertEqual(a["status"], "healthy")
        self.assertIsNone(a["reason"])
        self.assertEqual(a["items"], len(items))
        self.assertIsInstance(a["duration_seconds"], float)
        self.assertGreaterEqual(a["duration_seconds"], 0)
        self.assertEqual(self.feed(report, "b")["items"], 0)

    def test_unhealthy_bodies(self) -> None:
        cases = {
            "/notjson": Reply(HTTPStatus.OK, b"<html>"),
            "/array": json_reply(HTTPStatus.OK, ["a", "b"]),
            "/noitems": json_reply(HTTPStatus.OK, {"entries": []}),
            "/itemsdict": json_reply(HTTPStatus.OK, {"items": {}}),
            "/missing": json_reply(HTTPStatus.NOT_FOUND, {"items": []}),
        }
        with FakeFeedServer() as server:
            for path, reply in cases.items():
                server.routes[path] = [reply]
            code, report = self.run_cli(standard_config([{"name": p, "url": server.url(p)} for p in cases]))
            self.assertEqual(server.hits["/missing"], 1, "a 4xx answer is not retried")
        self.assertEqual(code, EXIT_UNHEALTHY)
        self.assertFalse(report["healthy"])
        for path in cases:
            entry = self.feed(report, path)
            self.assertEqual(entry["status"], "unhealthy", path)
            self.assertTrue(entry["reason"], path)
        self.assertIn(str(HTTPStatus.NOT_FOUND.value), self.feed(report, "/missing")["reason"])
        self.assertIn("JSON", self.feed(report, "/notjson")["reason"])

    def test_one_unhealthy_feed_makes_exit_one(self) -> None:
        with FakeFeedServer() as server:
            server.routes["/ok"] = [json_reply(HTTPStatus.OK, {"items": []})]
            server.routes["/bad"] = [Reply(HTTPStatus.OK, b"nope")]
            code, _ = self.run_cli(
                standard_config([{"name": "ok", "url": server.url("/ok")}, {"name": "bad", "url": server.url("/bad")}])
            )
        self.assertEqual(code, EXIT_UNHEALTHY)


class RetryTests(CliTestCase):
    def test_server_error_then_success_is_healthy(self) -> None:
        attempts = self.values["attempts"]
        with FakeFeedServer() as server:
            failures = [json_reply(HTTPStatus.SERVICE_UNAVAILABLE, {})] * (attempts - 1)
            server.routes["/f"] = [*failures, json_reply(HTTPStatus.OK, {"items": [{}]})]
            code, report = self.run_cli(standard_config([{"name": "f", "url": server.url("/f")}]))
            self.assertEqual(server.hits["/f"], attempts)
        self.assertEqual(code, EXIT_HEALTHY)
        self.assertEqual(self.feed(report, "f")["items"], 1)

    def test_server_error_on_every_attempt_is_unhealthy(self) -> None:
        with FakeFeedServer() as server:
            server.routes["/f"] = [json_reply(HTTPStatus.BAD_GATEWAY, {})]
            code, report = self.run_cli(standard_config([{"name": "f", "url": server.url("/f")}]))
            self.assertEqual(server.hits["/f"], self.values["attempts"])
        self.assertEqual(code, EXIT_UNHEALTHY)
        self.assertEqual(self.feed(report, "f")["status"], "unhealthy")
        self.assertIn(str(HTTPStatus.BAD_GATEWAY.value), self.feed(report, "f")["reason"])

    def test_no_listener_is_unreachable(self) -> None:
        code, report = self.run_cli(standard_config([{"name": "gone", "url": unused_port_url("/f")}]))
        self.assertEqual(code, EXIT_UNHEALTHY)
        entry = self.feed(report, "gone")
        self.assertEqual(entry["status"], "unreachable")
        self.assertTrue(entry["reason"])
        self.assertIsNone(entry["items"])

    def test_timeout_is_unreachable_after_all_attempts(self) -> None:
        attempts = self.values["attempts"]
        with FakeFeedServer() as server:
            server.routes["/slow"] = [json_reply(HTTPStatus.OK, {"items": []})]
            server.slow_paths.add("/slow")
            text = config_text(
                [{"name": "slow", "url": server.url("/slow")}],
                timeout=self.values["short_timeout_seconds"],
                attempts=attempts,
                backoff=0,
            )
            code, report = self.run_cli(text)
            self.assertEqual(server.hits["/slow"], attempts)
        self.assertEqual(code, EXIT_UNHEALTHY)
        self.assertEqual(self.feed(report, "slow")["status"], "unreachable")

    def policy(self) -> RetryPolicy:
        return RetryPolicy(
            timeout_seconds=self.values["timeout_seconds"],
            attempts=self.values["attempts"],
            retry_backoff_seconds=self.values["retry_backoff_seconds"],
        )

    def expected_waits(self) -> list[float]:
        backoff = self.values["retry_backoff_seconds"]
        return [backoff * retry for retry in range(1, self.values["attempts"])]

    def test_waits_grow_between_attempts(self) -> None:
        waits: list[float] = []
        with FakeFeedServer() as server:
            server.routes["/f"] = [json_reply(HTTPStatus.INTERNAL_SERVER_ERROR, {})]
            outcome = fetch(server.url("/f"), self.policy(), recording_sleep(waits))
            self.assertEqual(server.hits["/f"], self.values["attempts"])
        self.assertEqual(outcome, Answer(status=HTTPStatus.INTERNAL_SERVER_ERROR, body=b""))
        self.assertEqual(waits, self.expected_waits())
        self.assertEqual(waits, sorted(set(waits)), "each wait is longer than the one before")

    def test_no_wait_without_retry(self) -> None:
        waits: list[float] = []
        with FakeFeedServer() as server:
            server.routes["/f"] = [json_reply(HTTPStatus.OK, {"items": []})]
            fetch(server.url("/f"), self.policy(), recording_sleep(waits))
            self.assertEqual(server.hits["/f"], 1)
        self.assertEqual(waits, [])

    def test_unreachable_is_retried(self) -> None:
        waits: list[float] = []
        outcome = fetch(unused_port_url("/f"), self.policy(), recording_sleep(waits))
        self.assertIsInstance(outcome, NoAnswer)
        self.assertEqual(waits, self.expected_waits())


class StalenessTests(CliTestCase):
    def check(self, document: object) -> dict:
        with FakeFeedServer() as server:
            server.routes["/f"] = [json_reply(HTTPStatus.OK, document)]
            feed = {"name": "f", "url": server.url("/f"), "max_age_hours": self.values["max_age_hours"]}
            _, report = self.run_cli(standard_config([feed]))
        return self.feed(report, "f")

    def test_fresh_feed_is_healthy(self) -> None:
        max_age = self.values["max_age_hours"]
        items = [{"published": iso_hours_ago(max_age + 1)}, {"published": iso_hours_ago(max_age - 1)}]
        entry = self.check({"items": items})
        self.assertEqual(entry["status"], "healthy")
        self.assertEqual(entry["items"], len(items))

    def test_old_newest_item_is_stale(self) -> None:
        max_age = self.values["max_age_hours"]
        items = [{"published": iso_hours_ago(max_age + max_age)}, {"published": iso_hours_ago(max_age + 1)}]
        entry = self.check({"items": items})
        self.assertEqual(entry["status"], "stale")
        self.assertIn(f"{max_age:g} hours", entry["reason"])
        self.assertEqual(entry["items"], len(items))

    def test_zulu_suffix_is_accepted(self) -> None:
        published = (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(self.check({"items": [{"published": published}]})["status"], "healthy")

    def test_empty_feed_with_max_age_is_stale(self) -> None:
        self.assertEqual(self.check({"items": []})["status"], "stale")

    def test_bad_published_values_are_unhealthy(self) -> None:
        cases = (
            [{"title": "x"}],
            [{"published": "yesterday"}],
            [{"published": ["2024-01-01T00:00:00Z"]}],
            ["x"],
            [{"published": "2024-01-01T00:00:00"}],
        )
        for items in cases:
            with self.subTest(items=items):
                entry = self.check({"items": items})
                self.assertEqual(entry["status"], "unhealthy")
                self.assertTrue(entry["reason"])

    def test_without_max_age_published_is_not_checked(self) -> None:
        with FakeFeedServer() as server:
            server.routes["/f"] = [json_reply(HTTPStatus.OK, {"items": [{"published": "1999-01-01T00:00:00Z"}]})]
            code, _ = self.run_cli(standard_config([{"name": "f", "url": server.url("/f")}]))
        self.assertEqual(code, EXIT_HEALTHY)


class ConfigTests(CliTestCase):
    def assert_config_error(self, text: str | None, expected: str) -> None:
        if text is not None:
            self.config_path.write_text(text, encoding="utf-8")
        stderr = io.StringIO()
        with redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            main(["--config", str(self.config_path), "--output", str(self.report_path)])
        self.assertEqual(raised.exception.code, EXIT_CONFIG_ERROR)
        self.assertIn(expected, stderr.getvalue())
        self.assertFalse(self.report_path.exists())

    def test_missing_file(self) -> None:
        self.assert_config_error(None, "cannot read config file")

    def test_unreadable_file(self) -> None:
        self.config_path.mkdir()
        self.assert_config_error(None, "cannot read config file")

    def test_invalid_toml(self) -> None:
        self.assert_config_error("feeds = [", "not valid TOML")

    def test_invalid_values(self) -> None:
        good = {"name": "a", "url": "http://127.0.0.1/a"}
        timeout = self.values["timeout_seconds"]
        attempts = self.values["attempts"]
        cases = [
            ("attempts = 1\nretry_backoff_seconds = 0\n[[feeds]]\nname='a'\nurl='http://x/'\n", "timeout_seconds"),
            (config_text([good], timeout, attempts=0, backoff=0), "attempts"),
            (config_text([good], -timeout, attempts, backoff=0), "timeout_seconds"),
            (config_text([good], timeout, attempts, backoff=-1), "retry_backoff_seconds"),
            (standard_config([]), "feeds"),
            (standard_config([{"name": "a"}]), "url"),
            (standard_config([{"name": "a", "url": "ftp://x/"}]), "url"),
            (standard_config([{"name": "", "url": "http://x/"}]), "name"),
            (standard_config([good, good]), "unique"),
            (standard_config([{**good, "max_age_hours": 0}]), "max_age_hours"),
            (standard_config([{**good, "colour": "red"}]), "colour"),
            ("attempts = true\ntimeout_seconds = 1\nretry_backoff_seconds = 0\n[[feeds]]\nname='a'\nurl='http://x/'\n",
             "attempts"),
        ]
        for text, expected in cases:
            with self.subTest(expected=expected):
                self.assert_config_error(text, expected)

    def test_invalid_config_fetches_nothing(self) -> None:
        with FakeFeedServer() as server:
            server.routes["/a"] = [json_reply(HTTPStatus.OK, {"items": []})]
            text = standard_config([{"name": "a", "url": server.url("/a")}, {"name": "b", "url": "nope"}])
            self.assert_config_error(text, "url")
            self.assertEqual(server.total_hits(), 0)

    def test_valid_config_loads(self) -> None:
        feed = {"name": "a", "url": "https://example.org/a", "max_age_hours": self.values["max_age_hours"]}
        self.config_path.write_text(
            config_text(
                [feed],
                self.values["timeout_seconds"],
                self.values["attempts"],
                self.values["retry_backoff_seconds"],
            ),
            encoding="utf-8",
        )
        config = load_config(self.config_path)
        self.assertEqual(config.timeout_seconds, self.values["timeout_seconds"])
        self.assertEqual(config.attempts, self.values["attempts"])
        self.assertEqual(config.retry_backoff_seconds, self.values["retry_backoff_seconds"])
        self.assertEqual(config.feeds[0].max_age_hours, self.values["max_age_hours"])
        self.assertEqual(config.feeds[0].name, "a")


if __name__ == "__main__":
    unittest.main()
