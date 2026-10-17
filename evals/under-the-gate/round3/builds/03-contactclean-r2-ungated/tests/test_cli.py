import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr

from contactclean.cli import main

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = os.path.join(self.tmp.name, "clean.csv")
        self.report = os.path.join(self.tmp.name, "report.json")

    def write_input(self, text, encoding="utf-8"):
        path = os.path.join(self.tmp.name, "in.csv")
        with open(path, "w", encoding=encoding, newline="") as f:
            f.write(text)
        return path

    def run_main(self, path):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = main([path, "--output", self.output, "--report", self.report])
        return code, stderr.getvalue()

    def read_output(self):
        with open(self.output, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def read_report(self):
        with open(self.report, encoding="utf-8") as f:
            return json.load(f)

    def test_all_usable_exits_0(self):
        path = self.write_input(
            "name,email,phone,birthday,country\n"
            "Ann Lee,ANN@example.com,(415) 555-2671,1990-04-23,US\n"
            "Zoë,,,,\n"
        )
        code, _ = self.run_main(path)
        self.assertEqual(code, 0)
        rows = self.read_output()
        self.assertEqual(rows[0]["phone"], "+14155552671")
        self.assertEqual(rows[1], {"name": "Zoë", "email": "", "phone": "",
                                   "phone_status": "", "birthday": "", "country": ""})
        report = self.read_report()
        self.assertEqual(report["rejected"], [])
        self.assertEqual(report["invalid_fields"], [])
        self.assertEqual((report["rows_read"], report["rows_written"]), (2, 2))

    def test_merges_alone_still_exit_0(self):
        path = self.write_input(
            "name,email\nAnn,ann@example.com\nAnn Lee,Ann@Example.com\n")
        code, _ = self.run_main(path)
        self.assertEqual(code, 0)
        self.assertEqual(len(self.read_output()), 1)
        self.assertEqual(self.read_report()["merged"],
                         [{"kept_row": 2, "merged_rows": [3], "reason": "same email"}])

    def test_rejected_and_invalid_exit_1(self):
        path = self.write_input(
            "﻿Name , Email,Phone,Birthday,Country\n"   # BOM, odd header spacing
            ",nobody@example.com,,,\n"
            "Bob,bob@,555,03/04/1990,GB\n"
        )
        code, _ = self.run_main(path)
        self.assertEqual(code, 1)
        report = self.read_report()
        self.assertEqual(report["rejected"], [{"row": 2, "reason": "missing name"}])
        self.assertEqual([(i["row"], i["field"]) for i in report["invalid_fields"]],
                         [(3, "email"), (3, "phone"), (3, "birthday")])
        self.assertEqual(self.read_output(), [
            {"name": "Bob", "email": "", "phone": "", "phone_status": "",
             "birthday": "", "country": "GB"},
        ])

    def test_unreadable_exits_2(self):
        missing = os.path.join(self.tmp.name, "missing.csv")
        cases = {
            "missing file": missing,
            "empty file": self.write_input(""),
        }
        for label, path in cases.items():
            with self.subTest(label):
                code, err = self.run_main(path)
                self.assertEqual(code, 2)
                self.assertIn("cannot read", err)

    def test_no_name_column_exits_2(self):
        code, _ = self.run_main(self.write_input("email\na@example.com\n"))
        self.assertEqual(code, 2)

    def test_bad_encoding_exits_2(self):
        code, _ = self.run_main(self.write_input("name\nZo\xeb\n", encoding="latin-1"))
        self.assertEqual(code, 2)

    def test_module_entry_point(self):
        path = self.write_input("name\n\n")
        proc = subprocess.run(
            [sys.executable, "-m", "contactclean", path,
             "--output", self.output, "--report", self.report],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
