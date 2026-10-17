import unittest
from datetime import date

from contactclean.normalize import (
    InvalidValue,
    normalize_birthday,
    normalize_email,
    normalize_phone,
)

TODAY = date(2026, 10, 17)


class EmailTests(unittest.TestCase):
    def test_lowercases(self):
        self.assertEqual(normalize_email("Ann.Lee@Example.COM"), "ann.lee@example.com")

    def test_invalid(self):
        for bad in ["ann", "ann@", "@example.com", "ann@example", "a b@x.com",
                    "ann@@x.com", "ann..lee@x.com", ".ann@x.com"]:
            with self.subTest(bad=bad), self.assertRaises(InvalidValue):
                normalize_email(bad)


class PhoneTests(unittest.TestCase):
    def check(self, raw, country, expected):
        phone = normalize_phone(raw, country)
        self.assertEqual(phone.value, expected)
        self.assertTrue(phone.verified)

    def test_us(self):
        self.check("(415) 555-2671", "US", "+14155552671")
        self.check("1-415-555-2671", "US", "+14155552671")
        self.check("+1 415 555 2671", "US", "+14155552671")

    def test_gb(self):
        self.check("020 7946 0958", "GB", "+442079460958")
        self.check("07911 123456", "GB", "+447911123456")
        self.check("+44 (0)20 7946 0958", "GB", "+442079460958")
        self.check("0044 20 7946 0958", "GB", "+442079460958")

    def test_de(self):
        self.check("030 123456", "DE", "+4930123456")
        self.check("+49 151 23456789", "DE", "+4915123456789")

    def test_fr(self):
        self.check("01 23 45 67 89", "FR", "+33123456789")
        self.check("06.12.34.56.78", "FR", "+33612345678")
        self.check("+33 6 12 34 56 78", "FR", "+33612345678")

    def test_invalid_for_country(self):
        for raw, country in [("555-1234", "US"), ("(015) 555-2671", "US"),
                             ("01 23 45 67", "FR"), ("12345", "GB"),
                             ("call me", "US"), ("415-555-267x", "US")]:
            with self.subTest(raw=raw), self.assertRaises(InvalidValue):
                normalize_phone(raw, country)

    def test_unknown_country_unverified(self):
        for country in ["", "JP"]:
            phone = normalize_phone("03-1234-5678", country)
            self.assertEqual(phone.value, "03-1234-5678")
            self.assertFalse(phone.verified)

    def test_unknown_country_still_needs_digits(self):
        with self.assertRaises(InvalidValue):
            normalize_phone("n/a", "")

    def test_foreign_calling_code_unverified(self):
        phone = normalize_phone("+81 3 1234 5678", "US")
        self.assertFalse(phone.verified)
        self.assertEqual(phone.value, "+81 3 1234 5678")


class BirthdayTests(unittest.TestCase):
    def test_iso(self):
        self.assertEqual(normalize_birthday("1990-02-28", TODAY), "1990-02-28")

    def test_unambiguous_slash_forms(self):
        self.assertEqual(normalize_birthday("25/12/1990", TODAY), "1990-12-25")
        self.assertEqual(normalize_birthday("12/25/1990", TODAY), "1990-12-25")
        self.assertEqual(normalize_birthday("07/07/1990", TODAY), "1990-07-07")

    def test_ambiguous(self):
        with self.assertRaisesRegex(InvalidValue, "ambiguous"):
            normalize_birthday("03/04/1990", TODAY)

    def test_invalid(self):
        for bad in ["1990-02-30", "31/31/1990", "1990/01/01", "Jan 1 1990",
                    "29/02/1991", "2030-01-01"]:
            with self.subTest(bad=bad), self.assertRaises(InvalidValue):
                normalize_birthday(bad, TODAY)


if __name__ == "__main__":
    unittest.main()
