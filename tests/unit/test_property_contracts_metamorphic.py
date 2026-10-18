"""Metamorphic tests of property contracts (spec §13.2, P2): a change that should not
alter what the analysis concludes does not, and one that should, does."""

import json
import shutil
from pathlib import Path
from typing import Any

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions
from shockharness.api import analyze_paths
from shockharness.config import load_config
from tests.conftest import FIXTURES

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)
STATS = FIXTURES / "property_contracts" / "python" / "stats"

CATALOG = """\
[tool.shockharness]
include = ["app/**/*.py"]

[tool.shockharness.rules.property_contracts]
enabled = true
runtime_module = ["app/contracts.py"]

[[tool.shockharness.rules.property_contracts.properties]]
name = "redacted"
description = "text with addresses masked"
producers = []
runtime = "static"

[[tool.shockharness.rules.property_contracts.properties]]
name = "trimmed"
description = "no surrounding whitespace"
producers = []
runtime = "static"
"""
HEADER = "from app.contracts import preserves_except, produces, requires\n\n\n"
DELIVER = 'def deliver(text):\n    requires(text, "redacted")\n    return text\n\n\n'


def rows(root: Path) -> list[tuple[str, int, str, str]]:
    report = analyze_paths([root], root, load_config(root, None), OPTIONS)
    return [
        (f.path, f.span.line, f.rule_id, f.status)
        for f in report.findings
        if f.rule_id.startswith("PROP")
    ]


def messages(root: Path) -> list[str]:
    report = analyze_paths([root], root, load_config(root, None), OPTIONS)
    return [f.message for f in report.findings if f.rule_id.startswith("PROP")]


def project(root: Path, code: str) -> Path:
    (root / "app").mkdir(parents=True)
    (root / ".shockharness.toml").write_text(CATALOG, encoding="utf-8")
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "app" / "m.py").write_text(HEADER + DELIVER + code, encoding="utf-8")
    return root


def test_renaming_a_property_consistently_changes_only_the_names(tmp_path: Path) -> None:
    original = tmp_path / "original"
    renamed = tmp_path / "renamed"
    shutil.copytree(STATS, original)
    shutil.copytree(STATS, renamed)
    for path in [renamed / ".shockharness.toml", *sorted(renamed.rglob("*.py"))]:
        text = path.read_text(encoding="utf-8")
        # A new name that sorts where the old one did, so the sorted lists read the same.
        path.write_text(text.replace("normalized", "nominalized"), encoding="utf-8")
    assert rows(original) == rows(renamed)
    expected = [m.replace("normalized", "nominalized") for m in messages(original)]
    assert messages(renamed) == expected


def test_extracting_a_helper_that_produces_keeps_the_property(tmp_path: Path) -> None:
    inline = 'def f(raw):\n    x = produces(raw, "redacted")\n    return deliver(x)\n'
    helper = (
        'def clean(raw):\n    return produces(raw, "redacted")\n\n\n'
        "def f(raw):\n    x = clean(raw)\n    return deliver(x)\n"
    )
    assert rows(project(tmp_path / "inline", inline)) == []
    assert rows(project(tmp_path / "helper", helper)) == []
    # A helper of the helper is followed too (transitive summaries, max_depth 3).
    deeper = (
        'def clean(raw):\n    return produces(raw, "redacted")\n\n\n'
        "def tidy(raw):\n    return clean(raw)\n\n\n"
        "def f(raw):\n    return deliver(tidy(raw))\n"
    )
    assert rows(project(tmp_path / "deeper", deeper)) == []


def test_extracting_a_helper_with_only_an_undeclared_operation_loses_it(tmp_path: Path) -> None:
    inline = 'def f(raw):\n    x = produces(raw, "redacted")\n    return deliver(x)\n'
    helper = (
        "def strip(text):\n    return text.strip()\n\n\n"
        'def f(raw):\n    x = strip(produces(raw, "redacted"))\n    return deliver(x)\n'
    )
    assert rows(project(tmp_path / "inline", inline)) == []
    found = rows(project(tmp_path / "helper", helper))
    assert [(rule, status) for _path, _line, rule, status in found] == [("PROP001", "unknown")]


def test_an_unrelated_preserves_except_changes_nothing(tmp_path: Path) -> None:
    base = (
        'def f(raw):\n    x = produces(raw, "redacted")\n'
        '    y = preserves_except(x[:], x, "trimmed")\n'
        "    return deliver(y), deliver(raw)\n"
    )
    without = (
        'def f(raw):\n    x = produces(raw, "redacted")\n    y = x\n'
        "    return deliver(y), deliver(raw)\n"
    )
    assert rows(project(tmp_path / "with", base)) == rows(project(tmp_path / "without", without))


def test_every_fixture_expectation_is_valid_json() -> None:
    for expected in sorted((FIXTURES / "property_contracts").rglob("expected.json")):
        data: Any = json.loads(expected.read_text(encoding="utf-8"))
        assert isinstance(data, list), expected
