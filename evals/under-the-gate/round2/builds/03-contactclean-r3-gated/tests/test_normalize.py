import unittest

from contactclean.normalize import (
    load_phone_rules,
    normalize_birthday,
    normalize_email,
    normalize_phone,
)

RULES = load_phone_rules()


class EmailTest(unittest.TestCase):
    def test_trims_and_lowercases(self) -> None:
        self.assertEqual(normalize_email("  Ann.Lee@Example.COM ").value, "ann.lee@example.com")

    def test_rejects_invalid(self) -> None:
        for raw in ("ann", "ann@", "@example.com", "ann@example", "a b@example.com", "a@@example.com"):
            with self.subTest(raw=raw):
                self.assertIsNotNone(normalize_email(raw).invalid_reason)


class BirthdayTest(unittest.TestCase):
    def test_accepted_formats(self) -> None:
        cases = {
            "1990-04-23": "1990-04-23",
            "23/04/1990": "1990-04-23",
            "04/23/1990": "1990-04-23",
            "05/05/1990": "1990-05-05",
            " 13/2/2000 ": "2000-02-13",
            "2000-02-29": "2000-02-29",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                result = normalize_birthday(raw)
                self.assertIsNone(result.invalid_reason)
                self.assertEqual(result.value, expected)

    def test_ambiguous_is_invalid(self) -> None:
        result = normalize_birthday("04/05/1990")
        self.assertIn("ambiguous", result.invalid_reason)
        self.assertEqual(result.value, "")

    def test_invalid_dates(self) -> None:
        for raw in ("1990-13-01", "1990-02-30", "1999-02-29", "31/31/1990", "yesterday", "1990/04/23", "0000-01-01"):
            with self.subTest(raw=raw):
                self.assertIsNotNone(normalize_birthday(raw).invalid_reason)


class PhoneTest(unittest.TestCase):
    def test_e164_for_supported_countries(self) -> None:
        cases = [
            ("(415) 555-2671", "US", "+14155552671"),
            ("1-415-555-2671", "US", "+14155552671"),
            ("+1 415 555 2671", "US", "+14155552671"),
            ("020 7946 0958", "GB", "+442079460958"),
            ("+44 (0)20 7946 0958", "GB", "+442079460958"),
            ("0044 20 7946 0958", "GB", "+442079460958"),
            ("030 1234567", "DE", "+49301234567"),
            ("+49 151 23456789", "DE", "+4915123456789"),
            ("01 23 45 67 89", "FR", "+33123456789"),
            ("+33 6 12 34 56 78", "FR", "+33612345678"),
        ]
        for raw, country, expected in cases:
            with self.subTest(raw=raw, country=country):
                phone = normalize_phone(raw, country, RULES)
                self.assertIsNone(phone.invalid_reason)
                self.assertTrue(phone.verified)
                self.assertEqual(phone.value, expected)

    def test_unknown_country_keeps_digits_unverified(self) -> None:
        for country in ("", "JP"):
            with self.subTest(country=country):
                phone = normalize_phone("03-1234-5678", country, RULES)
                self.assertIsNone(phone.invalid_reason)
                self.assertFalse(phone.verified)
                self.assertEqual(phone.value, "0312345678")

    def test_invalid_phones(self) -> None:
        cases = [
            ("555-CALL-NOW", "US"),
            ("12345", "US"),
            ("+44 20 7946 0958", "US"),
            ("---", ""),
            ("0123456789", "US"),
        ]
        for raw, country in cases:
            with self.subTest(raw=raw, country=country):
                phone = normalize_phone(raw, country, RULES)
                self.assertIsNotNone(phone.invalid_reason)
                self.assertEqual(phone.value, "")


if __name__ == "__main__":
    unittest.main()
