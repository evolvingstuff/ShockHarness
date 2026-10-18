"""The report score."""

from app.contracts import requires
from app.model import fit
from app.stats import normalize


def score(values: list[float]) -> float:
    requires(values, "numeric")
    return fit(normalize(values))
