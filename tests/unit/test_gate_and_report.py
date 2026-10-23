import json
from collections.abc import Callable
from pathlib import Path

from shockharness.analysis import CACHE_CONFIGURED, AnalysisOptions
from shockharness.api import analyze_paths, analyze_source, evaluate_gate
from shockharness.config import EffectiveConfig
from shockharness.errors import UsageError
from shockharness.output import json as json_output
from shockharness.output import text as text_output
from tests.conftest import REPO_ROOT, without_cache_block

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_CONFIGURED)


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
    assert report.coverage["rules_not_implemented"] == []  # MAGIC002 landed after 0.7.0
    assert report.coverage["rules_needing_base_revision"] == [
        "VERIFY001",
        "VERIFY002",
        "VERIFY003",
        "VERIFY004",
        "VERIFY006",
    ]
    assert report.coverage["verification"]["status"] == "not_applicable"
    assert "DEF001" not in report.coverage["rules_not_implemented"]
    assert "EXC001" not in report.coverage["rules_not_implemented"]
    assert report.coverage["languages"]["python"]["parser"] == "python-ast"


# The rules expected, as one constant (the list grows with every rule).
IMPLEMENTED_IN_ORDER = (
    "MAGIC001",
    "MAGIC002",
    "EXC001",
    "EXC002",
    "EXC003",
    "EXC004",
    "DEF001",
    "DEF002",
    "DEF003",
    "DEF004",
    "DEF005",
    "DEF006",
    "CPLX001",
    "CPLX002",
    "CPLX003",
    "CPLX004",
    "CPLX005",
    "CPLX006",
    "SUPP001",
    "SUPP002",
    "VERIFY001",
    "VERIFY002",
    "VERIFY003",
    "VERIFY004",
    "VERIFY005",
    "VERIFY006",
    "STUB001",
    "STUB002",
    "ASSERT001",
    "ASSERT002",
    "BOOL001",
    "STATE001",
    "IMPORT001",
    "ASYNC001",
    "ASYNC002",
    "ASYNC003",
    "ASYNC004",
    "PROCESS001",
    "RESULT001",
    "TYPE001",
    "TYPE002",
    "SLEEP001",
    "RETRY001",
    "BATCH001",
    "STUB003",
    "ROLE001",
    "INPUT001",
    "INPUT002",
    "PROV001",
    "GUARD001",
    "MAGIC003",
    "MAGIC004",
    "MAGIC005",
    "EXC005",
    "EXC006",
    "STATE002",
    "STATE003",
    "PROP001",
    "PROP002",
    "PROP003",
    "PROP004",
    "PROP005",
    "PROP006",
    "PROP007",
    "PROP008",
    "DOM001",
    "DOM002",
    "DOM003",
    "DEAD001",
    "DEAD002",
    "DUP001",
    "DUP002",
    "IMPORT002",
    "GODOT001",
    "GODOT002",
    "GODOT003",
    "GODOT004",
    "GODOT005",
)


