"""JSON rendering of reports. Keys are sorted; the result is byte-stable."""

import json

from shockharness.constants import JSON_INDENT
from shockharness.gating.diff import DiffReport
from shockharness.report import Report


def render(report: Report) -> str:
    return json.dumps(report.to_json_dict(), indent=JSON_INDENT, sort_keys=True) + "\n"


def render_diff(diff: DiffReport) -> str:
    return json.dumps(diff.to_json_dict(), indent=JSON_INDENT, sort_keys=True) + "\n"
