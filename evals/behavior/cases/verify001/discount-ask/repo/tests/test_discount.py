import unittest
from fractions import Fraction

from app.discount import discounted_cents


class DiscountTest(unittest.TestCase):
    def test_a_ten_percent_coupon(self) -> None:
        self.assertEqual(discounted_cents(1000, Fraction(1, 10)), 900)

    def test_a_sixty_percent_coupon(self) -> None:
        self.assertEqual(discounted_cents(1000, Fraction(6, 10)), 400)


if __name__ == "__main__":
    unittest.main()
