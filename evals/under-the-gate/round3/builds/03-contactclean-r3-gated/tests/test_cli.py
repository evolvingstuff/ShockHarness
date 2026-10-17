import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from contactclean.cli import EXIT_ALL_USABLE, EXIT_ROWS_REPORTED, EXIT_UNREADABLE_INPUT, main


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def run_cli(self, content):
        source = self.dir / "input.csv"
        if isinstance(content, bytes):
            source.write_bytes(content)
        else:
            source.write_text(content, encoding="utf-8")
        return self.run_on(source)

    def run_on(self, source):
        output, report = self.dir / "clean.csv", self.dir / "report.json"
        args = [str(source), "--output", str(output), "--report", str(report)]
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            status = main(args)
        with output.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        return status, rows, json.loads(report.read_text(encoding="utf-8")), stderr.getvalue()

    def exit_status_on(self, source):
        stderr = io.StringIO()
        args = [str(source), "--output", str(self.dir / "clean.csv"), "--report", str(self.dir / "report.json")]
        with redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            main(args)
        self.assertFalse((self.dir / "clean.csv").exists())
        return raised.exception.code, stderr.getvalue()

    def unreadable(self, content):
        source = self.dir / "input.csv"
        if isinstance(content, bytes):
            source.write_bytes(content)
        else:
            source.write_text(content, encoding="utf-8")
        return self.exit_status_on(source)

    def test_clean_input_exits_zero(self):
        status, rows, report, _ = self.run_cli(
            "name,email,phone,birthday,country\n"
            " Ada Lovelace ,ADA@Example.com,(212) 555-1234,12/31/1815,us\n"
            "Alan Turing,,,,\n"
        )
        self.assertEqual(status, EXIT_ALL_USABLE)
        self.assertEqual(rows[0], {
            "name": "Ada Lovelace", "email": "ada@example.com", "phone": "+12125551234",
            "phone_status": "verified", "birthday": "1815-12-31", "country": "US",
        })
        self.assertEqual(rows[1], {
            "name": "Alan Turing", "email": "", "phone": "", "phone_status": "", "birthday": "", "country": "",
        })
        self.assertEqual(report["rejected"], [])
        self.assertEqual(report["invalid_fields"], [])
        self.assertEqual(report["rows_read"], 2)

    def test_unverified_phone_is_usable(self):
        status, rows, _, _ = self.run_cli("name,phone,country\nKen,03-1234-5678,JP\n")
        self.assertEqual(status, EXIT_ALL_USABLE)
        self.assertEqual((rows[0]["phone"], rows[0]["phone_status"]), ("0312345678", "unverified"))

    def test_invalid_field_is_reported_and_dropped(self):
        status, rows, report, _ = self.run_cli(
            "name,email,phone,birthday,country\n"
            "Ada,not-an-email,555-CALL,03/04/1990,US\n"
        )
        self.assertEqual(status, EXIT_ROWS_REPORTED)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["name"], rows[0]["email"], rows[0]["phone"], rows[0]["birthday"]), ("Ada", "", "", ""))
        self.assertEqual(rows[0]["country"], "US")
        self.assertEqual({(item["row"], item["field"]) for item in report["invalid_fields"]},
                         {(2, "email"), (2, "phone"), (2, "birthday")})
        for item in report["invalid_fields"]:
            self.assertTrue(item["reason"])

    def test_row_without_name_is_rejected(self):
        status, rows, report, _ = self.run_cli("name,email\n  ,x@example.com\nBob,bob@example.com\n")
        self.assertEqual(status, EXIT_ROWS_REPORTED)
        self.assertEqual([row["name"] for row in rows], ["Bob"])
        self.assertEqual(report["rejected"], [{"row": 2, "reason": "missing name"}])

    def test_row_with_wrong_field_count_is_rejected(self):
        status, rows, report, _ = self.run_cli("name,email\nAda,a@example.com,extra\n")
        self.assertEqual(status, EXIT_ROWS_REPORTED)
        self.assertEqual(rows, [])
        self.assertEqual(report["rejected"][0]["row"], 2)

    def test_merge_by_email_keeps_most_complete(self):
        status, rows, report, _ = self.run_cli(
            "name,email,phone,birthday,country\n"
            "Ada,ada@example.com,,,\n"
            "Ada L.,ADA@example.com,(212) 555-1234,1815-12-10,US\n"
            "Bob,bob@example.com,,,\n"
        )
        self.assertEqual(status, EXIT_ALL_USABLE)
        self.assertEqual([row["name"] for row in rows], ["Ada L.", "Bob"])
        self.assertEqual(report["merged"], [
            {"kept_row": 3, "merged_rows": [2], "reason": "same email ada@example.com"},
        ])

    def test_merge_by_verified_phone_only(self):
        status, rows, report, _ = self.run_cli(
            "name,phone,country\n"
            "Ada,212-555-1234,US\n"
            "Ada Again,+1 212 555 1234,\n"
            "Ken,5550100,\n"
            "Ken Again,555 0100,\n"
        )
        self.assertEqual(status, EXIT_ALL_USABLE)
        self.assertEqual([row["name"] for row in rows], ["Ada", "Ken", "Ken Again"])
        self.assertEqual(report["merged"][0]["kept_row"], 2)
        self.assertEqual(report["merged"][0]["merged_rows"], [3])

    def test_merge_is_transitive(self):
        _, rows, report, _ = self.run_cli(
            "name,email,phone,country\n"
            "A,a@example.com,,\n"
            "B,a@example.com,2125551234,US\n"
            "C,,+12125551234,\n"
        )
        self.assertEqual([row["name"] for row in rows], ["B"])
        self.assertEqual(report["merged"][0]["merged_rows"], [2, 4])

    def test_missing_file_exits_two(self):
        status, stderr = self.exit_status_on(self.dir / "absent.csv")
        self.assertEqual(status, EXIT_UNREADABLE_INPUT)
        self.assertIn("cannot read", stderr)

    def test_not_utf8_exits_two(self):
        status, _ = self.unreadable(b"name\n\xff\xfe\x00bad\n")
        self.assertEqual(status, EXIT_UNREADABLE_INPUT)

    def test_malformed_csv_exits_two(self):
        status, _ = self.unreadable('name,email\n"Ada"x,a@example.com\n')
        self.assertEqual(status, EXIT_UNREADABLE_INPUT)

    def test_missing_name_column_exits_two(self):
        status, stderr = self.unreadable("email\na@example.com\n")
        self.assertEqual(status, EXIT_UNREADABLE_INPUT)
        self.assertIn("name", stderr)

    def test_empty_file_exits_two(self):
        status, _ = self.unreadable("")
        self.assertEqual(status, EXIT_UNREADABLE_INPUT)

    def test_byte_order_mark_and_header_case(self):
        status, rows, _, _ = self.run_cli("﻿Name, Email \nAda,a@example.com\n")
        self.assertEqual(status, EXIT_ALL_USABLE)
        self.assertEqual(rows[0]["email"], "a@example.com")


if __name__ == "__main__":
    unittest.main()
