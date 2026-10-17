import datetime as dt
import unittest

from contactclean.core import (
    InvalidValue, clean, normalize_birthday, normalize_email, normalize_phone,
)

TODAY = dt.date(2026, 10, 17)


class EmailTests(unittest.TestCase):
    def test_trims_and_lowercases(self):
        self.assertEqual(normalize_email("  Ann.Lee@Example.COM "), "ann.lee@example.com")

    def test_empty_stays_empty(self):
        self.assertEqual(normalize_email("   "), "")

    def test_invalid(self):
        for bad in ("ann", "ann@", "@example.com", "ann@example", "a b@example.com", "a@@b.com"):
            with self.subTest(bad=bad), self.assertRaises(InvalidValue):
                normalize_email(bad)


class PhoneTests(unittest.TestCase):
    def test_e164_per_country(self):
        cases = [
            ("(415) 555-2671", "US", "+14155552671"),
            ("1-415-555-2671", "US", "+14155552671"),
            ("+1 415 555 2671", "US", "+14155552671"),
            ("020 7946 0958", "GB", "+442079460958"),
            ("+44 20 7946 0958", "GB", "+442079460958"),
            ("07700 900123", "GB", "+447700900123"),
            ("030 123456", "DE", "+4930123456"),
            ("0049 30 1234567", "DE", "+49301234567"),
            ("01 23 45 67 89", "FR", "+33123456789"),
            ("+33 6 12 34 56 78", "FR", "+33612345678"),
        ]
        for raw, country, expected in cases:
            with self.subTest(raw=raw, country=country):
                self.assertEqual(normalize_phone(raw, country), (expected, "verified"))

    def test_unknown_country_keeps_digits_unverified(self):
        self.assertEqual(normalize_phone("03-1234-5678", "JP"), ("0312345678", "unverified"))
        self.assertEqual(normalize_phone("+81 3 1234 5678", ""), ("+81312345678", "unverified"))

    def test_empty_stays_empty(self):
        self.assertEqual(normalize_phone("  ", "US"), ("", ""))

    def test_invalid(self):
        cases = [
            ("call me", "US"),
            ("555-1234", "US"),            # too short
            ("+44 20 7946 0958", "US"),    # wrong calling code
            ("0123 4567 890", "FR"),       # too long
            ("12", ""),                    # implausible even without a country
        ]
        for raw, country in cases:
            with self.subTest(raw=raw, country=country), self.assertRaises(InvalidValue):
                normalize_phone(raw, country)


class BirthdayTests(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(normalize_birthday("1990-07-04", TODAY), "1990-07-04")
        self.assertEqual(normalize_birthday("25/12/1985", TODAY), "1985-12-25")  # DD/MM
        self.assertEqual(normalize_birthday("12/25/1985", TODAY), "1985-12-25")  # MM/DD
        self.assertEqual(normalize_birthday("07/07/2000", TODAY), "2000-07-07")  # same either way

    def test_empty_stays_empty(self):
        self.assertEqual(normalize_birthday("", TODAY), "")

    def test_ambiguous_is_rejected(self):
        with self.assertRaisesRegex(InvalidValue, "ambiguous"):
            normalize_birthday("03/04/1990", TODAY)

    def test_invalid(self):
        for bad in ("1990-02-30", "31/31/1990", "July 4 1990", "1990/07/04", "2030-01-01"):
            with self.subTest(bad=bad), self.assertRaises(InvalidValue):
                normalize_birthday(bad, TODAY)


def rec(**kw):
    base = {"name": "", "email": "", "phone": "", "birthday": "", "country": ""}
    base.update(kw)
    return base


class CleanTests(unittest.TestCase):
    def test_all_good_rows_are_clean(self):
        result = clean([rec(name=" Ann ", email="A@X.COM", country="us")], TODAY)
        self.assertTrue(result.clean)
        self.assertEqual(result.contacts[0].as_row(), {
            "name": "Ann", "email": "a@x.com", "phone": "", "phone_status": "",
            "birthday": "", "country": "US",
        })

    def test_missing_name_rejected(self):
        result = clean([rec(name="Ann"), rec(name="  ", email="b@x.com")], TODAY)
        self.assertEqual(result.rejected, [{"row": 3, "reason": "missing name"}])
        self.assertEqual(len(result.contacts), 1)
        self.assertFalse(result.clean)

    def test_invalid_field_reported_and_dropped(self):
        result = clean([rec(name="Ann", email="nope", phone="(415) 555-2671",
                            birthday="03/04/1990", country="US")], TODAY)
        self.assertEqual([(i["row"], i["field"]) for i in result.invalid_fields],
                         [(2, "email"), (2, "birthday")])
        c = result.contacts[0]
        self.assertEqual((c.email, c.birthday, c.phone), ("", "", "+14155552671"))
        self.assertFalse(result.clean)

    def test_empty_optional_fields_not_reported(self):
        result = clean([rec(name="Ann")], TODAY)
        self.assertEqual(result.invalid_fields, [])
        self.assertTrue(result.clean)

    def test_merge_by_email_keeps_most_complete(self):
        result = clean([
            rec(name="Ann", email="ann@x.com"),
            rec(name="Ann Lee", email="ANN@x.com", phone="4155552671", country="US"),
        ], TODAY)
        self.assertEqual(len(result.contacts), 1)
        self.assertEqual(result.contacts[0].name, "Ann Lee")
        self.assertEqual(result.merged, [{"kept_row": 3, "merged_rows": [2]}])
        self.assertTrue(result.clean)  # merging is not a problem

    def test_merge_by_verified_phone_transitively(self):
        result = clean([
            rec(name="A", email="a@x.com", phone="415 555 2671", country="US"),
            rec(name="B", phone="+1 (415) 555-2671", country="US"),
            rec(name="C", email="a@x.com"),
        ], TODAY)
        self.assertEqual(len(result.contacts), 1)
        self.assertEqual(result.merged, [{"kept_row": 2, "merged_rows": [3, 4]}])

    def test_unverified_phones_do_not_merge(self):
        result = clean([rec(name="A", phone="12345678"), rec(name="B", phone="12345678")], TODAY)
        self.assertEqual(len(result.contacts), 2)
        self.assertEqual(result.merged, [])


if __name__ == "__main__":
    unittest.main()
