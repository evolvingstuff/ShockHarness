import unittest
from datetime import date

from contactclean.model import Invalid, Phone, PhoneStatus
from contactclean.normalize import (
    normalize_birthday,
    normalize_country,
    normalize_email,
    normalize_phone,
)
from contactclean.plans import load_phone_rules

TODAY = date.fromisoformat("2026-10-17")


class EmailTest(unittest.TestCase):
    def test_trims_and_lowercases(self):
        self.assertEqual(normalize_email("  Ann.Lee@Example.COM "), "ann.lee@example.com")

    def test_empty_stays_empty(self):
        self.assertEqual(normalize_email("   "), "")

    def test_invalid(self):
        for value in ("ann", "ann@example", "@example.com", "a b@example.com", "a@@b.com", "a..b@c.com", "a.@c.com"):
            with self.subTest(value=value):
                self.assertIsInstance(normalize_email(value), Invalid)


class CountryTest(unittest.TestCase):
    def test_uppercases(self):
        self.assertEqual(normalize_country(" de "), "DE")

    def test_empty_stays_empty(self):
        self.assertEqual(normalize_country(""), "")

    def test_not_alpha_2(self):
        self.assertIsInstance(normalize_country("Germany"), Invalid)


class PhoneTest(unittest.TestCase):
    def setUp(self):
        self.rules = load_phone_rules()

    def verified(self, value, country):
        return normalize_phone(value, country, self.rules)

    def test_supported_countries_to_e164(self):
        cases = [
            ("(555) 123-4567", "US", "+15551234567"),
            ("1-555-123-4567", "US", "+15551234567"),
            ("+1 555 123 4567", "US", "+15551234567"),
            ("020 7946 0958", "GB", "+442079460958"),
            ("+44 (0)20 7946 0958", "GB", "+442079460958"),
            ("030 123456", "DE", "+4930123456"),
            ("+49 30 1234567", "DE", "+49301234567"),
            ("06 12 34 56 78", "FR", "+33612345678"),
            ("+33 6.12.34.56.78", "FR", "+33612345678"),
        ]
        for value, country, expected in cases:
            with self.subTest(value=value, country=country):
                self.assertEqual(self.verified(value, country), Phone(expected, PhoneStatus.VERIFIED))

    def test_unknown_country_keeps_digits_unverified(self):
        self.assertEqual(self.verified(" 030 123-456 ", ""), Phone("030123456", PhoneStatus.UNVERIFIED))
        self.assertEqual(self.verified("+81 3 1234 5678", "JP"), Phone("+81312345678", PhoneStatus.UNVERIFIED))

    def test_empty_stays_empty(self):
        self.assertEqual(self.verified("  ", "US"), Phone("", PhoneStatus.EMPTY))

    def test_invalid(self):
        cases = [
            ("call me", "US"),
            ("555-1234", "US"),
            ("+44 20 7946 0958", "US"),
            ("06 12 34 56", "FR"),
            ("()", ""),
            ("1234567890123456", ""),
        ]
        for value, country in cases:
            with self.subTest(value=value, country=country):
                self.assertIsInstance(self.verified(value, country), Invalid)


class BirthdayTest(unittest.TestCase):
    def test_formats(self):
        cases = [
            ("1990-04-12", "1990-04-12"),
            ("31/12/1985", "1985-12-31"),
            ("12/31/1985", "1985-12-31"),
            ("5/5/2001", "2001-05-05"),
            ("29/02/2000", "2000-02-29"),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(normalize_birthday(value, TODAY), expected)

    def test_empty_stays_empty(self):
        self.assertEqual(normalize_birthday(" ", TODAY), "")

    def test_ambiguous_is_invalid(self):
        result = normalize_birthday("04/05/1990", TODAY)
        self.assertIsInstance(result, Invalid)
        self.assertIn("ambiguous", result.reason)

    def test_invalid(self):
        for value in ("1990-13-01", "1990-02-30", "29/02/2001", "13/13/2000", "April 1st", "1990/04/12", "2030-01-01"):
            with self.subTest(value=value):
                self.assertIsInstance(normalize_birthday(value, TODAY), Invalid)


if __name__ == "__main__":
    unittest.main()
