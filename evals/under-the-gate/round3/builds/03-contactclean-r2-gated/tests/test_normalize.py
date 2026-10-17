import unittest

from contactclean.normalize import (
    PHONE_UNVERIFIED,
    PHONE_VERIFIED,
    load_phone_rules,
    normalize_birthday,
    normalize_email,
    normalize_phone,
)

RULES = load_phone_rules()


class EmailTests(unittest.TestCase):
    def test_trims_and_lowercases(self):
        result = normalize_email("  Ann.Lee@Example.COM ")
        self.assertEqual(result.value, "ann.lee@example.com")
        self.assertIsNone(result.problem)

    def test_empty_is_not_invalid(self):
        result = normalize_email("   ")
        self.assertEqual(result.value, "")
        self.assertIsNone(result.problem)

    def test_invalid(self):
        for raw in ("ann", "ann@", "ann@example", "a b@example.com", "a@@example.com"):
            with self.subTest(raw=raw):
                result = normalize_email(raw)
                self.assertEqual(result.value, "")
                self.assertIsNotNone(result.problem)


class PhoneTests(unittest.TestCase):
    def test_known_countries_to_e164(self):
        cases = [
            ("(415) 555-2671", "US", "+14155552671"),
            ("1-415-555-2671", "US", "+14155552671"),
            ("+1 415 555 2671", "US", "+14155552671"),
            ("020 7946 0958", "GB", "+442079460958"),
            ("+44 (0)20 7946 0958", "GB", "+442079460958"),
            ("0044 20 7946 0958", "GB", "+442079460958"),
            ("030 1234567", "DE", "+49301234567"),
            ("+49 30 1234567", "DE", "+49301234567"),
            ("01 23 45 67 89", "FR", "+33123456789"),
            ("+33 1 23 45 67 89", "FR", "+33123456789"),
        ]
        for raw, country, expected in cases:
            with self.subTest(raw=raw, country=country):
                result = normalize_phone(raw, country, RULES)
                self.assertEqual(result.value, expected)
                self.assertEqual(result.status, PHONE_VERIFIED)
                self.assertIsNone(result.problem)

    def test_unknown_country_keeps_digits_unverified(self):
        for country in ("", "JP"):
            with self.subTest(country=country):
                result = normalize_phone(" 03-1234-5678 ", country, RULES)
                self.assertEqual(result.value, "0312345678")
                self.assertEqual(result.status, PHONE_UNVERIFIED)
                self.assertIsNone(result.problem)

    def test_invalid_for_known_country(self):
        for raw, country in (("555-2671", "US"), ("+44 20 7946 0958", "FR"), ("12", "DE")):
            with self.subTest(raw=raw):
                result = normalize_phone(raw, country, RULES)
                self.assertEqual(result.value, "")
                self.assertIsNotNone(result.problem)

    def test_letters_are_invalid(self):
        result = normalize_phone("call me", "", RULES)
        self.assertIsNotNone(result.problem)

    def test_empty(self):
        result = normalize_phone("", "US", RULES)
        self.assertEqual((result.value, result.status, result.problem), ("", "", None))


class BirthdayTests(unittest.TestCase):
    def test_formats(self):
        cases = [
            ("1990-04-23", "1990-04-23"),
            ("23/04/1990", "1990-04-23"),
            ("04/23/1990", "1990-04-23"),
            ("5/5/1990", "1990-05-05"),
            (" 29/02/2000 ", "2000-02-29"),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                result = normalize_birthday(raw)
                self.assertEqual(result.value, expected)
                self.assertIsNone(result.problem)

    def test_ambiguous_is_invalid(self):
        result = normalize_birthday("03/04/1990")
        self.assertEqual(result.value, "")
        self.assertIn("ambiguous", result.problem)

    def test_invalid(self):
        for raw in ("1990-13-01", "1990-02-30", "29/02/1999", "31/31/1990", "April 1", "1990/04/23"):
            with self.subTest(raw=raw):
                result = normalize_birthday(raw)
                self.assertEqual(result.value, "")
                self.assertIsNotNone(result.problem)

    def test_empty(self):
        self.assertEqual(normalize_birthday("").value, "")
        self.assertIsNone(normalize_birthday("").problem)


if __name__ == "__main__":
    unittest.main()
