import unittest
from datetime import datetime, timedelta, timezone

from feedcheck.checker import (
    HEALTHY,
    STALE,
    UNHEALTHY,
    UNREACHABLE,
    build_report,
    check_all,
    check_feed,
    parse_timestamp,
)
from feedcheck.config import Config, Feed
from tests.fakeserver import FakeFeedServer, Route, unused_port_url


def iso(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) - delta).isoformat()


class CheckFeedTest(unittest.TestCase):
    def setUp(self):
        self.server = FakeFeedServer().__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)
        self.sleeps: list[float] = []

    def check(self, path, route=None, attempts=3, timeout=2.0, max_age_hours=None, url=None):
        if route is not None:
            self.server.routes[path] = route
        feed = Feed(name=path.strip("/"), url=url or self.server.url(path), max_age_hours=max_age_hours)
        config = Config(feeds=[feed], timeout_seconds=timeout, attempts=attempts, backoff_seconds=0.5)
        return check_feed(feed, config, sleep=self.sleeps.append)

    def test_healthy_feed(self):
        result = self.check("/ok", Route({"items": [{"id": 1}, {"id": 2}]}))
        self.assertEqual(result.status, HEALTHY)
        self.assertIsNone(result.reason)
        self.assertEqual(result.items, 2)
        self.assertEqual(result.attempts, 1)
        self.assertGreaterEqual(result.duration_seconds, 0)

    def test_empty_items_list_is_healthy_without_max_age(self):
        result = self.check("/empty", Route({"items": []}))
        self.assertEqual((result.status, result.items), (HEALTHY, 0))

    def test_invalid_json_is_unhealthy(self):
        result = self.check("/bad", Route(raw=b"<html>oops</html>"))
        self.assertEqual(result.status, UNHEALTHY)
        self.assertIn("not valid JSON", result.reason)
        self.assertIsNone(result.items)

    def test_non_object_json_is_unhealthy(self):
        result = self.check("/list", Route(raw=b"[1, 2]"))
        self.assertEqual(result.status, UNHEALTHY)
        self.assertIn("not an object", result.reason)

    def test_missing_items_is_unhealthy(self):
        result = self.check("/noitems", Route({"entries": []}))
        self.assertEqual(result.status, UNHEALTHY)
        self.assertIn("no 'items'", result.reason)

    def test_items_not_a_list_is_unhealthy(self):
        result = self.check("/dict", Route({"items": {"a": 1}}))
        self.assertEqual(result.status, UNHEALTHY)
        self.assertIn("not a list", result.reason)

    def test_4xx_is_unhealthy_and_not_retried(self):
        result = self.check("/missing", Route(statuses=[404]))
        self.assertEqual(result.status, UNHEALTHY)
        self.assertEqual(result.reason, "HTTP 404")
        self.assertEqual(self.server.hits["/missing"], 1)
        self.assertEqual(self.sleeps, [])

    def test_non_200_success_is_unhealthy(self):
        result = self.check("/nocontent", Route(statuses=[204], raw=b""))
        self.assertEqual(result.status, UNHEALTHY)
        self.assertEqual(result.reason, "HTTP 204")

    def test_5xx_is_retried_with_growing_delay(self):
        result = self.check("/flaky", Route({"items": [1]}, statuses=[503, 500, 200]))
        self.assertEqual(result.status, HEALTHY)
        self.assertEqual(result.attempts, 3)
        self.assertEqual(self.server.hits["/flaky"], 3)
        self.assertEqual(self.sleeps, [0.5, 1.0])

    def test_5xx_on_every_attempt_is_unhealthy(self):
        result = self.check("/down", Route(statuses=[502]), attempts=4)
        self.assertEqual(result.status, UNHEALTHY)
        self.assertIn("HTTP 502", result.reason)
        self.assertIn("4 attempts", result.reason)
        self.assertEqual(self.server.hits["/down"], 4)
        self.assertEqual(self.sleeps, [0.5, 1.0, 2.0])

    def test_single_attempt_is_not_retried(self):
        result = self.check("/once", Route(statuses=[500]), attempts=1)
        self.assertEqual(result.status, UNHEALTHY)
        self.assertEqual(result.reason, "HTTP 500")
        self.assertEqual(self.server.hits["/once"], 1)

    def test_connection_refused_is_unreachable_after_retries(self):
        result = self.check("/gone", url=unused_port_url(), attempts=2)
        self.assertEqual(result.status, UNREACHABLE)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(self.sleeps, [0.5])
        self.assertIsNone(result.items)

    def test_timeout_is_unreachable(self):
        result = self.check("/slow", Route({"items": []}, delay=1.0), attempts=2, timeout=0.2)
        self.assertEqual(result.status, UNREACHABLE)
        self.assertIn("timed out", result.reason)
        self.assertEqual(self.server.hits["/slow"], 2)

    def test_dropped_connection_is_unreachable(self):
        result = self.check("/drop", Route(drop=True), attempts=2)
        self.assertEqual(result.status, UNREACHABLE)
        self.assertEqual(self.server.hits["/drop"], 2)

    def test_fresh_feed_with_max_age_is_healthy(self):
        body = {"items": [{"published": iso(timedelta(hours=30))}, {"published": iso(timedelta(hours=1))}]}
        result = self.check("/fresh", Route(body), max_age_hours=24)
        self.assertEqual(result.status, HEALTHY)
        self.assertEqual(result.items, 2)

    def test_old_feed_is_stale(self):
        body = {"items": [{"published": iso(timedelta(hours=50))}, {"published": iso(timedelta(hours=30))}]}
        result = self.check("/old", Route(body), max_age_hours=24)
        self.assertEqual(result.status, STALE)
        self.assertEqual(result.items, 2)
        self.assertIn("30.0h old", result.reason)

    def test_old_feed_without_max_age_is_healthy(self):
        body = {"items": [{"published": "2001-01-01T00:00:00Z"}]}
        result = self.check("/ancient", Route(body))
        self.assertEqual(result.status, HEALTHY)

    def test_newest_item_need_not_be_first(self):
        body = {"items": [{"published": "2001-01-01T00:00:00Z"}, {"published": iso(timedelta(minutes=5))}]}
        result = self.check("/unordered", Route(body), max_age_hours=1)
        self.assertEqual(result.status, HEALTHY)

    def test_empty_feed_with_max_age_is_stale(self):
        result = self.check("/empty", Route({"items": []}), max_age_hours=24)
        self.assertEqual(result.status, STALE)

    def test_invalid_published_is_unhealthy(self):
        body = {"items": [{"published": "yesterday"}]}
        result = self.check("/baddate", Route(body), max_age_hours=24)
        self.assertEqual(result.status, UNHEALTHY)
        self.assertIn("invalid 'published'", result.reason)

    def test_no_published_timestamps_is_unhealthy_with_max_age(self):
        result = self.check("/undated", Route({"items": [{"id": 1}]}), max_age_hours=24)
        self.assertEqual(result.status, UNHEALTHY)


