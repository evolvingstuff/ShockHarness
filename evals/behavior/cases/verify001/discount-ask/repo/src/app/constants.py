"""Every numeric constant of the package, each with what it means."""

from fractions import Fraction

# SPEC.md: a discount never exceeds half the price.
DISCOUNT_CAP = Fraction(1, 2)
