from collections.abc import Callable

import pytest

from shockharness.analysis import CACHE_CONFIGURED, AnalysisOptions, FileResult, analyze_text
from shockharness.config import EffectiveConfig
from shockharness.errors import ConfigError
from tests.conftest import finding_tuples

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_CONFIGURED)


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


def test_negative_one_is_allowed_by_default_negative_zero_is_not(
    analyze: Callable[[str, str], FileResult], make_config: Callable[[str], EffectiveConfig]
) -> None:
    text = "a = -1\nb = -0\nc = -0.0\nd = -1.0\nlast = items[-1]\n"
    lines = [f.span.line for f in analyze(text, "python").findings if f.rule_id == "MAGIC001"]
    assert lines == [2, 3]
    off = make_config("[tool.shockharness.rules.magic_numbers]\nallow_unary_negative_one = false\n")
    result = analyze_text("t.py", "python", text, off, AnalysisOptions(True, CACHE_CONFIGURED))
    assert [f.span.line for f in result.findings if f.rule_id == "MAGIC001"] == [1, 2, 3, 4, 5]
    assert not any("allow_unary_negative_one" in d for d in off.deviations)  # stricter


def test_allow_unary_negative_one(make_config: Callable[[str], EffectiveConfig]) -> None:
    config = make_config(
        "[tool.shockharness.rules.magic_numbers]\nallow_unary_negative_one = true\n"
    )
    result = analyze_text(
        "t.py",
        "python",
        "a = -1\nb = -1.0\nc = -0\nd = -2\n",
        config,
        AnalysisOptions(True, CACHE_CONFIGURED),
    )
    assert [f.span.line for f in result.findings if f.rule_id == "MAGIC001"] == [3, 4]
    js = analyze_text(
        "t.js",
        "javascript",
        "const a = -1, b = -0, c = -1n;\n",
        config,
        AnalysisOptions(True, CACHE_CONFIGURED),
    )
    assert [f.message.split(" ")[2] for f in js.findings if f.rule_id == "MAGIC001"] == ["-0"]


