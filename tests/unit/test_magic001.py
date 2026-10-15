from collections.abc import Callable

import pytest

from shockharness.analysis import AnalysisOptions, FileResult, analyze_text
from shockharness.config import EffectiveConfig
from shockharness.errors import ConfigError
from tests.conftest import finding_tuples

OPTIONS = AnalysisOptions(inline_suppressions=True)


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


# --- named_constant_definitions (0.2.0 feedback round, item 1) -----------------------------

PY_CONSTANTS = (
    "from typing import Final\n"
    "import typing as t\n"
    "MAX_PAGES = 8\n"  # 3: UPPER_SNAKE_CASE, int
    "_PORT_WAIT_SECONDS = 10.0\n"  # 4: leading underscore, float
    "NEGATIVE = -8\n"  # 5: unary minus
    "wait: Final = 2.5\n"  # 6: Final-annotated lower-case name
    "limit: t.Final[int] = 7\n"  # 7: qualified, subscripted Final
    "MAX_RETRIES: int = 5\n"  # 8: UPPER name with another annotation
    "LIMITS = {'retries': 3}\n"  # 9: container: reported
    "TIMEOUT = 30 * 60\n"  # 10: expression: both reported
    "A = B = 9\n"  # 11: chained targets: reported
    "lower = 4\n"  # 12: not a constant name: reported
    "class K:\n    N = 6\n"  # 14: class body: reported
    "def f():\n    x = 8\n    return x\n"  # 16: function body: reported
    "if True:\n    NESTED = 11\n"  # 19: not a statement of the module body: reported
)
JS_CONSTANTS = (
    "const MAX_PAGES = 8;\n"  # 1
    "export const _SETTLE_MS = -400;\n"  # 2
    "const A = 1, TWO = 2;\n"  # 3: each declarator on its own; 1 is allowed anyway
    "let maxPages = 8;\n"  # 4: let: reported
    "var LIMIT = 8;\n"  # 5: var: reported
    "const camel = 8;\n"  # 6: not a constant name: reported
    "const SIZES = [8, 16];\n"  # 7: container: reported
    "function f() { const INNER = 8; return INNER; }\n"  # 8: function body: reported
    "{ const BLOCK = 8; }\n"  # 9: block scope: reported
    "export default 5;\n"  # 10: not a declaration: reported
)
PY_DEFINITION_LINES = [3, 4, 5, 6, 7, 8]
PY_OTHER_LINES = [9, 10, 10, 11, 12, 14, 16, 19]
JS_DEFINITION_LINES = [1, 2, 3]  # line 3 holds two definitions; one is the permitted 1
JS_OTHER_LINES = [4, 5, 6, 7, 7, 8, 9, 10]


def _magic_lines(config: EffectiveConfig, text: str, language: str) -> list[int]:
    result = analyze_text(
        "src/a.py" if language == "python" else "src/a.js", language, text, config, OPTIONS
    )
    return [f.span.line for f in result.findings if f.rule_id == "MAGIC001"]


def test_constant_definitions_are_marked_in_the_ir() -> None:
    from shockharness.ir.javascript import extract_javascript_facts
    from shockharness.ir.python import extract_python_facts
    from shockharness.source import SourceText

    facts = extract_python_facts(SourceText.from_text(PY_CONSTANTS), "a.py")
    marked = [lit.span.line for lit in facts.numeric_literals if lit.constant_definition]
    assert marked == PY_DEFINITION_LINES
    facts = extract_javascript_facts(SourceText.from_text(JS_CONSTANTS), "a.js")
    marked = [lit.span.line for lit in facts.numeric_literals if lit.constant_definition]
    assert marked == [1, 2, 3, 3]


def test_strict_reports_constant_definitions_and_allow_is_a_deviation(
    strict_config: EffectiveConfig, make_config: Callable[[str], EffectiveConfig]
) -> None:
    assert strict_config.values["rules"]["magic_numbers"]["named_constant_definitions"] == "report"
    assert _magic_lines(strict_config, PY_CONSTANTS, "python") == sorted(
        PY_DEFINITION_LINES + PY_OTHER_LINES
    )
    assert _magic_lines(strict_config, JS_CONSTANTS, "javascript") == sorted(
        JS_DEFINITION_LINES + JS_OTHER_LINES
    )
    allowed = make_config(
        '[tool.shockharness.rules.magic_numbers]\nnamed_constant_definitions = "allow"\n'
    )
    assert allowed.values["profile"] == "strict"
    assert allowed.deviations == (
        "rules.magic_numbers.named_constant_definitions is 'allow'; a numeric literal that is "
        "the whole value of a module-level named constant definition is not reported",
    )
    assert _magic_lines(allowed, PY_CONSTANTS, "python") == PY_OTHER_LINES
    assert _magic_lines(allowed, JS_CONSTANTS, "javascript") == JS_OTHER_LINES
    # the acceptance examples, one by one
    assert _magic_lines(allowed, "MAX_PAGES = 8\n", "python") == []
    assert _magic_lines(allowed, "_PORT_WAIT_SECONDS = 10.0\n", "python") == []
    assert _magic_lines(allowed, "def f():\n    x = 8\n    return x\n", "python") == [2]
    assert _magic_lines(allowed, "const MAX_PAGES = 8;\n", "javascript") == []
    assert _magic_lines(allowed, "export const MAX_PAGES = 8;\n", "javascript") == []
    assert _magic_lines(allowed, "let maxPages = 8;\n", "javascript") == [1]
    assert _magic_lines(allowed, "LIMITS = {'retries': 3}\n", "python") == [1]
    explicit_report = make_config(
        '[tool.shockharness.rules.magic_numbers]\nnamed_constant_definitions = "report"\n'
    )
    assert explicit_report.deviations == ()
    assert _magic_lines(explicit_report, "MAX_PAGES = 8\n", "python") == [1]


def test_recommended_and_minimal_allow_constant_definitions(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    for profile in ("recommended", "minimal"):
        config = make_config(f'profile = "{profile}"\n')
        assert config.values["rules"]["magic_numbers"]["named_constant_definitions"] == "allow"
        assert _magic_lines(config, PY_CONSTANTS, "python") == PY_OTHER_LINES
        assert _magic_lines(config, JS_CONSTANTS, "javascript") == JS_OTHER_LINES
        assert "rules.magic_numbers.named_constant_definitions is 'allow'" in "\n".join(
            config.deviations
        )


def test_named_constant_mode_is_validated(make_config: Callable[[str], EffectiveConfig]) -> None:
    with pytest.raises(ConfigError, match=r"named_constant_definitions: must be one of"):
        make_config('[tool.shockharness.rules.magic_numbers]\nnamed_constant_definitions = "yes"\n')
