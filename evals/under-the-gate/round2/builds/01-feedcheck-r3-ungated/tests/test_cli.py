import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from feedcheck import cli
from tests.fakeserver import FakeFeedServer

ROOT = Path(__file__).resolve().parent.parent


def setUpModule():
    for var in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        os.environ.pop(var, None)
    os.environ["no_proxy"] = "*"


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.output = self.dir / "report.json"
        self.server = FakeFeedServer().__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)

    def write_config(self, feeds, header="timeout_seconds = 2\nattempts = 2\nbackoff_seconds = 0.01\n"):
        text = header
        for name, url in feeds:
            text += f'[[feeds]]\nname = "{name}"\nurl = "{url}"\n'
        path = self.dir / "feeds.toml"
        path.write_text(text)
        return path

    def run_main(self, *argv):
        err = io.StringIO()
        with redirect_stderr(err):
            code = cli.main(list(argv))
        return code, err.getvalue()

    def test_all_healthy_exit_0(self):
        a = self.server.route("/a", (200, {"items": [1, 2, 3]}))
        b = self.server.route("/b", (200, {"items": []}))
        config = self.write_config([("alpha", a), ("beta", b)])
        code, _ = self.run_main("--config", str(config), "--output", str(self.output))
        self.assertEqual(code, 0)
        report = json.loads(self.output.read_text())
        self.assertTrue(report["healthy"])
        self.assertIn("checked_at", report)
        self.assertEqual(report["summary"]["total"], 2)
        self.assertEqual(report["summary"]["healthy"], 2)
        feeds = {f["name"]: f for f in report["feeds"]}
        self.assertEqual(feeds["alpha"]["status"], "healthy")
        self.assertEqual(feeds["alpha"]["items"], 3)
        self.assertEqual(feeds["beta"]["items"], 0)
        for f in report["feeds"]:
            self.assertIsInstance(f["duration_seconds"], float)
            self.assertGreaterEqual(f["duration_seconds"], 0)
            self.assertIn("reason", f)

    def test_any_unhealthy_exit_1_and_every_feed_listed(self):
        good = self.server.route("/good", (200, {"items": []}))
        bad = self.server.route("/bad", (200, "garbage"))
        down = self.server.route("/down", (503, ""))
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        gone = f"http://127.0.0.1:{port}/x"
        config = self.write_config([("good", good), ("bad", bad), ("down", down), ("gone", gone)])
        code, err = self.run_main("--config", str(config), "--output", str(self.output))
        self.assertEqual(code, 1)
        report = json.loads(self.output.read_text())
        self.assertFalse(report["healthy"])
        statuses = {f["name"]: f["status"] for f in report["feeds"]}
        self.assertEqual(statuses, {
            "good": "healthy", "bad": "unhealthy", "down": "unhealthy", "gone": "unreachable",
        })
        reasons = {f["name"]: f["reason"] for f in report["feeds"]}
        self.assertIsNone(reasons["good"])
        self.assertIn("503", reasons["down"])
        self.assertEqual(self.server.hits["/down"], 2)
        self.assertIn("unreachable", err)

    def test_stale_exits_1(self):
        url = self.server.route("/old", (200, {"items": [{"published": "2000-01-01T00:00:00Z"}]}))
        config = self.dir / "feeds.toml"
        config.write_text(f'[[feeds]]\nname = "old"\nurl = "{url}"\nmax_age_hours = 24\n')
        code, _ = self.run_main("--config", str(config), "--output", str(self.output))
        self.assertEqual(code, 1)
        report = json.loads(self.output.read_text())
        self.assertEqual(report["feeds"][0]["status"], "stale")
        self.assertEqual(report["feeds"][0]["items"], 1)

    def test_invalid_config_stops_before_fetching(self):
        url = self.server.route("/a", (200, {"items": []}))
        config = self.dir / "feeds.toml"
        config.write_text(f'[[feeds]]\nname = "a"\nurl = "{url}"\n[[feeds]]\nname = "b"\n')
        with mock.patch("feedcheck.cli.check_all") as check_all:
            code, err = self.run_main("--config", str(config), "--output", str(self.output))
        self.assertEqual(code, 2)
        check_all.assert_not_called()
        self.assertEqual(self.server.hits, {})
        self.assertIn("feedcheck: error:", err)
        self.assertIn("'url'", err)
        self.assertFalse(self.output.exists())

    def test_missing_config(self):
        code, err = self.run_main("--config", str(self.dir / "nope.toml"), "--output", str(self.output))
        self.assertEqual(code, 2)
        self.assertIn("not found", err)
        self.assertFalse(self.output.exists())

    def test_malformed_toml(self):
        config = self.dir / "feeds.toml"
        config.write_text("[[feeds]\nname=")
        code, err = self.run_main("--config", str(config), "--output", str(self.output))
        self.assertEqual(code, 2)
        self.assertIn("not valid TOML", err)

    def test_missing_output_directory(self):
        url = self.server.route("/a", (200, {"items": []}))
        config = self.write_config([("a", url)])
        code, err = self.run_main("--config", str(config), "--output", str(self.dir / "no" / "r.json"))
        self.assertEqual(code, 2)
        self.assertIn("output directory", err)
        self.assertEqual(self.server.hits, {})

    def test_module_entry_point(self):
        url = self.server.route("/a", (200, {"items": [1]}))
        config = self.write_config([("a", url)])
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        proc = subprocess.run(
            [sys.executable, "-m", "feedcheck", "--config", str(config), "--output", str(self.output)],
            cwd=self.dir, env=env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(self.output.read_text())["feeds"][0]["status"], "healthy")


if __name__ == "__main__":
    unittest.main()
