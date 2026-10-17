"""Configuration, read once from the environment mapping at start-up."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    api_url: str


def load_config(env: Mapping[str, str]) -> Config:
    url = env["API_URL"]
    if not url.startswith("https://"):
        raise ValueError(f"API_URL must be an https URL, got {url!r}")
    return Config(api_url=url)
