import json
import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import feedcheck

HITS = {}


def iso(hours_ago):
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path
        HITS[path] = HITS.get(path, 0) + 1
        code, body = 200, {"items": [{"published": iso(1)}]}
        if path == "/old":
            body = {"items": [{"published": iso(100)}, {"published": iso(50)}]}
        elif path == "/notjson":
            body = None
        elif path == "/array":
            body = []
        elif path == "/noitems":
            body = {"items": "x"}
        elif path == "/404":
            code = 404
        elif path == "/500":
            code = 500
        elif path == "/flaky" and HITS[path] < 3:
            code = 503
        data = b"not json" if body is None else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _load(path):
    with open(path) as f:
        return json.load(f)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.srv.server_port}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        HITS.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def check(self, path, attempts=3, max_age=None, url=None):
        cfg = {"timeout": 2, "attempts": attempts, "backoff": 0}
        feed = {"name": "f", "url": url or self.base + path, "max_age_hours": max_age}
        return feedcheck.check_feed(feed, cfg, sleep=lambda s: None)


class CheckTests(Base):
    def test_healthy(self):
        r = self.check("/ok")
        self.assertEqual((r["status"], r["items"]), ("healthy", 1))
        self.assertIn("duration_seconds", r)

    def test_bad_bodies_unhealthy(self):
        for p in ("/notjson", "/array", "/noitems", "/404"):
            self.assertEqual(self.check(p)["status"], "unhealthy", p)
        self.assertEqual(HITS["/404"], 1)  # 4xx is not retried

    def test_5xx_retried_then_unhealthy(self):
        r = self.check("/500")
        self.assertEqual(r["status"], "unhealthy")
        self.assertEqual(HITS["/500"], 3)

    def test_retry_recovers(self):
        r = self.check("/flaky")
        self.assertEqual((r["status"], r["attempts"]), ("healthy", 3))

    def test_unreachable(self):
        r = self.check("", url="http://127.0.0.1:1/")
        self.assertEqual(r["status"], "unreachable")

    def test_backoff_grows(self):
        delays = []
        cfg = {"timeout": 2, "attempts": 4, "backoff": 1}
        feedcheck.check_feed({"name": "f", "url": self.base + "/500", "max_age_hours": None},
                             cfg, sleep=delays.append)
        self.assertEqual(delays, [1, 2, 4])

    def test_stale(self):
        self.assertEqual(self.check("/old", max_age=24)["status"], "stale")
        self.assertEqual(self.check("/old", max_age=200)["status"], "healthy")
        self.assertEqual(self.check("/ok", max_age=24)["status"], "healthy")
        self.assertEqual(self.check("/old")["status"], "healthy")


class CliTests(Base):
    def write(self, text):
        self.n = getattr(self, "n", 0) + 1
        p = os.path.join(self.tmp.name, f"feeds{self.n}.toml")
        with open(p, "w") as f:
            f.write(text)
        return p

    def run_cli(self, cfg_path):
        out = os.path.join(self.tmp.name, "report.json")
        code = feedcheck.main(["--config", cfg_path, "--output", out])
        return code, out

    def test_all_healthy_exit_0(self):
        p = self.write(f'timeout=2\nattempts=1\n[[feeds]]\nname="a"\nurl="{self.base}/ok"\n')
        code, out = self.run_cli(p)
        self.assertEqual(code, 0)
        rep = _load(out)
        self.assertEqual(rep["feeds"][0]["status"], "healthy")

    def test_any_bad_exit_1(self):
        p = self.write(f'timeout=2\nattempts=1\nbackoff=0\n[[feeds]]\nname="a"\nurl="{self.base}/ok"\n'
                       f'[[feeds]]\nname="b"\nurl="{self.base}/404"\n')
        code, out = self.run_cli(p)
        self.assertEqual(code, 1)
        self.assertEqual(len(_load(out)["feeds"]), 2)

    def test_bad_configs_stop_before_fetch(self):
        cases = [
            os.path.join(self.tmp.name, "missing.toml"),
            self.write("this is = = not toml"),
            self.write("attempts=1\n"),
            self.write(f'attempts=0\n[[feeds]]\nname="a"\nurl="{self.base}/ok"\n'),
            self.write('[[feeds]]\nname="a"\n'),
        ]
        for p in cases:
            HITS.clear()
            code, out = self.run_cli(p)
            self.assertEqual(code, 2, p)
            self.assertFalse(os.path.exists(out))
            self.assertEqual(HITS, {})


if __name__ == "__main__":
    unittest.main()
