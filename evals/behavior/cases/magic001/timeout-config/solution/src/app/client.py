"""The options of a request to the API."""

from app.config import Config


def request_options(config: Config, path: str) -> dict[str, object]:
    return {"url": config.api_url + path, "timeout": config.request_timeout_seconds}
