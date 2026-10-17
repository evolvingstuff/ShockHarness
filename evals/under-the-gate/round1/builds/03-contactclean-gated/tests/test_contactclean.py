import csv
import json
import tempfile
import unittest
from pathlib import Path

from contactclean.cli import EXIT_OK, EXIT_REPORTED, EXIT_UNREADABLE, main
from contactclean.fields import (
    STATUS_UNVERIFIED,
    STATUS_VERIFIED,
    normalize_birthday,
    normalize_email,
    normalize_phone,
)

HEADER = "name,email,phone,birthday,country\n"
FIRST_ROW = 1
SECOND_ROW = FIRST_ROW + 1
THIRD_ROW = SECOND_ROW + 1


class FieldTests(unittest.TestCase):
    def test_email_is_lowercased(self):
        self.assertEqual(normalize_email("Ann@Example.COM").value, "ann@example.com")

    def test_empty_is_not_invalid(self):
        self.assertIsNone(normalize_email("").problem)
        self.assertIsNone(normalize_phone("", "US").problem)
        self.assertIsNone(normalize_birthday("").problem)

    def test_invalid_email(self):
        self.assertIsNotNone(normalize_email("nope").problem)

    def test_phone_e164(self):
        cases = {
            ("(415) 555-2671", "US"): "+14155552671",
            ("020 7946 0958", "GB"): "+442079460958",
            ("+49 30 123456", "DE"): "+4930123456",
            ("01 23 45 67 89", "FR"): "+33123456789",
            ("0033 1 23 45 67 89", "FR"): "+33123456789",
        }
        for (raw, country), expected in cases.items():
            outcome = normalize_phone(raw, country)
            self.assertEqual((outcome.value, outcome.status), (expected, STATUS_VERIFIED))

    def test_phone_unknown_country_is_unverified(self):
        outcome = normalize_phone("555-1234", "")
        self.assertEqual((outcome.value, outcome.status), ("5551234", STATUS_UNVERIFIED))

    def test_invalid_phone(self):
        self.assertIsNotNone(normalize_phone("abc", "US").problem)
        self.assertIsNotNone(normalize_phone("123", "US").problem)
        self.assertIsNotNone(normalize_phone("+44 20 7946 0958", "US").problem)

    def test_birthdays(self):
        cases = {
            "1990-03-04": "1990-03-04",
            "25/12/1990": "1990-12-25",
            "12/25/1990": "1990-12-25",
            "05/05/1990": "1990-05-05",
        }
        for raw, expected in cases.items():
            self.assertEqual(normalize_birthday(raw).value, expected)

    def test_ambiguous_and_impossible_birthdays(self):
        for raw in ("03/04/1990", "31/02/1990", "1990-13-01", "yesterday"):
            self.assertIsNotNone(normalize_birthday(raw).problem, raw)


class CliTests(unittest.TestCase):
    def run_cli(self, content: str):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "in.csv"
            source.write_text(content, encoding="utf-8")
            code = main([str(source), "--output", str(root / "out.csv"), "--report", str(root / "r.json")])
            with (root / "out.csv").open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            report = json.loads((root / "r.json").read_text(encoding="utf-8"))
        return code, rows, report

    def test_clean_input_exits_ok(self):
        code, rows, report = self.run_cli(HEADER + "Ann,ANN@x.io,,,\n")
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(rows[0]["email"], "ann@x.io")
        self.assertEqual(rows[0]["phone"], "")
        self.assertEqual(report["issues"], [])

    def test_missing_name_rejected(self):
        code, rows, report = self.run_cli(HEADER + ",a@x.io,,,\n")
        self.assertEqual(code, EXIT_REPORTED)
        self.assertEqual(rows, [])
        self.assertEqual(report["issues"][0]["row"], FIRST_ROW)
        self.assertEqual(report["issues"][0]["field"], "name")

    def test_invalid_field_dropped_and_reported(self):
        code, rows, report = self.run_cli(HEADER + "Ann,bad,,,\nBob,b@x.io,,,\n")
        self.assertEqual(code, EXIT_REPORTED)
        self.assertEqual(rows[0]["name"], "Ann")
        self.assertEqual(rows[0]["email"], "")
        self.assertEqual(report["issues"][0]["row"], FIRST_ROW)
        self.assertEqual(report["issues"][0]["field"], "email")

    def test_merge_by_email(self):
        content = HEADER + "Ann,A@x.io,,,\nAnn B,a@x.io,415-555-2671,1990-01-02,US\n"
        code, rows, report = self.run_cli(content)
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(len(rows), FIRST_ROW)
        self.assertEqual(rows[0]["phone"], "+14155552671")
        self.assertEqual(report["merged"], [{"kept_row": SECOND_ROW, "rows": [FIRST_ROW, SECOND_ROW]}])

    def test_merge_by_verified_phone_only(self):
        content = (
            HEADER
            + "Ann,,415-555-2671,,US\n"
            + "Bob,b@x.io,(415) 555 2671,,US\n"
            + "Cy,,5551234,,\n"
            + "Di,,5551234,,\n"
        )
        _, rows, report = self.run_cli(content)
        self.assertEqual([row["name"] for row in rows], ["Bob", "Cy", "Di"])
        self.assertEqual(report["merged"][0]["rows"], [FIRST_ROW, SECOND_ROW])

    def test_unreadable_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            argv = [str(root / "missing.csv"), "--output", str(root / "o"), "--report", str(root / "r")]
            with self.assertRaises(SystemExit) as raised:
                main(argv)
        self.assertEqual(raised.exception.code, EXIT_UNREADABLE)

    def test_missing_name_column_is_unreadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "in.csv"
            source.write_text("email\na@x.io\n", encoding="utf-8")
            with self.assertRaises(SystemExit) as raised:
                main([str(source), "--output", str(root / "o"), "--report", str(root / "r")])
        self.assertEqual(raised.exception.code, EXIT_UNREADABLE)


if __name__ == "__main__":
    unittest.main()
