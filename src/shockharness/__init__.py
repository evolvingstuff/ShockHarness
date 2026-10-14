"""ShockHarness: a strict static-analysis quality gate for Python and JavaScript.

Three default-on policy families: exception transparency, no implicit defaults,
and no magic numbers (only 0 and 1 are permitted numeric literals). Findings are
deterministic, explained, and never averaged into a single score.

Public library API lives in :mod:`shockharness.api`.
"""

from shockharness.api import analyze_paths, analyze_source, evaluate_gate
from shockharness.version import __version__

__all__ = ["__version__", "analyze_paths", "analyze_source", "evaluate_gate"]
