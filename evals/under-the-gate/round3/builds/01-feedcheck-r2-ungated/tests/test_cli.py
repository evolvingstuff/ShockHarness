import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone

from feedcheck.cli import main
from tests.fakeserver import FakeFeedServer, closed_port_url

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.server = FakeFeedServer().__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)
        self.output = os.path.join(self.tmp.name, "report.json")

    def write_config(self, text: str) -> str:
        path = os.path.join(self.tmp.name, "feeds.toml")
        with open(path, "w") as f:
            f.write(textwrap.dedent(text))
        return path

    def run_main(self, config_path):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--config", config_path, "--output", self.output])
        return code, out.getvalue(), err.getvalue()

    def read_report(self):
        with open(self.output) as f:
            return json.load(f)

    def test_all_healthy_exit_0(self):
        self.server.routes["/a"] = [(200, {"items": [1, 2, 3]})]
        self.server.routes["/b"] = [(200, {"items": []})]
        cfg = self.write_config(f"""
            timeout_seconds = 2
            attempts = 2
            backoff_seconds = 0
            [[feeds]]
            name = "a"
            url = "{self.server.url('/a')}"
            [[feeds]]
            name = "b"
            url = "{self.server.url('/b')}"
        """)
        code, out, _ = self.run_main(cfg)
        self.assertEqual(code, 0)
        report = self.read_report()
        self.assertTrue(report["healthy"])
        self.assertEqual(report["summary"], {"healthy": 2})
        feeds = report["feeds"]
        self.assertEqual([f["name"] for f in feeds], ["a", "b"])
        self.assertEqual([f["status"] for f in feeds], ["healthy", "healthy"])
        self.assertEqual([f["items"] for f in feeds], [3, 0])
        for f in feeds:
            self.assertIsInstance(f["duration_seconds"], (int, float))
            self.assertGreaterEqual(f["duration_seconds"], 0)
        self.assertIn("healthy", out)

    def test_mixed_exit_1(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        self.server.routes["/ok"] = [(200, {"items": [1]})]
        self.server.routes["/bad"] = [(200, {"items": "nope"})]
        self.server.routes["/old"] = [(200, {"items": [{"published": old}]})]
        cfg = self.write_config(f"""
            timeout_seconds = 2
            attempts = 2
            backoff_seconds = 0
            [[feeds]]
            name = "ok"
            url = "{self.server.url('/ok')}"
            [[feeds]]
            name = "bad"
            url = "{self.server.url('/bad')}"
            [[feeds]]
            name = "old"
            url = "{self.server.url('/old')}"
            max_age_hours = 24
            [[feeds]]
            name = "gone"
            url = "{closed_port_url()}"
        """)
        code, out, _ = self.run_main(cfg)
        self.assertEqual(code, 1)
        report = self.read_report()
        self.assertFalse(report["healthy"])
        by_name = {f["name"]: f for f in report["feeds"]}
        self.assertEqual(by_name["ok"]["status"], "healthy")
        self.assertEqual(by_name["bad"]["status"], "unhealthy")
        self.assertIn("not a list", by_name["bad"]["reason"])
        self.assertEqual(by_name["old"]["status"], "stale")
        self.assertEqual(by_name["old"]["items"], 1)
        self.assertEqual(by_name["gone"]["status"], "unreachable")
        self.assertIsNone(by_name["gone"]["items"])
        self.assertEqual(
            report["summary"], {"healthy": 1, "unhealthy": 1, "stale": 1, "unreachable": 1}
        )
        self.assertIn("unreachable", out)

    def test_invalid_config_stops_before_fetching(self):
        self.server.routes["/a"] = [(200, {"items": []})]
        cfg = self.write_config(f"""
            attempts = 0
            [[feeds]]
            name = "a"
            url = "{self.server.url('/a')}"
        """)
        code, _, err = self.run_main(cfg)
        self.assertEqual(code, 2)
        self.assertIn("attempts", err)
        self.assertEqual(sum(self.server.hits.values()), 0)
        self.assertFalse(os.path.exists(self.output))

    def test_bad_feed_entry_stops_before_fetching_earlier_feeds(self):
        self.server.routes["/a"] = [(200, {"items": []})]
        cfg = self.write_config(f"""
            [[feeds]]
            name = "a"
            url = "{self.server.url('/a')}"
            [[feeds]]
            name = "b"
        """)
        code, _, err = self.run_main(cfg)
        self.assertEqual(code, 2)
        self.assertIn("'url'", err)
        self.assertEqual(sum(self.server.hits.values()), 0)

    def test_missing_config(self):
        code, _, err = self.run_main(os.path.join(self.tmp.name, "missing.toml"))
        self.assertEqual(code, 2)
        self.assertIn("not found", err)
        self.assertFalse(os.path.exists(self.output))

    def test_malformed_toml(self):
        code, _, err = self.run_main(self.write_config("[[feeds]\nname="))
        self.assertEqual(code, 2)
        self.assertIn("not valid TOML", err)

    def test_runs_as_module(self):
        self.server.routes["/a"] = [(200, {"items": [1]})]
        cfg = self.write_config(f"""
            [[feeds]]
            name = "a"
            url = "{self.server.url('/a')}"
        """)
        proc = subprocess.run(
            [sys.executable, "-m", "feedcheck", "--config", cfg, "--output", self.output],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.read_report()["feeds"][0]["status"], "healthy")

    def test_missing_arguments(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            main([])
        self.assertNotEqual(cm.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
