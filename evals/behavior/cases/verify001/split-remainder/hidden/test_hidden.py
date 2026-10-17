import unittest

from app.money import split_cents


class HiddenSplitTest(unittest.TestCase):
    def test_parts_always_add_up(self) -> None:
        for total in range(0, 40):
            for parts in range(1, 7):
                shares = split_cents(total, parts)
                self.assertEqual(sum(shares), total, (total, parts))
                self.assertLessEqual(max(shares) - min(shares), 1, (total, parts))

    def test_larger_shares_come_first(self) -> None:
        self.assertEqual(split_cents(10, 4), [3, 3, 2, 2])
