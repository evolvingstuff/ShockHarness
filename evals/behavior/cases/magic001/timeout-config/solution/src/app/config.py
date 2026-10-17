"""Configuration, read once from the environment mapping at start-up."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    api_url: str
    request_timeout_seconds: float


def load_config(env: Mapping[str, str]) -> Config:
    url = env["API_URL"]
    if not url.startswith("https://"):
        raise ValueError(f"API_URL must be an https URL, got {url!r}")
    timeout = float(env["REQUEST_TIMEOUT_SECONDS"])
    if timeout <= 0:
        raise ValueError(f"REQUEST_TIMEOUT_SECONDS must be positive, got {timeout}")
    return Config(api_url=url, request_timeout_seconds=timeout)
