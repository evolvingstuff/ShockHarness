import csv
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from contactclean.clean import clean_rows
from contactclean.cli import main
from contactclean.normalize import (
    InvalidValue,
    normalize_birthday,
    normalize_email,
    normalize_phone,
)

TODAY = dt.date(2026, 10, 17)
ROOT = Path(__file__).resolve().parent.parent


class EmailTests(unittest.TestCase):
    def test_trims_and_lowercases(self):
        self.assertEqual(normalize_email("  Alice@Example.COM "), "alice@example.com")

    def test_rejects_invalid(self):
        for bad in ["alice", "a@b", "a@@b.com", "a b@c.com", "@x.com", "a@-x.com", "a@x.c0m"]:
            with self.subTest(bad=bad), self.assertRaises(InvalidValue):
                normalize_email(bad)


class PhoneTests(unittest.TestCase):
    def test_e164_for_supported_countries(self):
        cases = [
            ("(212) 555-1234", "US", "+12125551234"),
            ("1-212-555-1234", "US", "+12125551234"),
            ("020 7946 0958", "GB", "+442079460958"),
            ("+44 20 7946 0958", "GB", "+442079460958"),
            ("030 1234567", "DE", "+49301234567"),
            ("0049 30 1234567", "DE", "+49301234567"),
            ("01 23 45 67 89", "FR", "+33123456789"),
            ("06.12.34.56.78", "FR", "+33612345678"),
        ]
        for raw, country, expected in cases:
            with self.subTest(raw=raw, country=country):
                self.assertEqual(normalize_phone(raw, country), (expected, True))

    def test_international_number_uses_its_own_calling_code(self):
        self.assertEqual(normalize_phone("+33 6 12 34 56 78", "US"), ("+33612345678", True))

    def test_unknown_country_keeps_digits_unverified(self):
        self.assertEqual(normalize_phone(" 555-0199 ", ""), ("5550199", False))
        self.assertEqual(normalize_phone("02 9876 5432", "AU"), ("0298765432", False))
        self.assertEqual(normalize_phone("+61 2 9876 5432", ""), ("+61298765432", False))

    def test_invalid(self):
        for raw, country in [
            ("call me", "US"),
            ("555-1234", "US"),  # too short for the US
            ("(112) 555-1234", "US"),  # area code cannot start with 1
            ("01 23 45", "FR"),
            ("123", ""),
            ("+44 12", ""),
        ]:
            with self.subTest(raw=raw), self.assertRaises(InvalidValue):
                normalize_phone(raw, country)


