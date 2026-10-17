import csv
import json
import tempfile
import unittest
from pathlib import Path

from contactclean.cli import EXIT_OK, EXIT_ROWS_REPORTED, EXIT_UNREADABLE, main
from contactclean.csvfiles import HEADER_ROWS

HEADER = "name,email,phone,birthday,country\n"
FIRST_ROW = HEADER_ROWS + 1
SECOND_ROW = FIRST_ROW + 1
THIRD_ROW = SECOND_ROW + 1


class CliTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.input = self.dir / "input.csv"
        self.output = self.dir / "clean.csv"
        self.report = self.dir / "report.json"

    def run_cli(self, content: str) -> int:
        self.input.write_text(content, encoding="utf-8")
        return main([str(self.input), "--output", str(self.output), "--report", str(self.report)])

    def rows(self) -> list[dict[str, str]]:
        with self.output.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    def report_data(self) -> dict:
        return json.loads(self.report.read_text(encoding="utf-8"))

    def test_clean_input_exits_ok(self) -> None:
        code = self.run_cli(HEADER + " Ann Lee , ANN@Example.com ,(415) 555-2671,23/04/1990,us\nBob,,,,\n")
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(
            self.rows(),
            [
                {"name": "Ann Lee", "email": "ann@example.com", "phone": "+14155552671",
                 "phone_status": "verified", "birthday": "1990-04-23", "country": "US"},
                {"name": "Bob", "email": "", "phone": "", "phone_status": "", "birthday": "", "country": ""},
            ],
        )
        report = self.report_data()
        self.assertEqual(report["rejected"], [])
        self.assertEqual(report["invalid_fields"], [])
        self.assertEqual(report["merged"], [])

    def test_unknown_country_phone_is_unverified(self) -> None:
        code = self.run_cli(HEADER + "Kenji,,03-1234-5678,,JP\n")
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(self.rows()[0]["phone"], "0312345678")
        self.assertEqual(self.rows()[0]["phone_status"], "unverified")

    def test_invalid_fields_are_reported_and_dropped(self) -> None:
        code = self.run_cli(HEADER + "Ann,not-an-email,12345,04/05/1990,US\n")
        self.assertEqual(code, EXIT_ROWS_REPORTED)
        self.assertEqual(
            self.rows(),
            [{"name": "Ann", "email": "", "phone": "", "phone_status": "", "birthday": "", "country": "US"}],
        )
        issues = self.report_data()["invalid_fields"]
        self.assertEqual(sorted(issue["field"] for issue in issues), ["birthday", "email", "phone"])
        self.assertTrue(all(issue["row"] == FIRST_ROW for issue in issues))
        self.assertTrue(all(issue["reason"] for issue in issues))

    def test_row_without_name_is_rejected(self) -> None:
        code = self.run_cli(HEADER + "Ann,,,,\n  ,bob@example.com,,,\n")
        self.assertEqual(code, EXIT_ROWS_REPORTED)
        self.assertEqual([row["name"] for row in self.rows()], ["Ann"])
        self.assertEqual(self.report_data()["rejected"], [{"row": SECOND_ROW, "reason": "row has no name"}])

    def test_merge_by_email_keeps_most_complete(self) -> None:
        code = self.run_cli(
            HEADER
            + "Ann,ann@example.com,,,\n"
            + "Ann Lee,ANN@example.com,(415) 555-2671,1990-04-23,US\n"
            + "Bob,bob@example.com,,,\n"
        )
        self.assertEqual(code, EXIT_OK)
        self.assertEqual([row["name"] for row in self.rows()], ["Ann Lee", "Bob"])
        self.assertEqual(
            self.report_data()["merged"],
            [{"kept_row": SECOND_ROW, "merged_rows": [FIRST_ROW], "reasons": ["same email"]}],
        )

    def test_merge_by_verified_phone_only(self) -> None:
        code = self.run_cli(
            HEADER
            + "Ann,,(415) 555-2671,,US\n"
            + "Annie,annie@example.com,+1 415 555 2671,,US\n"
            + "Kenji,,03-1234-5678,,\n"
            + "Ken,,03-1234-5678,,\n"
        )
        self.assertEqual(code, EXIT_OK)
        self.assertEqual([row["name"] for row in self.rows()], ["Annie", "Kenji", "Ken"])
        self.assertEqual(
            self.report_data()["merged"],
            [{"kept_row": SECOND_ROW, "merged_rows": [FIRST_ROW], "reasons": ["same phone"]}],
        )

    def test_merge_is_transitive(self) -> None:
        code = self.run_cli(
            HEADER
            + "A,a@example.com,,,\n"
            + "B,a@example.com,(415) 555-2671,,US\n"
            + "C,c@example.com,415-555-2671,1990-01-01,US\n"
        )
        self.assertEqual(code, EXIT_OK)
        self.assertEqual([row["name"] for row in self.rows()], ["C"])
        merged = self.report_data()["merged"]
        self.assertEqual(merged[0]["kept_row"], THIRD_ROW)
        self.assertEqual(merged[0]["merged_rows"], [FIRST_ROW, SECOND_ROW])

    def test_missing_file_exits_unreadable(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            main([str(self.dir / "absent.csv"), "--output", str(self.output), "--report", str(self.report)])
        self.assertEqual(raised.exception.code, EXIT_UNREADABLE)

    def test_missing_column_exits_unreadable(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            self.run_cli("name,email\nAnn,ann@example.com\n")
        self.assertEqual(raised.exception.code, EXIT_UNREADABLE)

    def test_undecodable_file_exits_unreadable(self) -> None:
        self.input.write_bytes(HEADER.encode() + b"\xff\xfe\xfa,,,,\n")
        with self.assertRaises(SystemExit) as raised:
            main([str(self.input), "--output", str(self.output), "--report", str(self.report)])
        self.assertEqual(raised.exception.code, EXIT_UNREADABLE)

    def test_empty_file_exits_unreadable(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            self.run_cli("")
        self.assertEqual(raised.exception.code, EXIT_UNREADABLE)


if __name__ == "__main__":
    unittest.main()
