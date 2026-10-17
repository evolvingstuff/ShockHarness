import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def path(self, name):
        return os.path.join(self.tmp.name, name)

    def run_cli(self, content, raw=None):
        inp = self.path("in.csv")
        with open(inp, "wb") as fh:
            fh.write(raw if raw is not None else content.encode("utf-8"))
        proc = subprocess.run(
            [sys.executable, "-m", "contactclean", inp,
             "--output", self.path("out.csv"), "--report", self.path("report.json")],
            cwd=ROOT, capture_output=True, text=True)
        return proc

    def outputs(self):
        with open(self.path("out.csv"), newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        with open(self.path("report.json"), encoding="utf-8") as fh:
            report = json.load(fh)
        return rows, report

    def test_exit_0_when_all_usable(self):
        proc = self.run_cli("name,email,phone,birthday,country\n"
                            "Ann,ANN@x.com,(415) 555-2671,1990-07-04,US\n"
                            "Bob,,,,\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows, report = self.outputs()
        self.assertEqual(rows[0]["phone"], "+14155552671")
        self.assertEqual(rows[0]["phone_status"], "verified")
        self.assertEqual(rows[1]["email"], "")
        self.assertEqual(report["rows_read"], 2)
        self.assertEqual(report["rejected"], [])

    def test_exit_1_when_rows_rejected_or_reported(self):
        proc = self.run_cli("name,email,phone,birthday,country\n"
                            ",a@x.com,,,\n"
                            "Ann,bad-email,,,\n")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        rows, report = self.outputs()
        self.assertEqual(len(rows), 1)
        self.assertEqual(report["rejected"][0]["row"], 2)
        self.assertEqual(report["invalid_fields"][0]["row"], 3)
        self.assertEqual(report["invalid_fields"][0]["field"], "email")

    def test_exit_2_when_input_missing(self):
        proc = subprocess.run(
            [sys.executable, "-m", "contactclean", self.path("nope.csv"),
             "--output", self.path("out.csv"), "--report", self.path("r.json")],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)

    def test_exit_2_when_not_utf8_or_no_name_column(self):
        self.assertEqual(self.run_cli("", raw=b"name\n\xff\xfe\n").returncode, 2)
        self.assertEqual(self.run_cli("email\na@x.com\n").returncode, 2)
        self.assertEqual(self.run_cli("").returncode, 2)


if __name__ == "__main__":
    unittest.main()