class BirthdayTests(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(normalize_birthday("1990-03-07", TODAY), "1990-03-07")
        self.assertEqual(normalize_birthday("25/12/1990", TODAY), "1990-12-25")  # DD/MM
        self.assertEqual(normalize_birthday("12/25/1990", TODAY), "1990-12-25")  # MM/DD
        self.assertEqual(normalize_birthday("05/05/1990", TODAY), "1990-05-05")  # same either way

    def test_ambiguous_is_invalid(self):
        with self.assertRaisesRegex(InvalidValue, "ambiguous"):
            normalize_birthday("03/04/1990", TODAY)

    def test_invalid(self):
        for bad in ["1990-02-30", "31/31/1990", "March 3 1990", "30/02/1990", "2030-01-01"]:
            with self.subTest(bad=bad), self.assertRaises(InvalidValue):
                normalize_birthday(bad, TODAY)


def row(name="", email="", phone="", birthday="", country=""):
    return {"name": name, "email": email, "phone": phone, "birthday": birthday, "country": country}


class CleanRowsTests(unittest.TestCase):
    def test_clean_row_has_no_report_entries(self):
        result = clean_rows([row(" Ann ", "ANN@X.COM", "2125551234", "1990-01-02", "us")], TODAY)
        self.assertTrue(result.all_usable)
        self.assertEqual(
            result.contacts[0].as_output(),
            {
                "name": "Ann",
                "email": "ann@x.com",
                "phone": "+12125551234",
                "phone_status": "verified",
                "birthday": "1990-01-02",
                "country": "US",
            },
        )

    def test_empty_optional_fields_are_not_reported(self):
        result = clean_rows([row("Ann", " ", "", "", "")], TODAY)
        self.assertTrue(result.all_usable)
        out = result.contacts[0].as_output()
        self.assertEqual(out["email"], "")
        self.assertEqual(out["phone_status"], "")

    def test_unverified_phone_is_kept_and_not_reported(self):
        result = clean_rows([row("Ann", phone="555 0199")], TODAY)
        self.assertTrue(result.all_usable)
        self.assertEqual(result.contacts[0].phone_status, "unverified")

    def test_invalid_field_is_reported_and_dropped(self):
        result = clean_rows([row("Ann", "nope", "12", "03/04/1990", "US")], TODAY)
        self.assertFalse(result.all_usable)
        self.assertEqual(len(result.contacts), 1)
        c = result.contacts[0]
        self.assertEqual((c.email, c.phone, c.birthday), ("", "", ""))
        self.assertEqual([i["field"] for i in result.issues], ["email", "phone", "birthday"])
        self.assertTrue(all(i["row"] == 2 for i in result.issues))
        self.assertIn("ambiguous", result.issues[2]["reason"])

    def test_row_without_name_is_rejected(self):
        result = clean_rows([row("Ann"), row("  ", "x@y.com")], TODAY)
        self.assertEqual(result.rejected, [{"row": 3, "reason": "missing name"}])
        self.assertEqual([c.name for c in result.contacts], ["Ann"])

    def test_merge_on_email_case_insensitive_keeps_most_complete(self):
        result = clean_rows(
            [
                row("Ann", "ann@x.com"),
                row("Ann Smith", "ANN@x.com", "2125551234", "1990-01-02", "US"),
                row("Bob", "bob@x.com"),
            ],
            TODAY,
        )
        self.assertEqual([c.name for c in result.contacts], ["Ann Smith", "Bob"])
        self.assertEqual(
            result.merged,
            [{"kept_row": 3, "merged_rows": [2], "rows": [2, 3], "matched_on": ["email"]}],
        )
        self.assertTrue(result.all_usable)

    def test_merge_on_verified_phone_in_different_formats(self):
        result = clean_rows(
            [row("Ann", phone="(212) 555-1234", country="US"), row("A.", phone="+1 212 555 1234")],
            TODAY,
        )
        self.assertEqual(len(result.contacts), 1)
        self.assertEqual(result.merged[0]["matched_on"], ["phone"])
        self.assertEqual(result.merged[0]["kept_row"], 2)  # tie broken by earliest row

    def test_unverified_phones_do_not_merge(self):
        result = clean_rows([row("Ann", phone="5550199"), row("Bob", phone="5550199")], TODAY)
        self.assertEqual(len(result.contacts), 2)
        self.assertEqual(result.merged, [])

    def test_merge_is_transitive(self):
        result = clean_rows(
            [
                row("A", "a@x.com"),
                row("B", "a@x.com", "2125551234", country="US"),
                row("C", phone="+12125551234", birthday="1990-01-01"),
            ],
            TODAY,
        )
        self.assertEqual(len(result.contacts), 1)
        self.assertEqual(result.merged[0]["rows"], [2, 3, 4])
        self.assertEqual(result.merged[0]["matched_on"], ["email", "phone"])

    def test_rejected_rows_do_not_merge(self):
        result = clean_rows([row("", "a@x.com"), row("Ann", "a@x.com")], TODAY)
        self.assertEqual(result.merged, [])
        self.assertEqual(len(result.contacts), 1)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.out = self.dir / "clean.csv"
        self.report = self.dir / "report.json"

    def tearDown(self):
        self.tmp.cleanup()

    def write_input(self, text):
        path = self.dir / "input.csv"
        path.write_text(text, encoding="utf-8")
        return path

    def run_cli(self, path):
        return main([str(path), "--output", str(self.out), "--report", str(self.report)])

    def read_output(self):
        with open(self.out, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    def test_all_usable_exits_0(self):
        path = self.write_input(
            "name,email,phone,birthday,country\n"
            "Ann,ann@x.com,020 7946 0958,1990-01-02,GB\n"
            "Bob,,,,\n"
        )
        self.assertEqual(self.run_cli(path), 0)
        rows = self.read_output()
        self.assertEqual([r["name"] for r in rows], ["Ann", "Bob"])
        self.assertEqual(rows[0]["phone"], "+442079460958")
        report = json.loads(self.report.read_text())
        self.assertEqual(report["summary"]["rows"], 2)
        self.assertEqual(report["rejected"], [])
        self.assertEqual(report["invalid_fields"], [])

    def test_rejected_or_reported_exits_1(self):
        path = self.write_input("name,email\n,a@x.com\nAnn,bad-email\n")
        self.assertEqual(self.run_cli(path), 1)
        report = json.loads(self.report.read_text())
        self.assertEqual(report["rejected"], [{"row": 2, "reason": "missing name"}])
        self.assertEqual(report["invalid_fields"][0]["row"], 3)
        self.assertEqual(self.read_output(), [
            {"name": "Ann", "email": "", "phone": "", "phone_status": "", "birthday": "", "country": ""}
        ])

    def test_merge_only_exits_0_and_is_reported(self):
        path = self.write_input("name,email\nAnn,a@x.com\nAnn B,A@X.com\n")
        self.assertEqual(self.run_cli(path), 0)
        report = json.loads(self.report.read_text())
        self.assertEqual(report["merged"][0]["rows"], [2, 3])

    def test_header_with_bom_and_odd_case(self):
        path = self.dir / "input.csv"
        path.write_bytes("﻿Name , EMAIL\nAnn,a@x.com\n".encode("utf-8"))
        self.assertEqual(self.run_cli(path), 0)
        self.assertEqual(self.read_output()[0]["email"], "a@x.com")

    def test_unreadable_input_exits_2(self):
        self.assertEqual(self.run_cli(self.dir / "missing.csv"), 2)
        self.assertEqual(self.run_cli(self.write_input("")), 2)
        self.assertEqual(self.run_cli(self.write_input("email,phone\na@x.com,1\n")), 2)
        path = self.dir / "latin1.csv"
        path.write_bytes(b"name\nJos\xe9\n")
        self.assertEqual(self.run_cli(path), 2)
        self.assertFalse(self.out.exists())

    def test_python_m_entry_point(self):
        path = self.write_input("name\nAnn\n")
        proc = subprocess.run(
            [sys.executable, "-m", "contactclean", str(path),
             "--output", str(self.out), "--report", str(self.report)],
            cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT)},
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(self.out.exists())


if __name__ == "__main__":
    unittest.main()
