"""Settings, read once at start-up from the environment mapping it is given."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    api_url: str
    retries: int


def load_settings(env: Mapping[str, str]) -> Settings:
    retries = int(env["RETRIES"])
    if retries < 0:
        raise ValueError(f"RETRIES must not be negative, got {retries}")
    return Settings(api_url=env["API_URL"], retries=retries)
