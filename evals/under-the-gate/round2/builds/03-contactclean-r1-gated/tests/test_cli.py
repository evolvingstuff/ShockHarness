import csv
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from contactclean.cli import EXIT_CLEAN, EXIT_REPORTED, EXIT_UNREADABLE, run

TODAY = date.fromisoformat("2026-10-17")
HEADER = "name,email,phone,birthday,country\n"


class CliTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        self.input = self.dir / "input.csv"
        self.output = self.dir / "clean.csv"
        self.report = self.dir / "report.json"

    def clean(self, content):
        if isinstance(content, bytes):
            self.input.write_bytes(content)
        else:
            self.input.write_text(content, encoding="utf-8")
        argv = [str(self.input), "--output", str(self.output), "--report", str(self.report)]
        return run(argv, TODAY)

    def rows(self):
        with self.output.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    def report_data(self):
        return json.loads(self.report.read_text(encoding="utf-8"))

    def test_clean_input_exits_zero(self):
        status = self.clean(HEADER + " Ann Lee , Ann@Example.com ,(555) 123-4567,12/31/1985,us\nBo,,,,\n")
        self.assertEqual(status, EXIT_CLEAN)
        self.assertEqual(
            self.rows(),
            [
                {
                    "name": "Ann Lee",
                    "email": "ann@example.com",
                    "phone": "+15551234567",
                    "phone_status": "verified",
                    "birthday": "1985-12-31",
                    "country": "US",
                },
                {"name": "Bo", "email": "", "phone": "", "phone_status": "", "birthday": "", "country": ""},
            ],
        )
        report = self.report_data()
        self.assertEqual(report["rejected"], [])
        self.assertEqual(report["invalid_fields"], [])

    def test_unverified_phone_is_usable(self):
        status = self.clean(HEADER + "Ann,,030 123456,,\n")
        self.assertEqual(status, EXIT_CLEAN)
        self.assertEqual(self.rows()[0]["phone"], "030123456")
        self.assertEqual(self.rows()[0]["phone_status"], "unverified")
        self.assertEqual(self.report_data()["unverified_phones"], json.loads('[{"row": 2, "phone": "030123456"}]'))

    def test_invalid_field_is_reported_and_dropped(self):
        status = self.clean(HEADER + "Ann,ann@nowhere,555-1234,04/05/1990,US\n")
        self.assertEqual(status, EXIT_REPORTED)
        row = self.rows()[0]
        self.assertEqual((row["name"], row["email"], row["phone"], row["birthday"]), ("Ann", "", "", ""))
        problems = self.report_data()["invalid_fields"]
        located = [{"row": item["row"], "field": item["field"]} for item in problems]
        expected = '[{"row": 2, "field": "email"}, {"row": 2, "field": "phone"}, {"row": 2, "field": "birthday"}]'
        self.assertEqual(located, json.loads(expected))
        self.assertTrue(all(item["reason"] for item in problems))

    def test_row_without_name_is_rejected(self):
        status = self.clean(HEADER + "Ann,,,,\n  ,x@example.com,,,\n")
        self.assertEqual(status, EXIT_REPORTED)
        self.assertEqual([row["name"] for row in self.rows()], ["Ann"])
        self.assertEqual(self.report_data()["rejected"], json.loads('[{"row": 3, "reason": "row has no name"}]'))

    def test_merges_same_email_keeping_most_complete(self):
        status = self.clean(HEADER + "Ann,ANN@example.com,,,\nAnn Lee,ann@example.com,020 7946 0958,1990-01-02,GB\n")
        self.assertEqual(status, EXIT_CLEAN)
        self.assertEqual([row["name"] for row in self.rows()], ["Ann Lee"])
        self.assertEqual(
            self.report_data()["merged"],
            json.loads('[{"kept_row": 3, "merged_rows": [2], "reason": "same email ann@example.com"}]'),
        )

    def test_merges_same_verified_phone_transitively(self):
        content = HEADER + (
            "A,a@example.com,06 12 34 56 78,,FR\n"
            "B,,+33 6 12 34 56 78,,FR\n"
            "C,a@example.com,,,\n"
            "D,,0612345678,,\n"
        )
        status = self.clean(content)
        self.assertEqual(status, EXIT_CLEAN)
        self.assertEqual([row["name"] for row in self.rows()], ["A", "D"])
        merged = self.report_data()["merged"]
        self.assertEqual(
            [{"kept_row": item["kept_row"], "merged_rows": item["merged_rows"]} for item in merged],
            json.loads('[{"kept_row": 2, "merged_rows": [3, 4]}]'),
        )

    def test_unverified_phones_are_not_merged(self):
        self.clean(HEADER + "A,,0612345678,,\nB,,0612345678,,\n")
        self.assertEqual([row["name"] for row in self.rows()], ["A", "B"])
        self.assertEqual(self.report_data()["merged"], [])

    def test_missing_optional_columns_and_bom(self):
        status = self.clean("﻿Name,Email\nAnn,ann@example.com\n".encode("utf-8"))
        self.assertEqual(status, EXIT_CLEAN)
        self.assertEqual(self.rows()[0]["email"], "ann@example.com")

    def assertUnreadable(self, argv):
        with self.assertRaises(SystemExit) as raised:
            run(argv, TODAY)
        self.assertEqual(raised.exception.code, EXIT_UNREADABLE)

    def test_missing_file_is_unreadable(self):
        argv = [str(self.dir / "missing.csv"), "--output", str(self.output), "--report", str(self.report)]
        self.assertUnreadable(argv)
        self.assertFalse(self.output.exists())

    def test_bad_input_is_unreadable(self):
        for content in (b"", b"email,phone\nx@example.com,\n", b"name\n\xff\xfe\n", b'name\n"unterminated\n'):
            with self.subTest(content=content):
                self.input.write_bytes(content)
                self.assertUnreadable([str(self.input), "--output", str(self.output), "--report", str(self.report)])

    def test_command_line_exit_status(self):
        self.input.write_text(HEADER + ",x@example.com,,,\n", encoding="utf-8")
        argv = ["--output", str(self.output), "--report", str(self.report)]
        completed = subprocess.run([sys.executable, "-m", "contactclean", str(self.input), *argv], check=False)
        self.assertEqual(completed.returncode, EXIT_REPORTED)
        missing = subprocess.run(
            [sys.executable, "-m", "contactclean", str(self.dir / "missing.csv"), *argv],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(missing.returncode, EXIT_UNREADABLE)
        self.assertIn("cannot read", missing.stderr)


if __name__ == "__main__":
    unittest.main()
