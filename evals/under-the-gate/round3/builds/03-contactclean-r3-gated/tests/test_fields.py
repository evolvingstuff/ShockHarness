import unittest

from contactclean.birthday import normalize_birthday
from contactclean.emails import normalize_email
from contactclean.phone import load_phone_plans, normalize_phone
from contactclean.results import Invalid, Phone, Valid


class EmailTest(unittest.TestCase):
    def test_trims_and_lowercases(self):
        self.assertEqual(normalize_email("  Ada@Example.COM "), Valid("ada@example.com"))

    def test_empty_stays_empty(self):
        self.assertEqual(normalize_email("   "), Valid(""))

    def test_invalid(self):
        for raw in ("ada", "ada@", "@example.com", "ada@example", "a b@example.com", "a@@b.com"):
            with self.subTest(raw=raw):
                self.assertIsInstance(normalize_email(raw), Invalid)


class BirthdayTest(unittest.TestCase):
    def test_iso(self):
        self.assertEqual(normalize_birthday(" 1990-04-23 "), Valid("1990-04-23"))

    def test_day_first(self):
        self.assertEqual(normalize_birthday("23/04/1990"), Valid("1990-04-23"))

    def test_month_first(self):
        self.assertEqual(normalize_birthday("04/23/1990"), Valid("1990-04-23"))

    def test_same_day_and_month_is_unambiguous(self):
        self.assertEqual(normalize_birthday("05/05/1990"), Valid("1990-05-05"))

    def test_ambiguous(self):
        result = normalize_birthday("03/04/1990")
        self.assertIsInstance(result, Invalid)
        self.assertIn("ambiguous", result.reason)

    def test_invalid_dates(self):
        for raw in ("1990-02-30", "1990-13-01", "31/02/1990", "13/13/1990", "yesterday", "1990/04/23", "0000-01-01"):
            with self.subTest(raw=raw):
                self.assertIsInstance(normalize_birthday(raw), Invalid)

    def test_leap_day(self):
        self.assertEqual(normalize_birthday("29/02/2000"), Valid("2000-02-29"))
        self.assertIsInstance(normalize_birthday("2001-02-29"), Invalid)

    def test_empty(self):
        self.assertEqual(normalize_birthday(""), Valid(""))


class PhoneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plans = load_phone_plans()

    def phone(self, raw, country):
        return normalize_phone(raw, country, self.plans)

    def test_known_countries(self):
        cases = [
            ("(212) 555-1234", "US", "+12125551234"),
            ("1-212-555-1234", "US", "+12125551234"),
            ("020 7946 0958", "GB", "+442079460958"),
            ("030 1234567", "DE", "+49301234567"),
            ("01 23 45 67 89", "FR", "+33123456789"),
            ("+33 1 23 45 67 89", "US", "+33123456789"),
            ("0044 20 7946 0958", "FR", "+442079460958"),
        ]
        for raw, country, expected in cases:
            with self.subTest(raw=raw, country=country):
                self.assertEqual(self.phone(raw, country), Phone(expected, verified=True))

    def test_unknown_country_keeps_digits_unverified(self):
        self.assertEqual(self.phone("03-1234-5678", "JP"), Phone("0312345678", verified=False))
        self.assertEqual(self.phone("555 0100", ""), Phone("5550100", verified=False))
        self.assertEqual(self.phone("+81 3 1234 5678", ""), Phone("+81312345678", verified=False))

    def test_invalid(self):
        cases = [("555-CALL", "US"), ("12345", "US"), ("0123", "FR"), ("+1 123", ""), ("--", "US"), ("1" * 16, "")]
        for raw, country in cases:
            with self.subTest(raw=raw):
                self.assertIsInstance(self.phone(raw, country), Invalid)

    def test_empty(self):
        self.assertEqual(self.phone("  ", "US"), Phone("", verified=False))


if __name__ == "__main__":
    unittest.main()
