"""JSON rendering of a report. Keys are sorted; the result is byte-stable."""

import json

from shockharness.constants import JSON_INDENT
from shockharness.report import Report


def render(report: Report) -> str:
    return json.dumps(report.to_json_dict(), indent=JSON_INDENT, sort_keys=True) + "\n"
