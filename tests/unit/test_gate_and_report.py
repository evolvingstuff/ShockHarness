import json
from collections.abc import Callable
from pathlib import Path

from shockharness.analysis import AnalysisOptions
from shockharness.api import analyze_paths, analyze_source, evaluate_gate
from shockharness.config import EffectiveConfig
from shockharness.errors import UnsupportedFeatureError, UsageError
from shockharness.output import json as json_output
from shockharness.output import text as text_output
from tests.conftest import REPO_ROOT

OPTIONS = AnalysisOptions(inline_suppressions=True)


def write(root: Path, relative: str, body: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_clean_project_passes(empty_root: Path, strict_config: EffectiveConfig) -> None:
    write(empty_root, "src/a.py", "x = 1\n")
    report = analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    assert report.gate.status == "pass"
    assert report.gate.exit_code == 0
    assert report.analysis_status == "complete"
    assert report.findings == ()


def test_violations_fail(empty_root: Path, strict_config: EffectiveConfig) -> None:
    write(empty_root, "src/a.py", "x = 2\n")
    write(empty_root, "src/b.js", "const y = 3;\n")
    report = analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    assert report.gate.status == "fail"
    assert report.gate.exit_code == 1
    assert report.gate.hard_violations == 2
    assert [f.path for f in report.findings] == ["src/a.py", "src/b.js"]


def test_suppressed_findings_do_not_fail_the_gate(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    write(empty_root, "src/a.py", 'x = 2  # shockharness: ignore[MAGIC001] reason="documented"\n')
    report = analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    assert report.gate.status == "pass"
    assert report.gate.suppressed == 1
    assert len(report.findings) == 1


def test_warnings_do_not_fail_the_gate(empty_root: Path, strict_config: EffectiveConfig) -> None:
    write(empty_root, "src/a.py", 'x = 1  # shockharness: ignore[MAGIC001] reason="stale"\n')
    report = analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    assert report.gate.status == "pass"
    assert report.gate.warnings == 1


def test_parse_error_is_exit_3_under_strict(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    write(empty_root, "src/a.py", "x = 2\n")
    write(empty_root, "src/bad.py", "def (:\n")
    report = analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    assert report.gate.status == "error"
    assert report.gate.exit_code == 3
    assert report.analysis_status == "failed"
    assert report.gate.analysis_failures == 1
    assert report.gate.hard_violations == 1


def test_parse_error_warn_mode_is_incomplete_not_clean(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    config = make_config('parse_errors = "warn"\n')
    write(empty_root, "src/bad.py", "def (:\n")
    report = analyze_paths([empty_root / "src"], empty_root, config, OPTIONS)
    assert report.gate.status == "pass"
    assert report.gate.exit_code == 0
    assert report.analysis_status == "incomplete"
    assert any("could not be analyzed" in r for r in report.gate.reasons)
    assert report.coverage["files_failed"] == 1


def test_hard_violations_warn_mode(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    config = make_config('[tool.shockharness.gates]\nnew_hard_violations = "warn"\n')
    write(empty_root, "src/a.py", "x = 2\n")
    report = analyze_paths([empty_root / "src"], empty_root, config, OPTIONS)
    assert report.gate.status == "pass"
    assert report.gate.hard_violations == 1
    assert any("reported as warnings" in r for r in report.gate.reasons)


def test_report_lists_unimplemented_rules(empty_root: Path, strict_config: EffectiveConfig) -> None:
    write(empty_root, "src/a.py", "x = 1\n")
    report = analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    assert "CPLX001" in report.coverage["rules_not_implemented"]
    assert "DEF001" not in report.coverage["rules_not_implemented"]
    assert "EXC001" not in report.coverage["rules_not_implemented"]
    assert report.coverage["rules_implemented"] == [
        "MAGIC001",
        "EXC001",
        "EXC002",
        "EXC003",
        "DEF001",
        "DEF002",
        "DEF003",
        "DEF004",
        "DEF005",
        "DEF006",
        "SUPP001",
        "SUPP002",
    ]
    assert report.coverage["languages"]["python"]["parser"] == "python-ast"


def test_json_output_is_byte_identical_across_runs_and_target_order(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    write(empty_root, "src/z.py", "x = 2\ny = 3\n")
    write(empty_root, "src/a.js", "const q = 4;\n")
    first = json_output.render(
        analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    )
    second = json_output.render(
        analyze_paths(
            [empty_root / "src" / "z.py", empty_root / "src" / "a.js"],
            empty_root,
            strict_config,
            OPTIONS,
        )
    )
    third = json_output.render(
        analyze_paths(
            [empty_root / "src" / "a.js", empty_root / "src" / "z.py"],
            empty_root,
            strict_config,
            OPTIONS,
        )
    )
    assert second == third
    first_data = json.loads(first)
    second_data = json.loads(second)
    assert first_data["findings"] == second_data["findings"]
    assert first_data["gate"] == second_data["gate"]


def test_text_output_mentions_everything_that_matters(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    write(empty_root, "src/a.py", "x = 2\n")
    write(empty_root, "src/bad.js", "function (\n")
    report = analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    text = text_output.render(report)
    assert "src/a.py:1:5: MAGIC001 error:" in text
    assert "src/bad.js" in text and "parse_error" in text
    assert "rules not implemented (not analyzed):" in text
    assert "gate: ERROR (exit 3)" in text


def test_analyze_source_rejects_unknown_language(strict_config: EffectiveConfig) -> None:
    import pytest

    with pytest.raises(UsageError, match="unsupported language"):
        analyze_source("x = 1", "rust", strict_config)
    result = analyze_source("x = 2", "python", strict_config)
    assert result.path == "<source>"
    assert len(result.findings) == 1


def test_evaluate_gate_refuses_baselines_for_now(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    import pytest

    write(empty_root, "src/a.py", "x = 2\n")
    report = analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    assert evaluate_gate(report, None, strict_config).status == "fail"
    with pytest.raises(UnsupportedFeatureError):
        evaluate_gate(report, {"baseline": True}, strict_config)


def _check(schema: dict, value: object, path: str) -> list[str]:
    """Tiny JSON-Schema subset checker: type, enum, required, properties, items."""
    problems: list[str] = []
    type_names = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool}
    if "type" in schema:
        expected = type_names[schema["type"]]
        ok = isinstance(value, expected) and not (expected is int and isinstance(value, bool))
        if not ok:
            problems.append(f"{path}: expected {schema['type']}")
            return problems
    if "enum" in schema and value not in schema["enum"]:
        problems.append(f"{path}: {value!r} not in {schema['enum']}")
    if isinstance(value, dict):
        if "required" in schema:
            for key in schema["required"]:
                if key not in value:
                    problems.append(f"{path}.{key}: missing")
        props: dict[str, object] = {}
        if "properties" in schema:
            props = schema["properties"]
        for key, sub in props.items():
            if key in value:
                problems.extend(_check(sub, value[key], f"{path}.{key}"))
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            problems.extend(_check(schema["items"], item, f"{path}[{index}]"))
    return problems


def test_report_matches_published_schema(empty_root: Path, strict_config: EffectiveConfig) -> None:
    write(empty_root, "src/a.py", 'x = 2  # shockharness: ignore[MAGIC001] reason="r"\ny = 3\n')
    write(empty_root, "src/bad.js", "function (\n")
    report = analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    data = json.loads(json_output.render(report))
    schema = json.loads(
        (REPO_ROOT / "schemas" / "report-v1.schema.json").read_text(encoding="utf-8")
    )
    assert _check(schema, data, "$") == []
    assert data["schema_version"] == "1"
