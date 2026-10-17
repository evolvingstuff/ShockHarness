import datetime as dt
import unittest

from contactclean.normalize import (
    InvalidValue,
    normalize_birthday,
    normalize_email,
    normalize_phone,
)

TODAY = dt.date(2026, 10, 17)


class EmailTests(unittest.TestCase):
    def test_trims_and_lowercases(self):
        self.assertEqual(normalize_email("  Alice@Example.COM "), "alice@example.com")

    def test_empty_stays_empty(self):
        self.assertEqual(normalize_email("   "), "")

    def test_invalid(self):
        for bad in ["alice", "alice@", "@example.com", "a b@example.com", "a@example", "a..b@x.com", "a@@x.com"]:
            with self.subTest(bad=bad), self.assertRaises(InvalidValue):
                normalize_email(bad)


class PhoneTests(unittest.TestCase):
    def check(self, raw, country, value, status="verified"):
        phone = normalize_phone(raw, country)
        self.assertEqual((phone.value, phone.status), (value, status))

    def test_us(self):
        self.check("(415) 555-2671", "US", "+14155552671")
        self.check("1-415-555-2671", "US", "+14155552671")
        self.check("+1 415 555 2671", "US", "+14155552671")

    def test_gb(self):
        self.check("020 7946 0958", "GB", "+442079460958")
        self.check("07700 900123", "GB", "+447700900123")
        self.check("+44 (0)20 7946 0958".replace("(0)", ""), "GB", "+442079460958")

    def test_de(self):
        self.check("030 123456", "DE", "+4930123456")
        self.check("0151 23456789", "DE", "+4915123456789")

    def test_fr(self):
        self.check("06 12 34 56 78", "FR", "+33612345678")
        self.check("0033 6 12 34 56 78", "FR", "+33612345678")

    def test_plus_number_from_another_supported_country(self):
        self.check("+33 6 12 34 56 78", "US", "+33612345678")

    def test_unknown_country_is_unverified_and_keeps_digits(self):
        self.check("03-1234-5678", "JP", "0312345678", "unverified")
        self.check("555 1234", "", "5551234", "unverified")
        self.check("+81 3 1234 5678", "", "+81312345678", "unverified")

    def test_empty_is_none(self):
        self.assertIsNone(normalize_phone("  ", "US"))

    def test_invalid(self):
        cases = [
            ("call me", "US"),
            ("555-1234", "US"),        # too short
            ("(115) 555-2671", "US"),  # area code cannot start with 1
            ("06 12 34", "FR"),
            ("12", ""),
            ("1234567890123456", ""),
            ("+1 555", "US"),
        ]
        for raw, country in cases:
            with self.subTest(raw=raw, country=country), self.assertRaises(InvalidValue):
                normalize_phone(raw, country)


class BirthdayTests(unittest.TestCase):
    def check(self, raw, expected):
        self.assertEqual(normalize_birthday(raw, TODAY), expected)

    def test_iso(self):
        self.check(" 1990-03-15 ", "1990-03-15")

    def test_dd_mm_when_day_over_12(self):
        self.check("25/12/1985", "1985-12-25")

    def test_mm_dd_when_day_over_12(self):
        self.check("12/25/1985", "1985-12-25")

    def test_same_day_and_month_is_unambiguous(self):
        self.check("07/07/2001", "2001-07-07")

    def test_empty(self):
        self.check("", "")

    def test_ambiguous_is_invalid(self):
        with self.assertRaisesRegex(InvalidValue, "ambiguous"):
            normalize_birthday("03/04/1990", TODAY)

    def test_invalid(self):
        for bad in ["1990-02-30", "31/31/1990", "yesterday", "1990/03/15", "15.03.1990", "2027-01-01", "29/02/2001"]:
            with self.subTest(bad=bad), self.assertRaises(InvalidValue):
                normalize_birthday(bad, TODAY)


if __name__ == "__main__":
    unittest.main()
