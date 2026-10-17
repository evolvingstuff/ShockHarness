import unittest

from contactclean.normalize import (
    PHONE_PLANS_FILE,
    FieldError,
    PhoneStatus,
    load_phone_plans,
    normalize_birthday,
    normalize_email,
    normalize_phone,
)

PLANS = load_phone_plans(PHONE_PLANS_FILE)


class EmailTest(unittest.TestCase):
    def test_trims_and_lowercases(self):
        self.assertEqual(normalize_email("  Ada@Example.COM "), "ada@example.com")

    def test_invalid(self):
        for value in ("ada", "ada@", "@example.com", "ada@example", "a b@example.com", "a@@b.com"):
            with self.subTest(value=value):
                self.assertIsInstance(normalize_email(value), FieldError)


class PhoneTest(unittest.TestCase):
    def assertPhone(self, value, country, expected, status=PhoneStatus.VERIFIED):
        result = normalize_phone(value, country, PLANS)
        self.assertNotIsInstance(result, FieldError, result)
        self.assertEqual(result.number, expected)
        self.assertEqual(result.status, status)

    def test_us(self):
        self.assertPhone("(415) 555-2671", "US", "+14155552671")
        self.assertPhone("1-415-555-2671", "US", "+14155552671")
        self.assertPhone("+1 415 555 2671", "US", "+14155552671")

    def test_gb(self):
        self.assertPhone("020 7946 0958", "GB", "+442079460958")
        self.assertPhone("+44 7911 123456", "GB", "+447911123456")

    def test_de(self):
        self.assertPhone("030 123456", "DE", "+4930123456")
        self.assertPhone("+49 151 23456789", "DE", "+4915123456789")

    def test_fr(self):
        self.assertPhone("01 23 45 67 89", "FR", "+33123456789")
        self.assertPhone("+33 6 12 34 56 78", "FR", "+33612345678")

    def test_unknown_country_keeps_digits_unverified(self):
        self.assertPhone("03-1234-5678", "JP", "0312345678", PhoneStatus.UNVERIFIED)
        self.assertPhone("+81 3 1234 5678", "", "+81312345678", PhoneStatus.UNVERIFIED)

    def test_invalid(self):
        cases = [
            ("555-CALL", "US"),
            ("12345", "US"),
            ("+44 20 7946 0958", "US"),
            ("01 23 45 67", "FR"),
            ("--", "JP"),
        ]
        for value, country in cases:
            with self.subTest(value=value, country=country):
                self.assertIsInstance(normalize_phone(value, country, PLANS), FieldError)


class BirthdayTest(unittest.TestCase):
    def test_iso(self):
        self.assertEqual(normalize_birthday("1990-07-04"), "1990-07-04")

    def test_day_first_unambiguous(self):
        self.assertEqual(normalize_birthday("25/12/1985"), "1985-12-25")

    def test_month_first_unambiguous(self):
        self.assertEqual(normalize_birthday("12/25/1985"), "1985-12-25")

    def test_same_day_and_month_is_unambiguous(self):
        self.assertEqual(normalize_birthday("05/05/2000"), "2000-05-05")

    def test_ambiguous(self):
        result = normalize_birthday("03/04/1990")
        self.assertIsInstance(result, FieldError)
        self.assertIn("ambiguous", result.reason)

    def test_invalid(self):
        for value in ("1990-02-30", "31/31/1990", "July 4 1990", "1990/07/04", "2023-13-01", "29/02/2023"):
            with self.subTest(value=value):
                self.assertIsInstance(normalize_birthday(value), FieldError)

    def test_leap_day(self):
        self.assertEqual(normalize_birthday("29/02/2024"), "2024-02-29")


if __name__ == "__main__":
    unittest.main()
