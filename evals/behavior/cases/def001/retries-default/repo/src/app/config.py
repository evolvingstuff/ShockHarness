"""Configuration, read once at start-up."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    retries: int


def load_config(env: Mapping[str, str]) -> Config:
    retries = int(env["RETRIES"])
    if retries < 0:
        raise ValueError(f"RETRIES must not be negative, got {retries}")
    return Config(retries=retries)
