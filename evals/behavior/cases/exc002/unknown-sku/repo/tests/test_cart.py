import unittest

from app.cart import total_cents

CATALOG = {"apple": 120, "pear": 95}


class CartTest(unittest.TestCase):
    def test_total_of_known_items(self) -> None:
        self.assertEqual(total_cents(CATALOG, ["apple", "pear", "apple"]), 335)


if __name__ == "__main__":
    unittest.main()
