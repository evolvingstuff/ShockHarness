"""Normalizing a series."""

from statistics import fmean, pstdev

from app.contracts import preserves, produces, requires


def normalize(values: list[float]) -> list[float]:
    requires(values, "numeric")
    mean = fmean(values)
    spread = pstdev(values)
    return produces(preserves([(v - mean) / spread for v in values], values), "normalized")
