import unittest
from datetime import date

from contactclean.normalize import (
    InvalidValue,
    Phone,
    normalize_birthday,
    normalize_email,
    normalize_phone,
)

TODAY = date(2026, 10, 17)


class EmailTests(unittest.TestCase):
    def test_lowercases(self):
        self.assertEqual(normalize_email("Ann.Lee@Example.COM"), "ann.lee@example.com")

    def test_invalid(self):
        for bad in ("ann", "ann@", "@example.com", "ann@example", "a b@example.com",
                    "ann@@example.com", "ann..lee@example.com"):
            with self.subTest(bad=bad), self.assertRaises(InvalidValue):
                normalize_email(bad)


class PhoneTests(unittest.TestCase):
    def test_known_countries_to_e164(self):
        cases = [
            ("(415) 555-2671", "US", "+14155552671"),
            ("1-415-555-2671", "US", "+14155552671"),
            ("020 7946 0958", "GB", "+442079460958"),
            ("07700 900123", "GB", "+447700900123"),
            ("030 1234567", "DE", "+49301234567"),
            ("0151 23456789", "DE", "+4915123456789"),
            ("01 23 45 67 89", "FR", "+33123456789"),
            ("06.12.34.56.78", "FR", "+33612345678"),
        ]
        for raw, country, expected in cases:
            with self.subTest(raw=raw, country=country):
                self.assertEqual(normalize_phone(raw, country), Phone(expected, True))

    def test_international_input(self):
        self.assertEqual(normalize_phone("+44 20 7946 0958", "GB"),
                         Phone("+442079460958", True))
        self.assertEqual(normalize_phone("0033 6 12 34 56 78", "FR"),
                         Phone("+33612345678", True))
        # Number from another supported country than the contact's.
        self.assertEqual(normalize_phone("+1 415 555 2671", "FR"),
                         Phone("+14155552671", True))

    def test_unknown_country_kept_unverified(self):
        self.assertEqual(normalize_phone("03-1234-5678", ""), Phone("0312345678", False))
        self.assertEqual(normalize_phone("03 1234 5678", "JP"), Phone("0312345678", False))
        self.assertEqual(normalize_phone("+81 3 1234 5678", ""), Phone("+81312345678", False))

    def test_invalid(self):
        cases = [
            ("555-CALL-NOW", "US"),
            ("12345", "US"),
            ("415 555 267", "US"),     # too short
            ("011 555 2671", "US"),    # area code can't start with 0/1
            ("01 23 45 67", "FR"),     # too short for FR
            ("+44 20 7946", "GB"),
            ("123", ""),
            ("not a number", ""),
        ]
        for raw, country in cases:
            with self.subTest(raw=raw, country=country), self.assertRaises(InvalidValue):
                normalize_phone(raw, country)


class BirthdayTests(unittest.TestCase):
    def test_formats(self):
        cases = [
            ("1990-04-23", "1990-04-23"),
            ("1990-4-3", "1990-04-03"),
            ("23/04/1990", "1990-04-23"),   # DD/MM
            ("04/23/1990", "1990-04-23"),   # MM/DD
            ("05/05/1990", "1990-05-05"),   # same either way
            ("29/02/2000", "2000-02-29"),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(normalize_birthday(raw, TODAY), expected)

    def test_ambiguous_rejected(self):
        with self.assertRaisesRegex(InvalidValue, "ambiguous"):
            normalize_birthday("03/04/1990", TODAY)

    def test_invalid(self):
        for bad in ("1990-02-30", "31/31/1990", "29/02/1999", "April 3 1990",
                    "1990/04/23", "23.04.1990", "2030-01-01"):
            with self.subTest(bad=bad), self.assertRaises(InvalidValue):
                normalize_birthday(bad, TODAY)


if __name__ == "__main__":
    unittest.main()
