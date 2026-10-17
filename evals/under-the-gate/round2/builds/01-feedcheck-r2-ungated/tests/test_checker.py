import unittest
from datetime import datetime, timedelta, timezone

from feedcheck.checker import HEALTHY, STALE, UNHEALTHY, UNREACHABLE, check_feed
from feedcheck.config import Config, Feed
from tests.fakeserver import FakeFeedServer, Response, closed_port_url

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)


def iso(delta_hours: float) -> str:
    return (NOW - timedelta(hours=delta_hours)).isoformat()


class CheckerTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeFeedServer().__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)
        self.sleeps = []

    def check(self, url, max_age=None, attempts=3, timeout=2.0, backoff=0.5):
        cfg = Config(feeds=[], timeout_seconds=timeout, attempts=attempts,
                     backoff_seconds=backoff)
        return check_feed(Feed("f", url, max_age), cfg,
                          sleep=self.sleeps.append, now=lambda: NOW)

    def test_healthy(self):
        url = self.server.add("/ok", Response(body={"items": [{"id": 1}, {"id": 2}]}))
        r = self.check(url)
        self.assertEqual(r.status, HEALTHY)
        self.assertEqual(r.item_count, 2)
        self.assertIsNone(r.reason)
        self.assertEqual(r.attempts, 1)
        self.assertGreaterEqual(r.duration_seconds, 0)
        self.assertEqual(self.sleeps, [])

    def test_empty_items_is_healthy(self):
        r = self.check(self.server.add("/e", Response(body={"items": []})))
        self.assertEqual((r.status, r.item_count), (HEALTHY, 0))

    def test_not_json(self):
        r = self.check(self.server.add("/x", Response(body=b"<html>")))
        self.assertEqual(r.status, UNHEALTHY)
        self.assertIn("not valid JSON", r.reason)

    def test_not_object(self):
        r = self.check(self.server.add("/x", Response(body=[1, 2])))
        self.assertEqual(r.status, UNHEALTHY)
        self.assertIn("not a JSON object", r.reason)

    def test_missing_items(self):
        r = self.check(self.server.add("/x", Response(body={"entries": []})))
        self.assertEqual(r.status, UNHEALTHY)
        self.assertIn("no 'items'", r.reason)

    def test_items_not_list(self):
        r = self.check(self.server.add("/x", Response(body={"items": {"a": 1}})))
        self.assertEqual(r.status, UNHEALTHY)
        self.assertIn("not a list", r.reason)

    def test_404_not_retried(self):
        r = self.check(self.server.add("/x", Response(404, b"nope")))
        self.assertEqual(r.status, UNHEALTHY)
        self.assertIn("404", r.reason)
        self.assertEqual(self.server.hits["/x"], 1)
        self.assertEqual(r.attempts, 1)

    def test_non_200_success_is_unhealthy(self):
        r = self.check(self.server.add("/x", Response(204, b"")))
        self.assertEqual(r.status, UNHEALTHY)
        self.assertIn("204", r.reason)

    def test_5xx_retried_then_recovers(self):
        url = self.server.add("/x", Response(503), Response(500),
                              Response(body={"items": [1]}))
        r = self.check(url, attempts=3)
        self.assertEqual(r.status, HEALTHY)
        self.assertEqual(r.attempts, 3)
        self.assertEqual(self.server.hits["/x"], 3)

    def test_5xx_exhausts_attempts(self):
        r = self.check(self.server.add("/x", Response(502)), attempts=4)
        self.assertEqual(r.status, UNHEALTHY)
        self.assertIn("502", r.reason)
        self.assertEqual(self.server.hits["/x"], 4)
        self.assertEqual(r.attempts, 4)

    def test_backoff_grows(self):
        self.check(self.server.add("/x", Response(500)), attempts=4, backoff=0.5)
        self.assertEqual(len(self.sleeps), 3)
        self.assertTrue(all(b > a for a, b in zip(self.sleeps, self.sleeps[1:])),
                        self.sleeps)

    def test_single_attempt_no_retry(self):
        r = self.check(self.server.add("/x", Response(500)), attempts=1)
        self.assertEqual(self.server.hits["/x"], 1)
        self.assertEqual(self.sleeps, [])
        self.assertEqual(r.status, UNHEALTHY)

    def test_connection_refused_unreachable(self):
        r = self.check(closed_port_url(), attempts=2)
        self.assertEqual(r.status, UNREACHABLE)
        self.assertEqual(r.attempts, 2)
        self.assertIsNone(r.item_count)
        self.assertEqual(len(self.sleeps), 1)

    def test_timeout_unreachable_and_retried(self):
        url = self.server.add("/slow", Response(body={"items": []}, delay=1.0))
        r = self.check(url, attempts=2, timeout=0.2)
        self.assertEqual(r.status, UNREACHABLE)
        self.assertIn("timed out", r.reason)
        self.assertEqual(self.server.hits["/slow"], 2)

    def test_timeout_then_recovers(self):
        url = self.server.add("/slow", Response(body={"items": []}, delay=1.0),
                              Response(body={"items": [1]}))
        r = self.check(url, attempts=2, timeout=0.2)
        self.assertEqual(r.status, HEALTHY)

    def test_fresh_feed(self):
        url = self.server.add("/x", Response(body={"items": [
            {"published": iso(30)}, {"published": iso(2)}]}))
        self.assertEqual(self.check(url, max_age=24).status, HEALTHY)

    def test_stale_feed(self):
        url = self.server.add("/x", Response(body={"items": [
            {"published": iso(30)}, {"published": iso(48)}]}))
        r = self.check(url, max_age=24)
        self.assertEqual(r.status, STALE)
        self.assertEqual(r.item_count, 2)
        self.assertIn("30.0h", r.reason)

    def test_staleness_ignored_without_max_age(self):
        url = self.server.add("/x", Response(body={"items": [{"published": iso(1000)}]}))
        self.assertEqual(self.check(url).status, HEALTHY)

    def test_z_suffix_and_offsets(self):
        url = self.server.add("/x", Response(body={"items": [
            {"published": "2026-10-17T11:00:00Z"},
            {"published": "2026-10-17T08:30:00-03:00"},  # 11:30Z, newest
        ]}))
        self.assertEqual(self.check(url, max_age=0.6).status, HEALTHY)
        self.assertEqual(self.check(url, max_age=0.4).status, STALE)

    def test_naive_dates_assumed_utc(self):
        url = self.server.add("/x", Response(body={"items": [
            {"published": "2026-10-17T11:00:00"}]}))
        self.assertEqual(self.check(url, max_age=2).status, HEALTHY)

    def test_no_dated_items_is_stale(self):
        url = self.server.add("/x", Response(body={"items": [{"id": 1}]}))
        r = self.check(url, max_age=24)
        self.assertEqual(r.status, STALE)
        self.assertIn("no item", r.reason)

    def test_invalid_published_unhealthy(self):
        url = self.server.add("/x", Response(body={"items": [{"published": "yesterday"}]}))
        r = self.check(url, max_age=24)
        self.assertEqual(r.status, UNHEALTHY)
        self.assertIn("published", r.reason)


if __name__ == "__main__":
    unittest.main()
