import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from contactclean.cli import main
from contactclean.core import clean

ROOT = Path(__file__).resolve().parent.parent


def run_clean(text):
    return clean(io.StringIO(textwrap.dedent(text).lstrip()))


class CleanTests(unittest.TestCase):
    def test_trims_and_keeps_empty_fields_empty(self):
        r = run_clean("""
            name,email,phone,birthday,country
              Ann Lee  ,,,,
        """)
        self.assertTrue(r.all_rows_usable)
        self.assertEqual(r.contacts[0].as_output(), {
            "name": "Ann Lee", "email": "", "phone": "", "phone_status": "",
            "birthday": "", "country": "",
        })

    def test_invalid_field_reported_and_dropped(self):
        r = run_clean("""
            name,email,phone,birthday,country
            Ann,not-an-email,555,03/04/1990,us
        """)
        self.assertFalse(r.all_rows_usable)
        c = r.contacts[0]
        self.assertEqual((c.name, c.email, c.phone, c.birthday, c.country),
                         ("Ann", "", "", "", "US"))
        self.assertEqual([(i["row"], i["field"]) for i in r.invalid_fields],
                         [(2, "email"), (2, "phone"), (2, "birthday")])
        self.assertTrue(all(i["reason"] for i in r.invalid_fields))

    def test_missing_name_rejected(self):
        r = run_clean("""
            name,email
            ,a@x.com
            Bob,b@x.com
        """)
        self.assertEqual(r.rejected, [{"row": 2, "reason": "missing name"}])
        self.assertEqual([c.name for c in r.contacts], ["Bob"])

    def test_unverified_phone(self):
        r = run_clean("""
            name,phone,country
            Ann,03-1234-5678,
        """)
        self.assertTrue(r.all_rows_usable)
        self.assertEqual(r.contacts[0].phone, "03-1234-5678")
        self.assertEqual(r.contacts[0].phone_status, "unverified")

    def test_merge_by_email_keeps_most_complete(self):
        r = run_clean("""
            name,email,phone,birthday,country
            Ann,ANN@x.com,,,
            Ann Lee,ann@x.com,(415) 555-2671,1990-01-01,US
            Bob,bob@x.com,,,
        """)
        self.assertEqual([c.row for c in r.contacts], [3, 4])
        self.assertEqual(r.merged, [{"kept_row": 3, "merged_rows": [2], "rows": [2, 3]}])
        self.assertTrue(r.all_rows_usable)

    def test_merge_by_verified_phone_and_transitively(self):
        r = run_clean("""
            name,email,phone,country
            A,a@x.com,415-555-2671,US
            B,,+1 (415) 555 2671,US
            C,a@x.com,,
        """)
        self.assertEqual(len(r.contacts), 1)
        self.assertEqual(r.merged[0]["rows"], [2, 3, 4])
        self.assertEqual(r.merged[0]["kept_row"], 2)

    def test_unverified_phones_not_merged(self):
        r = run_clean("""
            name,phone
            A,12345678
            B,12345678
        """)
        self.assertEqual(len(r.contacts), 2)
        self.assertEqual(r.merged, [])


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.out = self.dir / "clean.csv"
        self.rep = self.dir / "report.json"

    def tearDown(self):
        self.tmp.cleanup()

    def write_input(self, text, encoding="utf-8"):
        path = self.dir / "in.csv"
        path.write_text(textwrap.dedent(text).lstrip(), encoding=encoding)
        return path

    def run_main(self, path):
        from contextlib import redirect_stderr
        with redirect_stderr(io.StringIO()):
            return main([str(path), "--output", str(self.out), "--report", str(self.rep)])

    def test_exit_0_and_outputs(self):
        path = self.write_input("""
            name,email,phone,birthday,country
            Ann,Ann@X.com,020 7946 0958,25/12/1990,gb
        """)
        self.assertEqual(self.run_main(path), 0)
        with self.out.open(newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(rows, [{
            "name": "Ann", "email": "ann@x.com", "phone": "+442079460958",
            "phone_status": "verified", "birthday": "1990-12-25", "country": "GB",
        }])
        report = json.loads(self.rep.read_text())
        self.assertEqual(report["rejected"], [])
        self.assertEqual(report["invalid_fields"], [])

    def test_exit_1_when_rejected_or_reported(self):
        path = self.write_input("""
            name,email
            ,a@x.com
        """)
        self.assertEqual(self.run_main(path), 1)
        path = self.write_input("""
            name,email
            Ann,bad
        """)
        self.assertEqual(self.run_main(path), 1)
        report = json.loads(self.rep.read_text())
        self.assertEqual(report["invalid_fields"][0]["row"], 2)

    def test_merge_alone_is_exit_0(self):
        path = self.write_input("""
            name,email
            Ann,a@x.com
            Ann,A@x.com
        """)
        self.assertEqual(self.run_main(path), 0)
        self.assertEqual(len(json.loads(self.rep.read_text())["merged"]), 1)

    def test_exit_2_when_unreadable(self):
        self.assertEqual(self.run_main(self.dir / "missing.csv"), 2)
        self.assertEqual(self.run_main(self.write_input("")), 2)
        self.assertEqual(self.run_main(self.write_input("email,phone\na@x.com,\n")), 2)
        bad = self.dir / "bad.csv"
        bad.write_bytes(b"name\n\xff\xfe\x00bad\n")
        self.assertEqual(self.run_main(bad), 2)
        self.assertFalse(self.out.exists())

    def test_bom_and_header_case(self):
        path = self.write_input("Name,Email\nAnn,a@x.com\n", encoding="utf-8-sig")
        self.assertEqual(self.run_main(path), 0)

    def test_module_entry_point(self):
        path = self.write_input("name\nAnn\n")
        proc = subprocess.run(
            [sys.executable, "-m", "contactclean", str(path),
             "--output", str(self.out), "--report", str(self.rep)],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(self.out.exists())


if __name__ == "__main__":
    unittest.main()
