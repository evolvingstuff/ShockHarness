"""Public library API.

Library consumers never need the CLI. All inputs are explicit (no defaults);
all failures are typed exceptions from :mod:`shockharness.errors` or explicit
statuses inside the returned structures.
"""

from collections.abc import Sequence
from pathlib import Path

from shockharness import gate as gate_module
from shockharness.analysis import AnalysisOptions, FileResult, analyze_file, analyze_text
from shockharness.config import EffectiveConfig, load_config
from shockharness.discovery import discover
from shockharness.errors import UnsupportedFeatureError, UsageError
from shockharness.gate import GateResult
from shockharness.report import Report, build_report
from shockharness.rules import registry

SOURCE_PSEUDO_PATH = "<source>"


def analyze_source(source: str, language: str, config: EffectiveConfig) -> FileResult:
    """Analyze one in-memory source text. ``language`` is ``python`` or ``javascript``."""
    if language not in registry.ALL_LANGUAGES:
        raise UsageError(
            f"unsupported language {language!r}; use one of {', '.join(registry.ALL_LANGUAGES)}",
            None,
        )
    return analyze_text(
        SOURCE_PSEUDO_PATH, language, source, config, AnalysisOptions(inline_suppressions=True)
    )


def analyze_paths(
    paths: Sequence[Path],
    root: Path,
    config: EffectiveConfig,
    options: AnalysisOptions,
) -> Report:
    """Discover files under ``paths`` (relative to ``root``), analyze them, evaluate the gate."""
    discovery = discover(root, list(paths), config)
    results = [analyze_file(file, config, options) for file in discovery.files]
    findings = [f for result in results for f in result.findings]
    verdict = gate_module.evaluate(findings, results, config)
    return build_report(results, discovery, config, verdict)


def evaluate_gate(report: Report, baseline: object | None, config: EffectiveConfig) -> GateResult:
    """Re-evaluate a report's gate under ``config``. Baselines arrive in Milestone F."""
    if baseline is not None:
        raise UnsupportedFeatureError(
            "baseline comparison is not implemented in this version", None
        )
    return gate_module.evaluate(list(report.findings), list(report.files), config)


__all__ = [
    "AnalysisOptions",
    "EffectiveConfig",
    "FileResult",
    "GateResult",
    "Report",
    "analyze_paths",
    "analyze_source",
    "evaluate_gate",
    "load_config",
]
