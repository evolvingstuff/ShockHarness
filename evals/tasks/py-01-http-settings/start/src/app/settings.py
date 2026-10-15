"""HTTP settings (starting point: implicit defaults everywhere)."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    request_timeout_seconds: float = 30.0
    port: int = 5432


def load_settings(raw) -> Settings:
    timeout = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))
    port = int(raw.get("PORT", 5432))
    return Settings(request_timeout_seconds=timeout, port=port)


def connect(host: str, port: int = 5432) -> str:
    return f"{host}:{port}"
