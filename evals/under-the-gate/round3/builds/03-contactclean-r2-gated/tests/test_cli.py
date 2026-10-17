import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from contactclean.cli import EXIT_ALL_USABLE, EXIT_ROWS_REPORTED, EXIT_UNREADABLE_INPUT, main


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.output = self.root / "clean.csv"
        self.report = self.root / "report.json"

    def run_cli(self, text, encoding="utf-8"):
        source = self.root / "input.csv"
        source.write_bytes(text.encode(encoding))
        return main([str(source), "--output", str(self.output), "--report", str(self.report)])

    def rows(self):
        with self.output.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    def report_data(self):
        return json.loads(self.report.read_text(encoding="utf-8"))


class CleanRunTests(CliTestCase):
    def test_all_usable_exits_zero(self):
        status = self.run_cli(
            "name,email,phone,birthday,country\n"
            " Ann Lee , ANN@Example.com ,(415) 555-2671,04/23/1990,us\n"
            "Bob,,,,\n"
        )
        self.assertEqual(status, EXIT_ALL_USABLE)
        rows = self.rows()
        self.assertEqual(
            rows[0],
            {
                "name": "Ann Lee",
                "email": "ann@example.com",
                "phone": "+14155552671",
                "phone_status": "verified",
                "birthday": "1990-04-23",
                "country": "US",
            },
        )
        self.assertEqual(rows[1], {"name": "Bob", "email": "", "phone": "", "phone_status": "", "birthday": "", "country": ""})
        report = self.report_data()
        self.assertEqual(report["rejected"], [])
        self.assertEqual(report["invalid_fields"], [])
        self.assertEqual(report["rows_read"], 2)

    def test_unknown_country_phone_is_unverified(self):
        status = self.run_cli("name,phone\nCho,+81 3 1234 5678\n")
        self.assertEqual(status, EXIT_ALL_USABLE)
        self.assertEqual(self.rows()[0]["phone"], "+81312345678")
        self.assertEqual(self.rows()[0]["phone_status"], "unverified")

    def test_invalid_fields_are_reported_and_dropped(self):
        status = self.run_cli(
            "name,email,phone,birthday,country\n"
            "Ann,not-an-email,555,03/04/1990,US\n"
        )
        self.assertEqual(status, EXIT_ROWS_REPORTED)
        row = self.rows()[0]
        self.assertEqual((row["name"], row["email"], row["phone"], row["birthday"], row["country"]), ("Ann", "", "", "", "US"))
        issues = self.report_data()["invalid_fields"]
        self.assertEqual([(issue["row"], issue["field"]) for issue in issues], [(2, "email"), (2, "phone"), (2, "birthday")])
        self.assertTrue(all(issue["reason"] for issue in issues))

    def test_row_without_name_is_rejected(self):
        status = self.run_cli("name,email\nAnn,ann@example.com\n  ,ghost@example.com\n")
        self.assertEqual(status, EXIT_ROWS_REPORTED)
        self.assertEqual([row["name"] for row in self.rows()], ["Ann"])
        self.assertEqual(self.report_data()["rejected"], [{"row": 3, "reason": "row has no name"}])

    def test_row_with_too_many_fields_is_rejected(self):
        status = self.run_cli("name,email\nAnn,ann@example.com,extra\n")
        self.assertEqual(status, EXIT_ROWS_REPORTED)
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.report_data()["rejected"][0]["row"], 2)


class MergeTests(CliTestCase):
    def test_same_email_case_insensitive_keeps_most_complete(self):
        status = self.run_cli(
            "name,email,phone,birthday,country\n"
            "Ann,ann@example.com,,,\n"
            "Ann Lee,ANN@example.com,020 7946 0958,1990-04-23,GB\n"
            "Bob,bob@example.com,,,\n"
        )
        self.assertEqual(status, EXIT_ALL_USABLE)
        self.assertEqual([row["name"] for row in self.rows()], ["Ann Lee", "Bob"])
        self.assertEqual(self.report_data()["merged"], [{"kept_row": 3, "merged_rows": [2], "reason": "same email"}])

    def test_same_verified_phone_merges_transitively(self):
        self.run_cli(
            "name,email,phone,country\n"
            "Ann,ann@example.com,+44 20 7946 0958,GB\n"
            "A. Lee,,020 7946 0958,GB\n"
            "Annie,ann@example.com,,\n"
        )
        self.assertEqual([row["name"] for row in self.rows()], ["Ann"])
        self.assertEqual(
            self.report_data()["merged"],
            [{"kept_row": 2, "merged_rows": [3, 4], "reason": "same email or phone"}],
        )

    def test_unverified_phone_does_not_merge(self):
        self.run_cli("name,phone\nAnn,0312345678\nBob,0312345678\n")
        self.assertEqual([row["name"] for row in self.rows()], ["Ann", "Bob"])
        self.assertEqual(self.report_data()["merged"], [])

    def test_tie_keeps_first_row(self):
        self.run_cli("name,email\nFirst,x@example.com\nSecond,x@example.com\n")
        self.assertEqual([row["name"] for row in self.rows()], ["First"])


class UnreadableInputTests(CliTestCase):
    def assert_unreadable(self, action):
        with redirect_stderr(io.StringIO()) as errors, self.assertRaises(SystemExit) as raised:
            action()
        self.assertEqual(raised.exception.code, EXIT_UNREADABLE_INPUT)
        self.assertIn("contactclean:", errors.getvalue())

    def test_missing_file(self):
        missing = str(self.root / "missing.csv")
        self.assert_unreadable(lambda: main([missing, "--output", str(self.output), "--report", str(self.report)]))

    def test_not_utf8(self):
        self.assert_unreadable(lambda: self.run_cli("name\nJos\xe9\n", encoding="latin-1"))

    def test_broken_csv(self):
        self.assert_unreadable(lambda: self.run_cli('name,email\n"Ann,ann@example.com\n'))

    def test_no_name_column(self):
        self.assert_unreadable(lambda: self.run_cli("email\nann@example.com\n"))

    def test_empty_file(self):
        self.assert_unreadable(lambda: self.run_cli(""))


if __name__ == "__main__":
    unittest.main()