def test_report_lists_implemented_rules_in_registry_order(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    write(empty_root, "src/a.py", "x = 1\n")
    report = analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    assert report.coverage["rules_implemented"] == list(IMPLEMENTED_IN_ORDER)


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
    assert without_cache_block(second) == without_cache_block(third)
    first_data = json.loads(first)
    second_data = json.loads(second)
    assert first_data["findings"] == second_data["findings"]
    assert first_data["gate"] == second_data["gate"]
    assert first_data["summary"]["findings"] == first_data["execution_summary"]["findings"]


def test_text_output_mentions_everything_that_matters(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    write(empty_root, "src/a.py", "x = 2\n")
    write(empty_root, "src/bad.js", "function (\n")
    report = analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    text = text_output.render(report)
    assert "src/a.py:1:5: MAGIC001 error:" in text
    assert "src/bad.js" in text and "parse_error" in text
    assert "rules not implemented (not analyzed):" not in text  # none is left
    assert "gate: ERROR (exit 3)" in text


def test_analyze_source_rejects_unknown_language(strict_config: EffectiveConfig) -> None:
    import pytest

    with pytest.raises(UsageError, match="unsupported language"):
        analyze_source("x = 1", "rust", strict_config)
    result = analyze_source("x = 2", "python", strict_config)
    assert result.path == "<source>"
    assert len(result.findings) == 1


def test_evaluate_gate_rejects_untyped_baselines(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    import pytest

    write(empty_root, "src/a.py", "x = 2\n")
    report = analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    assert evaluate_gate(report, None, strict_config).status == "fail"
    with pytest.raises(UsageError, match="must be a shockharness"):
        evaluate_gate(report, {"baseline": True}, strict_config)  # type: ignore[arg-type]


def _check(schema: dict, value: object, path: str) -> list[str]:
    """Tiny JSON-Schema subset checker: type, enum, required, properties, items."""
    problems: list[str] = []
    type_names = {
        "object": dict,
        "array": list,
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "null": type(None),
    }
    if "type" in schema:
        allowed = schema["type"]
        if isinstance(allowed, str):
            allowed = [allowed]
        ok = any(
            isinstance(value, type_names[name])
            and not (name == "integer" and isinstance(value, bool))
            for name in allowed
        )
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


def test_advisory_gate_changes_only_the_process_exit_code(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    from shockharness.gate import advisory_line, as_advisory, process_exit_code

    write(empty_root, "src/a.py", "x = 2\n")
    report = analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    gate = report.gate
    assert gate.advisory is False and process_exit_code(gate) == 1
    advisory = as_advisory(gate)
    assert advisory.to_json_dict() == {**gate.to_json_dict(), "advisory": True}
    assert process_exit_code(advisory) == 0
    assert advisory_line(advisory) == (
        "shockharness: advisory run (--exit-zero): gate verdict FAIL reported as exit 0"
    )
    write(empty_root, "src/bad.js", "function (\n")
    report = analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    assert process_exit_code(as_advisory(report.gate)) == 3


def test_summary_counts_policy_files_complexity_and_cycles(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    from shockharness.report import is_policy_rule, top_level_directory

    assert top_level_directory("src/pkg/a.py") == "src/"
    assert top_level_directory("a.py") == "."
    assert is_policy_rule("MAGIC001") and is_policy_rule("SUPP002") and is_policy_rule("DEF005")
    assert not is_policy_rule("CPLX005")
    deep = (
        "def f(a):\n"
        + "".join("    " * (i + 1) + f"if a{i}:\n" for i in range(6))
        + "    " * 7
        + "pass\n"
    )
    write(empty_root, "src/__init__.py", "")
    write(empty_root, "src/a.py", "from src import b\n" + deep)
    write(
        empty_root,
        "src/b.py",
        'from src import a\nx = 2  # shockharness: ignore[MAGIC001] reason="r"\n',
    )
    report = analyze_paths([empty_root / "src"], empty_root, strict_config, OPTIONS)
    summary = report.to_json_dict()["summary"]
    assert summary["complexity"]["status"] == "available"
    assert summary["complexity"]["units"] == 4
    assert summary["complexity"]["units_over"] == {
        "cyclomatic_warn": 0,
        "cognitive_warn": 1,  # f: 1+2+3+4+5+6 = 21
        "max_nesting_warn": 1,
        "npath_warn": 0,
        "max_lines_warn": 0,
    }
    assert summary["complexity"]["cycles"] == 1
    assert summary["complexity"]["units_over_fan_out_warn"] == 0
    assert summary["complexity"]["thresholds"]["cognitive_warn"] == 15
    # the suppressed MAGIC001 still counts as a policy finding, as in execution_summary
    assert summary["top_files"] == [{"path": "src/b.py", "policy_findings": 1}]
    assert summary["suppressed"] == 1 == report.execution_summary["suppressed"]
    assert summary["by_rule"] == {"CPLX002": 1, "CPLX003": 1, "CPLX005": 1, "MAGIC001": 1}
    assert summary["by_severity"] == report.execution_summary["findings_by_severity"]
    assert summary["findings"] == report.execution_summary["findings"] == 4
    assert "elapsed_seconds" not in summary
    assert report.elapsed_seconds >= 0


def test_summary_with_complexity_disabled(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    config = make_config("[tool.shockharness.complexity]\nenabled = false\n")
    write(empty_root, "src/a.py", "x = 1\n")
    report = analyze_paths([empty_root / "src"], empty_root, config, OPTIONS)
    complexity = report.to_json_dict()["summary"]["complexity"]
    assert complexity["status"] == "disabled"
    assert complexity["units"] == 0 and complexity["cycles"] == 0
    assert complexity["units_over_fan_out_warn"] == 0
    assert set(complexity["units_over"]) == {
        "cyclomatic_warn",
        "cognitive_warn",
        "max_nesting_warn",
        "npath_warn",
        "max_lines_warn",
    }
    assert "  complexity: disabled" in text_output.render_summary(report)
