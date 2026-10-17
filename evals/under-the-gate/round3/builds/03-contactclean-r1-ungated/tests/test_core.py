import datetime as dt
import unittest

from contactclean.core import clean

TODAY = dt.date(2026, 10, 17)


def rows(*dicts):
    return [(i, d) for i, d in enumerate(dicts, start=2)]


class CleanTests(unittest.TestCase):
    def test_missing_name_rejected(self):
        result = clean(rows({"name": "  ", "email": "a@x.com"}), TODAY)
        self.assertEqual(result.contacts, [])
        self.assertEqual(result.rejected, [{"row": 2, "reason": "missing name"}])
        self.assertFalse(result.all_rows_usable)

    def test_empty_fields_are_not_invalid(self):
        result = clean(rows({"name": "Ann", "email": "", "phone": None, "birthday": " "}), TODAY)
        self.assertTrue(result.all_rows_usable)
        c = result.contacts[0]
        self.assertEqual((c.email, c.phone, c.phone_status, c.birthday, c.country), ("", "", "", "", ""))

    def test_invalid_field_reported_and_dropped(self):
        result = clean(rows({"name": "Ann", "email": "nope", "phone": "(415) 555-2671", "country": "us"}), TODAY)
        c = result.contacts[0]
        self.assertEqual(c.email, "")
        self.assertEqual(c.phone, "+14155552671")
        self.assertEqual(c.country, "US")
        self.assertEqual(len(result.invalid_fields), 1)
        issue = result.invalid_fields[0]
        self.assertEqual((issue["row"], issue["field"], issue["value"]), (2, "email", "nope"))
        self.assertTrue(issue["reason"])

    def test_merge_by_email_keeps_most_complete(self):
        result = clean(rows(
            {"name": "Ann", "email": "ANN@x.com"},
            {"name": "Ann B", "email": "ann@x.com", "birthday": "1990-01-02", "country": "GB"},
            {"name": "Bob", "email": "bob@x.com"},
        ), TODAY)
        self.assertEqual([c.name for c in result.contacts], ["Ann B", "Bob"])
        self.assertEqual(result.merged, [{"kept_row": 3, "merged_rows": [2], "matched_on": ["email"]}])
        self.assertTrue(result.all_rows_usable)

    def test_merge_by_verified_phone_and_transitively(self):
        result = clean(rows(
            {"name": "A", "email": "a@x.com", "phone": "415-555-2671", "country": "US"},
            {"name": "B", "phone": "+1 (415) 555 2671"},
            {"name": "C", "email": "A@X.com"},
        ), TODAY)
        self.assertEqual(len(result.contacts), 1)
        self.assertEqual(result.contacts[0].row, 2)
        self.assertEqual(result.merged[0]["merged_rows"], [3, 4])
        self.assertEqual(result.merged[0]["matched_on"], ["email", "phone"])

    def test_unverified_phones_do_not_merge(self):
        result = clean(rows(
            {"name": "A", "phone": "555 1234"},
            {"name": "B", "phone": "555-1234"},
        ), TODAY)
        self.assertEqual(len(result.contacts), 2)
        self.assertEqual(result.merged, [])

    def test_tie_keeps_earliest_row(self):
        result = clean(rows({"name": "A", "email": "a@x.com"}, {"name": "B", "email": "a@x.com"}), TODAY)
        self.assertEqual(result.contacts[0].name, "A")


if __name__ == "__main__":
    unittest.main()
