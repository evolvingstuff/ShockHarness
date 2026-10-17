"""MAGIC002: one string literal repeated across files (spec 21.1 decision 31)."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions
from shockharness.api import analyze_paths
from shockharness.config import EffectiveConfig
from shockharness.ir.javascript import extract_javascript_facts, extract_typescript_facts
from shockharness.ir.python import extract_python_facts
from shockharness.rules import registry
from shockharness.source import SourceText

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)


def project(root: Path, config: EffectiveConfig, files: dict[str, str]) -> Any:
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return analyze_paths([root], root, config, OPTIONS)


def rows(report: Any) -> list[tuple[str, int]]:
    return [(f.path, f.span.line) for f in report.findings if f.rule_id == "MAGIC002"]


def uses(facts: Any) -> list[tuple[int, str, str, str]]:
    return [(s.span.line, s.value, s.kind, s.callee) for s in facts.strings]


ORDERS = {
    "app/__init__.py": "",
    "app/orders.py": (
        "def ship(order):\n"
        "    if order.status == 'pending':\n"  # 2: the first use
        "        order.status = 'shipped'\n"
        "    return order\n"
    ),
    "app/views.py": (
        "def badge(order):\n"
        "    if order.status in ('pending', 'held'):\n"
        "        return 'Waiting'\n"
        "    return mark(order, 'pending')\n"
    ),
}


def test_magic002_reports_a_value_compared_in_two_files(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    report = project(empty_root, strict_config, ORDERS)
    assert rows(report) == [("app/orders.py", 2)]  # 'shipped' and 'held' appear once
    finding = next(f for f in report.findings if f.rule_id == "MAGIC002")
    assert finding.severity == "review"
    assert finding.confidence == "approximate"
    assert finding.message == (
        "'pending' is written out 3 times in 2 files (also app/views.py:2, app/views.py:4): "
        "if it names one thing (a status, an endpoint, a header, a code), give it one name"
    )
    assert registry.MAGIC002.implemented


def test_magic002_needs_comparisons_in_two_files(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    # Passed around and compared in one file only: a word that repeats, not a decision.
    files = {
        "app/a.py": "def f(x):\n    send('pending')\n    return x == 'pending'\n",
        "app/b.py": "def g():\n    send('pending')\n    send('pending')\n",
    }
    assert rows(project(empty_root, strict_config, files)) == []


def test_magic002_python_positions_never_counted() -> None:
    text = (
        '"""Module docstring: pending."""\n'
        "from typing import Literal\n\n"
        "__all__ = ['pending']\n"
        "PENDING = 'pending'\n"
        "_STATE: str = 'pending'\n\n\n"
        "def f(order: 'Order', mode: Literal['pending']) -> 'Order':\n"
        '    """Docstring."""\n'
        "    log.info('pending')\n"
        "    message = f'pending {order}'\n"
        "    if order.mode == 'held':\n"  # 13
        "        raise ValueError('pending')\n"
        "    return lookup[order, 'held'], {'key': 'value'}, check('held')\n"  # 15
    )
    facts = extract_python_facts(SourceText.from_text(text), "a.py")
    # Messages are recorded with their callee; the rule leaves them out (message_callees).
    assert uses(facts) == [
        (11, "pending", "argument", "log.info"),
        (13, "held", "compare", ""),
        (14, "pending", "argument", "ValueError"),
        (15, "held", "value", ""),  # a tuple index: a value
        (15, "key", "key", ""),
        (15, "value", "value", ""),
        (15, "held", "argument", "check"),
    ]


def test_magic002_javascript_and_typescript_positions() -> None:
    js = (
        '"use strict";\n'
        "import { a } from './a.js';\n"
        "const fs = require('node:fs');\n"
        "const MODE = 'pending';\n"
        "export function f(order) {\n"
        "  switch (order.status) {\n"
        "    case 'pending': return send(`pending`, { mode: 'held' });\n"  # 7
        "  }\n"
        "  return order.kind === 'held' ? map['held'] : `x ${order}`;\n"  # 9
        "}\n"
    )
    facts = extract_javascript_facts(SourceText.from_text(js), "a.js")
    assert uses(facts) == [
        (7, "pending", "compare", ""),
        (7, "pending", "argument", "send"),
        (7, "held", "value", ""),  # the key mode is an identifier, not a string
        (9, "held", "compare", ""),
        (9, "held", "subscript", ""),
    ]
    ts = "type Mode = 'pending' | 'held';\nlet m: Mode = 'held';\nif (m !== 'pending') go();\n"
    facts = extract_typescript_facts(SourceText.from_text(ts), "a.ts")
    assert uses(facts) == [(2, "held", "value", ""), (3, "pending", "compare", "")]


def test_magic002_across_javascript_files_and_roles(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    files = {
        "src/a.js": "export const f = (s) => s === 'archived';\n",
        "src/b.js": "export function g(s) {\n  if (s !== 'archived') return 'archived';\n}\n",
        "tests/a.test.js": "test('x', () => expect(s === 'archived'));\n",
    }
    report = project(empty_root, strict_config, files)
    assert rows(report) == [("src/a.js", 1)]
    finding = next(f for f in report.findings if f.rule_id == "MAGIC002")
    assert "3 times in 2 files" in finding.message  # the test file is not counted


def test_magic002_settings(empty_root: Path, make_config: Callable[[str], EffectiveConfig]) -> None:
    section = "[tool.shockharness.rules.magic_strings]\n"
    failing = make_config(section + 'mode = "fail"\n')
    report = project(empty_root, failing, ORDERS)
    assert [f.severity for f in report.findings if f.rule_id == "MAGIC002"] == ["error"]
    higher = make_config(section + "min_occurrences = 4\n")
    assert rows(project(empty_root, higher, {})) == []
    assert any("min_occurrences is 4 (strict: 3)" in d for d in higher.deviations)
    allowed = make_config(section + 'allowed = ["pending"]\n')
    assert rows(project(empty_root, allowed, {})) == []
    assert any("magic_strings.allowed" in d for d in allowed.deviations)
    off = make_config(section + "enabled = false\n")
    assert rows(project(empty_root, off, {})) == []
    assert "rules.magic_strings is disabled" in off.deviations
