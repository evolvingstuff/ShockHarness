"""Discounted prices."""

from fractions import Fraction

from app.constants import DISCOUNT_CAP


def discounted_cents(price_cents: int, coupon: Fraction) -> int:
    rate = min(coupon, DISCOUNT_CAP)
    return price_cents - int(price_cents * rate)
