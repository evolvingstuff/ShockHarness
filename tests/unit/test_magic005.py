"""MAGIC005: a number MAGIC001 would report, written as something else so that it does not
see it. Every shape here appeared in the under-the-gate experiment's gated builds."""

from pathlib import Path

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions, analyze_text
from shockharness.config import EffectiveConfig, load_config

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)


def _magic005(config: EffectiveConfig, text: str, name: str) -> list[tuple[int, str]]:
    language = "python" if name.endswith(".py") else "javascript"
    result = analyze_text(name, language, text, config, OPTIONS)
    return [(f.span.line, f.severity) for f in result.findings if f.rule_id == "MAGIC005"]


def test_python_disguises(strict_config: EffectiveConfig) -> None:
    text = (
        "import json\n"
        "import tomllib\n"
        'REPORT_INDENT = "  "\n'
        'WIDTH = len("  ")\n'  # 4: whitespace counted for its length
        "def f(report, x):\n"
        "    a = len((x, report))\n"  # 6: a display counted for its size
        '    b = int("30") + float("2.5")\n'  # 7, 7
        '    c = tomllib.loads("max_age_hours = 24")\n'  # 8
        '    d = json.dumps(report, indent="  ")\n'  # 9
        "    e = json.dumps(report, indent=REPORT_INDENT)\n"  # 10: through the constant
        "    return a, b, c, d, e\n"
    )
    assert _magic005(strict_config, text, "src/a.py") == [
        (4, "warning"),
        (6, "warning"),
        (7, "warning"),
        (7, "warning"),
        (8, "warning"),
        (9, "warning"),
        (10, "warning"),
    ]


def test_python_shapes_that_are_not_disguises(strict_config: EffectiveConfig) -> None:
    text = (
        "import json\n"
        "def f(line, x):\n"
        '    a = line[len("Bearer "):]\n'  # a prefix with content says what it is
        '    b = len("x") + int("1") + int("0")\n'  # allowed values
        '    c = float("inf") + float("nan")\n'  # not finite
        "    d = int(x) + len(x)\n"  # not a literal
        '    e = json.dumps(x, indent="\\t")\n'  # a tab is not a count of spaces
        '    f = json.loads(\'{"version": "1.2.3"}\')\n'  # a version is not a number
        "    return a, b, c, d, e, f\n"
    )
    assert _magic005(strict_config, text, "src/a.py") == []


def test_javascript_disguises(strict_config: EffectiveConfig) -> None:
    text = (
        'const INDENT = "  ";\n'
        "export function f(x) {\n"
        '  const a = Number("3000") + parseFloat("1.5") + +"30";\n'  # 3, 3, 3
        '  const b = JSON.parse("[2, 3]") + JSON.stringify(x, null, "  ");\n'  # 4, 4
        "  const c = JSON.stringify(x, null, INDENT) + [x, a].length;\n"  # 5, 5
        '  const d = "YYYY-MM-DD".length + x.length + JSON.stringify(x, null, "\\t");\n'
        "  return a + b + c + d;\n"
        "}\n"
    )
    assert [line for line, _ in _magic005(strict_config, text, "src/a.js")] == [
        3,
        3,
        3,
        4,
        4,
        5,
        5,
    ]


def test_magic005_applies_where_magic001_applies(tmp_path: Path) -> None:
    (tmp_path / ".shockharness.toml").write_text(
        '[tool.shockharness]\nprofile = "strict"\n\n'
        "[tool.shockharness.rules.magic_numbers]\n"
        'magic005_severity = "review"\n\n'
        "[[tool.shockharness.overrides]]\n"
        'paths = ["tests/**"]\n'
        'disable = ["MAGIC001", "DEF001"]\n'
        'reason = "Tests encode literal expected values"\n',
        encoding="utf-8",
    )
    config = load_config(tmp_path, None)
    text = 'value = int("30")\n'
    assert _magic005(config, text, "src/a.py") == [(1, "review")]
    assert _magic005(config, text, "tests/test_a.py") == []  # where MAGIC001 is off
