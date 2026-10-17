"""The total of a cart."""

from collections.abc import Mapping

from app.catalog import price_cents


def total_cents(catalog: Mapping[str, int], skus: list[str]) -> int:
    total = 0
    for sku in skus:
        price = price_cents(catalog, sku)
        if price is not None:
            total += price
    return total
