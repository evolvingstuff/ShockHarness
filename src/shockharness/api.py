"""Public library API.

Library consumers never need the CLI. All inputs are explicit (no defaults);
all failures are typed exceptions from :mod:`shockharness.errors` or explicit
statuses inside the returned structures.
"""

import time
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from shockharness import gate as gate_module
from shockharness.analysis import (
    CACHE_BYPASSED,
    AnalysisOptions,
    FileResult,
    analyze_files,
    analyze_text,
    with_unsupported_sources,
)
from shockharness.cache.store import (
    REASON_DISABLED,
    REASON_NO_CACHE_FLAG,
    STATUS_BYPASSED,
    STATUS_DISABLED,
    FileCache,
    cache_coverage_without_cache,
    cache_settings,
    open_cache,
)
from shockharness.config import EffectiveConfig, load_config
from shockharness.discovery import discover
from shockharness.errors import UsageError
from shockharness.gate import NO_REGRESSIONS, GateResult
from shockharness.gating.baseline import Baseline
from shockharness.gating.baseline import apply_baseline as apply_baseline_fingerprints
from shockharness.history.hotspots import collect_history
from shockharness.report import Report, build_report, rebuild_with_findings
from shockharness.roles import FILE_ROLES_KEY, role_classifier
from shockharness.rules import registry
from shockharness.rules.policy_integrity import fingerprinted, policy_attempt_findings
from shockharness.rules.registry import VERIFICATION_SECTION

SOURCE_PSEUDO_PATH = "<source>"


def analyze_source(source: str, language: str, config: EffectiveConfig) -> FileResult:
    """Analyze one in-memory source text. ``language`` is ``python`` or ``javascript``."""
    if language not in registry.ALL_LANGUAGES:
        raise UsageError(
            f"unsupported language {language!r}; use one of {', '.join(registry.ALL_LANGUAGES)}",
            None,
        )
    return analyze_text(
        SOURCE_PSEUDO_PATH,
        language,
        source,
        config,
        AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED),
    )


def analyze_paths(
    paths: Sequence[Path],
    root: Path,
    config: EffectiveConfig,
    options: AnalysisOptions,
) -> Report:
    """Discover files under ``paths`` (relative to ``root``), analyze them, evaluate the gate.

    Pure analysis: no git is run. ``metrics.complexity`` and ``metrics.graph`` are
    complete; ``metrics.history`` says ``not_collected`` until :func:`with_history`
    is applied. Complexity never affects the gate here.
    """
    started = time.perf_counter()
    discovery = discover(root, list(paths), config)
    cache, cache_coverage = _open_cache(root, config, options)
    outcome = analyze_files(discovery.files, config, options, cache)
    if cache is not None:
        cache_coverage = cache.coverage()
    files = with_unsupported_sources(outcome.files, discovery, config)
    # VERIFY003 for repository keys that tried to loosen the --policy file (H2 part 2):
    # the only verification finding a run without a base revision can produce.
    attempts = fingerprinted(
        policy_attempt_findings(config, root, config.section(VERIFICATION_SECTION))
    )
    classifier = role_classifier(config.values[FILE_ROLES_KEY])
    attempt_roles = {f.path: classifier.classify(f.path).role for f in attempts}
    findings = [*(f for result in files for f in result.findings), *attempts]
    verdict = gate_module.evaluate(findings, files, config, None, NO_REGRESSIONS)
    elapsed = time.perf_counter() - started
    return build_report(
        files,
        discovery,
        config,
        verdict,
        outcome.metrics,
        elapsed,
        cache_coverage,
        attempts,
        attempt_roles,
    )


def _open_cache(
    root: Path, config: EffectiveConfig, options: AnalysisOptions
) -> tuple[FileCache | None, dict[str, Any]]:
    """The cache for this run (``None`` when disabled or bypassed) and the
    ``coverage.cache`` block that applies when no cache is open."""
    settings = cache_settings(config)
    directory = str(settings["directory"])
    if options.cache == CACHE_BYPASSED:
        return None, cache_coverage_without_cache(STATUS_BYPASSED, directory, REASON_NO_CACHE_FLAG)
    if settings["enabled"] is False:
        return None, cache_coverage_without_cache(STATUS_DISABLED, directory, REASON_DISABLED)
    return open_cache(root, config), {}


def apply_baseline(report: Report, baseline: Baseline, config: EffectiveConfig) -> Report:
    """Mark the report's findings against ``baseline`` and re-evaluate the gate.

    ``gates.legacy`` decides what a match means: ``baseline`` (counted, never fails),
    ``ignore`` (not counted), ``fail`` (the baseline is recorded but not applied).
    """
    marked, application = apply_baseline_fingerprints(
        report.findings, baseline, config.values["gates"]["legacy"], config.digest
    )
    verdict = gate_module.evaluate(marked, report.files, config, application, NO_REGRESSIONS)
    return rebuild_with_findings(report, marked, verdict)


def evaluate_gate(report: Report, baseline: Baseline | None, config: EffectiveConfig) -> GateResult:
    """Re-evaluate a report's gate under ``config``, optionally against ``baseline``."""
    if baseline is None:
        return gate_module.evaluate(
            list(report.findings), list(report.files), config, None, NO_REGRESSIONS
        )
    if not isinstance(baseline, Baseline):
        raise UsageError(
            "baseline must be a shockharness.gating.baseline.Baseline, "
            f"got {type(baseline).__name__}",
            None,
        )
    return apply_baseline(report, baseline, config).gate


def with_history(report: Report, root: Path, revision: str, config: EffectiveConfig) -> Report:
    """Attach ``metrics.history`` read from local git for the report's files at ``revision``.

    Degrades explicitly: without git, outside a repository, or with
    ``history.enabled = false`` the metrics say so and why. Hotspots are computed from
    the churn and ``metrics.complexity``. Never affects the gate.
    """
    history = collect_history(
        root, revision, [f.path for f in report.files], config, report.metrics["complexity"]
    )
    metrics = dict(report.metrics)
    metrics["history"] = history
    return replace(report, metrics=metrics)


__all__ = [
    "AnalysisOptions",
    "Baseline",
    "EffectiveConfig",
    "FileResult",
    "GateResult",
    "Report",
    "analyze_paths",
    "analyze_source",
    "apply_baseline",
    "evaluate_gate",
    "load_config",
    "with_history",
]
