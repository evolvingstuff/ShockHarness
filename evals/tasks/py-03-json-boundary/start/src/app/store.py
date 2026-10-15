"""JSON store loading (starting point: every failure becomes a value)."""

import json


class StoreError(Exception):
    pass


def load_store(text: str) -> dict | None:
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            return {}
        for key, value in data.items():
            if not isinstance(value, str):
                raise StoreError(f"{key} is not a string")
        return data
    except json.JSONDecodeError:
        return {}
    except Exception:
        return None
