"""The value that marks an unusable field."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Rejected:
    """An optional field holds a value that cannot be normalized, for the given reason."""

    reason: str
