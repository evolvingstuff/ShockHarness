import unittest

from app.tokens import is_expired


class TokenTest(unittest.TestCase):
    def test_a_token_from_the_past_is_expired(self) -> None:
        self.assertTrue(is_expired(1_000_000_000.0))

    def test_a_fresh_token_is_not_expired(self) -> None:
        # Written when this token had a year left.
        self.assertFalse(is_expired(1_700_000_000.0))


if __name__ == "__main__":
    unittest.main()
