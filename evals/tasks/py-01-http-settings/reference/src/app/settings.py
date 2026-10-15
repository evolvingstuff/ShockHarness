"""HTTP settings: every value is required and validated once, at load time."""

from collections.abc import Mapping
from dataclasses import dataclass

MIN_PORT = 1
# The TCP port range is defined by RFC 793 section 3.1 (16-bit port numbers).
MAX_PORT = 65535  # shockharness: ignore[MAGIC001] reason="RFC 793 section 3.1: 16-bit port field"


@dataclass(frozen=True)
class Settings:
    request_timeout_seconds: float
    port: int


def load_settings(raw: Mapping[str, str]) -> Settings:
    """Build ``Settings`` from a mapping such as ``os.environ``; a missing key raises."""
    timeout = float(raw["REQUEST_TIMEOUT_SECONDS"])
    port = int(raw["PORT"])
    if timeout <= 0:
        raise ValueError(f"REQUEST_TIMEOUT_SECONDS must be positive, got {timeout}")
    if port < MIN_PORT or port > MAX_PORT:
        raise ValueError(f"PORT must be between {MIN_PORT} and {MAX_PORT}, got {port}")
    return Settings(request_timeout_seconds=timeout, port=port)


def connect(host: str, settings: Settings) -> str:
    return f"{host}:{settings.port}"
