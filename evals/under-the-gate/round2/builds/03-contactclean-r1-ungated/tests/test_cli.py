import csv
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

from contactclean.cli import main
from contactclean.core import clean

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def rec(**kw):
    base = {"name": "", "email": "", "phone": "", "birthday": "", "country": ""}
    base.update(kw)
    return base


class CleanTests(unittest.TestCase):
    TODAY = dt.date(2026, 10, 17)

    def run_clean(self, *records):
        return clean([(i + 2, r) for i, r in enumerate(records)], today=self.TODAY)

    def test_missing_name_rejected(self):
        contacts, report = self.run_clean(rec(name="  ", email="a@b.com"), rec(name="Bob"))
        self.assertEqual([c.name for c in contacts], ["Bob"])
        self.assertEqual(report.rejected, [{"row": 2, "reason": "missing name"}])
        self.assertTrue(report.has_issues)

    def test_empty_fields_are_not_invalid(self):
        contacts, report = self.run_clean(rec(name=" Alice "))
        self.assertEqual(contacts[0].as_row(), {
            "name": "Alice", "email": "", "phone": "", "phone_status": "",
            "birthday": "", "country": ""})
        self.assertFalse(report.has_issues)

    def test_invalid_field_dropped_and_reported(self):
        contacts, report = self.run_clean(
            rec(name="Alice", email="not-an-email", phone="(415) 555-2671", country="us",
                birthday="03/04/1990"))
        c = contacts[0]
        self.assertEqual((c.email, c.phone, c.phone_status, c.birthday, c.country),
                         ("", "+14155552671", "verified", "", "US"))
        self.assertEqual([(f["row"], f["field"]) for f in report.invalid_fields],
                         [(2, "email"), (2, "birthday")])
        self.assertEqual(report.invalid_fields[0]["value"], "not-an-email")

    def test_merge_by_email_keeps_most_complete(self):
        contacts, report = self.run_clean(
            rec(name="Al", email="AL@x.com"),
            rec(name="Alice", email="al@x.com", phone="020 7946 0018", country="GB"),
            rec(name="Bob", email="bob@x.com"),
        )
        self.assertEqual([c.name for c in contacts], ["Alice", "Bob"])
        self.assertEqual(report.merged, [{"kept_row": 3, "merged_rows": [2]}])
        self.assertFalse(report.has_issues)

    def test_merge_by_verified_phone_and_transitively(self):
        contacts, report = self.run_clean(
            rec(name="A", email="a@x.com", phone="+1 415 555 2671"),
            rec(name="B", phone="(415) 555-2671", country="US"),
            rec(name="C", email="a@x.com", birthday="1990-01-01", country="US"),
        )
        self.assertEqual(len(contacts), 1)
        self.assertEqual(report.merged, [{"kept_row": 4, "merged_rows": [2, 3]}])

    def test_tie_keeps_earliest_row(self):
        contacts, report = self.run_clean(rec(name="A", email="a@x.com"), rec(name="B", email="a@x.com"))
        self.assertEqual(contacts[0].name, "A")

    def test_unverified_phones_do_not_merge(self):
        contacts, report = self.run_clean(rec(name="A", phone="5551234"), rec(name="B", phone="555-1234"))
        self.assertEqual(len(contacts), 2)
        self.assertEqual(report.merged, [])


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = os.path.join(self.tmp.name, "clean.csv")
        self.rep = os.path.join(self.tmp.name, "report.json")

    def write_input(self, text):
        path = os.path.join(self.tmp.name, "in.csv")
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(textwrap.dedent(text).lstrip())
        return path

    def run_main(self, path):
        return main([path, "--output", self.out, "--report", self.rep])

    def read_output(self):
        with open(self.out, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        with open(self.rep, encoding="utf-8") as fh:
            return rows, json.load(fh)

    def test_all_usable_exits_0(self):
        path = self.write_input("""
            name,email,phone,birthday,country
            Alice , Alice@Example.com ,06 12 34 56 78,23/04/1990,fr
            Bob,,,,
        """)
        self.assertEqual(self.run_main(path), 0)
        rows, report = self.read_output()
        self.assertEqual(rows[0], {"name": "Alice", "email": "alice@example.com",
                                   "phone": "+33612345678", "phone_status": "verified",
                                   "birthday": "1990-04-23", "country": "FR"})
        self.assertEqual(rows[1]["name"], "Bob")
        self.assertEqual(report["rows_read"], 2)
        self.assertEqual(report["rows_written"], 2)

    def test_merges_alone_exit_0(self):
        path = self.write_input("""
            name,email
            A,a@x.com
            B,A@X.com
        """)
        self.assertEqual(self.run_main(path), 0)
        rows, report = self.read_output()
        self.assertEqual(len(rows), 1)
        self.assertEqual(report["merged"], [{"kept_row": 2, "merged_rows": [3]}])

    def test_rejections_exit_1_with_row_numbers(self):
        path = self.write_input("""
            name,email,phone,birthday,country

            ,a@x.com,,,
            Carol,bad@,,,
            Dan,d@x.com,,,,extra
        """)
        self.assertEqual(self.run_main(path), 1)
        rows, report = self.read_output()
        self.assertEqual([r["name"] for r in rows], ["Carol"])
        self.assertEqual(rows[0]["email"], "")
        self.assertEqual([r["row"] for r in report["rejected"]], [3, 5])
        self.assertEqual(report["invalid_fields"][0]["row"], 4)
        self.assertEqual(report["rows_read"], 3)

    def test_unreadable_input_exits_2(self):
        self.assertEqual(self.run_main(os.path.join(self.tmp.name, "missing.csv")), 2)
        self.assertEqual(self.run_main(self.write_input("")), 2)
        self.assertEqual(self.run_main(self.write_input("email,phone\na@x.com,\n")), 2)
        bad = os.path.join(self.tmp.name, "bin.csv")
        with open(bad, "wb") as fh:
            fh.write(b"name\n\xff\xfe\x00bad\n")
        self.assertEqual(self.run_main(bad), 2)
        self.assertFalse(os.path.exists(self.out))

    def test_module_entry_point(self):
        path = self.write_input("name\nAlice\n")
        proc = subprocess.run(
            [sys.executable, "-m", "contactclean", path, "--output", self.out, "--report", self.rep],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(os.path.exists(self.out))


if __name__ == "__main__":
    unittest.main()
