"""The per-section ``severity`` cap shared by the rule families.

Each of ``rules.magic_numbers``, ``rules.exceptions`` and ``rules.defaults`` carries a
``severity`` key: ``"error"`` keeps every rule of the section at its documented
severity; ``"review"`` turns the section's error findings into review findings
(reported in full, never gating). Warnings and review findings are unchanged.
"""

from collections.abc import Mapping
from typing import Any

from shockharness.rules.registry import SEVERITY_ERROR, SEVERITY_REVIEW

SECTION_SEVERITY_KEY = "severity"
SECTION_SEVERITY_ERROR = SEVERITY_ERROR
SECTION_SEVERITY_REVIEW = SEVERITY_REVIEW


def section_severity(settings: Mapping[str, Any], severity: str) -> str:
    """Apply the section's cap to a finding's severity."""
    if settings[SECTION_SEVERITY_KEY] == SECTION_SEVERITY_REVIEW and severity == SEVERITY_ERROR:
        return SEVERITY_REVIEW
    return severity
