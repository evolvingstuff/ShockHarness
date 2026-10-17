"""Prices from the catalog."""

from collections.abc import Mapping


def price_cents(catalog: Mapping[str, int], sku: str) -> int | None:
    try:
        return catalog[sku]
    except KeyError:
        return None
