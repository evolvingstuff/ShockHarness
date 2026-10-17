"""The total of a cart."""

from collections.abc import Mapping

from app.catalog import price_cents


def total_cents(catalog: Mapping[str, int], skus: list[str]) -> int:
    return sum(price_cents(catalog, sku) for sku in skus)
