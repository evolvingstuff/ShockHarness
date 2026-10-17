"""DOM002: a floating control a page-level press handler treats as outside (spec 21.1
decision 32)."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions
from shockharness.api import analyze_paths
from shockharness.config import EffectiveConfig
from shockharness.errors import ConfigError
from shockharness.rules.floating import compounds

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)
EXCLUSION = "src/mouse-events.js:isOutsideEditExclusion"


def project(root: Path, config: EffectiveConfig, files: dict[str, str]) -> Any:
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return analyze_paths([root], root, config, OPTIONS)


def rows(report: Any) -> list[tuple[str, int, str]]:
    return [(f.path, f.span.line, f.status) for f in report.findings if f.rule_id == "DOM002"]


# MetaList before the fix: the notice stack was not in the skip list.
APP = {
    "src/selectors.js": "export const SHELL_SELECTOR = '.meta-shell';\n",
    "src/mouse-events.js": (
        "import { SHELL_SELECTOR } from './selectors.js';\n"
        "const PANELS = ['#ai-chat-panel', '.paste-format-offer'];\n"
        "export function isOutsideEditExclusion(target) {\n"
        "  return target.closest([\n"
        "    '.modal', '#menu-button', SHELL_SELECTOR, '[data-keep]',\n"
        "  ].join(',')) !== null || target.closest(PANELS.join(',')) !== null;\n"
        "}\n"
    ),
    "src/notice-stack.js": (
        "export function appNoticeStack() {\n"
        "  const stack = document.createElement('div');\n"
        "  stack.className = 'app-notice-stack';\n"
        "  document.body.appendChild(stack);\n"
        "  return stack;\n"
        "}\n"
    ),
    "src/backup-reminder.js": (
        "import { appNoticeStack } from './notice-stack.js';\n"
        "export function showReminder(open) {\n"
        "  const notice = document.createElement('aside');\n"
        "  notice.className = 'backup-reminder-notice';\n"
        "  const backUp = document.createElement('button');\n"
        "  backUp.addEventListener('click', open);\n"
        "  notice.append(backUp);\n"
        "  appNoticeStack().append(notice);\n"  # 8
        "}\n"
    ),
    "src/banner.js": (
        "export function showBanner(type, message) {\n"
        "  const banner = document.createElement('div');\n"
        "  banner.className = `error-banner error-banner-${type}`;\n"
        '  banner.innerHTML = `<span>${message}</span><button class="close">x</button>`;\n'
        "  document.body.insertBefore(banner, document.body.firstChild);\n"  # 5
        "}\n"
    ),
    "src/modal.js": (
        "export function openModal() {\n"
        "  const modal = document.createElement('div');\n"
        "  modal.classList.add('modal', 'is-open');\n"
        "  const ok = document.createElement('button');\n"
        "  modal.append(ok);\n"
        "  document.body.append(modal);\n"  # skipped: .modal
        "}\n"
    ),
    "src/shell.js": (
        "export function openShell() {\n"
        "  const shell = document.createElement('section');\n"
        "  shell.setAttribute('class', 'meta-shell');\n"  # skipped through SHELL_SELECTOR
        "  shell.onclick = () => null;\n"
        "  document.body.append(shell);\n"
        "}\n"
    ),
    "src/download.js": (
        "export function download(url) {\n"
        "  const link = document.createElement('a');\n"
        "  link.href = url;\n"
        "  document.body.appendChild(link);\n"
        "  link.addEventListener('click', () => null);\n"
        "  link.click();\n"
        "  link.remove();\n"  # transient
        "}\n"
    ),
    "src/probe.js": (
        "export function measure() {\n"
        "  const probe = document.createElement('div');\n"
        "  document.body.append(probe);\n"  # nothing pressable
        "  return probe.offsetWidth;\n"
        "}\n"
    ),
}


def configured(make_config: Callable[[str], EffectiveConfig], entries: str) -> EffectiveConfig:
    return make_config(f"[tool.shockharness.rules.dom]\npress_exclusions = [{entries}]\n")


def test_dom002_reports_floating_controls_the_skip_list_misses(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    report = project(empty_root, configured(make_config, f'"{EXCLUSION}"'), APP)
    assert rows(report) == [
        ("src/backup-reminder.js", 8, "violation"),
        ("src/banner.js", 5, "violation"),
    ]
    notice = next(f for f in report.findings if f.path == "src/backup-reminder.js")
    assert notice.severity == "review"
    assert notice.message.startswith(
        "this pressable element (.backup-reminder-notice, aside) is appended into "
        "appNoticeStack() (.app-notice-stack, div), on the body, and matches no selector "
        f"that {EXCLUSION} skips"
    )
    banner = next(f for f in report.findings if f.path == "src/banner.js")
    assert "(.error-banner, div) is attached" in banner.message


def test_dom002_the_fix_and_the_opt_in(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    fixed = dict(APP)
    fixed["src/mouse-events.js"] = APP["src/mouse-events.js"].replace(
        "'.modal',", "'.modal', '.app-notice-stack', '.error-banner',"
    )
    assert rows(project(empty_root, configured(make_config, f'"{EXCLUSION}"'), fixed)) == []
    assert rows(project(empty_root, make_config(""), {})) == []  # nothing named: off


def test_dom002_every_list_must_skip_the_control(
    empty_root: Path, make_config: Callable[[str], EffectiveConfig]
) -> None:
    files = dict(APP)
    files["src/click.js"] = (
        "export function handleClick(event) {\n"
        "  if (event.target.closest('.app-notice-stack, .error-banner, .modal, .meta-shell')) {\n"
        "    return;\n"
        "  }\n"
        "}\n"
    )
    entries = f'"{EXCLUSION}", "src/click.js:handleClick", "src/click.js:missing"'
    report = project(empty_root, configured(make_config, entries), files)
    assert rows(report) == [
        ("src/backup-reminder.js", 8, "violation"),  # the first list still misses it
        ("src/banner.js", 5, "violation"),
        ("src/click.js", 1, "unknown"),  # no function named missing
    ]
    assert "matches no selector that src/mouse-events.js:isOutsideEditExclusion skips" in next(
        f.message for f in report.findings if f.path == "src/banner.js"
    )


def test_dom002_selector_compounds() -> None:
    assert compounds(".modal .close, #menu > button.icon, [data-keep], a:not(.x)") == [
        frozenset({".close"}),
        frozenset({"button", ".icon"}),
        frozenset({"a"}),
    ]
    assert compounds("${STATUS}, .note") == [frozenset({".note"})]


def test_dom002_bad_entries_are_configuration_errors(
    make_config: Callable[[str], EffectiveConfig],
) -> None:
    with pytest.raises(ConfigError, match="press_exclusions"):
        configured(make_config, '"src/mouse-events.js"')