def test_extra_allowed_values_are_honoured_and_reported(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    config = make_config(
        "[tool.shockharness.rules.magic_numbers]\nallowed_values = [0, 1, 2, 100]\n"
    )
    result = analyze_text(
        "t.py",
        "python",
        "a = 2\nb = 100\nc = 100.0\nd = 3\n",
        config,
        AnalysisOptions(True, CACHE_CONFIGURED),
    )
    assert [f.span.line for f in result.findings] == [4]
    assert any("allowed_values permits 100, 2" in d for d in config.deviations)


def test_annotation_literals_are_flagged_and_labelled(
    analyze: Callable[[str, str], FileResult],
) -> None:
    result = analyze("def f(x: Literal[2]) -> int:\n    return 1\n", "python")
    (finding,) = result.findings
    assert "type annotation" in finding.message


def test_a_named_constant_needs_no_justification(
    analyze: Callable[[str, str], FileResult],
) -> None:
    # Spec 21.1 decision 36: the definition is the name MAGIC001 asks for; the literal
    # where a number is used is still reported.
    result = analyze("ITERATIONS = 2\nMAX_RETRIES = 5\nwait = 7 * ITERATIONS\n", "python")
    assert [(f.rule_id, f.span.line) for f in result.findings] == [("MAGIC001", 3)]


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
    result = analyze_text(
        "t.py", "python", "x = 42\n", config, AnalysisOptions(True, CACHE_CONFIGURED)
    )
    assert result.findings == ()
    assert "MAGIC001" not in result.rules_applied
    assert [(d.rule_id, d.origin) for d in result.rules_disabled] == [
        ("MAGIC001", "config"),
        ("MAGIC004", "config"),
    ]
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
    "TIMEOUT = 30 * 60\n"  # 10: literal arithmetic: a definition since 0.3.0
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
PY_DEFINITION_LINES = [3, 4, 5, 6, 7, 8, 10, 10]
PY_OTHER_LINES = [9, 11, 12, 14, 16, 19]
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


def test_every_profile_allows_constant_definitions_and_report_is_a_tightening(
    strict_config: EffectiveConfig, make_config: Callable[[str], EffectiveConfig]
) -> None:
    # Spec 21.1 decision 36: "allow" in every profile, so it is no deviation; "report"
    # (every definition needs a suppression) is a tightening, no deviation either.
    for profile in ("strict", "recommended", "minimal"):
        config = make_config(f'profile = "{profile}"\n')
        assert config.values["rules"]["magic_numbers"]["named_constant_definitions"] == "allow"
        assert not any("named_constant_definitions" in d for d in config.deviations)
        assert _magic_lines(config, PY_CONSTANTS, "python") == PY_OTHER_LINES
        assert _magic_lines(config, JS_CONSTANTS, "javascript") == JS_OTHER_LINES
    # the acceptance examples, one by one
    assert _magic_lines(strict_config, "MAX_PAGES = 8\n", "python") == []
    assert _magic_lines(strict_config, "_PORT_WAIT_SECONDS = 10.0\n", "python") == []
    assert _magic_lines(strict_config, "def f():\n    x = 8\n    return x\n", "python") == [2]
    assert _magic_lines(strict_config, "const MAX_PAGES = 8;\n", "javascript") == []
    assert _magic_lines(strict_config, "export const MAX_PAGES = 8;\n", "javascript") == []
    assert _magic_lines(strict_config, "let maxPages = 8;\n", "javascript") == [1]
    assert _magic_lines(strict_config, "LIMITS = {'retries': 3}\n", "python") == [1]
    reported = make_config(
        '[tool.shockharness.rules.magic_numbers]\nnamed_constant_definitions = "report"\n'
    )
    assert reported.deviations == ()
    assert _magic_lines(reported, PY_CONSTANTS, "python") == sorted(
        PY_DEFINITION_LINES + PY_OTHER_LINES
    )
    assert _magic_lines(reported, JS_CONSTANTS, "javascript") == sorted(
        JS_DEFINITION_LINES + JS_OTHER_LINES
    )


def test_named_constant_mode_is_validated(make_config: Callable[[str], EffectiveConfig]) -> None:
    with pytest.raises(ConfigError, match=r"named_constant_definitions: must be one of"):
        make_config('[tool.shockharness.rules.magic_numbers]\nnamed_constant_definitions = "yes"\n')


# --- literal arithmetic in named constants (0.3.0 brief, item 2) ---------------------------


def test_literal_arithmetic_in_a_named_constant_is_a_definition(
    strict_config: EffectiveConfig, make_config: Callable[[str], EffectiveConfig]
) -> None:
    allowed = strict_config  # "allow" is the default since decision 36
    reported = make_config(
        '[tool.shockharness.rules.magic_numbers]\nnamed_constant_definitions = "report"\n'
    )
    # the acceptance examples
    assert _magic_lines(allowed, "CHUNK_BYTES = 64 * 1024\n", "python") == []
    assert _magic_lines(allowed, "const MAX_MS = 30 * 60 * 1000;\n", "javascript") == []
    assert _magic_lines(allowed, "TIMEOUT = BASE * 2\n", "python") == [1]
    assert _magic_lines(allowed, "SIZE = int(x) * 2\n", "python") == [1]
    assert _magic_lines(allowed, "LIMITS = [8, 16]\n", "python") == [1, 1]
    assert _magic_lines(reported, "CHUNK_BYTES = 64 * 1024\n", "python") == [1, 1]
    assert _magic_lines(allowed, "def f():\n    K = 64 * 1024\n    return K\n", "python") == [
        2,
        2,
    ]
    # the whole operator set, unary signs and parentheses, in both languages
    full = "P = -(30 * 60) / 2 + (2 ** 10) // 3 % 7 - +4\n"
    assert _magic_lines(allowed, full, "python") == []
    assert len(_magic_lines(reported, full, "python")) == 8
    js_full = "export const P = -(30 * 60) / 2 + (2 ** 10) % 7 - +4;\n"
    assert _magic_lines(allowed, js_full, "javascript") == []
    assert len(_magic_lines(reported, js_full, "javascript")) == 7
    assert _magic_lines(allowed, "F: float = 2.5 * 4\nwait: Final = 3 * 5\n", "python") == []
    # anything else in the expression keeps every literal reported
    for text in (
        "A = 2 * len(x)\n",
        "B = 2 * x.y\n",
        "C = 2 * xs[0]\n",
        "D = '3' * 2\n",
        "E = True * 2\n",
        "F = 2 << 3\n",
        "G = 2 if x else 3\n",
    ):
        assert len(_magic_lines(allowed, text, "python")) == len(
            _magic_lines(reported, text, "python")
        ), text
        assert len(_magic_lines(allowed, text, "python")) > 0, text
    for text in (
        "const A = 2 * f(x);\n",
        "const B = 2 * x.y;\n",
        "const C = 2 << 3;\n",
        "const D = '3' * 2;\n",
        "const E = 2 * (x, 3);\n",
    ):
        assert len(_magic_lines(allowed, text, "javascript")) == len(
            _magic_lines(reported, text, "javascript")
        ), text
        assert len(_magic_lines(allowed, text, "javascript")) > 0, text
    # a comment inside the parentheses does not disqualify a JavaScript definition
    assert _magic_lines(allowed, "const C = (2 /* two */ * 4);\n", "javascript") == []
