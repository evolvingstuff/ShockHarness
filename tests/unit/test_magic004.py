"""MAGIC004 (spec 21.1 decision 36): a named constant whose name only spells a number."""

from collections.abc import Callable

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions, analyze_text
from shockharness.config import EffectiveConfig
from shockharness.rules.magic_numbers import spells_a_number

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)


def _magic004(config: EffectiveConfig, text: str, language: str) -> list[tuple[int, str]]:
    name = "src/a.py" if language == "python" else "src/a.js"
    result = analyze_text(name, language, text, config, OPTIONS)
    return [(f.span.line, f.severity) for f in result.findings if f.rule_id == "MAGIC004"]


def test_names_that_only_spell_a_number() -> None:
    for name in ("TWO", "ONE_HUNDRED", "VALUE_100", "_TWENTY_FOUR", "NUMBER_TEN", "DOZEN"):
        assert spells_a_number(name), name
    for name in ("TIMEOUT_30", "INDENT_SPACES", "N", "VALUE", "MAX_RETRIES", "FIRST", "ONE_JOB"):
        assert not spells_a_number(name), name


def test_python_definitions_are_reported_at_review(strict_config: EffectiveConfig) -> None:
    text = (
        "from typing import Final\n"
        "TWO = 2\n"  # 2
        "ONE_HUNDRED = 10 * 10\n"  # 3: literal arithmetic is a definition
        "two: Final = 2\n"  # 4: a Final name, read in capitals
        "TIMEOUT_30 = 30\n"  # 5: another word: not reported
        "def f():\n    THREE = 3\n    return THREE\n"  # 7: not a module-level definition
        "TWELVE = [12]\n"  # 9: a container is not a definition
    )
    assert _magic004(strict_config, text, "python") == [
        (2, "review"),
        (3, "review"),
        (4, "review"),
    ]


def test_javascript_definitions_are_reported(strict_config: EffectiveConfig) -> None:
    text = (
        "const THREE = 3;\n"  # 1
        "export const DOZEN = 12;\n"  # 2
        "let FOUR = 4;\n"  # 3: let is not a constant definition
        "const SETTLE_MS = 400;\n"  # 4
    )
    assert _magic004(strict_config, text, "javascript") == [(1, "review"), (2, "review")]


def test_severity_and_family_switch(make_config: Callable[[str], EffectiveConfig]) -> None:
    raised = make_config('[tool.shockharness.rules.magic_numbers]\nmagic004_severity = "error"\n')
    assert _magic004(raised, "TWO = 2\n", "python") == [(1, "error")]
    off = make_config("[tool.shockharness.rules.magic_numbers]\nenabled = false\n")
    assert _magic004(off, "TWO = 2\n", "python") == []
    lowered = make_config(
        '[tool.shockharness.rules.magic_numbers]\nmagic004_severity = "warning"\n'
    )
    assert _magic004(lowered, "TWO = 2\n", "python") == [(1, "warning")]
