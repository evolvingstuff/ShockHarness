"""The weekly report, written as JSON for the dashboard."""

import json
from pathlib import Path

# The dashboard's fixtures and diffs expect two-space JSON.
REPORT_INDENT_SPACES = 2


def render(report: dict[str, object]) -> str:
    return json.dumps(report, indent=REPORT_INDENT_SPACES, sort_keys=True) + "\n"


def write_report(path: Path, report: dict[str, object]) -> None:
    path.write_text(render(report), encoding="utf-8")
