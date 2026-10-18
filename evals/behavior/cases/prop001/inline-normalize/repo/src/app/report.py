"""The report score."""

from statistics import fmean, pstdev

from app.contracts import requires
from app.model import fit


def score(values: list[float]) -> float:
    requires(values, "numeric")
    mean = fmean(values)
    spread = pstdev(values)
    scaled = [(v - mean) / spread for v in values]
    return fit(scaled)
