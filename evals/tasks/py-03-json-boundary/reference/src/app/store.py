"""JSON store loading: decoding is the one boundary; every failure is a StoreError."""

import json


class StoreError(Exception):
    """The store text is not a JSON object of strings."""


def load_store(text: str) -> dict[str, str]:
    # Boundary (declared in .shockharness.toml): decoding external input.
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StoreError(f"malformed store: {exc}") from exc
    if not isinstance(data, dict):
        raise StoreError(f"store must be a JSON object, got {type(data).__name__}")
    for key, value in data.items():
        if not isinstance(value, str):
            raise StoreError(f"store value for {key!r} must be a string")
    return data
