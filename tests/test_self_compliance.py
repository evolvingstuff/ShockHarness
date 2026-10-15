"""ShockHarness must pass its own gate with the repository configuration."""

from shockharness.analysis import CACHE_CONFIGURED, AnalysisOptions
from shockharness.api import analyze_paths
from shockharness.config import load_config
from tests.conftest import REPO_ROOT


def test_tool_source_passes_its_own_gate() -> None:
    config = load_config(REPO_ROOT, None)
    assert config.source.tier == "dedicated"
    report = analyze_paths(
        [REPO_ROOT / "src", REPO_ROOT / "tests"],
        REPO_ROOT,
        config,
        AnalysisOptions(True, CACHE_CONFIGURED),
    )
    offenders = [
        (f.path, f.span.line, f.message)
        for f in report.findings
        if not f.is_suppressed and f.severity == "error"
    ]
    assert offenders == []
    assert report.gate.status == "pass", report.gate.reasons
    # Complexity findings on the tool are advisory warnings (recorded in STATUS.md); the
    # gate never fails on them and none of them is suppressed to hide it.
    advisory = [f for f in report.findings if f.rule_id.startswith("CPLX")]
    assert all(f.severity == "warning" and not f.is_suppressed for f in advisory)
    assert report.metrics["complexity"]["status"] == "available"
    assert report.metrics["graph"]["summary"]["cycles"] == 0, report.metrics["graph"]["cycles"]
    assert report.analysis_status == "complete"
    exempt = [f for f in report.files if f.path == "src/shockharness/constants.py"]
    assert len(exempt) == 1
    assert [d.rule_id for d in exempt[0].rules_disabled] == ["MAGIC001"]
