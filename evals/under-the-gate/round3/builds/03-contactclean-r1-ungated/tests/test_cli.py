import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.out = self.dir / "clean.csv"
        self.report = self.dir / "report.json"

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, content, encoding="utf-8", name="in.csv"):
        path = self.dir / name
        if content is not None:
            path.write_bytes(content if isinstance(content, bytes) else content.encode(encoding))
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        return subprocess.run(
            [sys.executable, "-m", "contactclean", str(path), "--output", str(self.out), "--report", str(self.report)],
            capture_output=True, text=True, env=env, cwd=self.dir,
        )

    def read_output(self):
        with open(self.out, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def test_clean_input_exits_0(self):
        proc = self.run_cli(
            "name,email,phone,birthday,country\n"
            " Ann ,ANN@Example.com,(415) 555-2671,25/12/1985,US\n"
            "Bob,,,,\n"
            "Chie,,03-1234-5678,,JP\n"
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = self.read_output()
        self.assertEqual(out[0], {
            "name": "Ann", "email": "ann@example.com", "phone": "+14155552671",
            "phone_status": "verified", "birthday": "1985-12-25", "country": "US",
        })
        self.assertEqual(out[1], {k: "" for k in out[1]} | {"name": "Bob"})
        self.assertEqual((out[2]["phone"], out[2]["phone_status"]), ("0312345678", "unverified"))
        report = json.loads(self.report.read_text())
        self.assertEqual(report["rejected"], [])
        self.assertEqual(report["invalid_fields"], [])
        self.assertEqual(report["rows_read"], 3)

    def test_merges_alone_still_exit_0(self):
        proc = self.run_cli("name,email\nAnn,a@x.com\nAnn,A@x.com\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = json.loads(self.report.read_text())
        self.assertEqual(report["merged"], [{"kept_row": 2, "merged_rows": [3], "matched_on": ["email"]}])
        self.assertEqual(len(self.read_output()), 1)

    def test_problems_exit_1(self):
        proc = self.run_cli(
            "name,email,phone,birthday,country\n"
            ",x@y.com,,,\n"
            "Ann,bad-email,,03/04/1990,FR\n"
        )
        self.assertEqual(proc.returncode, 1, proc.stderr)
        report = json.loads(self.report.read_text())
        self.assertEqual(report["rejected"], [{"row": 2, "reason": "missing name"}])
        self.assertEqual([(i["row"], i["field"]) for i in report["invalid_fields"]], [(3, "email"), (3, "birthday")])
        self.assertEqual(self.read_output(), [{
            "name": "Ann", "email": "", "phone": "", "phone_status": "", "birthday": "", "country": "FR",
        }])

    def test_missing_optional_columns_and_bom(self):
        proc = self.run_cli("﻿Name,Email\nAnn,a@x.com\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.read_output()[0]["email"], "a@x.com")

    def test_missing_file_exits_2(self):
        proc = self.run_cli(None, name="nope.csv")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("cannot read", proc.stderr)
        self.assertFalse(self.out.exists())

    def test_empty_file_exits_2(self):
        self.assertEqual(self.run_cli("").returncode, 2)

    def test_no_name_column_exits_2(self):
        self.assertEqual(self.run_cli("email,phone\na@x.com,\n").returncode, 2)

    def test_undecodable_exits_2(self):
        self.assertEqual(self.run_cli(b"name\n\xff\xfe\xfa\n").returncode, 2)

    def test_directory_exits_2(self):
        proc = subprocess.run(
            [sys.executable, "-m", "contactclean", str(self.dir), "--output", str(self.out), "--report", str(self.report)],
            capture_output=True, text=True, env=dict(os.environ, PYTHONPATH=str(ROOT)),
        )
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
