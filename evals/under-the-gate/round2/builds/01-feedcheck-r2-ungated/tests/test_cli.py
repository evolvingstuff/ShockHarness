import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from feedcheck.cli import main
from tests.fakeserver import FakeFeedServer, Response, closed_port_url


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.server = FakeFeedServer().__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)
        self.config = os.path.join(self.tmp.name, "feeds.toml")
        self.output = os.path.join(self.tmp.name, "report.json")

    def write_config(self, text):
        with open(self.config, "w", encoding="utf-8") as fh:
            fh.write(text)

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(args) or ["--config", self.config, "--output", self.output])
        return code, out.getvalue(), err.getvalue()

    def report(self):
        with open(self.output, encoding="utf-8") as fh:
            return json.load(fh)

    def test_all_healthy_exit_0(self):
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        a = self.server.add("/a", Response(body={"items": [{"published": recent}]}))
        b = self.server.add("/b", Response(body={"items": []}))
        self.write_config(f"""
timeout_seconds = 2
attempts = 2
backoff_seconds = 0
[[feeds]]
name = "a"
url = "{a}"
max_age_hours = 6
[[feeds]]
name = "b"
url = "{b}"
""")
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        report = self.report()
        self.assertTrue(report["healthy"])
        self.assertEqual([f["name"] for f in report["feeds"]], ["a", "b"])
        for feed in report["feeds"]:
            self.assertEqual(feed["status"], "healthy")
            self.assertIn("item_count", feed)
            self.assertIsInstance(feed["duration_seconds"], float)
        self.assertEqual(report["feeds"][0]["item_count"], 1)
        self.assertEqual(report["feeds"][1]["item_count"], 0)
        self.assertIn("healthy", out)

    def test_mixed_exit_1(self):
        ok = self.server.add("/ok", Response(body={"items": [1, 2, 3]}))
        bad = self.server.add("/bad", Response(body={"items": "nope"}))
        old = self.server.add("/old", Response(body={"items": [
            {"published": "2001-01-01T00:00:00Z"}]}))
        down = closed_port_url()
        self.write_config(f"""
timeout_seconds = 1
attempts = 2
backoff_seconds = 0.01
[[feeds]]
name = "ok"
url = "{ok}"
[[feeds]]
name = "bad"
url = "{bad}"
[[feeds]]
name = "old"
url = "{old}"
max_age_hours = 24
[[feeds]]
name = "down"
url = "{down}"
""")
        code, _, _ = self.run_cli()
        self.assertEqual(code, 1)
        report = self.report()
        self.assertFalse(report["healthy"])
        by_name = {f["name"]: f for f in report["feeds"]}
        self.assertEqual(by_name["ok"]["status"], "healthy")
        self.assertEqual(by_name["ok"]["item_count"], 3)
        self.assertEqual(by_name["bad"]["status"], "unhealthy")
        self.assertTrue(by_name["bad"]["reason"])
        self.assertEqual(by_name["old"]["status"], "stale")
        self.assertEqual(by_name["down"]["status"], "unreachable")
        self.assertEqual(report["summary"],
                         {"total": 4, "healthy": 1, "unhealthy": 1, "stale": 1,
                          "unreachable": 1})

    def assertConfigErrorBeforeFetch(self, fragment):
        code, out, err = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn("feedcheck: error:", err)
        self.assertIn(fragment, err)
        self.assertFalse(os.path.exists(self.output))
        self.assertEqual(dict(self.server.hits), {})

    def test_missing_config(self):
        self.assertConfigErrorBeforeFetch("not found")

    def test_invalid_config_fetches_nothing(self):
        good = self.server.add("/a", Response(body={"items": []}))
        self.write_config(f'[[feeds]]\nname = "a"\nurl = "{good}"\n'
                          '[[feeds]]\nname = "b"\n')
        self.assertConfigErrorBeforeFetch("'url'")

    def test_malformed_toml(self):
        self.write_config("[[feeds]\n")
        self.assertConfigErrorBeforeFetch("TOML")

    def test_missing_output_dir(self):
        url = self.server.add("/a", Response(body={"items": []}))
        self.write_config(f'[[feeds]]\nname = "a"\nurl = "{url}"\n')
        code, _, err = self.run_cli("--config", self.config,
                                    "--output", os.path.join(self.tmp.name, "no", "r.json"))
        self.assertEqual(code, 2)
        self.assertIn("output directory", err)
        self.assertEqual(dict(self.server.hits), {})

    def test_required_args(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                main([])
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
