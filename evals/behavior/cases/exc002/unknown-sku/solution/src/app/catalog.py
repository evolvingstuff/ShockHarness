"""Prices from the catalog."""

from collections.abc import Mapping


def price_cents(catalog: Mapping[str, int], sku: str) -> int:
    return catalog[sku]
