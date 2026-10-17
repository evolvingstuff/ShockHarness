"""DOM001: a delegated handler that drops SVG targets (spec 21.1 decision 27)."""

from collections.abc import Callable

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions, FileResult, analyze_text
from shockharness.config import EffectiveConfig
from shockharness.rules import registry

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)

HANDLERS = (
    "export function wire(list, menu, grid, ok, nav) {\n"
    '  list.addEventListener("click", (event) => {\n'
    "    if (!(event.target instanceof HTMLElement)) return;\n"  # 3: reported
    '    event.target.closest("li")?.classList.toggle("open");\n'
    "  });\n"
    "  menu.onclick = function (e) {\n"
    "    const target = e.target;\n"
    '    if (target instanceof HTMLElement) { target.closest("li")?.remove(); }\n'  # 8
    "  };\n"
    '  grid.addEventListener("click", (e) => {\n'
    "    if (!(e.target instanceof HTMLButtonElement)) { return; }\n"  # a narrower filter
    '    e.target.closest("tr")?.remove();\n'
    "  });\n"
    '  ok.addEventListener("click", (e) => {\n'
    "    if (!(e.target instanceof Element)) return;\n"  # the fix
    '    e.target.closest("a")?.focus();\n'
    "  });\n"
    '  nav.addEventListener("click", (e) => {\n'
    "    if (!(e.currentTarget instanceof HTMLElement)) return;\n"  # the listener's element
    '    e.currentTarget.closest("nav")?.blur();\n'
    "    if (!(e.target instanceof HTMLElement)) return;\n"  # no closest after it
    "    e.target.focus();\n"
    "  });\n"
    "}\n"
)


def run(config: EffectiveConfig, path: str, language: str, text: str) -> FileResult:
    return analyze_text(path, language, text, config, OPTIONS)


def lines(result: FileResult) -> list[int]:
    return [f.span.line for f in result.findings if f.rule_id == "DOM001"]


def test_dom001_reports_html_element_guards_before_closest(
    strict_config: EffectiveConfig,
) -> None:
    result = run(strict_config, "src/menu.js", "javascript", HANDLERS)
    assert lines(result) == [3, 8]
    message = next(f.message for f in result.findings if f.rule_id == "DOM001")
    assert message.startswith(
        "event.target instanceof HTMLElement drops an event whose target is an SVG element"
    )
    assert message.endswith("which works on any Element: test instanceof Element")
    typed = run(strict_config, "src/menu.ts", "typescript", HANDLERS)
    assert lines(typed) == [3, 8]
    assert registry.DOM001.languages == ("javascript", "typescript")
    assert "DOM001" not in run(strict_config, "src/a.py", "python", "x = 0\n").rules_applied


def test_dom001_classes_and_roles(make_config: Callable[[str], EffectiveConfig]) -> None:
    wider = make_config(
        '[tool.shockharness.rules.dom]\nclasses = ["HTMLElement", "HTMLButtonElement"]\n'
    )
    assert lines(run(wider, "src/menu.js", "javascript", HANDLERS)) == [3, 8, 11]
    none = make_config("[tool.shockharness.rules.dom]\nclasses = []\n")
    assert lines(run(none, "src/menu.js", "javascript", HANDLERS)) == []
    assert any("rules.dom.classes no longer lists 'HTMLElement'" in d for d in none.deviations)
    default = make_config("")
    assert "DOM001" not in run(default, "tests/menu.test.js", "javascript", HANDLERS).rules_applied
