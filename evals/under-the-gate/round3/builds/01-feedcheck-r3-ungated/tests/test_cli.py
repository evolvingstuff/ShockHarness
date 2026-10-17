import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from feedcheck.cli import main
from tests.fakeserver import FakeFeedServer, Route

ROOT = Path(__file__).resolve().parent.parent


class CliTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, ignore_errors=True))
        self.server = FakeFeedServer().__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)
        self.output = self.dir / "report.json"

    def config(self, feeds: list[tuple[str, str, float | None]], extra="") -> Path:
        lines = ["timeout_seconds = 2", "attempts = 2", "backoff_seconds = 0.01", extra]
        for name, path, max_age in feeds:
            lines += ["[[feeds]]", f'name = "{name}"', f'url = "{self.server.url(path)}"']
            if max_age is not None:
                lines.append(f"max_age_hours = {max_age}")
        path = self.dir / "feeds.toml"
        path.write_text("\n".join(lines) + "\n")
        return path

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_all_healthy_exits_0_and_writes_report(self):
        now = datetime.now(timezone.utc).isoformat()
        self.server.routes["/a"] = Route({"items": [{"published": now}]})
        self.server.routes["/b"] = Route({"items": []})
        cfg = self.config([("a", "/a", 1), ("b", "/b", None)])

        code, out, err = self.run_main("--config", str(cfg), "--output", str(self.output))

        self.assertEqual(code, 0, err)
        report = json.loads(self.output.read_text())
        self.assertTrue(report["healthy"])
        self.assertEqual([f["name"] for f in report["feeds"]], ["a", "b"])
        for entry in report["feeds"]:
            self.assertEqual(entry["status"], "healthy")
            self.assertIsInstance(entry["duration_seconds"], float)
            self.assertIn("items", entry)
        self.assertEqual(report["feeds"][0]["items"], 1)
        self.assertEqual(report["feeds"][1]["items"], 0)
        self.assertIn("healthy", out)

    def test_any_bad_feed_exits_1(self):
        self.server.routes["/a"] = Route({"items": []})
        self.server.routes["/stale"] = Route({"items": [{"published": "2001-01-01T00:00:00Z"}]})
        self.server.routes["/err"] = Route(statuses=[500])
        cfg = self.config([("a", "/a", None), ("stale", "/stale", 24), ("err", "/err", None)])

        code, out, _ = self.run_main("--config", str(cfg), "--output", str(self.output))

        self.assertEqual(code, 1)
        report = json.loads(self.output.read_text())
        statuses = {f["name"]: f["status"] for f in report["feeds"]}
        self.assertEqual(statuses, {"a": "healthy", "stale": "stale", "err": "unhealthy"})
        self.assertIsNotNone(report["feeds"][2]["reason"])
        self.assertEqual(report["feeds"][2]["attempts"], 2)
        self.assertIn("stale", out)

    def test_invalid_config_stops_before_fetching(self):
        self.server.routes["/a"] = Route({"items": []})
        cfg = self.config([("a", "/a", None)], extra="attempts = 0")
        cfg.write_text(cfg.read_text().replace("attempts = 2\n", ""))

        code, _, err = self.run_main("--config", str(cfg), "--output", str(self.output))

        self.assertEqual(code, 2)
        self.assertIn("attempts", err)
        self.assertEqual(self.server.hits["/a"], 0)
        self.assertFalse(self.output.exists())

    def test_invalid_feed_after_valid_one_stops_before_fetching(self):
        self.server.routes["/a"] = Route({"items": []})
        cfg = self.config([("a", "/a", None)])
        cfg.write_text(cfg.read_text() + '[[feeds]]\nname = "bad"\n')

        code, _, err = self.run_main("--config", str(cfg), "--output", str(self.output))

        self.assertEqual(code, 2)
        self.assertIn("'url'", err)
        self.assertEqual(self.server.hits["/a"], 0)

    def test_missing_config(self):
        code, _, err = self.run_main("--config", str(self.dir / "nope.toml"), "--output", str(self.output))
        self.assertEqual(code, 2)
        self.assertIn("not found", err)
        self.assertFalse(self.output.exists())

    def test_output_directory_missing(self):
        self.server.routes["/a"] = Route({"items": []})
        cfg = self.config([("a", "/a", None)])
        code, _, err = self.run_main("--config", str(cfg), "--output", str(self.dir / "no" / "r.json"))
        self.assertEqual(code, 2)
        self.assertIn("output directory", err)
        self.assertEqual(self.server.hits["/a"], 0)

    def test_runs_as_module(self):
        self.server.routes["/a"] = Route({"items": [1, 2, 3]})
        cfg = self.config([("a", "/a", None)])
        proc = subprocess.run(
            [sys.executable, "-m", "feedcheck", "--config", str(cfg), "--output", str(self.output)],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(self.output.read_text())["feeds"][0]["items"], 3)

    def test_missing_arguments_is_usage_error(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            main([])
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
