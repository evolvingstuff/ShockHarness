import json
import tempfile
import threading
import tomllib
import unittest
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import feedcheck

NOW = datetime.fromisoformat("2026-01-01T00:00:00+00:00")
SETTINGS = '[settings]\ntimeout_seconds = 1\nattempts = 3\nbackoff_seconds = 0\n'


def stamp(hours_ago: str) -> str:
    return (NOW - timedelta(hours=float(hours_ago))).isoformat()


class FakeFeeds(BaseHTTPRequestHandler):
    hits: dict[str, int] = {}
    routes: dict[str, list[tuple[int, bytes]]] = {}

    def do_GET(self) -> None:
        if self.path not in FakeFeeds.hits:
            FakeFeeds.hits[self.path] = 0
        FakeFeeds.hits[self.path] += 1
        answers = FakeFeeds.routes[self.path]
        status, body = answers[min(FakeFeeds.hits[self.path], len(answers)) - 1]
        self.send_response(status)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def ok(document: object) -> tuple[int, bytes]:
    return HTTPStatus.OK, json.dumps(document).encode()


class FeedcheckTest(unittest.TestCase):
    def setUp(self) -> None:
        FakeFeeds.hits = {}
        FakeFeeds.routes = {}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeFeeds)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.tmp = Path(tempfile.mkdtemp())

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.server.server_port}{path}"

    def run_tool(self, feeds_toml: str) -> tuple[int, dict]:
        config = self.tmp / "feeds.toml"
        config.write_text(SETTINGS + feeds_toml)
        output = self.tmp / "report.json"
        code = feedcheck.main(["--config", str(config), "--output", str(output)])
        return code, json.loads(output.read_text())

    def feed(self, name: str, path: str, extra: str) -> str:
        return f'[[feeds]]\nname = "{name}"\nurl = "{self.url(path)}"\n{extra}\n'

    def status_of(self, report: dict, name: str) -> dict:
        return next(f for f in report["feeds"] if f["name"] == name)

    def test_healthy_feed(self) -> None:
        FakeFeeds.routes["/a"] = [ok({"items": [{}, {}]})]
        code, report = self.run_tool(self.feed("a", "/a", ""))
        self.assertEqual(code, feedcheck.EXIT_OK)
        entry = self.status_of(report, "a")
        self.assertEqual(entry["status"], "healthy")
        self.assertEqual(entry["items"], len(FakeFeeds.routes["/a"]) + 1)
        self.assertGreaterEqual(entry["elapsed_seconds"], 0)

    def test_unhealthy_variants(self) -> None:
        FakeFeeds.routes["/notjson"] = [(HTTPStatus.OK, b"<html>")]
        FakeFeeds.routes["/noitems"] = [ok({"items": "x"})]
        FakeFeeds.routes["/list"] = [ok([])]
        FakeFeeds.routes["/missing"] = [(HTTPStatus.NOT_FOUND, b"")]
        toml = "".join(self.feed(n, "/" + n, "") for n in ("notjson", "noitems", "list", "missing"))
        code, report = self.run_tool(toml)
        self.assertEqual(code, feedcheck.EXIT_UNHEALTHY)
        for name in ("notjson", "noitems", "list", "missing"):
            entry = self.status_of(report, name)
            self.assertEqual(entry["status"], "unhealthy", name)
            self.assertTrue(entry["reason"])
        self.assertEqual(FakeFeeds.hits["/missing"], 1)

    def test_retry_on_5xx_then_success(self) -> None:
        FakeFeeds.routes["/r"] = [(HTTPStatus.SERVICE_UNAVAILABLE, b""), ok({"items": []})]
        code, report = self.run_tool(self.feed("r", "/r", ""))
        self.assertEqual(code, feedcheck.EXIT_OK)
        self.assertEqual(FakeFeeds.hits["/r"], len(FakeFeeds.routes["/r"]))

    def test_5xx_exhausts_attempts(self) -> None:
        FakeFeeds.routes["/down"] = [(HTTPStatus.BAD_GATEWAY, b"")]
        code, report = self.run_tool(self.feed("down", "/down", ""))
        self.assertEqual(code, feedcheck.EXIT_UNHEALTHY)
        self.assertEqual(self.status_of(report, "down")["status"], "unreachable")
        self.assertEqual(FakeFeeds.hits["/down"], tomllib.loads(SETTINGS)["settings"]["attempts"])

    def test_no_answer_is_unreachable(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        code, report = self.run_tool(self.feed("gone", "/x", ""))
        self.assertEqual(code, feedcheck.EXIT_UNHEALTHY)
        self.assertEqual(self.status_of(report, "gone")["status"], "unreachable")

    def test_stale_and_fresh(self) -> None:
        FakeFeeds.routes["/old"] = [ok({"items": [{"published": stamp("10")}, {"published": stamp("5")}]})]
        FakeFeeds.routes["/new"] = [ok({"items": [{"published": stamp("1")}, {"published": stamp("10")}]})]
        feeds = self.feed("old", "/old", "max_age_hours = 2") + self.feed("new", "/new", "max_age_hours = 2")
        feeds += self.feed("noage", "/old", "")
        results = feedcheck.run_checks(feedcheck.parse_config(SETTINGS + feeds), NOW)
        by_name = {r.name: r.status for r in results}
        self.assertEqual(by_name, {"old": "stale", "new": "healthy", "noage": "healthy"})

    def test_max_age_without_published_is_unhealthy(self) -> None:
        FakeFeeds.routes["/p"] = [ok({"items": [{"title": "t"}]})]
        code, report = self.run_tool(self.feed("p", "/p", "max_age_hours = 1"))
        self.assertEqual(self.status_of(report, "p")["status"], "unhealthy")

    def test_bad_config_stops_before_fetching(self) -> None:
        bad = {
            "not toml": "this is = = bad",
            "no settings": '[[feeds]]\nname = "a"\nurl = "http://x"\n',
            "bad attempts": SETTINGS.replace("attempts = 3", "attempts = 0") + self.feed("a", "/a", ""),
            "bad url": SETTINGS + '[[feeds]]\nname = "a"\nurl = "nonsense"\n',
            "no url": SETTINGS + '[[feeds]]\nname = "a"\n',
        }
        for label, text in bad.items():
            config = self.tmp / "bad.toml"
            config.write_text(text)
            with self.subTest(label), self.assertRaises(SystemExit) as raised:
                feedcheck.main(["--config", str(config), "--output", str(self.tmp / "o.json")])
            self.assertEqual(raised.exception.code, feedcheck.EXIT_CONFIG)
        self.assertEqual(FakeFeeds.hits, {})
        self.assertFalse((self.tmp / "o.json").exists())

    def test_missing_config(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            feedcheck.main(["--config", str(self.tmp / "nope.toml"), "--output", str(self.tmp / "o.json")])
        self.assertEqual(raised.exception.code, feedcheck.EXIT_CONFIG)


if __name__ == "__main__":
    unittest.main()
