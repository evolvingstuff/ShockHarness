"""ShockHarness must pass its own gate with the repository configuration."""

from shockharness.analysis import AnalysisOptions
from shockharness.api import analyze_paths
from shockharness.config import load_config
from tests.conftest import REPO_ROOT


def test_tool_source_passes_its_own_gate() -> None:
    config = load_config(REPO_ROOT, None)
    assert config.source.tier == "dedicated"
    report = analyze_paths(
        [REPO_ROOT / "src", REPO_ROOT / "tests"], REPO_ROOT, config, AnalysisOptions(True)
    )
    offenders = [(f.path, f.span.line, f.message) for f in report.findings if not f.is_suppressed]
    assert offenders == []
    assert report.gate.status == "pass", report.gate.reasons
    assert report.analysis_status == "complete"
    exempt = [f for f in report.files if f.path == "src/shockharness/constants.py"]
    assert len(exempt) == 1
    assert [d.rule_id for d in exempt[0].rules_disabled] == ["MAGIC001"]
