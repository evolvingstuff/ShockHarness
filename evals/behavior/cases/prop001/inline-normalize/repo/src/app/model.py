"""The model: it is only valid on normalized input."""

from app.contracts import requires


def fit(values: list[float]) -> float:
    requires(values, "normalized")
    return max(values) - min(values)
