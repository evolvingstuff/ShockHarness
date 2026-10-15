from collections.abc import Callable

from shockharness.analysis import CACHE_CONFIGURED, AnalysisOptions, FileResult, analyze_text
from shockharness.config import EffectiveConfig
from tests.conftest import finding_tuples


def test_valid_suppression_keeps_finding_but_marks_it(
    analyze: Callable[[str, str], FileResult],
) -> None:
    result = analyze(
        'x = 30  # shockharness: ignore[MAGIC001] reason="RFC 1234 field width"\n', "python"
    )
    (finding,) = result.findings
    assert finding.rule_id == "MAGIC001"
    assert finding.suppression is not None
    assert finding.suppression.reason == "RFC 1234 field width"
    assert finding.suppression.line == 1


def test_multiple_rule_ids(analyze: Callable[[str, str], FileResult]) -> None:
    result = analyze(
        'x = 30  # shockharness: ignore[SUPP002, MAGIC001] reason="two ids"\n', "python"
    )
    rules = [(f.rule_id, f.is_suppressed) for f in result.findings]
    assert ("MAGIC001", True) in rules


def test_malformed_suppression_is_an_error_and_does_not_suppress(
    analyze: Callable[[str, str], FileResult],
) -> None:
    result = analyze("x = 30  # shockharness: ignore[MAGIC001]\n", "python")
    assert finding_tuples(result) == [("MAGIC001", 1, 5), ("SUPP001", 1, 9)]
    assert not result.findings[0].is_suppressed


def test_unknown_rule_and_empty_reason(analyze: Callable[[str, str], FileResult]) -> None:
    text = (
        'a = 30  # shockharness: ignore[NOPE] reason="x"\n'
        'b = 30  # shockharness: ignore[MAGIC001] reason=""\n'
    )
    result = analyze(text, "python")
    messages = [f.message for f in result.findings if f.rule_id == "SUPP001"]
    assert any("unknown rule 'NOPE'" in m for m in messages)
    assert any("empty reason" in m for m in messages)


def test_unused_suppression_is_a_warning(analyze: Callable[[str, str], FileResult]) -> None:
    result = analyze('x = 1  # shockharness: ignore[MAGIC001] reason="stale"\n', "python")
    (finding,) = result.findings
    assert finding.rule_id == "SUPP002"
    assert finding.severity == "warning"


def test_suppression_on_other_line_does_not_apply(
    analyze: Callable[[str, str], FileResult],
) -> None:
    result = analyze('# shockharness: ignore[MAGIC001] reason="above"\nx = 30\n', "python")
    assert finding_tuples(result) == [("SUPP002", 1, 1), ("MAGIC001", 2, 5)]


def test_javascript_line_and_block_forms(analyze: Callable[[str, str], FileResult]) -> None:
    text = (
        'const a = 30; // shockharness: ignore[MAGIC001] reason="line"\n'
        'const b = 30; /* shockharness: ignore[MAGIC001] reason="block" */\n'
    )
    result = analyze(text, "javascript")
    assert [(f.rule_id, f.is_suppressed) for f in result.findings] == [
        ("MAGIC001", True),
        ("MAGIC001", True),
    ]


def test_no_inline_suppressions_mode(strict_config: EffectiveConfig) -> None:
    text = 'x = 30  # shockharness: ignore[MAGIC001] reason="valid but ignored"\n'
    result = analyze_text(
        "t.py",
        "python",
        text,
        strict_config,
        AnalysisOptions(inline_suppressions=False, cache=CACHE_CONFIGURED),
    )
    rules = [(f.rule_id, f.is_suppressed) for f in result.findings]
    assert rules == [("MAGIC001", False), ("SUPP001", False)]
    assert "disabled by policy" in result.findings[1].message


def test_suppression_rules_can_be_disabled_by_override(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    config = make_config(
        "[[tool.shockharness.overrides]]\n"
        'paths = ["*.py"]\ndisable = ["SUPP002"]\nreason = "legacy"\n'
    )
    result = analyze_text(
        "t.py",
        "python",
        'x = 1  # shockharness: ignore[MAGIC001] reason="stale"\n',
        config,
        AnalysisOptions(True, CACHE_CONFIGURED),
    )
    assert result.findings == ()
    assert "SUPP002" not in result.rules_applied