class ParseTimestampTest(unittest.TestCase):
    def test_formats(self):
        utc = timezone.utc
        self.assertEqual(parse_timestamp("2026-10-17T12:00:00Z"), datetime(2026, 10, 17, 12, tzinfo=utc))
        self.assertEqual(
            parse_timestamp("2026-10-17T14:00:00+02:00"), datetime(2026, 10, 17, 12, tzinfo=utc)
        )
        # Naive timestamps are taken as UTC.
        self.assertEqual(parse_timestamp("2026-10-17T12:00:00"), datetime(2026, 10, 17, 12, tzinfo=utc))
        self.assertEqual(parse_timestamp("2026-10-17"), datetime(2026, 10, 17, tzinfo=utc))

    def test_invalid(self):
        for value in ["", "not a date", None, 12345, "2026-13-01"]:
            self.assertIsNone(parse_timestamp(value), value)


class CheckAllTest(unittest.TestCase):
    def test_results_keep_config_order_and_report_counts(self):
        with FakeFeedServer() as server:
            server.routes["/a"] = Route({"items": [1]}, delay=0.2)
            server.routes["/b"] = Route(statuses=[404])
            feeds = [
                Feed("a", server.url("/a")),
                Feed("b", server.url("/b")),
                Feed("c", unused_port_url()),
            ]
            config = Config(feeds=feeds, timeout_seconds=2, attempts=1, backoff_seconds=0)
            results = check_all(config)

        self.assertEqual([r.name for r in results], ["a", "b", "c"])
        self.assertEqual([r.status for r in results], [HEALTHY, UNHEALTHY, UNREACHABLE])

        report = build_report(results, datetime(2026, 10, 17, tzinfo=timezone.utc))
        self.assertFalse(report["healthy"])
        self.assertEqual(
            report["summary"], {"total": 3, "healthy": 1, "unhealthy": 1, "unreachable": 1, "stale": 0}
        )
        self.assertEqual(report["feeds"][0]["items"], 1)


if __name__ == "__main__":
    unittest.main()
