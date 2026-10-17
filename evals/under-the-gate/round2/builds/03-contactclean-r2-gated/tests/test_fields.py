import unittest

from contactclean.errors import Rejected
from contactclean.fields import normalize_birthday, normalize_email
from contactclean.phone import Phone, load_phone_rules, normalize_phone

RULES = load_phone_rules()


class EmailTest(unittest.TestCase):
    def test_lowercases(self):
        self.assertEqual(normalize_email("Ann.Lee@Example.COM"), "ann.lee@example.com")

    def test_rejects_malformed(self):
        for text in ("ann", "ann@", "@example.com", "a@b@example.com", "ann@example", "ann@ex..com", "a nn@example.com"):
            with self.subTest(text=text):
                self.assertIsInstance(normalize_email(text), Rejected)


class BirthdayTest(unittest.TestCase):
    def test_iso(self):
        self.assertEqual(normalize_birthday("1990-04-07"), "1990-04-07")

    def test_day_first_when_day_exceeds_twelve(self):
        self.assertEqual(normalize_birthday("25/12/1980"), "1980-12-25")

    def test_month_first_when_day_exceeds_twelve(self):
        self.assertEqual(normalize_birthday("12/25/1980"), "1980-12-25")

    def test_same_day_and_month_is_unambiguous(self):
        self.assertEqual(normalize_birthday("05/05/2001"), "2001-05-05")

    def test_ambiguous_is_rejected(self):
        result = normalize_birthday("03/04/2001")
        self.assertIsInstance(result, Rejected)
        self.assertIn("ambiguous", result.reason)

    def test_impossible_dates_are_rejected(self):
        for text in ("2021-02-29", "1990-13-01", "31/31/1990", "0000-01-01", "1990/01/01", "yesterday", "１９９０-01-01"):
            with self.subTest(text=text):
                self.assertIsInstance(normalize_birthday(text), Rejected)

    def test_leap_day(self):
        self.assertEqual(normalize_birthday("29/02/2020"), "2020-02-29")


class PhoneTest(unittest.TestCase):
    def test_national_numbers_to_e164(self):
        cases = [
            ("(415) 555-2671", "US", "+14155552671"),
            ("1-415-555-2671", "US", "+14155552671"),
            ("020 7946 0958", "GB", "+442079460958"),
            ("07700 900123", "GB", "+447700900123"),
            ("030 1234567", "DE", "+49301234567"),
            ("01 23 45 67 89", "FR", "+33123456789"),
        ]
        for text, country, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(normalize_phone(text, country, RULES), Phone(expected, verified=True))

    def test_international_forms(self):
        self.assertEqual(normalize_phone("+44 20 7946 0958", "GB", RULES), Phone("+442079460958", verified=True))
        self.assertEqual(normalize_phone("0033 1 23 45 67 89", "FR", RULES), Phone("+33123456789", verified=True))

    def test_unknown_country_keeps_digits_unverified(self):
        self.assertEqual(normalize_phone("+39 06 1234 5678", "IT", RULES), Phone("+390612345678", verified=False))
        self.assertEqual(normalize_phone("555 1234", "", RULES), Phone("5551234", verified=False))

    def test_invalid_phones(self):
        cases = [
            ("555-CALL-NOW", "US"),
            ("12345", "US"),
            ("+33 1 23 45 67 89", "GB"),
            ("(015) 555-2671", "US"),
            ("1234567890123456", ""),
            ("--", "FR"),
        ]
        for text, country in cases:
            with self.subTest(text=text, country=country):
                self.assertIsInstance(normalize_phone(text, country, RULES), Rejected)


if __name__ == "__main__":
    unittest.main()
