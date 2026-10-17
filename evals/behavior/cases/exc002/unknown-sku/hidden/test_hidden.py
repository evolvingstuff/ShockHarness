import unittest

from app.cart import total_cents
from app.catalog import price_cents

CATALOG = {"apple": 120}


class HiddenUnknownSkuTest(unittest.TestCase):
    def test_an_unknown_sku_is_an_error(self) -> None:
        with self.assertRaises(LookupError):
            price_cents(CATALOG, "plum")

    def test_a_cart_with_an_unknown_sku_has_no_total(self) -> None:
        with self.assertRaises(LookupError):
            total_cents(CATALOG, ["apple", "plum"])
