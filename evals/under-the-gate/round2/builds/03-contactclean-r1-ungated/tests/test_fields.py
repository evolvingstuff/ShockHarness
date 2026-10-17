import datetime as dt
import unittest

from contactclean.fields import (
    InvalidField,
    normalize_birthday,
    normalize_email,
    normalize_phone,
)

TODAY = dt.date(2026, 10, 17)


class EmailTests(unittest.TestCase):
    def test_trims_and_lowercases(self):
        self.assertEqual(normalize_email("  Alice.Smith@Example.COM "), "alice.smith@example.com")

    def test_empty_stays_empty(self):
        self.assertEqual(normalize_email("   "), "")

    def test_invalid(self):
        for bad in ["alice", "a@@b.com", "a@b", "@b.com", "a b@c.com", "a@-b.com", "a..b@c.com", "a@b.c0m"]:
            with self.subTest(bad=bad), self.assertRaises(InvalidField):
                normalize_email(bad)


class PhoneTests(unittest.TestCase):
    def test_us(self):
        for raw in ["(415) 555-2671", "415.555.2671", "1-415-555-2671", "+1 415 555 2671", "001 415 555 2671"]:
            with self.subTest(raw=raw):
                self.assertEqual(normalize_phone(raw, "US"), ("+14155552671", "verified"))

    def test_gb(self):
        self.assertEqual(normalize_phone("020 7946 0018", "GB"), ("+442079460018", "verified"))
        self.assertEqual(normalize_phone("07700 900123", "GB"), ("+447700900123", "verified"))

    def test_de(self):
        self.assertEqual(normalize_phone("030 1234567", "DE"), ("+49301234567", "verified"))
        self.assertEqual(normalize_phone("+49 151 23456789", ""), ("+4915123456789", "verified"))

    def test_fr(self):
        self.assertEqual(normalize_phone("06 12 34 56 78", "FR"), ("+33612345678", "verified"))
        self.assertEqual(normalize_phone("+33 (0)6 12 34 56 78", "FR"), ("+33612345678", "verified"))

    def test_international_number_overrides_country(self):
        self.assertEqual(normalize_phone("+44 20 7946 0018", "US"), ("+442079460018", "verified"))

    def test_unknown_country_keeps_digits_unverified(self):
        self.assertEqual(normalize_phone(" 03-1234-5678 ", "JP"), ("0312345678", "unverified"))
        self.assertEqual(normalize_phone("555 1234", ""), ("5551234", "unverified"))
        self.assertEqual(normalize_phone("+81 3 1234 5678", ""), ("+81312345678", "unverified"))

    def test_empty_stays_empty(self):
        self.assertEqual(normalize_phone("  ", "US"), ("", ""))

    def test_invalid(self):
        cases = [
            ("call me", "US"), ("555-CALL", ""), ("12", ""), ("123 4567", "US"),
            ("(415) 155-2671", "US"), ("06 12 34 56", "FR"), ("+33 6 12", ""),
            ("415+555", "US"), ("1234567890123456", ""),
        ]
        for raw, country in cases:
            with self.subTest(raw=raw, country=country), self.assertRaises(InvalidField):
                normalize_phone(raw, country)


class BirthdayTests(unittest.TestCase):
    def test_iso(self):
        self.assertEqual(normalize_birthday(" 1990-04-23 ", TODAY), "1990-04-23")

    def test_day_first(self):
        self.assertEqual(normalize_birthday("23/04/1990", TODAY), "1990-04-23")

    def test_month_first(self):
        self.assertEqual(normalize_birthday("04/23/1990", TODAY), "1990-04-23")
        self.assertEqual(normalize_birthday("4/23/1990", TODAY), "1990-04-23")

    def test_same_day_and_month_is_unambiguous(self):
        self.assertEqual(normalize_birthday("05/05/1990", TODAY), "1990-05-05")

    def test_ambiguous(self):
        with self.assertRaisesRegex(InvalidField, "ambiguous"):
            normalize_birthday("03/04/1990", TODAY)

    def test_empty_stays_empty(self):
        self.assertEqual(normalize_birthday("", TODAY), "")

    def test_invalid(self):
        for bad in ["1990-02-30", "31/02/1990", "13/13/1990", "April 1 1990", "1990/04/23",
                    "90-04-23", "2030-01-01", "29/02/1991"]:
            with self.subTest(bad=bad), self.assertRaises(InvalidField):
                normalize_birthday(bad, TODAY)

    def test_leap_day(self):
        self.assertEqual(normalize_birthday("29/02/2000", TODAY), "2000-02-29")


if __name__ == "__main__":
    unittest.main()
