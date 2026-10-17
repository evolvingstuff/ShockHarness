import unittest
from datetime import datetime, timedelta, timezone

from feedcheck.checker import check_feed, parse_timestamp
from feedcheck.config import Config, FeedConfig
from tests.fakeserver import FakeFeedServer, closed_port_url

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


class CheckerTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeFeedServer().__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)
        self.sleeps: list[float] = []

    def check(self, path, *, max_age=None, attempts=3, timeout=2.0, url=None):
        feed = FeedConfig(name="f", url=url or self.server.url(path), max_age_hours=max_age)
        cfg = Config(feeds=[feed], timeout_seconds=timeout, attempts=attempts,
                     backoff_seconds=0.25)
        return check_feed(feed, cfg, sleep=self.sleeps.append, now=lambda: NOW)

    def test_healthy(self):
        self.server.routes["/ok"] = [(200, {"items": [{"id": 1}, {"id": 2}]})]
        r = self.check("/ok")
        self.assertEqual(r.status, "healthy")
        self.assertIsNone(r.reason)
        self.assertEqual(r.items, 2)
        self.assertEqual(r.attempts, 1)
        self.assertGreaterEqual(r.duration_seconds, 0)
        self.assertEqual(self.sleeps, [])

    def test_healthy_empty_items(self):
        self.server.routes["/ok"] = [(200, {"items": []})]
        r = self.check("/ok")
        self.assertEqual((r.status, r.items), ("healthy", 0))

    def test_not_found_is_unhealthy_without_retry(self):
        r = self.check("/missing")
        self.assertEqual(r.status, "unhealthy")
        self.assertIn("404", r.reason)
        self.assertEqual(r.attempts, 1)
        self.assertEqual(self.server.hits["/missing"], 1)

    def test_non_200_success_is_unhealthy(self):
        self.server.routes["/nc"] = [(204, b"")]
        r = self.check("/nc")
        self.assertEqual(r.status, "unhealthy")
        self.assertIn("204", r.reason)

    def test_invalid_json(self):
        self.server.routes["/bad"] = [(200, "not json{")]
        r = self.check("/bad")
        self.assertEqual(r.status, "unhealthy")
        self.assertIn("not valid JSON", r.reason)

    def test_not_an_object(self):
        self.server.routes["/list"] = [(200, [1, 2])]
        r = self.check("/list")
        self.assertEqual(r.status, "unhealthy")
        self.assertIn("not a JSON object", r.reason)

    def test_missing_items(self):
        self.server.routes["/x"] = [(200, {"entries": []})]
        r = self.check("/x")
        self.assertEqual(r.status, "unhealthy")
        self.assertIn("no 'items'", r.reason)

    def test_items_not_list(self):
        self.server.routes["/x"] = [(200, {"items": {"a": 1}})]
        r = self.check("/x")
        self.assertEqual(r.status, "unhealthy")
        self.assertIn("not a list", r.reason)

    def test_retries_5xx_then_succeeds_with_growing_backoff(self):
        self.server.routes["/flaky"] = [(503, "down"), (500, "down"), (200, {"items": [1]})]
        r = self.check("/flaky", attempts=3)
        self.assertEqual(r.status, "healthy")
        self.assertEqual(r.attempts, 3)
        self.assertEqual(self.server.hits["/flaky"], 3)
        self.assertEqual(self.sleeps, [0.25, 0.5])

    def test_persistent_5xx_is_unhealthy_after_all_attempts(self):
        self.server.routes["/down"] = [(502, "bad gateway")]
        r = self.check("/down", attempts=4)
        self.assertEqual(r.status, "unhealthy")
        self.assertIn("502", r.reason)
        self.assertIn("after 4 attempts", r.reason)
        self.assertEqual(self.server.hits["/down"], 4)
        self.assertEqual(self.sleeps, [0.25, 0.5, 1.0])
        self.assertIsNone(r.items)

    def test_single_attempt_does_not_retry(self):
        self.server.routes["/down"] = [(500, "x")]
        r = self.check("/down", attempts=1)
        self.assertEqual(self.server.hits["/down"], 1)
        self.assertEqual(self.sleeps, [])
        self.assertIn("after 1 attempt)", r.reason)

    def test_connection_refused_is_unreachable(self):
        r = self.check(None, url=closed_port_url(), attempts=2)
        self.assertEqual(r.status, "unreachable")
        self.assertIn("connection failed", r.reason)
        self.assertEqual(r.attempts, 2)
        self.assertEqual(self.sleeps, [0.25])

    def test_timeout_is_unreachable_and_retried(self):
        self.server.routes["/slow"] = [("sleep", 1.0, 200, {"items": []})]
        r = self.check("/slow", timeout=0.2, attempts=2)
        self.assertEqual(r.status, "unreachable")
        self.assertIn("timed out", r.reason)
        self.assertEqual(self.server.hits["/slow"], 2)

    def test_timeout_then_success(self):
        self.server.routes["/slow"] = [("sleep", 1.0, 200, {"items": []}), (200, {"items": [1]})]
        r = self.check("/slow", timeout=0.2, attempts=2)
        self.assertEqual(r.status, "healthy")
        self.assertEqual(r.attempts, 2)

    def test_dropped_connection_is_retried(self):
        self.server.routes["/drop"] = ["drop", (200, {"items": []})]
        r = self.check("/drop", attempts=2)
        self.assertEqual(r.status, "healthy")
        self.assertEqual(r.attempts, 2)

    def test_fresh_feed_is_healthy(self):
        items = [
            {"published": iso(NOW - timedelta(hours=30))},
            {"published": iso(NOW - timedelta(hours=2))},
        ]
        self.server.routes["/f"] = [(200, {"items": items})]
        r = self.check("/f", max_age=24)
        self.assertEqual(r.status, "healthy")
        self.assertEqual(r.items, 2)
        self.assertEqual(r.newest_item, (NOW - timedelta(hours=2)).isoformat())

    def test_old_feed_is_stale(self):
        items = [
            {"published": iso(NOW - timedelta(hours=50))},
            {"published": "2026-10-16T09:00:00+00:00"},  # 27h old, the newest
        ]
        self.server.routes["/f"] = [(200, {"items": items})]
        r = self.check("/f", max_age=24)
        self.assertEqual(r.status, "stale")
        self.assertIn("27.0h", r.reason)
        self.assertEqual(r.items, 2)

    def test_timezone_offsets_are_respected(self):
        # 13:00+02:00 is 11:00Z, one hour before NOW.
        self.server.routes["/f"] = [(200, {"items": [{"published": "2026-10-17T13:00:00+02:00"}]})]
        self.assertEqual(self.check("/f", max_age=1.5).status, "healthy")
        self.assertEqual(self.check("/f", max_age=0.5).status, "stale")

    def test_max_age_ignored_when_not_set(self):
        self.server.routes["/f"] = [(200, {"items": [{"published": "2000-01-01T00:00:00Z"}]})]
        self.assertEqual(self.check("/f").status, "healthy")

    def test_max_age_with_no_items_is_stale(self):
        self.server.routes["/f"] = [(200, {"items": []})]
        r = self.check("/f", max_age=24)
        self.assertEqual(r.status, "stale")
        self.assertIn("no items", r.reason)

    def test_max_age_with_bad_published_is_unhealthy(self):
        for bad in ({"published": "yesterday"}, {"title": "no date"}, "string item"):
            self.server.routes["/f"] = [(200, {"items": [{"published": iso(NOW)}, bad]})]
            r = self.check("/f", max_age=24)
            self.assertEqual(r.status, "unhealthy", bad)
            self.assertIn("item 1", r.reason)


class TimestampTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(
            parse_timestamp("2026-10-17T12:00:00Z"),
            datetime(2026, 10, 17, 12, tzinfo=timezone.utc),
        )
        self.assertEqual(
            parse_timestamp("2026-10-17T12:00:00"),
            datetime(2026, 10, 17, 12, tzinfo=timezone.utc),
        )
        self.assertEqual(
            parse_timestamp("2026-10-17T14:00:00.5+02:00"),
            datetime(2026, 10, 17, 12, 0, 0, 500000, tzinfo=timezone.utc),
        )
        self.assertIsNone(parse_timestamp("nope"))
        self.assertIsNone(parse_timestamp(12345))
        self.assertIsNone(parse_timestamp(None))


if __name__ == "__main__":
    unittest.main()
