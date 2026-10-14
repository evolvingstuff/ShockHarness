"""Fingerprint stability and baseline create / match / stale behaviour."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from shockharness.analysis import AnalysisOptions
from shockharness.api import analyze_paths, analyze_source, apply_baseline, evaluate_gate
from shockharness.config import EffectiveConfig
from shockharness.errors import UsageError
from shockharness.gating.baseline import (
    Baseline,
    build_baseline,
    load_baseline,
    normalize_evidence,
    parse_baseline,
    render_baseline,
)
from tests.conftest import REPO_ROOT

OPTIONS = AnalysisOptions(inline_suppressions=True)


def write(root: Path, relative: str, body: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def fingerprints(source: str, config: EffectiveConfig) -> list[str]:
    result = analyze_source(source, "python", config)
    return [f.fingerprint for f in result.findings if f.fingerprint is not None]


def test_every_finding_gets_a_fingerprint(strict_config: EffectiveConfig) -> None:
    result = analyze_source(
        'x = 2  # shockharness: ignore[MAGIC001] reason="r"\ny = 3\n', "python", strict_config
    )
    assert all(f.fingerprint is not None for f in result.findings)
    assert all(f.baseline is None for f in result.findings)
    assert len({f.fingerprint for f in result.findings}) == len(result.findings)


def test_fingerprint_survives_line_moves_and_whitespace(strict_config: EffectiveConfig) -> None:
    original = fingerprints("def f():\n    return 3\n", strict_config)
    moved = fingerprints("\n\n# comment\nimport os\n\ndef f():\n    return 3\n", strict_config)
    reformatted = fingerprints("def f():\n        return   3\n", strict_config)
    assert original == moved == reformatted
    assert len(original) == 1


def test_fingerprint_changes_with_rule_scope_or_construct(strict_config: EffectiveConfig) -> None:
    base = fingerprints("def f():\n    return 3\n", strict_config)
    other_scope = fingerprints("def g():\n    return 3\n", strict_config)
    other_value = fingerprints("def f():\n    return 4\n", strict_config)
    assert base != other_scope
    assert base != other_value


def test_identical_lines_get_occurrence_indexes(strict_config: EffectiveConfig) -> None:
    two = fingerprints("x = 2\nx = 2\n", strict_config)
    three = fingerprints("x = 2\nx = 2\nx = 2\n", strict_config)
    assert len(set(two)) == 2
    assert three[:2] == two  # existing occurrences keep their fingerprints
    assert three[2] not in two


def test_scope_less_findings_are_distinct_from_module_scope(strict_config: EffectiveConfig) -> None:
    result = analyze_source(
        'x = 1  # shockharness: ignore[MAGIC001] reason="r"\n', "python", strict_config
    )
    assert [f.rule_id for f in result.findings] == ["SUPP002"]
    assert result.findings[0].scope is None
    assert result.findings[0].fingerprint is not None


def test_normalize_evidence_removes_all_whitespace() -> None:
    assert normalize_evidence("  x  =\t 2 ") == "x=2"


def test_baseline_round_trip_is_byte_identical(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    write(empty_root, "src/a.py", 'x = 2\ny = 3  # shockharness: ignore[MAGIC001] reason="r"\n')
    report = analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    baseline = build_baseline(report.findings, report.tool_version, strict_config.digest)
    assert [e.rule_id for e in baseline.entries] == ["MAGIC001"]  # suppressed findings excluded
    text = render_baseline(baseline)
    again = render_baseline(
        build_baseline(report.findings, report.tool_version, strict_config.digest)
    )
    assert text == again
    path = empty_root / "baseline.json"
    path.write_text(text, encoding="utf-8")
    loaded = load_baseline(path)
    assert loaded.fingerprints == baseline.fingerprints
    assert loaded.config_digest == strict_config.digest
    assert render_baseline(loaded) == text


def test_baseline_matches_published_schema(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    from tests.unit.test_gate_and_report import _check

    write(empty_root, "src/a.py", "x = 2\n")
    report = analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    data = json.loads(render_baseline(build_baseline(report.findings, "0", strict_config.digest)))
    schema = json.loads(
        (REPO_ROOT / "schemas" / "baseline-v1.schema.json").read_text(encoding="utf-8")
    )
    assert _check(schema, data, "$") == []


def _apply(
    root: Path, config: EffectiveConfig, baseline: Baseline
) -> tuple[list[tuple[str, int, str | None]], dict]:
    report = analyze_paths([root / "src"], root, config, OPTIONS)
    applied = apply_baseline(report, baseline, config)
    rows = [(f.path, f.span.line, f.baseline) for f in applied.findings]
    return rows, applied.gate.to_json_dict()


def test_legacy_baseline_mode_marks_and_counts_but_does_not_fail(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    write(empty_root, "src/a.py", "x = 2\n")
    report = analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    baseline = build_baseline(report.findings, report.tool_version, strict_config.digest)
    write(empty_root, "src/a.py", "import os\n\nx = 2\n")  # moved line, still legacy
    rows, gate = _apply(empty_root, strict_config, baseline)
    assert rows == [("src/a.py", 3, "matched")]
    assert gate["status"] == "pass"
    assert gate["hard_violations"] == 1
    assert gate["new_hard_violations"] == 0
    assert gate["baselined"] == 1
    assert gate["baseline"]["applied"] is True
    assert gate["baseline"]["matched"] == 1
    assert gate["baseline"]["stale"] == []
    assert gate["baseline"]["config_digest_matches"] is True
    assert any("do not fail the gate" in r for r in gate["reasons"])

    write(empty_root, "src/a.py", "import os\n\nx = 2\ny = 4\n")  # a new violation
    rows, gate = _apply(empty_root, strict_config, baseline)
    assert rows == [("src/a.py", 3, "matched"), ("src/a.py", 4, None)]
    assert gate["status"] == "fail"
    assert gate["new_hard_violations"] == 1


def test_legacy_fail_mode_ignores_the_baseline(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    config = make_config('[tool.shockharness.gates]\nlegacy = "fail"\n')
    write(empty_root, "src/a.py", "x = 2\n")
    report = analyze_paths([empty_root / "src"], empty_root, config, OPTIONS)
    baseline = build_baseline(report.findings, report.tool_version, config.digest)
    rows, gate = _apply(empty_root, config, baseline)
    assert rows == [("src/a.py", 1, None)]
    assert gate["status"] == "fail"
    assert gate["baselined"] == 0
    assert gate["baseline"]["applied"] is False
    assert any('gates.legacy = "fail"' in r for r in gate["reasons"])


def test_legacy_ignore_mode_drops_matches_from_the_counts(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    config = make_config('[tool.shockharness.gates]\nlegacy = "ignore"\n')
    write(empty_root, "src/a.py", "x = 2\n")
    report = analyze_paths([empty_root / "src"], empty_root, config, OPTIONS)
    baseline = build_baseline(report.findings, report.tool_version, config.digest)
    rows, gate = _apply(empty_root, config, baseline)
    assert rows == [("src/a.py", 1, "ignored")]  # still listed
    assert gate["status"] == "pass"
    assert gate["hard_violations"] == 0
    assert gate["baselined"] == 1
    assert any("were not counted" in r for r in gate["reasons"])


def test_stale_entries_are_reported_and_never_fail(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    write(empty_root, "src/a.py", "x = 2\ny = 3\n")
    report = analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    baseline = build_baseline(report.findings, report.tool_version, strict_config.digest)
    write(empty_root, "src/a.py", "x = 2\n")  # the y = 3 entry is now stale
    rows, gate = _apply(empty_root, strict_config, baseline)
    assert rows == [("src/a.py", 1, "matched")]
    assert gate["status"] == "pass"
    assert [e["evidence"] for e in gate["baseline"]["stale"]] == ["y = 3"]
    assert any("stale" in r for r in gate["reasons"])


def test_changed_config_digest_is_noted(empty_root: Path, strict_config: EffectiveConfig) -> None:
    write(empty_root, "src/a.py", "x = 2\n")
    report = analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    baseline = build_baseline(report.findings, report.tool_version, "0000")
    _rows, gate = _apply(empty_root, strict_config, baseline)
    assert gate["baseline"]["config_digest_matches"] is False
    assert any("different configuration" in n for n in gate["baseline"]["notes"])
    assert gate["status"] == "pass"


def test_evaluate_gate_accepts_a_typed_baseline(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    write(empty_root, "src/a.py", "x = 2\n")
    report = analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    baseline = build_baseline(report.findings, report.tool_version, strict_config.digest)
    assert evaluate_gate(report, None, strict_config).status == "fail"
    verdict = evaluate_gate(report, baseline, strict_config)
    assert verdict.status == "pass"
    assert verdict.baselined == 1


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ([], "must be a JSON object"),
        ({}, "missing the string field 'schema_version'"),
        ({"schema_version": "9"}, "schema_version '9' is not supported"),
        (
            {"schema_version": "1", "fingerprint_version": "0"},
            "fingerprint_version '0' does not match",
        ),
        (
            {
                "schema_version": "1",
                "fingerprint_version": "1",
                "tool_version": "0",
                "config_digest": "d",
                "fingerprints": [{"fingerprint": "f"}],
            },
            "missing the string field 'rule_id'",
        ),
        (
            {
                "schema_version": "1",
                "fingerprint_version": "1",
                "tool_version": "0",
                "config_digest": "d",
                "fingerprints": [
                    {
                        "fingerprint": "f",
                        "rule_id": "R",
                        "path": "p",
                        "scope": None,
                        "evidence": "e",
                        "occurrence": 0,
                    }
                ]
                * 2,
            },
            "duplicate fingerprint",
        ),
    ],
)
def test_malformed_baselines_are_typed_errors(document: object, message: str) -> None:
    with pytest.raises(UsageError, match=message):
        parse_baseline(document, "<test>")


def test_unreadable_or_invalid_baseline_files(empty_root: Path) -> None:
    with pytest.raises(UsageError, match="cannot read baseline"):
        load_baseline(empty_root / "missing.json")
    bad = empty_root / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(UsageError, match="not valid JSON"):
        load_baseline(bad)
    bad.write_bytes(b"\xff\xfe")
    with pytest.raises(UsageError, match="not valid UTF-8"):
        load_baseline(bad)
