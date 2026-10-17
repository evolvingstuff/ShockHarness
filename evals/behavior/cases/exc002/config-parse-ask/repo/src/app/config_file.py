"""The configuration file."""

import json
from pathlib import Path


def load_config(path: Path) -> dict[str, object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
