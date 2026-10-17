import unittest

from app.tokens import is_expired

NOW = 1_800_000_000.0


class TokenTest(unittest.TestCase):
    def test_a_token_from_the_past_is_expired(self) -> None:
        self.assertTrue(is_expired(1_000_000_000.0, NOW))

    def test_a_fresh_token_is_not_expired(self) -> None:
        self.assertFalse(is_expired(NOW + 3600, NOW))


if __name__ == "__main__":
    unittest.main()
