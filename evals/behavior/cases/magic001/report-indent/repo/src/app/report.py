"""The weekly report, written as JSON for the dashboard."""

import json
from pathlib import Path


def render(report: dict[str, object]) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def write_report(path: Path, report: dict[str, object]) -> None:
    path.write_text(render(report), encoding="utf-8")
