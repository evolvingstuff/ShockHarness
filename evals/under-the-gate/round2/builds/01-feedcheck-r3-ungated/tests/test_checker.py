import os
import socket
import unittest
from datetime import datetime, timedelta, timezone

from feedcheck.checker import (
    HEALTHY,
    STALE,
    UNHEALTHY,
    UNREACHABLE,
    check_feed,
)
from feedcheck.config import Config, Feed
from tests.fakeserver import FakeFeedServer, drop_connection, slow

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)


def setUpModule():
    # Never route the local fake server through a proxy from the environment.
    for var in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        os.environ.pop(var, None)
    os.environ["no_proxy"] = "*"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class CheckerTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeFeedServer().__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)
        self.sleeps = []

    def check(self, url, *, max_age_hours=None, attempts=3, timeout=2.0, backoff=0.5):
        config = Config(
            feeds=[],
            timeout_seconds=timeout,
            attempts=attempts,
            backoff_seconds=backoff,
        )
        feed = Feed(name="f", url=url, max_age_hours=max_age_hours)
        return check_feed(feed, config, sleep=self.sleeps.append, now=lambda: NOW)

    # --- healthy / unhealthy -------------------------------------------------

    def test_healthy(self):
        url = self.server.route("/ok", (200, {"items": [{"id": 1}, {"id": 2}]}))
        r = self.check(url)
        self.assertEqual(r.status, HEALTHY)
        self.assertIsNone(r.reason)
        self.assertEqual(r.items, 2)
        self.assertEqual(r.attempts, 1)
        self.assertGreaterEqual(r.duration_seconds, 0)

    def test_empty_items_is_healthy_without_max_age(self):
        url = self.server.route("/empty", (200, {"items": []}))
        r = self.check(url)
        self.assertEqual((r.status, r.items), (HEALTHY, 0))

    def test_invalid_json(self):
        url = self.server.route("/bad", (200, "{not json"))
        r = self.check(url)
        self.assertEqual(r.status, UNHEALTHY)
        self.assertIn("not valid JSON", r.reason)
        self.assertEqual(r.attempts, 1)

    def test_not_an_object(self):
        url = self.server.route("/list", (200, [1, 2]))
        r = self.check(url)
        self.assertEqual(r.status, UNHEALTHY)
        self.assertIn("not a JSON object", r.reason)

    def test_missing_items(self):
        url = self.server.route("/noitems", (200, {"entries": []}))
        r = self.check(url)
        self.assertEqual(r.status, UNHEALTHY)
        self.assertIn("'items'", r.reason)

    def test_items_not_list(self):
        url = self.server.route("/dict", (200, {"items": {"a": 1}}))
        r = self.check(url)
        self.assertEqual(r.status, UNHEALTHY)
        self.assertIn("not a list", r.reason)

    def test_4xx_is_unhealthy_without_retry(self):
        url = self.server.url("/missing")  # unrouted -> 404
        r = self.check(url)
        self.assertEqual(r.status, UNHEALTHY)
        self.assertIn("404", r.reason)
        self.assertEqual(self.server.hits["/missing"], 1)
        self.assertEqual(self.sleeps, [])

    def test_non_200_success_is_unhealthy(self):
        url = self.server.route("/nocontent", (204, b""))
        r = self.check(url)
        self.assertEqual(r.status, UNHEALTHY)
        self.assertIn("204", r.reason)

    # --- retries ---------------------------------------------------------------

    def test_5xx_retried_then_succeeds(self):
        url = self.server.route(
            "/flaky", (503, "down"), (500, "down"), (200, {"items": [1]})
        )
        r = self.check(url, attempts=3)
        self.assertEqual(r.status, HEALTHY)
        self.assertEqual(r.attempts, 3)
        self.assertEqual(self.server.hits["/flaky"], 3)

    def test_5xx_exhausts_attempts(self):
        url = self.server.route("/down", (502, "bad gateway"))
        r = self.check(url, attempts=4)
        self.assertEqual(r.status, UNHEALTHY)
        self.assertIn("502", r.reason)
        self.assertEqual(self.server.hits["/down"], 4)
        self.assertEqual(r.attempts, 4)

    def test_backoff_grows(self):
        url = self.server.route("/down", (500, "x"))
        self.check(url, attempts=4, backoff=0.5)
        self.assertEqual(len(self.sleeps), 3)  # no wait before the first attempt
        self.assertTrue(all(b > a for a, b in zip(self.sleeps, self.sleeps[1:])), self.sleeps)
        self.assertGreater(self.sleeps[0], 0)

    def test_single_attempt_means_no_retry(self):
        url = self.server.route("/down", (500, "x"))
        r = self.check(url, attempts=1)
        self.assertEqual(self.server.hits["/down"], 1)
        self.assertEqual(r.status, UNHEALTHY)
        self.assertEqual(self.sleeps, [])

    def test_connection_refused_is_unreachable_and_retried(self):
        r = self.check(f"http://127.0.0.1:{free_port()}/feed", attempts=3)
        self.assertEqual(r.status, UNREACHABLE)
        self.assertEqual(r.attempts, 3)
        self.assertEqual(len(self.sleeps), 2)
        self.assertIsNone(r.items)

    def test_timeout_is_unreachable(self):
        url = self.server.route("/slow", slow(1.5))
        r = self.check(url, attempts=2, timeout=0.3)
        self.assertEqual(r.status, UNREACHABLE)
        self.assertIn("timed out", r.reason)
        self.assertEqual(self.server.hits["/slow"], 2)
        self.assertLess(r.duration_seconds, 1.5)

    def test_dropped_connection_is_unreachable(self):
        url = self.server.route("/drop", drop_connection)
        r = self.check(url, attempts=2)
        self.assertEqual(r.status, UNREACHABLE)
        self.assertEqual(self.server.hits["/drop"], 2)

    def test_recovers_after_dropped_connection(self):
        url = self.server.route("/drop", drop_connection, (200, {"items": []}))
        r = self.check(url, attempts=2)
        self.assertEqual(r.status, HEALTHY)

    # --- staleness -------------------------------------------------------------

    def iso(self, hours_ago):
        return (NOW - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")

    def test_fresh_feed_is_healthy(self):
        url = self.server.route("/fresh", (200, {"items": [
            {"published": self.iso(30)},
            {"published": self.iso(1)},
        ]}))
        r = self.check(url, max_age_hours=24)
        self.assertEqual(r.status, HEALTHY)
        self.assertEqual(r.items, 2)

    def test_old_feed_is_stale(self):
        url = self.server.route("/old", (200, {"items": [
            {"published": self.iso(48)},
            {"published": self.iso(30)},
        ]}))
        r = self.check(url, max_age_hours=24)
        self.assertEqual(r.status, STALE)
        self.assertEqual(r.items, 2)
        self.assertIn("30.0h", r.reason)

    def test_newest_item_wins_regardless_of_order(self):
        url = self.server.route("/order", (200, {"items": [
            {"published": self.iso(100)},
            {"published": self.iso(2)},
            {"published": self.iso(50)},
        ]}))
        self.assertEqual(self.check(url, max_age_hours=24).status, HEALTHY)

    def test_timezone_offsets_compared_correctly(self):
        # 10:00 at -05:00 is 15:00 UTC, i.e. in the future relative to NOW - fresh.
        url = self.server.route("/tz", (200, {"items": [{"published": "2026-10-17T10:00:00-05:00"}]}))
        self.assertEqual(self.check(url, max_age_hours=1).status, HEALTHY)
        # 13:00 at +05:00 is 08:00 UTC, four hours before NOW - stale for max 1h.
        url = self.server.route("/tz2", (200, {"items": [{"published": "2026-10-17T13:00:00+05:00"}]}))
        self.assertEqual(self.check(url, max_age_hours=1).status, STALE)

    def test_max_age_ignored_when_unset(self):
        url = self.server.route("/old", (200, {"items": [{"published": self.iso(1000)}]}))
        self.assertEqual(self.check(url).status, HEALTHY)

    def test_no_items_with_max_age_is_stale(self):
        url = self.server.route("/none", (200, {"items": []}))
        r = self.check(url, max_age_hours=24)
        self.assertEqual(r.status, STALE)
        self.assertEqual(r.items, 0)

    def test_bad_timestamps_ignored_but_all_bad_is_stale(self):
        url = self.server.route("/mixed", (200, {"items": [
            {"published": "yesterday"},
            {"published": 12345},
            "not an object",
            {"published": self.iso(3)},
        ]}))
        self.assertEqual(self.check(url, max_age_hours=24).status, HEALTHY)
        url = self.server.route("/allbad", (200, {"items": [{"published": "nope"}, {}]}))
        r = self.check(url, max_age_hours=24)
        self.assertEqual(r.status, STALE)
        self.assertIn("published", r.reason)


if __name__ == "__main__":
    unittest.main()
