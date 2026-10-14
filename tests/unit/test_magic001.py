from collections.abc import Callable

from shockharness.analysis import AnalysisOptions, FileResult, analyze_text
from shockharness.config import EffectiveConfig
from tests.conftest import finding_tuples


def test_python_range_two_fails(analyze: Callable[[str, str], FileResult]) -> None:
    result = analyze("for i in range(2):\n    pass\n", "python")
    assert finding_tuples(result) == [("MAGIC001", 1, 16)]
    (finding,) = result.findings
    assert finding.severity == "error"
    assert finding.confidence == "exact"
    assert finding.safe_autofix is False
    assert finding.evidence == "for i in range(2):"
    assert finding.scope == "<module>"
    assert "Numeric literal 2" in finding.message


def test_javascript_for_loop_fails(analyze: Callable[[str, str], FileResult]) -> None:
    result = analyze("for (let i = 0; i < 2; i++) {}\n", "javascript")
    assert finding_tuples(result) == [("MAGIC001", 1, 21)]


def test_zero_and_one_in_any_encoding_pass(analyze: Callable[[str, str], FileResult]) -> None:
    assert (
        analyze("a = [0, 1, 0.0, 1.0, 0x0, 0x1, 0o1, 0b1, 1e0, 0j, 00]\n", "python").findings == ()
    )
    assert (
        analyze(
            "const a = [0, 1, 0.0, 1.0, 0x0, 0x1, 0o1, 0b1, 1e0, 0n, 1n, .0, 1.];\n", "javascript"
        ).findings
        == ()
    )


def test_negative_one_and_negative_zero_fail_by_default(
    analyze: Callable[[str, str], FileResult],
) -> None:
    result = analyze("a = -1\nb = -0\nc = -0.0\nd = -1.0\n", "python")
    assert [f.span.line for f in result.findings] == [1, 2, 3, 4]


def test_allow_unary_negative_one(make_config: Callable[[str], EffectiveConfig]) -> None:
    config = make_config(
        "[tool.shockharness.rules.magic_numbers]\nallow_unary_negative_one = true\n"
    )
    result = analyze_text(
        "t.py", "python", "a = -1\nb = -1.0\nc = -0\nd = -2\n", config, AnalysisOptions(True)
    )
    assert [f.span.line for f in result.findings] == [3, 4]
    js = analyze_text(
        "t.js", "javascript", "const a = -1, b = -0, c = -1n;\n", config, AnalysisOptions(True)
    )
    assert [f.message.split(" ")[2] for f in js.findings] == ["-0"]


def test_extra_allowed_values_are_honoured_and_reported(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    config = make_config(
        "[tool.shockharness.rules.magic_numbers]\nallowed_values = [0, 1, 2, 100]\n"
    )
    result = analyze_text(
        "t.py", "python", "a = 2\nb = 100\nc = 100.0\nd = 3\n", config, AnalysisOptions(True)
    )
    assert [f.span.line for f in result.findings] == [4]
    assert any("allowed_values permits 100, 2" in d for d in config.deviations)


def test_annotation_literals_are_flagged_and_labelled(
    analyze: Callable[[str, str], FileResult],
) -> None:
    result = analyze("def f(x: Literal[2]) -> int:\n    return 1\n", "python")
    (finding,) = result.findings
    assert "type annotation" in finding.message


def test_named_constant_is_still_a_literal(analyze: Callable[[str, str], FileResult]) -> None:
    result = analyze("ITERATIONS = 2\nMAX_RETRIES = 5\n", "python")
    assert [f.span.line for f in result.findings] == [1, 2]


def test_stdlib_constants_are_fine(analyze: Callable[[str, str], FileResult]) -> None:
    assert analyze("import math\narea = math.pi * r * r\n", "python").findings == ()
    assert (
        analyze(
            "const a = Math.PI * r * r; const b = Number.MAX_SAFE_INTEGER;\n", "javascript"
        ).findings
        == ()
    )


def test_disabled_rule_produces_nothing_and_is_recorded(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    config = make_config("[tool.shockharness.rules.magic_numbers]\nenabled = false\n")
    result = analyze_text("t.py", "python", "x = 42\n", config, AnalysisOptions(True))
    assert result.findings == ()
    assert "MAGIC001" not in result.rules_applied
    assert [(d.rule_id, d.origin) for d in result.rules_disabled] == [("MAGIC001", "config")]
    assert "rules.magic_numbers is disabled" in config.deviations


def test_findings_are_sorted_by_position_regardless_of_ast_order(
    analyze: Callable[[str, str], FileResult],
) -> None:
    result = analyze("d = {1: 2, 3: 4}\n", "python")
    assert [f.span.column for f in result.findings] == [9, 12, 15]
