import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from contactclean.cli import run

HEADER = "name,email,phone,birthday,country\n"


class CliTest(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.output = self.directory / "clean.csv"
        self.report = self.directory / "report.json"

    def run_on(self, content):
        source = self.directory / "input.csv"
        source.write_text(content, encoding="utf-8")
        status = run([str(source), "--output", str(self.output), "--report", str(self.report)])
        return status, self.output.read_text(encoding="utf-8").splitlines(), json.loads(self.report.read_text(encoding="utf-8"))

    def test_clean_input_exits_zero(self):
        status, lines, report = self.run_on(HEADER + "  Ann Lee , ANN@Example.com ,(415) 555-2671,1990-04-07, us \n")
        self.assertEqual(status, 0)
        self.assertEqual(lines, [
            "name,email,phone,phone_status,birthday,country",
            "Ann Lee,ann@example.com,+14155552671,verified,1990-04-07,US",
        ])
        self.assertEqual(report["rejected"], [])
        self.assertEqual(report["invalid_fields"], [])

    def test_empty_optional_fields_stay_empty_and_are_not_reported(self):
        status, lines, report = self.run_on(HEADER + "Bob,,,,\nCleo\n")
        self.assertEqual(status, 0)
        self.assertEqual(lines[1:], ["Bob,,,,,", "Cleo,,,,,"])
        self.assertEqual(report["invalid_fields"], [])

    def test_unknown_country_marks_phone_unverified(self):
        status, lines, _ = self.run_on(HEADER + "Dan,,+39 06 1234 5678,,IT\n")
        self.assertEqual(status, 0)
        self.assertEqual(lines[1], "Dan,,+390612345678,unverified,,IT")

    def test_invalid_fields_are_reported_and_dropped(self):
        status, lines, report = self.run_on(HEADER + "Eve,not-an-email,555-CALL,03/04/2001,US\n")
        self.assertEqual(status, 1)
        self.assertEqual(lines[1], "Eve,,,,,US")
        self.assertEqual([(issue["row"], issue["field"]) for issue in report["invalid_fields"]],
                         [(2, "email"), (2, "phone"), (2, "birthday")])
        self.assertTrue(all(issue["reason"] for issue in report["invalid_fields"]))

    def test_row_without_name_is_rejected(self):
        status, lines, report = self.run_on(HEADER + "Fay,fay@example.com,,,\n  ,ghost@example.com,,,\n")
        self.assertEqual(status, 1)
        self.assertEqual(len(lines), 2)
        self.assertEqual(report["rejected"], [{"row": 3, "reason": "name is missing"}])

    def test_merges_by_email_and_verified_phone(self):
        content = HEADER + (
            "Gil,GIL@example.com,,,\n"
            "Gil Moss,gil@example.com,020 7946 0958,1970-01-02,GB\n"
            "G. Moss,,+44 20 7946 0958,,GB\n"
            "Hal,,555 1234,,\n"
            "Hal Two,,555 1234,,\n"
        )
        status, lines, report = self.run_on(content)
        self.assertEqual(status, 0)
        self.assertEqual(lines[1:], [
            "Gil Moss,gil@example.com,+442079460958,verified,1970-01-02,GB",
            "Hal,,5551234,unverified,,",
            "Hal Two,,5551234,unverified,,",
        ])
        self.assertEqual(report["merged"], [{"kept_row": 3, "rows": [2, 3, 4]}])
        self.assertEqual(report["rows_read"], 5)
        self.assertEqual(report["rows_written"], 3)

    def test_unreadable_input_exits_two(self):
        missing = self.directory / "missing.csv"
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            run([str(missing), "--output", str(self.output), "--report", str(self.report)])
        self.assertEqual(raised.exception.code, 2)

    def test_bad_inputs_exit_two(self):
        for name, content in (("empty.csv", b""), ("binary.csv", b"\xff\xfe\x00name"), ("columns.csv", b"name,email\nA,a@b.c\n")):
            with self.subTest(name=name):
                source = self.directory / name
                source.write_bytes(content)
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                    run([str(source), "--output", str(self.output), "--report", str(self.report)])
                self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
