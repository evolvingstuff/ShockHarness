import unittest

from app.money import split_cents


class SplitTest(unittest.TestCase):
    def test_even_split(self) -> None:
        self.assertEqual(split_cents(90, 3), [30, 30, 30])

    def test_the_remainder_is_not_lost(self) -> None:
        self.assertEqual(split_cents(100, 3), [34, 33, 33])


if __name__ == "__main__":
    unittest.main()
