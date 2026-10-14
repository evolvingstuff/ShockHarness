"""Settings are explicit: each one is required and validated when loaded."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    request_timeout_seconds: float
    page_size: int


def load_settings(raw: Mapping[str, str]) -> Settings:
    """Build ``Settings`` from a mapping such as ``os.environ``; a missing key raises."""
    timeout = float(raw["REQUEST_TIMEOUT_SECONDS"])
    page_size = int(raw["PAGE_SIZE"])
    if timeout <= 0:
        raise ValueError(f"REQUEST_TIMEOUT_SECONDS must be positive, got {timeout}")
    if page_size < 1:
        raise ValueError(f"PAGE_SIZE must be at least 1, got {page_size}")
    return Settings(request_timeout_seconds=timeout, page_size=page_size)
