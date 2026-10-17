import unittest
from datetime import date

from contactclean.clean import clean_rows

TODAY = date(2026, 10, 17)


def row(name="", email="", phone="", birthday="", country=""):
    return {"name": name, "email": email, "phone": phone,
            "birthday": birthday, "country": country}


class CleanTests(unittest.TestCase):
    def test_trims_and_normalizes(self):
        result = clean_rows([row("  Ann Lee ", " ANN@Example.com ", " (415) 555-2671 ",
                                 " 23/04/1990 ", " us ")], today=TODAY)
        self.assertTrue(result.all_usable)
        self.assertEqual(result.contacts[0].as_output(), {
            "name": "Ann Lee", "email": "ann@example.com", "phone": "+14155552671",
            "phone_status": "verified", "birthday": "1990-04-23", "country": "US",
        })

    def test_empty_optional_fields_are_not_errors(self):
        result = clean_rows([row("Ann"), {"name": "Bob", "email": None}], today=TODAY)
        self.assertTrue(result.all_usable)
        self.assertEqual(result.contacts[0].as_output(), {
            "name": "Ann", "email": "", "phone": "", "phone_status": "",
            "birthday": "", "country": "",
        })
        self.assertEqual(len(result.contacts), 2)

    def test_unverified_phone(self):
        result = clean_rows([row("Ann", phone="03 1234 5678")], today=TODAY)
        self.assertTrue(result.all_usable)
        out = result.contacts[0].as_output()
        self.assertEqual((out["phone"], out["phone_status"]), ("0312345678", "unverified"))

    def test_invalid_fields_reported_and_dropped(self):
        result = clean_rows([row("Ann", "not-an-email", "12", "31/31/1990", "US")],
                            today=TODAY)
        self.assertFalse(result.all_usable)
        contact = result.contacts[0]
        self.assertEqual((contact.email, contact.phone, contact.birthday), ("", "", ""))
        self.assertEqual(contact.country, "US")
        self.assertEqual([(i["row"], i["field"]) for i in result.invalid_fields],
                         [(2, "email"), (2, "phone"), (2, "birthday")])
        for issue in result.invalid_fields:
            self.assertTrue(issue["reason"])

    def test_missing_name_rejected(self):
        result = clean_rows([row("Ann"), row("   ", "x@example.com")], today=TODAY)
        self.assertEqual(result.rejected, [{"row": 3, "reason": "missing name"}])
        self.assertEqual([c.name for c in result.contacts], ["Ann"])
        self.assertFalse(result.all_usable)

    def test_merge_by_email_keeps_most_complete(self):
        result = clean_rows([
            row("Ann", "ann@example.com"),
            row("Ann Lee", "ANN@example.com", "415 555 2671", "1990-04-23", "US"),
            row("Bob", "bob@example.com"),
        ], today=TODAY)
        self.assertEqual([c.name for c in result.contacts], ["Ann Lee", "Bob"])
        self.assertEqual(result.merged, [
            {"kept_row": 3, "merged_rows": [2], "reason": "same email"},
        ])
        self.assertTrue(result.all_usable)

    def test_merge_by_verified_phone_only(self):
        result = clean_rows([
            row("Ann", phone="(415) 555-2671", country="US"),
            row("Ann L", "ann@example.com", "+1 415 555 2671", "1990-04-23"),
            row("Kenji", phone="0312345678"),
            row("Kenji T", phone="0312345678"),  # unverified: no merge
        ], today=TODAY)
        self.assertEqual([c.name for c in result.contacts], ["Ann L", "Kenji", "Kenji T"])
        self.assertEqual(result.merged, [
            {"kept_row": 3, "merged_rows": [2], "reason": "same phone"},
        ])

    def test_merge_is_transitive_and_ties_keep_first(self):
        result = clean_rows([
            row("A", "a@example.com", "020 7946 0958", country="GB"),
            row("B", "b@example.com", "+442079460958"),
            row("C", "B@example.com", country="FR"),
        ], today=TODAY)
        self.assertEqual([c.name for c in result.contacts], ["A"])
        self.assertEqual(result.merged, [
            {"kept_row": 2, "merged_rows": [3, 4], "reason": "same email and phone"},
        ])

    def test_rejected_rows_do_not_merge(self):
        result = clean_rows([row("", "a@example.com"), row("Ann", "a@example.com")],
                            today=TODAY)
        self.assertEqual(result.merged, [])
        self.assertEqual(len(result.contacts), 1)


if __name__ == "__main__":
    unittest.main()
