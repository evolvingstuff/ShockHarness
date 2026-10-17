"""MAGIC003: a small number standing in for a meaning (spec 21.1 decision 30)."""

from collections.abc import Callable

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions, FileResult, analyze_text
from shockharness.config import EffectiveConfig
from shockharness.rules import registry

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)


def run(config: EffectiveConfig, path: str, text: str) -> FileResult:
    language = "python" if path.endswith(".py") else "javascript"
    return analyze_text(path, language, text, config, OPTIONS)


def lines(result: FileResult) -> list[int]:
    return [f.span.line for f in result.findings if f.rule_id == "MAGIC003"]


PYTHON = (
    "import sys\n\nNO_SELECTION = -1\n\n\n"
    "def f(items, n, state):\n"
    "    selected = -1\n"  # 7: assigned
    "    last = items[-1]\n"  # a subscript
    "    for i in range(n - 1, -1, -1):\n"  # an index callee
    "        pass\n"
    "    if selected == -1:\n"  # a comparison
    "        return -1\n"  # 12: returned
    "    head, _rest = 'a,b'.split(',', -1)\n"  # an index callee (a count)
    "    run(n, -1, timeout=-1)\n"  # 14, 14: passed
    "    state = {'selected': -1, 'count': 0}\n"  # 15: an entry; 0 is not checked
    "    sys.exit(-1)\n"  # 16: an exit code
    "    state.SELECTED = -1\n"  # a name already
    "    return items.pop(-1)\n"  # an index callee
)


def test_magic003_python_positions(strict_config: EffectiveConfig) -> None:
    result = run(strict_config, "src/a.py", PYTHON)
    assert lines(result) == [7, 12, 14, 14, 15, 16]
    messages = [f.message for f in result.findings if f.rule_id == "MAGIC003"]
    assert messages[0].startswith("-1 is assigned to selected: if it stands for something")
    assert messages[3].startswith("-1 is passed to run(...) as timeout")
    finding = next(f for f in result.findings if f.rule_id == "MAGIC003")
    assert (finding.severity, finding.confidence) == ("review", "approximate")
    assert not any(f.rule_id == "MAGIC001" for f in result.findings)
    assert registry.category_of("MAGIC003") == "contract_integrity"
    assert "MAGIC003" not in run(strict_config, "tests/test_a.py", PYTHON).rules_applied


def test_magic003_javascript_and_typescript(strict_config: EffectiveConfig) -> None:
    text = (
        "const NO_SELECTION = -1;\n"
        "let selectedIndex = -1;\n"  # 2
        "export const view = { selectedIndex: -1, open: false };\n"  # 3
        "export function find(a, x) {\n"
        "  if (a.indexOf(x) === -1) { return -1; }\n"  # 5: the return, not the comparison
        "  return a.at(-1) + a.slice(-1)[0];\n"
        "}\n"
        "export const none = () => -1;\n"  # 8
    )
    assert lines(run(strict_config, "src/a.js", text)) == [2, 3, 5, 8]
    typed = analyze_text(
        "src/a.ts",
        "typescript",
        "export let code: number = -1 as number;\n",
        strict_config,
        OPTIONS,
    )
    assert lines(typed) == [1]


def test_magic003_settings(make_config: Callable[[str], EffectiveConfig]) -> None:
    text = "def f():\n    count = 0\n    level = -1\n    return count, level\n"
    with_zero = make_config("[tool.shockharness.rules.sentinels]\nvalues = [-1, 0]\n")
    assert lines(run(with_zero, "src/a.py", text)) == [2, 3]
    # a value MAGIC001 reports is not reported twice
    strict_minus = make_config(
        "[tool.shockharness.rules.magic_numbers]\nallow_unary_negative_one = false\n"
    )
    result = run(strict_minus, "src/a.py", text)
    assert lines(result) == []
    assert [f.span.line for f in result.findings if f.rule_id == "MAGIC001"] == [3]
    widened = make_config(
        '[tool.shockharness.rules.sentinels]\npython_index_callees = ["range", ".level"]\n'
    )
    assert any("python_index_callees also permits '.level'" in d for d in widened.deviations)
