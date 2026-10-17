import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from contactclean.cli import EXIT_ALL_USABLE, EXIT_INPUT_UNREADABLE, EXIT_ROWS_REPORTED, main

ROOT = Path(__file__).resolve().parent.parent
HEADER = "name,email,phone,birthday,country\n"


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.output = self.dir / "clean.csv"
        self.report_path = self.dir / "report.json"

    def tearDown(self):
        self.tmp.cleanup()

    def run_on(self, text, encoding="utf-8"):
        source = self.dir / "in.csv"
        source.write_bytes(text.encode(encoding) if isinstance(text, str) else text)
        return main([str(source), "--output", str(self.output), "--report", str(self.report_path)])

    def rows(self):
        with self.output.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    def report(self):
        return json.loads(self.report_path.read_text(encoding="utf-8"))

    def test_clean_input_exits_zero(self):
        status = self.run_on(HEADER + " Ada Lovelace , ADA@Example.com ,(415) 555-2671,1815-12-10,us\n"
                             "Alan Turing,,,,\n")
        self.assertEqual(status, EXIT_ALL_USABLE)
        rows = self.rows()
        self.assertEqual(rows[0], {
            "name": "Ada Lovelace", "email": "ada@example.com", "phone": "+14155552671",
            "phone_status": "verified", "birthday": "1815-12-10", "country": "US",
        })
        self.assertEqual(rows[1], {
            "name": "Alan Turing", "email": "", "phone": "", "phone_status": "", "birthday": "", "country": "",
        })
        report = self.report()
        self.assertEqual(report["rejected"], [])
        self.assertEqual(report["invalid_fields"], [])

    def test_unverified_phone_is_usable(self):
        status = self.run_on(HEADER + "Kenji,,03-1234-5678,,JP\n")
        self.assertEqual(status, EXIT_ALL_USABLE)
        self.assertEqual(self.rows()[0]["phone"], "0312345678")
        self.assertEqual(self.rows()[0]["phone_status"], "unverified")

    def test_invalid_field_is_reported_and_dropped(self):
        status = self.run_on(HEADER + "Ada,not-an-email,555-CALL,03/04/1990,US\n")
        self.assertEqual(status, EXIT_ROWS_REPORTED)
        row = self.rows()[0]
        self.assertEqual((row["name"], row["email"], row["phone"], row["birthday"]), ("Ada", "", "", ""))
        problems = self.report()["invalid_fields"]
        self.assertEqual([(p["row"], p["field"]) for p in problems], [(2, "email"), (2, "phone"), (2, "birthday")])
        self.assertIn("ambiguous", problems[2]["reason"])

    def test_row_without_name_is_rejected(self):
        status = self.run_on(HEADER + "  ,a@example.com,,,\nBob,,,,\n")
        self.assertEqual(status, EXIT_ROWS_REPORTED)
        self.assertEqual([row["name"] for row in self.rows()], ["Bob"])
        self.assertEqual(self.report()["rejected"], [{"row": 2, "reason": "name is missing"}])

    def test_wrong_field_count_is_rejected(self):
        status = self.run_on(HEADER + "Ada,a@example.com\n")
        self.assertEqual(status, EXIT_ROWS_REPORTED)
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.report()["rejected"][0]["row"], 2)

    def test_merge_by_email_keeps_most_complete(self):
        status = self.run_on(HEADER + "Ada,ada@example.com,,,\n"
                             "Ada Lovelace,ADA@example.com,415 555 2671,1815-12-10,US\n"
                             "Bob,bob@example.com,,,\n")
        self.assertEqual(status, EXIT_ALL_USABLE)
        rows = self.rows()
        self.assertEqual([row["name"] for row in rows], ["Ada Lovelace", "Bob"])
        merged = self.report()["merged"]
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["kept_row"], 3)
        self.assertEqual(merged[0]["merged_rows"], [2, 3])
        self.assertIn("ada@example.com", merged[0]["reason"])

    def test_merge_by_verified_phone_and_transitively(self):
        status = self.run_on(HEADER + "A,a@example.com,+1 415 555 2671,,US\n"
                             "B,,(415) 555-2671,,US\n"
                             "C,a@example.com,,,\n")
        self.assertEqual(status, EXIT_ALL_USABLE)
        self.assertEqual(len(self.rows()), 1)
        merged = self.report()["merged"]
        self.assertEqual(merged[0]["merged_rows"], [2, 3, 4])
        self.assertEqual(merged[0]["kept_row"], 2)

    def test_unverified_phones_do_not_merge(self):
        self.run_on(HEADER + "A,,0312345678,,JP\nB,,0312345678,,JP\n")
        self.assertEqual(len(self.rows()), 2)
        self.assertEqual(self.report()["merged"], [])

    def test_bom_and_column_order(self):
        status = self.run_on("﻿country,Name,email,phone,birthday\nFR,Marie,,01 23 45 67 89,\n")
        self.assertEqual(status, EXIT_ALL_USABLE)
        self.assertEqual(self.rows()[0]["phone"], "+33123456789")

    def assertUnreadable(self, text):
        with self.assertRaises(SystemExit) as caught:
            self.run_on(text)
        self.assertEqual(caught.exception.code, EXIT_INPUT_UNREADABLE)

    def test_missing_file(self):
        with self.assertRaises(SystemExit) as caught:
            main([str(self.dir / "absent.csv"), "--output", str(self.output), "--report", str(self.report_path)])
        self.assertEqual(caught.exception.code, EXIT_INPUT_UNREADABLE)

    def test_empty_file(self):
        self.assertUnreadable("")

    def test_missing_name_column(self):
        self.assertUnreadable("email,phone,birthday,country\n")

    def test_not_utf8(self):
        self.assertUnreadable(b"name,email,phone,birthday,country\n\xff\xfe,,,,\n")

    def test_malformed_csv(self):
        self.assertUnreadable(HEADER + 'Ada,"unterminated,,,\n')


class ProcessTest(unittest.TestCase):
    def test_exit_status_from_command_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            source = out / "in.csv"
            source.write_text(HEADER + ",x@example.com,,,\n", encoding="utf-8")
            args = [sys.executable, "-m", "contactclean", str(source),
                    "--output", str(out / "c.csv"), "--report", str(out / "r.json")]
            self.assertEqual(subprocess.run(args, cwd=ROOT).returncode, EXIT_ROWS_REPORTED)
            args[3] = str(out / "missing.csv")
            result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, EXIT_INPUT_UNREADABLE)
            self.assertIn("cannot read", result.stderr)


if __name__ == "__main__":
    unittest.main()
