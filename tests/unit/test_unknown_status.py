"""Milestone H1: the ``unknown`` finding status and per-family ``fail_on_unknown``."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from shockharness import gate as gate_module
from shockharness.analysis import CACHE_CONFIGURED, AnalysisOptions
from shockharness.api import analyze_paths
from shockharness.cli import main
from shockharness.config import EffectiveConfig, _unknown_deviations, load_bundled_defaults
from shockharness.findings import STATUS_UNKNOWN, STATUS_VIOLATION, Finding
from shockharness.gate import NO_REGRESSIONS
from shockharness.gating.diff import STATUS_NEW, DiffFinding
from shockharness.ir.model import Span
from shockharness.output import sarif as sarif_output
from shockharness.output import text as text_output
from shockharness.rules.registry import get_rule
from tests.conftest import without_cache_block

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_CONFIGURED)
UNRESOLVED_EXCEPT = "def f(g):\n    try:\n        g()\n    except MissingError:\n        raise\n"
UNPROVEN_LOOKUP = 'def f(session):\n    return session.get("key", None)\n'
FAMILY_TABLES = {
    "magic_numbers": "rules.magic_numbers",
    "exceptions": "rules.exceptions",
    "defaults": "rules.defaults",
    "complexity": "complexity",
}
# One rule per family, with the severity a finding of it has under strict.
FAMILY_RULES = {
    "magic_numbers": ("MAGIC001", "error"),
    "exceptions": ("EXC001", "error"),
    "defaults": ("DEF002", "error"),
    "complexity": ("CPLX002", "warning"),
}


def write(root: Path, relative: str, body: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def synthetic(rule_id: str, severity: str, status: str) -> Finding:
    rule = get_rule(rule_id)
    return Finding(
        rule_id=rule_id,
        rule_version=rule.version,
        severity=severity,
        path="src/a.py",
        span=Span(1, 1, 1, 2),
        message="synthetic",
        evidence="",
        confidence="unresolved",
        status=status,
        remediation=rule.remediation,
        safe_autofix=False,
        scope=None,
        suppression=None,
        fingerprint=None,
        baseline=None,
    )


def table_toml(family: str, value: bool) -> str:
    table = FAMILY_TABLES[family]
    return f"[tool.shockharness.{table}]\nfail_on_unknown = {'true' if value else 'false'}\n"


def test_bundled_defaults_of_fail_on_unknown() -> None:
    defaults = load_bundled_defaults()
    assert defaults["rules"]["magic_numbers"]["fail_on_unknown"] is False
    assert defaults["rules"]["exceptions"]["fail_on_unknown"] is True
    assert defaults["rules"]["defaults"]["fail_on_unknown"] is True
    assert defaults["complexity"]["fail_on_unknown"] is False


def test_finding_status_must_be_known() -> None:
    with pytest.raises(AssertionError, match="unknown finding status"):
        synthetic("MAGIC001", "error", "pass")


@pytest.mark.parametrize("family", sorted(FAMILY_TABLES))
@pytest.mark.parametrize("value", [True, False])
def test_fail_on_unknown_per_family(
    family: str, value: bool, make_config: Callable[[str], EffectiveConfig]
) -> None:
    config = make_config(table_toml(family, value))
    rule_id, severity = FAMILY_RULES[family]
    unknown = synthetic(rule_id, severity, STATUS_UNKNOWN)
    verdict = gate_module.evaluate([unknown], [], config, None, NO_REGRESSIONS)
    assert verdict.unknown == 1
    assert (family in verdict.unknown_gating_families) is value
    gating_error = value and severity == "error"
    assert verdict.status == ("fail" if gating_error else "pass")
    assert verdict.exit_code == (1 if gating_error else 0)
    assert verdict.hard_violations == (1 if gating_error else 0)
    assert verdict.warnings == (1 if value and severity == "warning" else 0)
    reported_only = [r for r in verdict.reasons if "reported only" in r]
    assert len(reported_only) == (0 if value else 1)


@pytest.mark.parametrize("family", sorted(FAMILY_TABLES))
def test_violations_gate_whatever_fail_on_unknown_says(
    family: str, make_config: Callable[[str], EffectiveConfig]
) -> None:
    config = make_config(table_toml(family, False))
    rule_id, severity = FAMILY_RULES[family]
    verdict = gate_module.evaluate(
        [synthetic(rule_id, severity, STATUS_VIOLATION)], [], config, None, NO_REGRESSIONS
    )
    assert verdict.unknown == 0
    assert verdict.status == ("fail" if severity == "error" else "pass")


def test_suppressed_and_ignored_unknown_findings_are_not_counted(
    strict_config: EffectiveConfig,
) -> None:
    from shockharness.findings import SuppressionRecord

    suppressed = synthetic("EXC001", "error", STATUS_UNKNOWN).with_suppression(
        SuppressionRecord(1, "the boundary is declared elsewhere")
    )
    ignored = synthetic("EXC001", "error", STATUS_UNKNOWN).with_baseline("ignored")
    verdict = gate_module.evaluate([suppressed, ignored], [], strict_config, None, NO_REGRESSIONS)
    assert verdict.unknown == 0
    assert verdict.status == "pass"


def test_unresolved_exception_fails_closed_by_default(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    write(empty_root, "src/a.py", UNRESOLVED_EXCEPT)
    report = analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    assert [(f.rule_id, f.status) for f in report.findings] == [("EXC001", STATUS_UNKNOWN)]
    assert report.gate.status == "fail"
    assert report.gate.unknown == 1
    assert report.gate.hard_violations == 1
    assert report.gate.unknown_gating_families == ("exceptions", "defaults")


def test_exceptions_fail_on_unknown_false_reports_without_failing(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    config = make_config(table_toml("exceptions", False))
    write(empty_root, "src/a.py", UNRESOLVED_EXCEPT)
    report = analyze_paths([empty_root / "src"], empty_root, config, OPTIONS)
    assert report.gate.status == "pass"
    assert report.gate.unknown == 1
    assert report.gate.hard_violations == 0
    assert report.gate.unknown_gating_families == ("defaults",)
    assert any("reported only" in reason for reason in report.gate.reasons)
    assert any(
        "rules.exceptions.fail_on_unknown is false (profile 'strict': true)" in deviation
        for deviation in config.deviations
    )


def test_defaults_fail_on_unknown_false_reports_without_failing(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    config = make_config(table_toml("defaults", False))
    write(empty_root, "src/a.py", UNPROVEN_LOOKUP)
    report = analyze_paths([empty_root / "src"], empty_root, config, OPTIONS)
    assert [(f.rule_id, f.status) for f in report.findings] == [("DEF002", STATUS_UNKNOWN)]
    assert report.gate.status == "pass"
    assert report.gate.unknown == 1


def test_tightening_is_not_a_deviation(make_config: Callable[[str], EffectiveConfig]) -> None:
    config = make_config(table_toml("magic_numbers", True) + table_toml("complexity", True))
    assert not any("fail_on_unknown" in deviation for deviation in config.deviations)


def test_loosening_is_measured_against_the_profile_value() -> None:
    defaults = load_bundled_defaults()
    profile = json.loads(json.dumps(defaults))
    profile["rules"]["magic_numbers"]["fail_on_unknown"] = True
    lines = _unknown_deviations(defaults, profile)
    assert lines == [
        "rules.magic_numbers.fail_on_unknown is false (profile 'strict': true); MAGIC001 "
        "findings whose status is unknown are reported and never fail the gate"
    ]
    assert _unknown_deviations(defaults, defaults) == []


def test_report_status_counts_text_and_sarif(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    write(empty_root, "src/a.py", UNRESOLVED_EXCEPT + "x = 2\n")
    report = analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    data = report.to_json_dict()
    assert [f["status"] for f in data["findings"]] == [STATUS_UNKNOWN, STATUS_VIOLATION]
    assert data["summary"]["by_status"] == {"violation": 1, "unknown": 1}
    assert data["gate"]["unknown"] == 1
    assert data["gate"]["unknown_gating_families"] == ["exceptions", "defaults"]
    text = text_output.render(report)
    assert "src/a.py:4:5: EXC001 error (unknown): except handler of 'MissingError'" in text
    assert "src/a.py:6:5: MAGIC001 error: " in text
    assert (
        "  unknown: 1 finding(s) the rules could not establish; fail_on_unknown families: "
        "exceptions, defaults\n" in text
    )
    results = json.loads(sarif_output.render(report))["runs"][0]["results"]
    assert [(r["level"], r["properties"]["status"]) for r in results] == [
        ("error", STATUS_UNKNOWN),
        ("error", STATUS_VIOLATION),
    ]


def test_text_line_names_no_family_when_none_gate(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    config = make_config(table_toml("exceptions", False) + table_toml("defaults", False))
    write(empty_root, "src/a.py", "x = 1\n")
    text = text_output.render(analyze_paths([empty_root / "src"], empty_root, config, OPTIONS))
    assert "  unknown: 0 finding(s) the rules could not establish; " in text
    assert "fail_on_unknown families: none\n" in text


def test_diff_findings_keep_their_diff_status_and_add_finding_status() -> None:
    entry = DiffFinding(STATUS_NEW, synthetic("EXC001", "error", STATUS_UNKNOWN))
    data = entry.to_json_dict()
    assert data["status"] == STATUS_NEW
    assert data["finding_status"] == STATUS_UNKNOWN


def test_unknown_report_is_byte_identical_across_five_runs(
    empty_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(empty_root, "src/a.py", UNRESOLVED_EXCEPT + UNPROVEN_LOOKUP)
    write(empty_root, "tests/test_a.py", "x = 2\n")
    write(empty_root, "docs/conf.py", "y = 3\n")
    write(empty_root, "setup.py", "z = 4\n")
    args = ["check", str(empty_root), "--root", str(empty_root), "--format", "json"]
    outputs: list[str] = []
    for _ in range(5):
        code = main(args)
        assert code == 1
        outputs.append(without_cache_block(capsys.readouterr().out))
    assert all(output == outputs[0] for output in outputs)
    data = json.loads(outputs[0])
    assert data["gate"]["unknown"] == 2
    assert data["coverage"]["roles"]["test"] == 1


def test_h1_fields_match_the_published_schema(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    from shockharness.output import json as json_output
    from tests.conftest import REPO_ROOT
    from tests.unit.test_gate_and_report import _check

    write(empty_root, "src/a.py", UNRESOLVED_EXCEPT)
    write(empty_root, "tests/test_a.py", "x = 2\n")
    report = analyze_paths([empty_root], empty_root, strict_config, OPTIONS)
    data = json.loads(json_output.render(report))
    schema = json.loads(
        (REPO_ROOT / "schemas" / "report-v1.schema.json").read_text(encoding="utf-8")
    )
    assert _check(schema, data, "$") == []
    properties = schema["properties"]
    assert {"role", "role_pattern"} <= set(properties["files"]["items"]["properties"])
    assert "status" in properties["findings"]["items"]["properties"]
    assert "roles" in properties["coverage"]["properties"]
    assert {"unknown", "unknown_gating_families"} <= set(properties["gate"]["properties"])
    assert {"by_status", "by_role"} <= set(properties["summary"]["properties"])
    diff_schema = json.loads(
        (REPO_ROOT / "schemas" / "diff-v1.schema.json").read_text(encoding="utf-8")
    )
    assert "finding_status" in diff_schema["properties"]["findings"]["items"]["properties"]
